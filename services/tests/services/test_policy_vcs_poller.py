"""Unit tests for the policy VCS poller."""

import io
import tarfile
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from terrapod.services.policy_vcs_poller import _extract_rego_files, _sync_policy_set


def _make_tarball(files: dict[str, str]) -> bytes:
    """Create an in-memory gzipped tarball with the given path->content mapping."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        for path, content in files.items():
            data = content.encode()
            info = tarfile.TarInfo(name=path)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class TestExtractRegoFiles:
    def test_extracts_from_policy_path(self):
        archive = _make_tarball(
            {
                "repo-abc123/policies/deny_s3.rego": 'package terrapod\ndeny contains msg if { false\n  msg := "no" }',
                "repo-abc123/policies/warn_tags.rego": "package terrapod\nwarn contains msg if { false }",
                "repo-abc123/policies/sub/nested.rego": "package terrapod\n# nested should be excluded",
                "repo-abc123/README.md": "# Policies",
            }
        )
        result = _extract_rego_files(archive, "policies")
        assert "deny_s3" in result
        assert "warn_tags" in result
        assert "nested" not in result
        assert "README" not in result

    def test_extracts_from_root_when_path_empty(self):
        archive = _make_tarball(
            {
                "repo-abc123/main.rego": "package terrapod\ndeny contains msg if { false }",
                "repo-abc123/sub/other.rego": "package terrapod\n# sub should be excluded",
            }
        )
        result = _extract_rego_files(archive, "")
        assert "main" in result
        assert "other" not in result

    def test_strips_rego_extension_for_name(self):
        archive = _make_tarball(
            {
                "repo-abc123/my-policy.rego": "package terrapod\ndeny contains msg if { false }",
            }
        )
        result = _extract_rego_files(archive, "")
        assert "my-policy" in result
        assert "my-policy.rego" not in result

    def test_ignores_non_rego_files(self):
        archive = _make_tarball(
            {
                "repo-abc123/policies/valid.rego": "package terrapod\ndeny contains msg if { false }",
                "repo-abc123/policies/README.md": "# docs",
                "repo-abc123/policies/data.json": "{}",
            }
        )
        result = _extract_rego_files(archive, "policies")
        assert "valid" in result
        assert len(result) == 1

    def test_handles_trailing_slash_in_path(self):
        archive = _make_tarball(
            {
                "repo-abc123/policies/test.rego": "package terrapod\ndeny contains msg if { false }",
            }
        )
        result = _extract_rego_files(archive, "policies/")
        assert "test" in result

    def test_empty_archive_returns_empty(self):
        archive = _make_tarball({})
        result = _extract_rego_files(archive, "policies")
        assert result == {}

    def test_no_matching_path_returns_empty(self):
        archive = _make_tarball(
            {
                "repo-abc123/other-dir/test.rego": "package terrapod\ndeny contains msg if { false }",
            }
        )
        result = _extract_rego_files(archive, "policies")
        assert result == {}


# ── _sync_policy_set tests ──────────────────────────────────────────────


def _mock_policy_set(**overrides):
    ps = MagicMock()
    ps.id = overrides.get("id", uuid.uuid4())
    ps.name = overrides.get("name", "test-set")
    ps.source = "vcs"
    ps.vcs_repo_url = overrides.get("vcs_repo_url", "https://github.com/org/policies")
    ps.vcs_branch = overrides.get("vcs_branch", "main")
    ps.policy_path = overrides.get("policy_path", "policies")
    ps.vcs_last_commit_sha = overrides.get("vcs_last_commit_sha", "")
    ps.vcs_last_synced_at = None
    ps.vcs_last_error = None
    ps.policies = overrides.get("policies", [])
    conn = MagicMock()
    conn.provider = "github"
    ps.vcs_connection = overrides.get("vcs_connection", conn)
    return ps


def _mock_policy(name, rego="package terrapod\n"):
    p = MagicMock()
    p.name = name
    p.rego = rego
    p.updated_at = None
    return p


class TestSyncPolicySet:
    @pytest.mark.asyncio
    @patch("terrapod.services.policy_vcs_poller._get_provider")
    async def test_skips_when_sha_unchanged(self, mock_get_provider):
        """No work done if branch SHA matches vcs_last_commit_sha."""
        provider = AsyncMock()
        provider.parse_repo_url.return_value = ("org", "policies")
        provider.get_branch_sha = AsyncMock(return_value="abc123")
        mock_get_provider.return_value = provider

        ps = _mock_policy_set(vcs_last_commit_sha="abc123")
        db = AsyncMock()

        await _sync_policy_set(db, ps)

        provider.download_archive.assert_not_called()
        assert ps.vcs_last_error is None

    @pytest.mark.asyncio
    @patch("terrapod.services.policy_vcs_poller._get_provider")
    async def test_sets_error_when_branch_not_found(self, mock_get_provider):
        """vcs_last_error is set when the branch doesn't exist."""
        provider = AsyncMock()
        provider.parse_repo_url.return_value = ("org", "policies")
        provider.get_branch_sha = AsyncMock(return_value=None)
        mock_get_provider.return_value = provider

        ps = _mock_policy_set(vcs_branch="nonexistent")
        db = AsyncMock()

        await _sync_policy_set(db, ps)

        assert "not found" in ps.vcs_last_error

    @pytest.mark.asyncio
    @patch("terrapod.services.policy_vcs_poller._get_provider")
    async def test_inserts_new_policies(self, mock_get_provider):
        """New .rego files are added as Policy rows."""
        archive = _make_tarball(
            {
                "repo-abc123/policies/new_policy.rego": "package terrapod\ndeny contains msg if { false }",
            }
        )
        provider = AsyncMock()
        provider.parse_repo_url.return_value = ("org", "policies")
        provider.get_branch_sha = AsyncMock(return_value="def456")
        provider.download_archive = AsyncMock(return_value=archive)
        mock_get_provider.return_value = provider

        ps = _mock_policy_set(policies=[])
        db = AsyncMock()

        await _sync_policy_set(db, ps)

        db.add.assert_called_once()
        added = db.add.call_args[0][0]
        assert added.name == "new_policy"
        assert ps.vcs_last_commit_sha == "def456"
        assert ps.vcs_last_error is None

    @pytest.mark.asyncio
    @patch("terrapod.services.policy_vcs_poller._get_provider")
    async def test_updates_modified_policies(self, mock_get_provider):
        """Existing policies with changed content get updated."""
        new_rego = "package terrapod\ndeny contains msg if { true }"
        archive = _make_tarball(
            {
                "repo-abc123/policies/existing.rego": new_rego,
            }
        )
        provider = AsyncMock()
        provider.parse_repo_url.return_value = ("org", "policies")
        provider.get_branch_sha = AsyncMock(return_value="def456")
        provider.download_archive = AsyncMock(return_value=archive)
        mock_get_provider.return_value = provider

        existing_policy = _mock_policy("existing", rego="package terrapod\nold content")
        ps = _mock_policy_set(policies=[existing_policy])
        db = AsyncMock()

        await _sync_policy_set(db, ps)

        assert existing_policy.rego == new_rego
        db.add.assert_not_called()  # update, not insert

    @pytest.mark.asyncio
    @patch("terrapod.services.policy_vcs_poller._get_provider")
    async def test_deletes_removed_policies(self, mock_get_provider):
        """Policies whose .rego files no longer exist get deleted."""
        archive = _make_tarball(
            {
                "repo-abc123/policies/kept.rego": "package terrapod\ndeny contains msg if { false }",
            }
        )
        provider = AsyncMock()
        provider.parse_repo_url.return_value = ("org", "policies")
        provider.get_branch_sha = AsyncMock(return_value="def456")
        provider.download_archive = AsyncMock(return_value=archive)
        mock_get_provider.return_value = provider

        kept = _mock_policy("kept")
        removed = _mock_policy("old_policy")
        ps = _mock_policy_set(policies=[kept, removed])
        db = AsyncMock()

        await _sync_policy_set(db, ps)

        db.delete.assert_called_once_with(removed)

    @pytest.mark.asyncio
    @patch("terrapod.services.policy_vcs_poller._get_provider")
    async def test_sets_error_on_exception(self, mock_get_provider):
        """Exceptions during sync are caught and stored in vcs_last_error."""
        provider = AsyncMock()
        provider.parse_repo_url.return_value = ("org", "policies")
        provider.get_branch_sha = AsyncMock(side_effect=RuntimeError("network timeout"))
        mock_get_provider.return_value = provider

        ps = _mock_policy_set()
        db = AsyncMock()

        await _sync_policy_set(db, ps)

        assert "network timeout" in ps.vcs_last_error

    @pytest.mark.asyncio
    async def test_sets_error_when_connection_deleted(self):
        """vcs_last_error is set when the VCS connection is None (FK SET NULL)."""
        ps = _mock_policy_set(vcs_connection=None)
        db = AsyncMock()

        await _sync_policy_set(db, ps)

        assert "VCS connection deleted" in ps.vcs_last_error
