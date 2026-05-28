"""Policy VCS poller — syncs .rego files from git repos into policy sets.

For each PolicySet with source=vcs, checks the tracked branch for new
commits. On a new commit, downloads the archive, extracts .rego files
from the configured policy_path, and upserts them into the policies
table. Deletes policies whose .rego files no longer exist in the repo.

Registered as a periodic task alongside vcs_poll and registry_vcs_poll.
"""

import asyncio
import io
import os
import posixpath
import tarfile
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from terrapod.db.models import Policy, PolicySet, VCSConnection, now_utc
from terrapod.db.session import get_db_session
from terrapod.logging_config import get_logger
from terrapod.services import github_service, gitlab_service
from terrapod.services.scheduler import enqueue_trigger

logger = get_logger(__name__)

# Max archive size (256 MB) — defence against pathological repos OOMing the worker.
_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


def _parse_repo_url(conn: VCSConnection, repo_url: str) -> tuple[str, str] | None:
    """Parse a repo URL via the appropriate provider."""
    if conn.provider == "gitlab":
        return gitlab_service.parse_repo_url(repo_url)
    return github_service.parse_repo_url(repo_url)


async def _get_default_branch(conn: VCSConnection, owner: str, repo: str) -> str | None:
    """Get default branch via the appropriate provider."""
    if conn.provider == "gitlab":
        return await gitlab_service.get_default_branch(conn, owner, repo)
    return await github_service.get_repo_default_branch(conn, owner, repo)


async def _get_branch_sha(conn: VCSConnection, owner: str, repo: str, branch: str) -> str | None:
    """Get branch HEAD SHA via the appropriate provider."""
    if conn.provider == "gitlab":
        return await gitlab_service.get_branch_sha(conn, owner, repo, branch)
    return await github_service.get_repo_branch_sha(conn, owner, repo, branch)


def _extract_rego_files(archive_bytes: bytes, policy_path: str) -> dict[str, str]:
    """Extract .rego files from a tarball at the given path.

    Returns {policy_name: rego_content} where policy_name is the filename
    without extension. Only direct children of policy_path are included
    (no recursive descent into subdirectories).
    """
    policies: dict[str, str] = {}
    with tarfile.open(fileobj=io.BytesIO(archive_bytes), mode="r:gz") as tar:
        for member in tar.getmembers():
            if not member.isfile() or not member.name.endswith(".rego"):
                continue

            # Reject path traversal: absolute paths or .. components.
            if member.name.startswith("/") or member.name.startswith(".."):
                continue
            normalized = posixpath.normpath(member.name)
            if normalized.startswith(".."):
                continue

            parts = member.name.split("/", 1)
            if len(parts) < 2:
                continue
            relative_path = parts[1]

            target_dir = policy_path.strip("/")
            if target_dir:
                if not relative_path.startswith(target_dir + "/"):
                    continue
                remainder = relative_path[len(target_dir) + 1 :]
            else:
                remainder = relative_path

            if "/" in remainder:
                continue

            name = os.path.splitext(remainder)[0]
            f = tar.extractfile(member)
            if f is not None:
                policies[name] = f.read().decode("utf-8")
    return policies


async def _download_archive(conn: VCSConnection, owner: str, repo: str, ref: str) -> bytes:
    """Download archive via the appropriate provider.

    Validates size post-download. A full streaming cap requires changes
    to the provider protocol (accept max_bytes); for now the 256 MB
    guard catches adversarial repos before extraction. Practical risk is
    bounded by the provider APIs' own response limits (~100 MB on GitHub,
    ~250 MB on GitLab).
    """
    if conn.provider == "gitlab":
        archive = await gitlab_service.download_archive(conn, owner, repo, ref)
    else:
        archive = await github_service.download_repo_archive(conn, owner, repo, ref)
    if len(archive) > _MAX_ARCHIVE_BYTES:
        raise ValueError(
            f"Archive exceeds {_MAX_ARCHIVE_BYTES // (1024 * 1024)} MB limit ({len(archive)} bytes)"
        )
    return archive


async def _sync_policy_set(db: AsyncSession, ps: PolicySet) -> None:
    """Sync a single VCS policy set."""
    conn = ps.vcs_connection
    if conn is None:
        ps.vcs_last_error = "VCS connection deleted"
        return

    parsed = _parse_repo_url(conn, ps.vcs_repo_url)
    if parsed is None:
        ps.vcs_last_error = f"Cannot parse repo URL: {ps.vcs_repo_url}"
        return

    owner, repo = parsed
    branch = ps.vcs_branch

    try:
        if not branch:
            branch = await _get_default_branch(conn, owner, repo) or "main"

        sha = await _get_branch_sha(conn, owner, repo, branch)
        if sha is None:
            ps.vcs_last_error = f"Branch '{branch}' not found"
            return

        if sha == ps.vcs_last_commit_sha:
            return

        archive = await _download_archive(conn, owner, repo, sha)
        rego_files = await asyncio.to_thread(_extract_rego_files, archive, ps.policy_path)

        existing = {p.name: p for p in ps.policies}

        for name, rego in rego_files.items():
            if name in existing:
                if existing[name].rego != rego:
                    existing[name].rego = rego
                    existing[name].updated_at = now_utc()
            else:
                db.add(
                    Policy(
                        policy_set_id=ps.id,
                        name=name,
                        rego=rego,
                    )
                )

        for name, policy in existing.items():
            if name not in rego_files:
                await db.delete(policy)

        ps.vcs_last_commit_sha = sha
        ps.vcs_last_synced_at = now_utc()
        ps.vcs_last_error = None

        logger.info(
            "Policy set synced from VCS",
            policy_set=ps.name,
            commit=sha[:8],
            policies_count=len(rego_files),
        )

    except Exception as e:
        ps.vcs_last_error = str(e)[-2000:]
        logger.warning(
            "Policy VCS sync failed",
            policy_set=ps.name,
            error=str(e),
        )


async def handle_policy_vcs_sync(payload: dict) -> None:
    """Triggered handler: sync a single VCS policy set by ID.

    Enqueued by the POST /policy-sets/{id}/actions/sync endpoint and by
    policy_vcs_poll_cycle (fan-out).
    """
    ps_id = uuid.UUID(payload["policy_set_id"])
    async with get_db_session() as db:
        ps = (
            await db.execute(
                select(PolicySet)
                .where(PolicySet.id == ps_id)
                .options(selectinload(PolicySet.policies))
            )
        ).scalar_one_or_none()
        if ps is None or ps.source != "vcs":
            return
        await _sync_policy_set(db, ps)
        await db.commit()


async def policy_vcs_poll_cycle() -> None:
    """Fan-out: enumerate VCS policy sets and enqueue one sync trigger per set.

    Each set syncs independently via handle_policy_vcs_sync — a slow repo
    cannot stall other sets.
    """
    async with get_db_session() as db:
        result = await db.execute(
            select(PolicySet.id)
            .where(PolicySet.source == "vcs", PolicySet.enabled.is_(True))
        )
        ps_ids = result.scalars().all()

    for ps_id in ps_ids:
        await enqueue_trigger(
            "policy_vcs_sync",
            payload={"policy_set_id": str(ps_id)},
            dedup_key=f"policy_vcs_sync:{ps_id}",
            dedup_ttl=30,
        )
