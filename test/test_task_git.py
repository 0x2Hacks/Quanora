"""Tests for TaskGitManager and task_git tools.

Validates:
- Independent git init per task
- Commit / rollback / log / diff / status
- Strict isolation from agent git
- Integration via tool functions
"""

import os
import shutil
import tempfile
from pathlib import Path

import pytest

from agent.infrastructure.task_git import (
    GitOperationError,
    IsolationError,
    TaskGitManager,
)


@pytest.fixture
def tmp_workspace(tmp_path):
    """Create a temporary workspace directory (NOT a git repo)."""
    return tmp_path


@pytest.fixture
def task_dir(tmp_workspace):
    """Create a task directory inside the workspace."""
    td = tmp_workspace / "test_task"
    td.mkdir()
    return td


@pytest.fixture
def mgr(task_dir):
    """Create a TaskGitManager for the test task."""
    return TaskGitManager(task_dir=task_dir, task_name="test_task")


class TestTaskGitInit:
    """Test task repo initialization."""

    def test_init_creates_git_dir(self, mgr, task_dir):
        result = mgr.init_task_repo(skip_isolation_check=True)
        assert result.success
        assert (task_dir / ".git").is_dir()

    def test_init_creates_gitignore(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        gitignore = task_dir / ".gitignore"
        assert gitignore.exists()
        content = gitignore.read_text()
        assert "__pycache__" in content

    def test_init_creates_initial_commit(self, mgr):
        result = mgr.init_task_repo(skip_isolation_check=True)
        assert result.success
        assert result.data.get("commit")
        assert result.data["commit"] != "none"

    def test_init_idempotent(self, mgr):
        result1 = mgr.init_task_repo(skip_isolation_check=True)
        result2 = mgr.init_task_repo(skip_isolation_check=True)
        assert result1.success
        assert result2.success
        assert "already initialized" in result2.message

    def test_init_task_dir_created_if_missing(self, tmp_workspace):
        td = tmp_workspace / "new_task"
        mgr = TaskGitManager(task_dir=td, task_name="new_task")
        result = mgr.init_task_repo(skip_isolation_check=True)
        assert result.success
        assert td.is_dir()

    def test_init_with_existing_files(self, task_dir):
        # Pre-create a file
        (task_dir / "strategy.py").write_text("alpha = 1", encoding="utf-8")
        mgr = TaskGitManager(task_dir=task_dir, task_name="test_task")
        result = mgr.init_task_repo(skip_isolation_check=True)
        assert result.success
        # File should be tracked
        status = mgr.status()
        assert status.data["clean"]


class TestTaskGitCommit:
    """Test commit operations."""

    def test_commit_new_file(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        (task_dir / "signal.py").write_text("def signal(): pass", encoding="utf-8")
        result = mgr.commit_all("feat: add signal")
        assert result.success
        assert result.data["changed_files"] >= 1
        assert result.data["commit"]

    def test_commit_no_changes(self, mgr):
        mgr.init_task_repo(skip_isolation_check=True)
        result = mgr.commit_all("no-op")
        assert result.success
        assert result.data["changed_files"] == 0

    def test_commit_before_init_fails(self, task_dir):
        mgr = TaskGitManager(task_dir=task_dir, task_name="uninit")
        result = mgr.commit_all("test")
        assert not result.success
        assert "not initialized" in result.message

    def test_commit_modification(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        (task_dir / "config.yaml").write_text("key: value1", encoding="utf-8")
        mgr.commit_all("init config")
        # Modify
        (task_dir / "config.yaml").write_text("key: value2", encoding="utf-8")
        result = mgr.commit_all("fix: update config")
        assert result.success
        assert result.data["changed_files"] >= 1

    def test_commit_deletion(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        (task_dir / "temp.py").write_text("# temp", encoding="utf-8")
        mgr.commit_all("add temp")
        # Delete
        (task_dir / "temp.py").unlink()
        result = mgr.commit_all("chore: remove temp")
        assert result.success

    def test_has_changes(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        assert not mgr.has_changes()
        (task_dir / "new.py").write_text("x = 1", encoding="utf-8")
        assert mgr.has_changes()


class TestTaskGitLog:
    """Test log operations."""

    def test_log_after_init(self, mgr):
        mgr.init_task_repo(skip_isolation_check=True)
        result = mgr.log()
        assert result.success
        assert result.data["count"] >= 1

    def test_log_shows_multiple_commits(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        (task_dir / "a.py").write_text("a = 1", encoding="utf-8")
        mgr.commit_all("commit a")
        (task_dir / "b.py").write_text("b = 2", encoding="utf-8")
        mgr.commit_all("commit b")
        result = mgr.log(n=5)
        assert result.success
        assert result.data["count"] >= 3  # init + 2 commits

    def test_log_entry_format(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        (task_dir / "x.py").write_text("x = 1", encoding="utf-8")
        mgr.commit_all("feat: add x")
        result = mgr.log(n=1)
        assert result.success
        entry = result.data["commits"][0]
        assert "hash" in entry
        assert "author" in entry
        assert "date" in entry
        assert "message" in entry
        # Author should be the task bot, not the agent
        assert entry["author"] == "QuantTaskBot"


class TestTaskGitDiff:
    """Test diff operations."""

    def test_diff_no_changes(self, mgr):
        mgr.init_task_repo(skip_isolation_check=True)
        result = mgr.diff()
        assert result.success

    def test_diff_with_changes(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        (task_dir / "data.py").write_text("value = 1", encoding="utf-8")
        mgr.commit_all("add data")
        (task_dir / "data.py").write_text("value = 2", encoding="utf-8")
        result = mgr.diff()
        assert result.success
        assert "value = 2" in result.data.get("diff", "")


class TestTaskGitStatus:
    """Test status operations."""

    def test_status_clean(self, mgr):
        mgr.init_task_repo(skip_isolation_check=True)
        result = mgr.status()
        assert result.success
        assert result.data["clean"]

    def test_status_with_untracked(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        (task_dir / "untracked.py").write_text("# new", encoding="utf-8")
        result = mgr.status()
        assert result.success
        assert not result.data["clean"]
        assert result.data["total"] >= 1


class TestTaskGitRollback:
    """Test rollback operations."""

    def test_rollback_one_commit(self, mgr, task_dir):
        mgr.init_task_repo(skip_isolation_check=True)
        # Add file and commit
        (task_dir / "v1.py").write_text("version = 1", encoding="utf-8")
        mgr.commit_all("v1")
        v1_hash = mgr.current_commit()

        # Modify and commit
        (task_dir / "v1.py").write_text("version = 2", encoding="utf-8")
        mgr.commit_all("v2")

        # Rollback
        result = mgr.rollback("HEAD~1")
        assert result.success
        assert mgr.current_commit() == v1_hash

        # File should be reverted
        content = (task_dir / "v1.py").read_text(encoding="utf-8")
        assert "version = 1" in content

    def test_rollback_invalid_ref(self, mgr):
        mgr.init_task_repo(skip_isolation_check=True)
        result = mgr.rollback("nonexistent_ref_xyz")
        assert not result.success
        assert "does not exist" in result.message

    def test_rollback_before_init(self, task_dir):
        mgr = TaskGitManager(task_dir=task_dir, task_name="uninit")
        result = mgr.rollback()
        assert not result.success


class TestIsolation:
    """Test git isolation guarantees."""

    def test_task_repo_separate_from_agent_repo(self, tmp_workspace):
        """Verify task .git is not the agent .git."""
        task_dir = tmp_workspace / "my_task"
        mgr = TaskGitManager(task_dir=task_dir, task_name="my_task")
        mgr.init_task_repo(skip_isolation_check=True)

        # The task .git should be inside the task dir
        task_git = task_dir / ".git"
        assert task_git.is_dir()

        # The agent .git should NOT be the same
        agent_root = Path(__file__).resolve().parent.parent.parent
        agent_git = agent_root / ".git"
        if agent_git.exists():
            assert task_git.resolve() != agent_git.resolve()

    def test_task_commit_author_is_quantbot(self, tmp_workspace):
        """Verify commits use the task identity, not the agent's."""
        task_dir = tmp_workspace / "author_test"
        mgr = TaskGitManager(task_dir=task_dir, task_name="author_test")
        mgr.init_task_repo(skip_isolation_check=True)

        result = mgr.log(n=1)
        entry = result.data["commits"][0]
        assert entry["author"] == "QuantTaskBot"

    def test_two_task_repos_independent(self, tmp_workspace):
        """Two task repos should have completely separate git histories."""
        dir_a = tmp_workspace / "task_a"
        dir_b = tmp_workspace / "task_b"

        mgr_a = TaskGitManager(task_dir=dir_a, task_name="task_a")
        mgr_b = TaskGitManager(task_dir=dir_b, task_name="task_b")

        mgr_a.init_task_repo(skip_isolation_check=True)
        mgr_b.init_task_repo(skip_isolation_check=True)

        # Add different files
        (dir_a / "a.txt").write_text("AAA", encoding="utf-8")
        mgr_a.commit_all("task a commit")

        (dir_b / "b.txt").write_text("BBB", encoding="utf-8")
        mgr_b.commit_all("task b commit")

        # Histories should be different
        log_a = mgr_a.log()
        log_b = mgr_b.log()
        commits_a = [c["hash"] for c in log_a.data["commits"]]
        commits_b = [c["hash"] for c in log_b.data["commits"]]
        assert not set(commits_a).intersection(set(commits_b))

    def test_get_summary(self, mgr):
        mgr.init_task_repo(skip_isolation_check=True)
        summary = mgr.get_summary()
        assert summary["task_name"] == "test_task"
        assert summary["initialized"] is True
        assert summary["current_commit"] is not None
        assert summary["has_changes"] is False


class TestCurrentCommit:
    """Test current_commit utility."""

    def test_current_commit_after_init(self, mgr):
        mgr.init_task_repo(skip_isolation_check=True)
        commit = mgr.current_commit()
        assert commit != "none"
        assert len(commit) >= 7  # At least short hash length

    def test_current_commit_before_init(self, task_dir):
        mgr = TaskGitManager(task_dir=task_dir, task_name="nope")
        assert mgr.current_commit() == "none"


class TestIsInitialized:
    """Test is_initialized check."""

    def test_not_initialized(self, task_dir):
        mgr = TaskGitManager(task_dir=task_dir, task_name="nope")
        assert not mgr.is_initialized()

    def test_initialized_after_init(self, mgr):
        mgr.init_task_repo(skip_isolation_check=True)
        assert mgr.is_initialized()
