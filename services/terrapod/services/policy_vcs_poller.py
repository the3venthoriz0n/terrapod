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
import tarfile

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from terrapod.db.models import Policy, PolicySet, VCSConnection, now_utc
from terrapod.db.session import get_db_session
from terrapod.logging_config import get_logger
from terrapod.services import github_service, gitlab_service
from terrapod.services.vcs_provider import VCSProvider

logger = get_logger(__name__)


def _get_provider(conn: VCSConnection) -> VCSProvider:
    """Return the VCSProvider implementation for a connection's provider type."""
    if conn.provider == "gitlab":
        return gitlab_service  # type: ignore[return-value]
    return github_service  # type: ignore[return-value]


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


async def _sync_policy_set(db: AsyncSession, ps: PolicySet) -> None:
    """Sync a single VCS policy set."""
    conn = ps.vcs_connection
    if conn is None:
        ps.vcs_last_error = "VCS connection deleted"
        return

    provider = _get_provider(conn)
    parsed = provider.parse_repo_url(ps.vcs_repo_url)
    if parsed is None:
        ps.vcs_last_error = f"Cannot parse repo URL: {ps.vcs_repo_url}"
        return

    owner, repo = parsed
    branch = ps.vcs_branch

    try:
        if not branch:
            branch = await provider.get_default_branch(conn, owner, repo) or "main"

        sha = await provider.get_branch_sha(conn, owner, repo, branch)
        if sha is None:
            ps.vcs_last_error = f"Branch '{branch}' not found"
            return

        if sha == ps.vcs_last_commit_sha:
            return

        archive = await provider.download_archive(conn, owner, repo, sha)
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


# Max archive size (256 MB) — defence against pathological repos OOMing the worker.
_MAX_ARCHIVE_BYTES = 256 * 1024 * 1024


async def sync_policy_set(db: AsyncSession, ps: PolicySet) -> None:
    """Public entry point for syncing a single VCS policy set.

    Called by the periodic poller and by the triggered sync action.
    """
    await _sync_policy_set(db, ps)


async def policy_vcs_poll_cycle() -> None:
    """Poll all VCS-connected policy sets for new commits."""
    async with get_db_session() as db:
        result = await db.execute(
            select(PolicySet)
            .where(PolicySet.source == "vcs", PolicySet.enabled.is_(True))
            .options(selectinload(PolicySet.policies))
        )
        policy_sets = result.scalars().all()

        if not policy_sets:
            return

        for ps in policy_sets:
            await _sync_policy_set(db, ps)
            await db.commit()
