"""Tests for --self-dev mode wiring.

Covers:
- enable / disable / is_self_dev_mode globals in settings
- guard reshape (protected paths reduced, repo root becomes workspace)
- write_file is actually authorised against agent/ when in self-dev mode
- .git/ stays protected even in self-dev
- build_system_prompt(self_dev=True) appends the addendum
- self_dev skill is discoverable
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Always restore default state after each test — these tests mutate a global.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_default_guard():
    from agent.infrastructure.config import settings as settings_mod
    yield
    settings_mod.disable_self_dev_mode()


# ---------------------------------------------------------------------------
# Settings: enable / disable / is_self_dev_mode
# ---------------------------------------------------------------------------

def test_is_self_dev_mode_starts_false():
    from agent.infrastructure.config import settings as settings_mod
    settings_mod.disable_self_dev_mode()  # paranoia
    assert settings_mod.is_self_dev_mode() is False


def test_enable_self_dev_mode_flips_flag_and_returns_new_guard():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_dev_mode()
    assert settings_mod.is_self_dev_mode() is True
    assert g is settings_mod.get_workspace_guard()


def test_self_dev_workspace_root_is_quanora_repo():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_dev_mode()
    assert g.root == settings_mod._QUANORA_REPO_ROOT.resolve()


def test_self_dev_protected_paths_only_git_and_env():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_dev_mode()
    names = {p.name for p in g.protected_paths}
    # .git always exists (this IS a git repo). .env may or may not.
    assert ".git" in names
    # Whatever is protected must be a strict subset of {.git, .env}.
    assert names.issubset({".git", ".env"})
    # And the count is small (1 or 2) — definitely not the default 10.
    assert len(g.protected_paths) <= 2


def test_self_dev_allows_writing_into_agent_dir():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_dev_mode()
    target = settings_mod._QUANORA_REPO_ROOT / "agent" / "hypothetical.py"
    assert g.check_write(target) is None  # ALLOWED


def test_self_dev_still_blocks_git_writes():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_dev_mode()
    target = settings_mod._QUANORA_REPO_ROOT / ".git" / "HEAD"
    violation = g.check_write(target)
    assert violation is not None
    assert violation.status == "protected"


def test_disable_self_dev_restores_defaults():
    from agent.infrastructure.config import settings as settings_mod
    settings_mod.enable_self_dev_mode()
    settings_mod.disable_self_dev_mode()
    assert settings_mod.is_self_dev_mode() is False
    g = settings_mod.get_workspace_guard()
    # The default guard protects 10 paths (agent/, test/, .quanora/, etc.).
    # Be tolerant of the exact count, but assert it's clearly the default set.
    names = {p.name for p in g.protected_paths}
    assert "agent" in names
    assert ".git" in names
    assert len(g.protected_paths) >= 5


# ---------------------------------------------------------------------------
# Prompt: self-dev addendum is conditional
# ---------------------------------------------------------------------------

def test_build_system_prompt_default_omits_self_dev():
    from agent.prompts import build_system_prompt
    p = build_system_prompt(self_dev=False)
    assert "<self_dev_mode" not in p
    assert "SELF-DEVELOPMENT MODE" not in p


def test_build_system_prompt_self_dev_appends_addendum():
    from agent.prompts import build_system_prompt
    p = build_system_prompt(self_dev=True)
    assert "<self_dev_mode" in p
    # The mandatory workflow is mentioned by number.
    assert "Mandatory workflow" in p or "mandatory workflow" in p.lower()
    # The PR step is described.
    assert "gh pr create" in p
    assert "genspark_ai_developer" in p


def test_self_dev_prompt_includes_workspace_boundary_warning():
    """Self-dev relaxes protected paths but the workspace_boundary
    section still applies — the prompt must NOT promise unrestricted access."""
    from agent.prompts import build_system_prompt
    p = build_system_prompt(self_dev=True)
    # data_integrity_mandate and workspace_boundary survive
    assert "<data_integrity_mandate" in p
    assert "<workspace_boundary" in p
    # but .git is still off-limits
    assert ".git" in p


# ---------------------------------------------------------------------------
# Integration: write_file actually works against agent/ when self-dev is on
# ---------------------------------------------------------------------------

def test_write_file_into_agent_is_blocked_by_default(tmp_path):
    """Sanity: without self-dev, the guard rejects writes into agent/."""
    from agent.infrastructure.config import settings as settings_mod
    from agent.infrastructure.tools.impl.tools.file_ops import write_file

    settings_mod.disable_self_dev_mode()
    target = settings_mod._QUANORA_REPO_ROOT / "agent" / "_should_not_appear.py"
    r = json.loads(write_file(str(target), "# nope"))
    assert r["ok"] is False
    assert r["error_type"] == "WorkspaceViolation"
    assert r["meta"]["violation_status"] == "protected"
    # And the file MUST NOT exist (we never wrote it).
    assert not target.exists()


def test_write_file_into_agent_works_with_self_dev():
    """In self-dev mode, the same write succeeds. We immediately delete the
    test artefact so it doesn't pollute the repo."""
    from agent.infrastructure.config import settings as settings_mod
    from agent.infrastructure.tools.impl.tools.file_ops import write_file

    settings_mod.enable_self_dev_mode()
    target = settings_mod._QUANORA_REPO_ROOT / "agent" / "_self_dev_test_artifact.py"
    try:
        r = json.loads(write_file(str(target), "# self-dev test artefact\n"))
        assert r["ok"] is True, r
        assert target.exists()
        assert target.read_text(encoding="utf-8").startswith("# self-dev test")
    finally:
        if target.exists():
            target.unlink()


def test_write_file_into_git_still_blocked_in_self_dev():
    from agent.infrastructure.config import settings as settings_mod
    from agent.infrastructure.tools.impl.tools.file_ops import write_file

    settings_mod.enable_self_dev_mode()
    target = settings_mod._QUANORA_REPO_ROOT / ".git" / "HEAD"
    r = json.loads(write_file(str(target), "ref: refs/heads/pwned"))
    assert r["ok"] is False
    assert r["error_type"] == "WorkspaceViolation"
    assert r["meta"]["violation_status"] == "protected"


# ---------------------------------------------------------------------------
# Bootstrap wiring
# ---------------------------------------------------------------------------

def test_bootstrap_threads_self_dev_into_system_prompt(tmp_path):
    """build_basic_agent_dependencies(self_dev=True) must seed the session
    with the self-dev addendum, not the base prompt."""
    from agent.bootstrap import build_basic_agent_dependencies

    deps = build_basic_agent_dependencies(
        session_dir=str(tmp_path),
        self_dev=True,
    )
    session = deps["session"]
    # The session store exposes its system prompt via property.
    sp = session.system_prompt
    assert "<self_dev_mode" in sp


def test_bootstrap_default_omits_self_dev_addendum(tmp_path):
    from agent.bootstrap import build_basic_agent_dependencies

    deps = build_basic_agent_dependencies(
        session_dir=str(tmp_path),
        self_dev=False,
    )
    sp = deps["session"].system_prompt
    assert "<self_dev_mode" not in sp


# ---------------------------------------------------------------------------
# Skill discovery
# ---------------------------------------------------------------------------

def test_self_dev_skill_is_discoverable():
    """The self_dev skill must be picked up by the repository so it can be
    auto-injected when its triggers fire."""
    from agent.infrastructure.skills import SkillRepository

    repo = SkillRepository()
    skill = repo.get_skill("self_dev")
    assert skill is not None
    # Triggers should include both English and Chinese phrases.
    triggers = {t.lower() for t in skill.triggers}
    assert any("self-dev" in t or "self_dev" in t for t in triggers)
    assert any("自我" in t for t in skill.triggers)


def test_self_dev_skill_mentions_workflow_steps():
    from agent.infrastructure.skills import SkillRepository

    repo = SkillRepository()
    skill = repo.get_skill("self_dev")
    assert skill is not None
    body = skill.body or ""
    # Spot-check that the 10-step workflow is documented.
    for keyword in ("plan_create", "git rebase", "gh pr create", "genspark_ai_developer"):
        assert keyword in body, f"self_dev skill missing keyword: {keyword}"


# ---------------------------------------------------------------------------
# switch_to_project_workspace: self-dev mode should NOT create workspace/ sub-dir
# ---------------------------------------------------------------------------


def test_switch_to_project_workspace_self_dev_uses_repo_root():
    """In self-dev mode, switch_to_project_workspace should set project_dir
    to the repo root (not a workspace/ sub-directory)."""
    from agent.infrastructure.config import settings as settings_mod

    settings_mod.disable_self_dev_mode()
    settings_mod.enable_self_dev_mode()

    try:
        # Record existing workspace/ sub-dirs before the call
        workspace_dir = settings_mod._QUANORA_REPO_ROOT / "workspace"
        before = set()
        if workspace_dir.exists():
            before = {d.name for d in workspace_dir.iterdir() if d.is_dir()}

        result = settings_mod.switch_to_project_workspace(
            task_description="test task for self dev"
        )
        # The returned project_dir should be the repo root itself
        assert result == settings_mod._QUANORA_REPO_ROOT

        # No NEW workspace/ sub-directory should have been created
        after = set()
        if workspace_dir.exists():
            after = {d.name for d in workspace_dir.iterdir() if d.is_dir()}
        new_dirs = after - before
        assert len(new_dirs) == 0, (
            f"switch_to_project_workspace should not create new workspace/ "
            f"sub-dirs in self-dev mode, found new: {new_dirs}"
        )
    finally:
        settings_mod.disable_self_dev_mode()


def test_switch_to_project_workspace_self_dev_guard_root_is_repo():
    """In self-dev mode, guard_root must be the repo root so that
    agent/ source files are writable."""
    from agent.infrastructure.config import settings as settings_mod

    settings_mod.disable_self_dev_mode()
    settings_mod.enable_self_dev_mode()

    try:
        settings_mod.switch_to_project_workspace(
            task_description="test task for self dev"
        )
        guard = settings_mod._WORKSPACE_GUARD
        assert guard._cfg.root == settings_mod._QUANORA_REPO_ROOT
        assert guard._cfg.resolve_root == settings_mod._QUANORA_REPO_ROOT
    finally:
        settings_mod.disable_self_dev_mode()


def test_switch_to_project_workspace_self_dev_workspace_still_protected():
    """In self-dev mode, workspace/ must remain in fully_protected so that
    write_file to workspace/ paths is still rejected."""
    from agent.infrastructure.config import settings as settings_mod

    settings_mod.disable_self_dev_mode()
    settings_mod.enable_self_dev_mode()

    try:
        settings_mod.switch_to_project_workspace(
            task_description="test task for self dev"
        )
        guard = settings_mod._WORKSPACE_GUARD
        workspace_path = (settings_mod._QUANORA_REPO_ROOT / "workspace").resolve()
        assert workspace_path in guard._cfg.fully_protected_paths, (
            "workspace/ must be fully_protected even in self-dev mode"
        )
    finally:
        settings_mod.disable_self_dev_mode()
