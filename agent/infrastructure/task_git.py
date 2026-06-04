"""
TaskGitManager — Per-task independent git version control for quant research.

Each quant research task gets its own isolated git repository, completely
independent from the agent's own git repo. This ensures strict isolation:
- Different .git/ directories
- Different git authors
- No shared state with the agent repo

Design principles:
1. Zero external dependencies (only git CLI via subprocess)
2. Strict path isolation (task repos live only in <workspace>/<task_name>/)
3. Clear error messages when isolation rules are violated
4. Deterministic, testable operations
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default gitignore content for quant research task repos
_DEFAULT_GITIGNORE = """\
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
.eggs/

# Virtual environments
.venv/
venv/
env/

# IDE
.idea/
.vscode/
*.swp
*.swo
*~

# OS
.DS_Store
Thumbs.db

# Large data files (use DVC or external storage for these)
*.parquet
*.hdf5
*.h5
*.csv.gz
*.zip
*.tar.gz

# Sensitive data
*.pem
*.key
.env
"""

# Task git identity (separate from agent git)
_TASK_GIT_AUTHOR_NAME = "QuantTaskBot"
_TASK_GIT_GIT_AUTHOR_EMAIL = "task@quant.local"


@dataclass
class GitResult:
    """Structured result from a git operation."""
    success: bool
    message: str
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "success": self.success,
            "message": self.message,
            **self.data,
        }


class TaskGitManager:
    """Manages an independent git repository for a single quant research task.

    The repository lives at ``task_dir`` and is completely isolated from the
    agent's own git repo. All git operations are scoped to this directory
    using ``git -C <task_dir>`` so they never affect the agent repo context.

    Usage::

        mgr = TaskGitManager(
            task_dir=Path("/workspace/xauusd_reversal"),
            task_name="xauusd_reversal",
        )
        mgr.init_task_repo()
        # ... user makes changes ...
        mgr.commit_all("feat: add mean-reversion strategy")
        mgr.log()
    """

    def __init__(self, task_dir: Path, task_name: str) -> None:
        self.task_dir = Path(task_dir).resolve()
        self.task_name = task_name
        self._git_dir = self.task_dir / ".git"

        # Git identity for this task repo
        self._author_name = _TASK_GIT_AUTHOR_NAME
        self._author_email = _TASK_GIT_GIT_AUTHOR_EMAIL

    # ── Isolation checks ──────────────────────────────────────────────

    def _validate_isolation(self) -> None:
        """Ensure this task repo does not overlap with any parent git repo.

        Raises:
            IsolationError: If the task directory is inside another git repo
                or is the agent repo itself.
        """
        # Check that task_dir is not inside a parent .git
        current = self.task_dir.parent
        while current != current.parent:  # stop at filesystem root
            if (current / ".git").exists():
                raise IsolationError(
                    f"Task directory {self.task_dir} is inside another git "
                    f"repository at {current}. This violates the isolation "
                    f"requirement. Task repos must be in a workspace that is "
                    f"NOT a git repository itself, or must be at the top level."
                )
            current = current.parent

    def _validate_not_agent_repo(self, agent_repo_root: Path | None = None) -> None:
        """Ensure task_dir is not the agent repo or a subdirectory of it.

        Args:
            agent_repo_root: Path to the agent's own git repo root.
                If None, attempts to detect automatically.
        """
        if agent_repo_root is None:
            # Try to find agent repo by walking up from this file
            current = Path(__file__).resolve().parent
            while current != current.parent:
                if (current / ".git").exists() and (current / "agent").is_dir():
                    agent_repo_root = current
                    break
                current = current.parent

        if agent_repo_root is not None:
            agent_repo_root = Path(agent_repo_root).resolve()
            try:
                self.task_dir.relative_to(agent_repo_root)
                raise IsolationError(
                    f"Task directory {self.task_dir} is inside the agent "
                    f"repository at {agent_repo_root}. Task repos must be "
                    f"completely separate from the agent repository."
                )
            except ValueError:
                pass  # task_dir is not inside agent_repo_root — good

    # ── Core git operations ────────────────────────────────────────────

    def _run_git(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        """Run a git command scoped to this task's directory.

        Uses ``git -C <task_dir>`` to avoid changing the working directory.
        Sets GIT_AUTHOR_NAME/EMAIL and GIT_COMMITTER_NAME/EMAIL to the
        task identity so commits are never attributed to the agent's git
        config.
        """
        cmd = [
            "git", "-C", str(self.task_dir),
            *args,
        ]
        env_override = {
            "GIT_AUTHOR_NAME": self._author_name,
            "GIT_AUTHOR_EMAIL": self._author_email,
            "GIT_COMMITTER_NAME": self._author_name,
            "GIT_COMMITTER_EMAIL": self._author_email,
            # Prevent git from asking for input
            "GIT_TERMINAL_PROMPT": "0",
        }
        import os
        env = {**os.environ, **env_override}

        logger.debug("TaskGit [%s]: %s", self.task_name, " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=env,
            timeout=60,
        )
        if check and result.returncode != 0:
            raise GitOperationError(
                f"git {' '.join(args)} failed (rc={result.returncode}): "
                f"{result.stderr.strip() or result.stdout.strip()}"
            )
        return result

    # ── Public API ─────────────────────────────────────────────────────

    def is_initialized(self) -> bool:
        """Check if the task repo has been initialized."""
        return self._git_dir.is_dir()

    def init_task_repo(
        self,
        agent_repo_root: Path | None = None,
        skip_isolation_check: bool = False,
    ) -> GitResult:
        """Initialize a new independent git repo for this task.

        Creates:
        - ``<task_dir>/.git/`` (the repository)
        - ``<task_dir>/.gitignore`` (sensible defaults)
        - Initial commit with all existing files

        Args:
            agent_repo_root: Path to the agent repo root, used for
                isolation validation. Auto-detected if None.
            skip_isolation_check: Skip isolation validation (for testing
                or special cases). Default False.

        Returns:
            GitResult with success status and commit hash.
        """
        if self.is_initialized():
            return GitResult(
                success=True,
                message=f"Task repo already initialized at {self.task_dir}",
                data={"commit": self.current_commit()},
            )

        # Validate isolation
        if not skip_isolation_check:
            self._validate_not_agent_repo(agent_repo_root)
            # Note: _validate_isolation checks for parent .git dirs.
            # For workspace/<task>/ structure, the workspace dir should
            # NOT be a git repo, so this check is valid.

        # Ensure task directory exists
        self.task_dir.mkdir(parents=True, exist_ok=True)

        # git init
        self._run_git("init")

        # Set git config for this repo so task-managed repos are
        # identifiable via `git config user.name`
        self._run_git("config", "user.name", self._author_name)
        self._run_git("config", "user.email", self._author_email)

        logger.info("Initialized task git repo at %s", self.task_dir)

        # Write .gitignore
        gitignore_path = self.task_dir / ".gitignore"
        if not gitignore_path.exists():
            gitignore_path.write_text(_DEFAULT_GITIGNORE, encoding="utf-8")

        # Initial commit
        self._run_git("add", "-A")
        # git commit may fail if there are no files — that's OK
        result = self._run_git(
            "commit", "-m", f"init: task {self.task_name}",
            "--allow-empty",
            check=False,
        )
        if result.returncode != 0:
            logger.warning("Initial commit had issues: %s", result.stderr)

        return GitResult(
            success=True,
            message=f"Initialized task repo for '{self.task_name}' at {self.task_dir}",
            data={"commit": self.current_commit()},
        )

    def commit_all(self, message: str) -> GitResult:
        """Stage all changes and commit.

        Args:
            message: Commit message.

        Returns:
            GitResult with commit hash and count of changed files.
        """
        if not self.is_initialized():
            return GitResult(
                success=False,
                message="Task repo not initialized. Call init_task_repo() first.",
            )

        # Check for changes
        status_result = self._run_git("status", "--porcelain")
        changed_files = [
            line.strip() for line in status_result.stdout.strip().splitlines()
            if line.strip()
        ]

        if not changed_files:
            return GitResult(
                success=True,
                message="No changes to commit.",
                data={"commit": self.current_commit(), "changed_files": 0},
            )

        # Stage all
        self._run_git("add", "-A")

        # Commit
        self._run_git("commit", "-m", message)

        commit_hash = self.current_commit()
        logger.info(
            "TaskGit [%s]: committed %d files as %s",
            self.task_name, len(changed_files), commit_hash[:8],
        )

        return GitResult(
            success=True,
            message=f"Committed {len(changed_files)} file(s): {message}",
            data={
                "commit": commit_hash,
                "changed_files": len(changed_files),
                "files": changed_files[:20],  # Limit to first 20 for brevity
            },
        )

    def has_changes(self) -> bool:
        """Check if there are uncommitted changes."""
        if not self.is_initialized():
            return False
        result = self._run_git("status", "--porcelain")
        return bool(result.stdout.strip())

    def status(self) -> GitResult:
        """Get the working tree status.

        Returns:
            GitResult with list of changed files and their status codes.
        """
        if not self.is_initialized():
            return GitResult(
                success=False,
                message="Task repo not initialized.",
            )

        result = self._run_git("status", "--porcelain")
        files = [
            line.strip() for line in result.stdout.strip().splitlines()
            if line.strip()
        ]

        staged = [f for f in files if f[:1] in ("M", "A", "D", "R")]
        unstaged = [f for f in files if f[1:2] in ("M", "A", "D")]

        return GitResult(
            success=True,
            message=f"{len(files)} changed file(s)",
            data={
                "total": len(files),
                "staged": len(staged),
                "unstaged": len(unstaged),
                "files": files[:30],
                "clean": len(files) == 0,
            },
        )

    def log(self, n: int = 10) -> GitResult:
        """Show commit history.

        Args:
            n: Number of recent commits to show.

        Returns:
            GitResult with list of commit entries.
        """
        if not self.is_initialized():
            return GitResult(
                success=False,
                message="Task repo not initialized.",
            )

        result = self._run_git(
            "log", f"-{n}", "--pretty=format:%h|%an|%ai|%s", "--no-color"
        )
        commits = []
        for line in result.stdout.strip().splitlines():
            if not line.strip():
                continue
            parts = line.split("|", 3)
            if len(parts) == 4:
                commits.append({
                    "hash": parts[0],
                    "author": parts[1],
                    "date": parts[2],
                    "message": parts[3],
                })

        return GitResult(
            success=True,
            message=f"Last {len(commits)} commit(s)",
            data={"commits": commits, "count": len(commits)},
        )

    def diff(self, ref: str = "HEAD") -> GitResult:
        """Show diff against a reference.

        Args:
            ref: Git reference to diff against (default: HEAD).

        Returns:
            GitResult with diff text.
        """
        if not self.is_initialized():
            return GitResult(
                success=False,
                message="Task repo not initialized.",
            )

        result = self._run_git("diff", ref, "--stat")
        stat = result.stdout.strip()

        result_full = self._run_git("diff", ref, "--no-color")
        full_diff = result_full.stdout.strip()

        return GitResult(
            success=True,
            message=f"Diff against {ref}" + ("" if stat else " (no changes)"),
            data={"ref": ref, "stat": stat, "diff": full_diff[:5000]},
        )

    def rollback(self, ref: str = "HEAD~1") -> GitResult:
        """Rollback (hard reset) to a previous commit.

        ⚠ This is a destructive operation. Uncommitted changes will be lost.
        The rolled-back commits are still recoverable via ``git reflog``
        for 30 days by default.

        Args:
            ref: Git reference to reset to (default: HEAD~1 = one commit back).

        Returns:
            GitResult with the new HEAD commit hash.
        """
        if not self.is_initialized():
            return GitResult(
                success=False,
                message="Task repo not initialized.",
            )

        # Save current commit for the message
        old_commit = self.current_commit()

        # Verify ref exists
        verify = self._run_git("rev-parse", "--verify", ref, check=False)
        if verify.returncode != 0:
            return GitResult(
                success=False,
                message=f"Cannot rollback: reference '{ref}' does not exist.",
            )

        # Hard reset
        self._run_git("reset", "--hard", ref)

        new_commit = self.current_commit()
        logger.warning(
            "TaskGit [%s]: rolled back from %s to %s (ref=%s)",
            self.task_name, old_commit[:8], new_commit[:8], ref,
        )

        return GitResult(
            success=True,
            message=f"Rolled back from {old_commit[:8]} to {new_commit[:8]} (ref={ref})",
            data={
                "old_commit": old_commit,
                "new_commit": new_commit,
                "ref": ref,
                "note": "Rolled-back commits are recoverable via 'git reflog' for ~30 days.",
            },
        )

    def current_commit(self) -> str:
        """Get the current HEAD commit hash.

        Returns:
            Full commit hash string, or "none" if no commits exist.
        """
        if not self.is_initialized():
            return "none"
        result = self._run_git("rev-parse", "HEAD", check=False)
        if result.returncode != 0:
            return "none"
        return result.stdout.strip()

    def get_summary(self) -> dict[str, Any]:
        """Get a summary of the task repo state.

        Returns:
            Dict with task_name, initialized, commit, has_changes, etc.
        """
        return {
            "task_name": self.task_name,
            "task_dir": str(self.task_dir),
            "initialized": self.is_initialized(),
            "current_commit": self.current_commit() if self.is_initialized() else None,
            "has_changes": self.has_changes() if self.is_initialized() else False,
        }


class IsolationError(Exception):
    """Raised when a task repo would violate isolation from other git repos."""
    pass


class GitOperationError(Exception):
    """Raised when a git operation fails."""
    pass
