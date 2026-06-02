"""Self-dev mode hook: automatically push + PR after each turn with commits.

When the agent is in self-dev mode and finishes a turn that left un-pushed
commits on the ``genspark_ai_developer`` branch, this hook automatically:

1. ``git fetch origin main`` + ``git rebase origin/main``
2. Squash incremental commits (optional, controlled by config)
3. ``git push -f origin genspark_ai_developer``
4. Open a Pull Request via ``gh pr create`` (or fall back to URL)

This removes the reliance on the LLM *remembering* steps 6-10 of the
SELF_DEV_MODE_PROMPT.  The hook is deterministic code, not a prompt.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

BRANCH = "genspark_ai_developer"
BASE_BRANCH = "main"

# ---------------------------------------------------------------------------
# Test-file cleanup patterns
# ---------------------------------------------------------------------------
# In self-dev mode the agent may generate temporary test files (e.g. HTML
# outputs from generate_ppt_html / generate_doc_html) that should NOT be
# pushed to GitHub.  These patterns are matched against files tracked by
# git in the repo root directory.  Matching files are removed before push.
#
# Each entry is a dict with:
#   pattern  – fnmatch-style glob (matched against the filename only)
#   reason   – human-readable explanation for the log
TEST_CLEANUP_PATTERNS: list[dict[str, str]] = [
    {"pattern": "*.html", "reason": "generated HTML test/demo file"},
]


def _cleanup_test_files(repo_root: Path) -> list[str]:
    """Remove git-tracked files matching TEST_CLEANUP_PATTERNS from repo root.

    Only files in the **root** directory are considered, so ``docs/*.html``
    or ``agent/templates/*.html`` are left alone.

    Returns a list of removed file paths (relative to repo_root).
    """
    removed: list[str] = []

    # Bail out early if the directory doesn't look like a valid git repo
    if not repo_root.is_dir():
        return removed
    git_dir = repo_root / ".git"
    if not git_dir.exists():
        return removed

    # Get the list of git-tracked files in the repo root only
    r = _run_git("ls-files", "--", cwd=repo_root, check=False)
    if r.returncode != 0:
        logger.warning("git ls-files failed, skipping test-file cleanup")
        return removed

    import fnmatch

    root_files = [f for f in r.stdout.splitlines() if f and "/" not in f]
    for tracked in root_files:
        for entry in TEST_CLEANUP_PATTERNS:
            if fnmatch.fnmatch(tracked, entry["pattern"]):
                # Remove from git index and disk
                _run_git("rm", "--cached", "-f", tracked, cwd=repo_root, check=False)
                full_path = repo_root / tracked
                if full_path.exists():
                    try:
                        full_path.unlink()
                    except OSError:
                        pass
                removed.append(tracked)
                logger.info(
                    "Cleaned up test file: %s (%s)", tracked, entry["reason"]
                )
                break  # one match is enough

    if removed:
        # Commit the cleanup so it's included in the push
        _run_git("add", "-A", cwd=repo_root, check=False)
        _run_git(
            "commit", "-m", "chore: auto-cleanup test files before push",
            cwd=repo_root, check=False,
        )
        logger.info("Committed removal of %d test file(s): %s", len(removed), removed)

    return removed


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class PushResult:
    """Outcome of a push+PR attempt."""
    pushed: bool = False
    pr_url: Optional[str] = None
    pr_number: Optional[int] = None
    error: Optional[str] = None
    commit_count: int = 0
    cleaned_files: Optional[list[str]] = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_git(
    *args: str,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command, return CompletedProcess."""
    cmd = ["git"] + list(args)
    logger.debug("Running: %s (cwd=%s)", " ".join(cmd), cwd or ".")
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=check,
        cwd=cwd,
    )


def _run_gh(
    *args: str,
    cwd: Path | None = None,
    token: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run a ``gh`` CLI command, optionally with GH_TOKEN."""
    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token
    cmd = ["gh"] + list(args)
    logger.debug("Running: %s (cwd=%s, token=%s)", " ".join(cmd), cwd, bool(token))
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        check=check,
        cwd=cwd,
        env=env,
    )


def _get_gh_token() -> Optional[str]:
    """Extract a GitHub token from ``~/.git-credentials`` (same logic as prompt)."""
    cred_file = Path.home() / ".git-credentials"
    if not cred_file.exists():
        return None
    try:
        for line in cred_file.read_text().splitlines():
            m = re.search(r"x-access-token:([^@]+)@", line)
            if m:
                return m.group(1)
    except OSError:
        pass
    return None


def _count_unpushed_commits(repo_root: Path, branch: str = BRANCH) -> int:
    """Return the number of commits on *branch* not yet on ``origin/<branch>``."""
    # Ensure remote ref exists
    _run_git("fetch", "origin", branch, cwd=repo_root, check=False)
    result = _run_git(
        "rev-list",
        "--count",
        f"origin/{branch}..HEAD",
        cwd=repo_root,
        check=False,
    )
    if result.returncode != 0:
        # Maybe no remote branch yet — count all commits
        result2 = _run_git("rev-list", "--count", "HEAD", cwd=repo_root, check=False)
        return int(result2.stdout.strip()) if result2.returncode == 0 else 0
    return int(result.stdout.strip())


def _current_branch(repo_root: Path) -> str:
    result = _run_git("rev-parse", "--abbrev-ref", "HEAD", cwd=repo_root, check=True)
    return result.stdout.strip()


def _ensure_branch(repo_root: Path) -> None:
    """Make sure we are on ``genspark_ai_developer``, creating it from main if needed."""
    current = _current_branch(repo_root)
    if current == BRANCH:
        return
    # Try to check out existing branch
    r = _run_git("checkout", BRANCH, cwd=repo_root, check=False)
    if r.returncode != 0:
        # Branch doesn't exist yet — create from main
        _run_git("checkout", "-b", BRANCH, cwd=repo_root, check=True)


def _has_staged_or_unstaged_changes(repo_root: Path) -> bool:
    """Return True if there are uncommitted changes (staged or unstaged)."""
    r = _run_git("status", "--porcelain", cwd=repo_root, check=True)
    return bool(r.stdout.strip())


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def auto_push_and_pr(
    repo_root: Path,
    squash: bool = True,
    dry_run: bool = False,
) -> PushResult:
    """Execute the self-dev push+PR pipeline.

    Parameters
    ----------
    repo_root:
        Path to the git repository root.
    squash:
        If True, squash all incremental commits on the branch into a single
        commit before pushing.  This keeps the PR history clean.
    dry_run:
        If True, only report what *would* happen — don't actually push or
        create a PR.

    Returns
    -------
    PushResult
    """
    result = PushResult()

    # 1. Ensure we're on the right branch
    try:
        _ensure_branch(repo_root)
    except subprocess.CalledProcessError as exc:
        result.error = f"Failed to switch to {BRANCH}: {exc.stderr}"
        return result

    # 2. Check for uncommitted changes — if any, commit them first
    if _has_staged_or_unstaged_changes(repo_root):
        _run_git("add", "-A", cwd=repo_root, check=True)
        _run_git("commit", "-m", "chore: auto-commit before push", cwd=repo_root, check=True)
        logger.info("Auto-committed pending changes before push.")

    # 2.5. Cleanup test/temporary files before push
    #      In self-dev mode the agent may generate temporary test files
    #      (e.g. HTML outputs) that must NOT be pushed to GitHub.
    cleaned = _cleanup_test_files(repo_root)
    if cleaned:
        result.cleaned_files = cleaned
        logger.info("Cleaned up %d test file(s) before push: %s", len(cleaned), cleaned)

    # 3. Count un-pushed commits
    try:
        result.commit_count = _count_unpushed_commits(repo_root)
    except Exception as exc:
        result.error = f"Failed to count unpushed commits: {exc}"
        return result

    if result.commit_count == 0:
        logger.info("No un-pushed commits — nothing to do.")
        return result

    if dry_run:
        logger.info("[DRY RUN] Would push %d commit(s) and create PR.", result.commit_count)
        return result

    # 4. Fetch + rebase
    try:
        _run_git("fetch", "origin", BASE_BRANCH, cwd=repo_root, check=True)
    except subprocess.CalledProcessError as exc:
        result.error = f"git fetch origin {BASE_BRANCH} failed: {exc.stderr}"
        return result

    try:
        _run_git("rebase", f"origin/{BASE_BRANCH}", cwd=repo_root, check=True)
    except subprocess.CalledProcessError as exc:
        # Rebase conflict — abort and report
        _run_git("rebase", "--abort", cwd=repo_root, check=False)
        result.error = f"git rebase failed (conflict?): {exc.stderr}"
        return result

    # 5. Squash incremental commits (optional)
    if squash and result.commit_count > 1:
        try:
            _run_git(
                "reset", "--soft", f"HEAD~{result.commit_count}",
                cwd=repo_root, check=True,
            )
            # Use the first commit's message as the squash message
            # (or a generic one)
            msg_result = _run_git(
                "log", "--format=%s", "-1", "HEAD",
                cwd=repo_root, check=True,
            )
            squash_msg = msg_result.stdout.strip() or "feat: self-dev improvements"
            _run_git("commit", "-m", squash_msg, cwd=repo_root, check=True)
            logger.info("Squashed %d commits into one.", result.commit_count)
        except subprocess.CalledProcessError as exc:
            logger.warning("Squash failed, pushing unsquashed: %s", exc.stderr)

    # 6. Push (force-needed after rebase/squash)
    try:
        _run_git("push", "-f", "origin", BRANCH, cwd=repo_root, check=True)
        result.pushed = True
        logger.info("Pushed to origin/%s.", BRANCH)
    except subprocess.CalledProcessError as exc:
        result.error = f"git push failed: {exc.stderr}"
        return result

    # 7. Create PR via gh CLI
    token = _get_gh_token()
    pr_body = _build_pr_body(repo_root)

    # Write PR body to a temp file to avoid shell quoting issues
    import tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", delete=False, prefix="pr_body_"
    ) as tf:
        tf.write(pr_body)
        body_file = tf.name

    try:
        r = _run_gh(
            "pr", "create",
            "--base", BASE_BRANCH,
            "--head", BRANCH,
            "--title", _build_pr_title(repo_root),
            "--body-file", body_file,
            cwd=repo_root,
            token=token,
            check=False,
        )
    finally:
        try:
            os.unlink(body_file)
        except OSError:
            pass

    if r.returncode == 0:
        # Parse PR URL from output
        output = r.stdout.strip()
        # gh pr create outputs the URL on the last line
        for line in output.splitlines():
            m = re.match(r"(https://github\.com/.+/pull/\d+)", line.strip())
            if m:
                result.pr_url = m.group(1)
                # Extract PR number
                num_match = re.search(r"/pull/(\d+)", m.group(1))
                if num_match:
                    result.pr_number = int(num_match.group(1))
                break
        if not result.pr_url:
            # Sometimes gh outputs just the URL
            result.pr_url = output.splitlines()[-1] if output else None
        logger.info("PR created: %s", result.pr_url)
    else:
        # PR might already exist — that's fine
        stderr = r.stderr or ""
        if "already exists" in stderr.lower():
            logger.info("PR already exists — skipping creation.")
            # Try to get existing PR URL
            r2 = _run_gh(
                "pr", "view", BRANCH,
                "--json", "url,number",
                cwd=repo_root,
                token=token,
                check=False,
            )
            if r2.returncode == 0:
                import json
                try:
                    pr_data = json.loads(r2.stdout)
                    result.pr_url = pr_data.get("url")
                    result.pr_number = pr_data.get("number")
                except (json.JSONDecodeError, KeyError):
                    pass
        else:
            logger.warning("gh pr create failed: %s", stderr)
            result.error = f"gh pr create failed: {stderr}"

    return result


# ---------------------------------------------------------------------------
# PR body helpers
# ---------------------------------------------------------------------------

def _build_pr_title(repo_root: Path) -> str:
    """Build a PR title from the latest commit message."""
    r = _run_git("log", "--format=%s", "-1", cwd=repo_root, check=True)
    return r.stdout.strip() or "feat: self-dev improvements"


def _build_pr_body(repo_root: Path) -> str:
    """Build a PR body with Why / What changed / Tests / Files sections."""
    # Get diff stat
    r = _run_git(
        "diff", "--stat", f"origin/{BASE_BRANCH}...HEAD",
        cwd=repo_root, check=False,
    )
    diff_stat = r.stdout.strip() if r.returncode == 0 else "(unable to get diff stat)"

    # Get list of changed files
    r2 = _run_git(
        "diff", "--name-only", f"origin/{BASE_BRANCH}...HEAD",
        cwd=repo_root, check=False,
    )
    changed_files = r2.stdout.strip().splitlines() if r2.returncode == 0 else []

    # Get commit messages for context
    r3 = _run_git(
        "log", "--format=- %s", f"origin/{BASE_BRANCH}...HEAD",
        cwd=repo_root, check=False,
    )
    commit_msgs = r3.stdout.strip() if r3.returncode == 0 else ""

    modified = [f for f in changed_files if not f.startswith("test/")]
    created = []  # No easy way to distinguish without full diff
    tests = [f for f in changed_files if f.startswith("test/")]

    body = f"""## Why
Self-dev mode automated improvements.

## What changed
{commit_msgs}

## Tests
- `python3 -m pytest test/ --no-header -q`

## Files
- Modified: {', '.join(modified) if modified else 'none'}
- Created: {', '.join(created) if created else 'none'}
- Tests: {', '.join(tests) if tests else 'none'}

## Diff stat
```
{diff_stat}
```
"""
    return body


# ---------------------------------------------------------------------------
# Hook interface (called from chat_cli on TurnCompletedEvent)
# ---------------------------------------------------------------------------

def on_turn_completed_self_dev(repo_root: Path, *, trigger: str = "TurnCompletedEvent") -> None:
    """Entry point for the self-dev push hook.

    Called by ChatCLI when a turn completes (or fails/cancels) in
    self-dev mode.  If there are un-pushed commits, runs the push+PR
    pipeline automatically and prints a summary to stderr.

    Parameters
    ----------
    trigger :
        Which event triggered this call.  Used for logging only.
        One of ``"TurnCompletedEvent"``, ``"TurnFailedEvent"``,
        ``"TurnCancelledEvent"``.
    """
    try:
        # Quick check: are we on the right branch?
        current = _current_branch(repo_root)
        if current != BRANCH:
            print(
                f"[self-dev] Skipping push hook: on branch '{current}', "
                f"not '{BRANCH}' (trigger={trigger})",
                file=sys.stderr,
            )
            return

        # Quick check: any un-pushed commits?
        count = _count_unpushed_commits(repo_root)
        if count == 0:
            # Only log at debug level when there's nothing to push
            logger.debug("No un-pushed commits, skipping self-dev push hook (trigger=%s).", trigger)
            return

        print(
            f"\n[self-dev] Detected {count} un-pushed commit(s) — "
            f"auto-running push + PR pipeline (trigger={trigger}) …",
            file=sys.stderr,
        )

        result = auto_push_and_pr(repo_root, squash=True)

        if result.error:
            print(f"[self-dev] ❌ Push/PR failed: {result.error}", file=sys.stderr)
        else:
            if result.pushed:
                print(f"[self-dev] ✅ Pushed {result.commit_count} commit(s).", file=sys.stderr)
            if result.pr_url:
                print(f"[self-dev] ✅ PR: {result.pr_url}", file=sys.stderr)
            elif result.pushed:
                print("[self-dev] ⚠ Pushed but PR creation failed or PR already exists.", file=sys.stderr)

    except Exception as exc:
        # Never let the hook crash the CLI
        logger.exception("Self-dev push hook failed unexpectedly (trigger=%s)", trigger)
        print(f"[self-dev] ❌ Hook error: {exc}", file=sys.stderr)
        print(
            "[self-dev] You may need to manually: "
            "git push origin genspark_ai_developer && gh pr create",
            file=sys.stderr,
        )
