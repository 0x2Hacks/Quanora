"""Task-level git version control tools for quant research.

Provides tools that let the agent manage independent git repositories
for each quant research task. These repos are strictly isolated from
the agent's own git repo.

Tools:
1. task_git_init    — Initialize a task git repo
2. task_git_commit  — Stage all changes and commit
3. task_git_rollback — Rollback to a previous commit
4. task_git_log     — View commit history
5. task_git_status  — Check working tree status
6. task_git_diff    — Show diff against a reference
7. task_git_info    — Get task repo summary
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any

from agent.domain.tool_result import tool_error, tool_ok
from agent.infrastructure.task_git import (
    IsolationError,
    GitOperationError,
    TaskGitManager,
)

_TOOL_NAME = "task_git"

# ── Active task repo registry (per-session) ──────────────────────────
# Maps task_name → TaskGitManager instance, so the agent doesn't need to
# pass task_dir on every call.

_active_repos: dict[str, TaskGitManager] = {}


def _get_or_create_manager(
    task_name: str,
    task_dir: str | None = None,
) -> tuple[TaskGitManager | None, str]:
    """Get an existing manager or create a new one.

    Returns (manager, error_message). If manager is None, error_message
    explains why.
    """
    if task_name in _active_repos:
        return _active_repos[task_name], ""

    if task_dir is None:
        return None, (
            f"Task '{task_name}' has no active git manager. "
            "Provide task_dir to initialize, or call task_git_init first."
        )

    from agent.infrastructure.config import Config
    workspace = Path(Config.WORKSPACE_ROOT) if Config.WORKSPACE_ROOT else Path(".")

    resolved_dir = (workspace / task_dir).resolve()

    mgr = TaskGitManager(task_dir=resolved_dir, task_name=task_name)
    _active_repos[task_name] = mgr
    return mgr, ""


# ── Tool functions ────────────────────────────────────────────────────

def task_git_init(
    task_name: str,
    task_dir: str = "",
    skip_isolation_check: bool = False,
) -> str:
    """Initialize an independent git repository for a quant research task.
    Each task gets its own isolated .git/ directory, completely separate from
    the agent's git repo. Called automatically during onboarding when a new
    task is created.

    Args:
        task_name: Name of the task (e.g. "xauusd_reversal").
        task_dir: Task workspace directory path (relative to workspace root).
            If empty, defaults to <workspace>/<task_name>/.
        skip_isolation_check: Skip isolation validation (for testing only).
    """
    from agent.infrastructure.config import Config
    workspace = Path(Config.WORKSPACE_ROOT) if Config.WORKSPACE_ROOT else Path(".")

    if not task_dir:
        task_dir = task_name

    resolved_dir = (workspace / task_dir).resolve()

    mgr = TaskGitManager(task_dir=resolved_dir, task_name=task_name)
    _active_repos[task_name] = mgr

    try:
        result = mgr.init_task_repo(skip_isolation_check=skip_isolation_check)
    except IsolationError as e:
        return tool_error(_TOOL_NAME, f"Isolation violation: {e}")
    except GitOperationError as e:
        return tool_error(_TOOL_NAME, f"Git operation failed: {e}")

    return tool_ok(_TOOL_NAME, result.message, result.data)


def task_git_commit(
    task_name: str,
    message: str,
) -> str:
    """Stage all changes in the task workspace and create a git commit.
    Should be called after every meaningful code or configuration change
    to maintain version history. The commit author is 'QuantTaskBot',
    separate from the agent's git identity.

    Args:
        task_name: Name of the task to commit.
        message: Commit message describing the change.
    """
    mgr, err = _get_or_create_manager(task_name)
    if mgr is None:
        return tool_error(_TOOL_NAME, err)

    try:
        result = mgr.commit_all(message)
    except GitOperationError as e:
        return tool_error(_TOOL_NAME, f"Commit failed: {e}")

    return tool_ok(_TOOL_NAME, result.message, result.data)


def task_git_rollback(
    task_name: str,
    ref: str = "HEAD~1",
) -> str:
    """Rollback the task workspace to a previous commit (hard reset).
    WARNING: This is a destructive operation. Uncommitted changes will be
    lost. However, rolled-back commits are recoverable via 'git reflog'
    for approximately 30 days. Always check task_git_log before rolling back.

    Args:
        task_name: Name of the task to rollback.
        ref: Git reference to reset to (default "HEAD~1" = one commit back).
            Examples: "HEAD~1", "HEAD~3", "abc1234" (commit hash).
    """
    mgr, err = _get_or_create_manager(task_name)
    if mgr is None:
        return tool_error(_TOOL_NAME, err)

    try:
        result = mgr.rollback(ref)
    except GitOperationError as e:
        return tool_error(_TOOL_NAME, f"Rollback failed: {e}")

    return tool_ok(_TOOL_NAME, result.message, result.data)


def task_git_log(
    task_name: str,
    n: int = 10,
) -> str:
    """View the commit history of a task's git repository.
    Use this before task_git_rollback to identify which commit to revert to.

    Args:
        task_name: Name of the task.
        n: Number of recent commits to show (default 10).
    """
    mgr, err = _get_or_create_manager(task_name)
    if mgr is None:
        return tool_error(_TOOL_NAME, err)

    try:
        result = mgr.log(n)
    except GitOperationError as e:
        return tool_error(_TOOL_NAME, f"Log failed: {e}")

    return tool_ok(_TOOL_NAME, result.message, result.data)


def task_git_status(
    task_name: str,
) -> str:
    """Check the working tree status of a task's git repository.
    Shows staged, unstaged, and untracked files. Returns 'clean' if
    there are no pending changes.

    Args:
        task_name: Name of the task.
    """
    mgr, err = _get_or_create_manager(task_name)
    if mgr is None:
        return tool_error(_TOOL_NAME, err)

    try:
        result = mgr.status()
    except GitOperationError as e:
        return tool_error(_TOOL_NAME, f"Status failed: {e}")

    return tool_ok(_TOOL_NAME, result.message, result.data)


def task_git_diff(
    task_name: str,
    ref: str = "HEAD",
) -> str:
    """Show the diff between the working tree and a reference commit.
    Useful for reviewing what has changed before committing.

    Args:
        task_name: Name of the task.
        ref: Git reference to diff against (default "HEAD").
    """
    mgr, err = _get_or_create_manager(task_name)
    if mgr is None:
        return tool_error(_TOOL_NAME, err)

    try:
        result = mgr.diff(ref)
    except GitOperationError as e:
        return tool_error(_TOOL_NAME, f"Diff failed: {e}")

    return tool_ok(_TOOL_NAME, result.message, result.data)


def task_git_info(
    task_name: str,
) -> str:
    """Get a summary of a task's git repository state.
    Returns task name, directory, initialization status, current commit,
    and whether there are uncommitted changes.

    Args:
        task_name: Name of the task.
    """
    mgr, err = _get_or_create_manager(task_name)
    if mgr is None:
        return tool_error(_TOOL_NAME, err)

    return tool_ok(_TOOL_NAME, "Task git info", mgr.get_summary())
