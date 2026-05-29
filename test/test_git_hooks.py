"""Tests for agent.infrastructure.git_hooks (self-dev auto push + PR)."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from agent.infrastructure.git_hooks import (
    BRANCH,
    PushResult,
    _build_pr_body,
    _build_pr_title,
    _count_unpushed_commits,
    _current_branch,
    _ensure_branch,
    _get_gh_token,
    _has_staged_or_unstaged_changes,
    auto_push_and_pr,
    on_turn_completed_self_dev,
)


# ---------------------------------------------------------------------------
# _get_gh_token
# ---------------------------------------------------------------------------

class TestGetGhToken:
    def test_returns_none_when_no_credential_file(self, tmp_path, monkeypatch):
        monkeypatch.setattr(Path, "home", lambda: tmp_path / "nohome")
        assert _get_gh_token() is None

    def test_extracts_token_from_git_credentials(self, tmp_path, monkeypatch):
        cred = tmp_path / ".git-credentials"
        cred.write_text("https://x-access-token:ghp_ABC123@github.com\n")
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert _get_gh_token() == "ghp_ABC123"

    def test_returns_none_for_malformed_line(self, tmp_path, monkeypatch):
        cred = tmp_path / ".git-credentials"
        cred.write_text("https://user:pass@github.com\n")  # no x-access-token
        monkeypatch.setattr(Path, "home", lambda: tmp_path)
        assert _get_gh_token() is None


# ---------------------------------------------------------------------------
# _count_unpushed_commits
# ---------------------------------------------------------------------------

class TestCountUnpushedCommits:
    @patch("agent.infrastructure.git_hooks._run_git")
    def test_returns_zero_when_no_unpushed(self, mock_git):
        # fetch succeeds, rev-list returns 0
        mock_git.side_effect = [
            MagicMock(returncode=0),          # git fetch origin branch
            MagicMock(returncode=0, stdout="0\n"),  # rev-list count
        ]
        assert _count_unpushed_commits(Path("/fake")) == 0

    @patch("agent.infrastructure.git_hooks._run_git")
    def test_returns_positive_count(self, mock_git):
        mock_git.side_effect = [
            MagicMock(returncode=0),          # git fetch
            MagicMock(returncode=0, stdout="3\n"),  # count = 3
        ]
        assert _count_unpushed_commits(Path("/fake")) == 3

    @patch("agent.infrastructure.git_hooks._run_git")
    def test_fallback_when_no_remote_branch(self, mock_git):
        # fetch fails, then origin/branch..HEAD fails, then rev-list HEAD works
        mock_git.side_effect = [
            MagicMock(returncode=1),               # fetch fails
            MagicMock(returncode=1),               # rev-list origin/branch..HEAD fails
            MagicMock(returncode=0, stdout="5\n"), # rev-list HEAD
        ]
        assert _count_unpushed_commits(Path("/fake")) == 5


# ---------------------------------------------------------------------------
# _current_branch
# ---------------------------------------------------------------------------

class TestCurrentBranch:
    @patch("agent.infrastructure.git_hooks._run_git")
    def test_returns_branch_name(self, mock_git):
        mock_git.return_value = MagicMock(stdout="genspark_ai_developer\n")
        assert _current_branch(Path("/fake")) == "genspark_ai_developer"


# ---------------------------------------------------------------------------
# _has_staged_or_unstaged_changes
# ---------------------------------------------------------------------------

class TestHasChanges:
    @patch("agent.infrastructure.git_hooks._run_git")
    def test_no_changes(self, mock_git):
        mock_git.return_value = MagicMock(stdout="")
        assert _has_staged_or_unstaged_changes(Path("/fake")) is False

    @patch("agent.infrastructure.git_hooks._run_git")
    def test_has_changes(self, mock_git):
        mock_git.return_value = MagicMock(stdout="M file.py\n")
        assert _has_staged_or_unstaged_changes(Path("/fake")) is True


# ---------------------------------------------------------------------------
# auto_push_and_pr — high-level unit test using granular patches
# ---------------------------------------------------------------------------

class TestAutoPushAndPr:
    """We patch individual helper functions so we don't have to micromanage
    the _run_git call sequence inside auto_push_and_pr."""

    @patch("agent.infrastructure.git_hooks._run_gh")
    @patch("agent.infrastructure.git_hooks._build_pr_body")
    @patch("agent.infrastructure.git_hooks._build_pr_title")
    @patch("agent.infrastructure.git_hooks._get_gh_token")
    @patch("agent.infrastructure.git_hooks._run_git")
    @patch("agent.infrastructure.git_hooks._count_unpushed_commits")
    @patch("agent.infrastructure.git_hooks._has_staged_or_unstaged_changes")
    @patch("agent.infrastructure.git_hooks._ensure_branch")
    def test_no_unpushed_commits_returns_early(
        self, mock_ensure, mock_changes, mock_count, mock_git,
        mock_token, mock_title, mock_body, mock_gh,
    ):
        mock_ensure.return_value = None
        mock_changes.return_value = False
        mock_count.return_value = 0
        result = auto_push_and_pr(Path("/fake"))
        assert result.commit_count == 0
        assert not result.pushed
        mock_gh.assert_not_called()

    @patch("agent.infrastructure.git_hooks._run_gh")
    @patch("agent.infrastructure.git_hooks._build_pr_body")
    @patch("agent.infrastructure.git_hooks._build_pr_title")
    @patch("agent.infrastructure.git_hooks._get_gh_token")
    @patch("agent.infrastructure.git_hooks._run_git")
    @patch("agent.infrastructure.git_hooks._count_unpushed_commits")
    @patch("agent.infrastructure.git_hooks._has_staged_or_unstaged_changes")
    @patch("agent.infrastructure.git_hooks._ensure_branch")
    def test_push_and_create_pr(
        self, mock_ensure, mock_changes, mock_count, mock_git,
        mock_token, mock_title, mock_body, mock_gh,
    ):
        mock_ensure.return_value = None
        mock_changes.return_value = False
        mock_count.return_value = 2
        mock_token.return_value = None
        mock_title.return_value = "feat: something"
        mock_body.return_value = "## Why\nTest\n## What changed\n- stuff\n"
        # All _run_git calls succeed (fetch, rebase, squash ops, push)
        mock_git.return_value = MagicMock(returncode=0, stdout="")
        # gh pr create returns a URL
        mock_gh.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/org/repo/pull/42\n",
        )

        result = auto_push_and_pr(Path("/fake"), squash=True)

        assert result.pushed is True
        assert result.commit_count == 2
        assert result.pr_url == "https://github.com/org/repo/pull/42"
        assert result.pr_number == 42

    @patch("agent.infrastructure.git_hooks._run_git")
    @patch("agent.infrastructure.git_hooks._count_unpushed_commits")
    @patch("agent.infrastructure.git_hooks._has_staged_or_unstaged_changes")
    @patch("agent.infrastructure.git_hooks._ensure_branch")
    def test_rebase_failure_aborts_and_returns_error(
        self, mock_ensure, mock_changes, mock_count, mock_git,
    ):
        mock_ensure.return_value = None
        mock_changes.return_value = False
        mock_count.return_value = 1
        # fetch succeeds, rebase fails, abort succeeds
        call_count = [0]
        def git_side_effect(*args, **kwargs):
            call_count[0] += 1
            if "rebase" in args and "--abort" not in args:
                raise subprocess.CalledProcessError(1, "git rebase", stderr="conflict")
            return MagicMock(returncode=0, stdout="")
        mock_git.side_effect = git_side_effect

        result = auto_push_and_pr(Path("/fake"))
        assert result.error is not None
        assert "rebase" in result.error.lower()

    @patch("agent.infrastructure.git_hooks._count_unpushed_commits")
    @patch("agent.infrastructure.git_hooks._has_staged_or_unstaged_changes")
    @patch("agent.infrastructure.git_hooks._ensure_branch")
    def test_dry_run_does_not_push(
        self, mock_ensure, mock_changes, mock_count,
    ):
        mock_ensure.return_value = None
        mock_changes.return_value = False
        mock_count.return_value = 3
        result = auto_push_and_pr(Path("/fake"), dry_run=True)
        assert result.commit_count == 3
        assert not result.pushed

    @patch("agent.infrastructure.git_hooks._run_gh")
    @patch("agent.infrastructure.git_hooks._build_pr_body")
    @patch("agent.infrastructure.git_hooks._build_pr_title")
    @patch("agent.infrastructure.git_hooks._get_gh_token")
    @patch("agent.infrastructure.git_hooks._run_git")
    @patch("agent.infrastructure.git_hooks._count_unpushed_commits")
    @patch("agent.infrastructure.git_hooks._has_staged_or_unstaged_changes")
    @patch("agent.infrastructure.git_hooks._ensure_branch")
    def test_pr_already_exists(
        self, mock_ensure, mock_changes, mock_count, mock_git,
        mock_token, mock_title, mock_body, mock_gh,
    ):
        mock_ensure.return_value = None
        mock_changes.return_value = False
        mock_count.return_value = 1
        mock_token.return_value = None
        mock_title.return_value = "feat: test"
        mock_body.return_value = "body"
        mock_git.return_value = MagicMock(returncode=0, stdout="")

        # gh pr create fails with "already exists", then view returns existing PR
        mock_gh.side_effect = [
            MagicMock(returncode=1, stderr="pull request already exists"),
            MagicMock(returncode=0, stdout='{"url":"https://github.com/org/repo/pull/99","number":99}'),
        ]

        result = auto_push_and_pr(Path("/fake"), squash=False)
        assert result.pushed is True
        assert result.pr_url == "https://github.com/org/repo/pull/99"
        assert result.pr_number == 99


# ---------------------------------------------------------------------------
# on_turn_completed_self_dev — integration-style test
# ---------------------------------------------------------------------------

class TestOnTurnCompletedSelfDev:
    @patch("agent.infrastructure.git_hooks.auto_push_and_pr")
    @patch("agent.infrastructure.git_hooks._count_unpushed_commits")
    @patch("agent.infrastructure.git_hooks._current_branch")
    def test_calls_auto_push_when_commits_exist(self, mock_branch, mock_count, mock_push):
        mock_branch.return_value = BRANCH
        mock_count.return_value = 2
        mock_push.return_value = PushResult(
            pushed=True, pr_url="https://github.com/org/repo/pull/7", commit_count=2
        )
        on_turn_completed_self_dev(Path("/fake"))
        mock_push.assert_called_once()

    @patch("agent.infrastructure.git_hooks.auto_push_and_pr")
    @patch("agent.infrastructure.git_hooks._count_unpushed_commits")
    @patch("agent.infrastructure.git_hooks._current_branch")
    def test_skips_when_no_commits(self, mock_branch, mock_count, mock_push):
        mock_branch.return_value = BRANCH
        mock_count.return_value = 0
        on_turn_completed_self_dev(Path("/fake"))
        mock_push.assert_not_called()

    @patch("agent.infrastructure.git_hooks.auto_push_and_pr")
    @patch("agent.infrastructure.git_hooks._count_unpushed_commits")
    @patch("agent.infrastructure.git_hooks._current_branch")
    def test_skips_when_wrong_branch(self, mock_branch, mock_count, mock_push):
        mock_branch.return_value = "main"
        on_turn_completed_self_dev(Path("/fake"))
        mock_push.assert_not_called()

    @patch("agent.infrastructure.git_hooks.auto_push_and_pr")
    @patch("agent.infrastructure.git_hooks._count_unpushed_commits")
    @patch("agent.infrastructure.git_hooks._current_branch")
    def test_exception_does_not_propagate(self, mock_branch, mock_count, mock_push):
        mock_branch.side_effect = RuntimeError("git broken")
        # Should not raise
        on_turn_completed_self_dev(Path("/fake"))
        mock_push.assert_not_called()


# ---------------------------------------------------------------------------
# PushResult dataclass
# ---------------------------------------------------------------------------

class TestPushResult:
    def test_defaults(self):
        r = PushResult()
        assert r.pushed is False
        assert r.pr_url is None
        assert r.error is None
        assert r.commit_count == 0

    def test_with_values(self):
        r = PushResult(pushed=True, pr_url="http://x", commit_count=5)
        assert r.pushed is True
        assert r.pr_url == "http://x"
        assert r.commit_count == 5


# ---------------------------------------------------------------------------
# _build_pr_title / _build_pr_body
# ---------------------------------------------------------------------------

class TestBuildPrTitle:
    @patch("agent.infrastructure.git_hooks._run_git")
    def test_uses_last_commit_message(self, mock_git):
        mock_git.return_value = MagicMock(stdout="feat: add new hook\n")
        assert _build_pr_title(Path("/fake")) == "feat: add new hook"


class TestBuildPrBody:
    @patch("agent.infrastructure.git_hooks._run_git")
    def test_contains_required_sections(self, mock_git):
        mock_git.side_effect = [
            MagicMock(returncode=0, stdout="file.py | 1 +\n"),  # diff --stat
            MagicMock(returncode=0, stdout="agent/file.py\n"),   # diff --name-only
            MagicMock(returncode=0, stdout="- feat: stuff\n"),   # log --format
        ]
        body = _build_pr_body(Path("/fake"))
        assert "## Why" in body
        assert "## What changed" in body
        assert "## Tests" in body
        assert "## Files" in body
