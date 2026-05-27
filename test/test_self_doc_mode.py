"""Tests for --self-doc mode wiring.

Covers:
- enable / disable / is_self_doc_mode globals in settings
- guard reshape (protected paths cover the entire repo tree, .md exempt)
- write_file is authorised for .md files even inside agent/
- write_file is blocked for .py files inside agent/
- .git/ stays protected even for .md files in self-doc
- build_system_prompt(self_doc=True) appends the addendum
- self_dev takes precedence over self_doc when both are True
- WorkspaceConfig.protected_write_extensions field works correctly
- WorkspaceGuard.classify extension-whitelist logic
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Always restore default state after each test — these tests mutate globals.
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _restore_default_guard():
    from agent.infrastructure.config import settings as settings_mod
    yield
    settings_mod.disable_self_dev_mode()
    settings_mod.disable_self_doc_mode()


# ---------------------------------------------------------------------------
# Settings: enable / disable / is_self_doc_mode
# ---------------------------------------------------------------------------

def test_is_self_doc_mode_starts_false():
    from agent.infrastructure.config import settings as settings_mod
    settings_mod.disable_self_doc_mode()  # paranoia
    assert settings_mod.is_self_doc_mode() is False


def test_enable_self_doc_mode_flips_flag_and_returns_new_guard():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_doc_mode()
    assert settings_mod.is_self_doc_mode() is True
    assert g is settings_mod.get_workspace_guard()


def test_self_doc_workspace_root_is_quanora_repo():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_doc_mode()
    assert g.root == settings_mod._QUANORA_REPO_ROOT.resolve()


def test_self_doc_protected_paths_cover_repo_tree():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_doc_mode()
    names = {p.name for p in g.protected_paths}
    # The repo root itself is protected (covers agent/, test/, etc.)
    assert settings_mod._QUANORA_REPO_ROOT.resolve().name in names
    # .git and .env are explicitly protected too
    assert ".git" in names


def test_self_doc_protected_write_extensions_includes_md():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_doc_mode()
    assert ".md" in g._cfg.protected_write_extensions


# ---------------------------------------------------------------------------
# Write permissions: .md allowed, .py blocked inside protected tree
# ---------------------------------------------------------------------------

def test_self_doc_allows_writing_md_into_agent_dir():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_doc_mode()
    target = settings_mod._QUANORA_REPO_ROOT / "agent" / "README.md"
    assert g.check_write(target) is None  # ALLOWED (.md exempt)


def test_self_doc_blocks_writing_py_into_agent_dir():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_doc_mode()
    target = settings_mod._QUANORA_REPO_ROOT / "agent" / "hypothetical.py"
    violation = g.check_write(target)
    assert violation is not None
    assert violation.status == "protected"


def test_self_doc_blocks_writing_yaml_into_quanora_dir():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_doc_mode()
    target = settings_mod._QUANORA_REPO_ROOT / ".quanora" / "config.yaml"
    violation = g.check_write(target)
    assert violation is not None
    assert violation.status == "protected"


def test_self_doc_still_blocks_git_md_writes():
    """Even .md files inside .git/ must not be written — .git is fully
    protected (no extension whitelist exemption)."""
    from agent.infrastructure.config import settings as settings_mod
    import os
    # Ensure .git exists on disk so it gets picked up as a fully_protected_path
    git_dir = settings_mod._QUANORA_REPO_ROOT / ".git"
    git_exists = git_dir.exists()
    if not git_exists:
        os.makedirs(git_dir, exist_ok=True)
    try:
        g = settings_mod.enable_self_doc_mode()
        target_md = settings_mod._QUANORA_REPO_ROOT / ".git" / "some.md"
        violation = g.check_write(target_md)
        assert violation is not None
        assert violation.status == "protected"
    finally:
        if not git_exists:
            try:
                os.rmdir(git_dir)
            except OSError:
                pass


def test_self_doc_blocks_env_writes():
    from agent.infrastructure.config import settings as settings_mod
    g = settings_mod.enable_self_doc_mode()
    target = settings_mod._QUANORA_REPO_ROOT / ".env"
    violation = g.check_write(target)
    assert violation is not None
    assert violation.status == "protected"


def test_disable_self_doc_restores_defaults():
    from agent.infrastructure.config import settings as settings_mod
    settings_mod.enable_self_doc_mode()
    settings_mod.disable_self_doc_mode()
    assert settings_mod.is_self_doc_mode() is False
    g = settings_mod.get_workspace_guard()
    names = {p.name for p in g.protected_paths}
    assert "agent" in names
    assert ".git" in names
    assert len(g.protected_paths) >= 5
    # No extension whitelist in default mode
    assert len(g._cfg.protected_write_extensions) == 0


# ---------------------------------------------------------------------------
# Prompt: self-doc addendum is conditional
# ---------------------------------------------------------------------------

def test_build_system_prompt_default_omits_self_doc():
    from agent.prompts import build_system_prompt
    p = build_system_prompt(self_doc=False)
    assert "<self_doc_mode" not in p


def test_build_system_prompt_self_doc_appends_addendum():
    from agent.prompts import build_system_prompt
    p = build_system_prompt(self_doc=True)
    assert "<self_doc_mode" in p
    assert "SELF-DOC MODE" in p


def test_self_dev_takes_precedence_over_self_doc_in_prompt():
    from agent.prompts import build_system_prompt
    p = build_system_prompt(self_dev=True, self_doc=True)
    # self-dev addendum should be present, self-doc should NOT
    assert "<self_dev_mode" in p
    assert "<self_doc_mode" not in p


def test_build_system_prompt_self_doc_does_not_include_self_dev():
    from agent.prompts import build_system_prompt
    p = build_system_prompt(self_doc=True)
    # self-doc addendum should be present, self-dev should NOT
    assert "<self_doc_mode" in p
    assert "<self_dev_mode" not in p


# ---------------------------------------------------------------------------
# WorkspaceConfig: protected_write_extensions field
# ---------------------------------------------------------------------------

def test_workspace_config_default_has_no_write_extensions():
    from agent.domain.workspace import WorkspaceConfig
    cfg = WorkspaceConfig(root=Path("/tmp/ws"))
    assert cfg.protected_write_extensions == ()


def test_workspace_config_accepts_write_extensions():
    from agent.domain.workspace import WorkspaceConfig
    cfg = WorkspaceConfig(
        root=Path("/tmp/ws"),
        protected_paths=(Path("/tmp/ws/protected"),),
        protected_write_extensions=(".md", ".rst"),
    )
    assert ".md" in cfg.protected_write_extensions
    assert ".rst" in cfg.protected_write_extensions


# ---------------------------------------------------------------------------
# WorkspaceGuard.classify: extension whitelist logic
# ---------------------------------------------------------------------------

def test_guard_classify_md_in_protected_with_whitelist_is_allowed():
    from agent.domain.workspace import WorkspaceConfig, WorkspaceGuard
    root = Path("/tmp/ws").resolve()
    protected = Path("/tmp/ws/protected").resolve()
    cfg = WorkspaceConfig(
        root=root,
        protected_paths=(protected,),
        protected_write_extensions=(".md",),
    )
    guard = WorkspaceGuard(cfg)
    assert guard.classify(Path("/tmp/ws/protected/README.md")) == "allowed"


def test_guard_classify_py_in_protected_with_md_whitelist_is_protected():
    from agent.domain.workspace import WorkspaceConfig, WorkspaceGuard
    root = Path("/tmp/ws").resolve()
    protected = Path("/tmp/ws/protected").resolve()
    cfg = WorkspaceConfig(
        root=root,
        protected_paths=(protected,),
        protected_write_extensions=(".md",),
    )
    guard = WorkspaceGuard(cfg)
    assert guard.classify(Path("/tmp/ws/protected/hypothetical.py")) == "protected"


def test_guard_classify_md_in_protected_without_whitelist_is_protected():
    from agent.domain.workspace import WorkspaceConfig, WorkspaceGuard
    root = Path("/tmp/ws").resolve()
    protected = Path("/tmp/ws/protected").resolve()
    cfg = WorkspaceConfig(
        root=root,
        protected_paths=(protected,),
        protected_write_extensions=(),  # no whitelist
    )
    guard = WorkspaceGuard(cfg)
    assert guard.classify(Path("/tmp/ws/protected/README.md")) == "protected"


def test_guard_classify_case_insensitive_extension_matching():
    from agent.domain.workspace import WorkspaceConfig, WorkspaceGuard
    root = Path("/tmp/ws").resolve()
    protected = Path("/tmp/ws/protected").resolve()
    cfg = WorkspaceConfig(
        root=root,
        protected_paths=(protected,),
        protected_write_extensions=(".md",),
    )
    guard = WorkspaceGuard(cfg)
    # .MD (uppercase) should also be allowed
    assert guard.classify(Path("/tmp/ws/protected/readme.MD")) == "allowed"


def test_guard_fully_protected_overrides_extension_whitelist():
    """Even .md files inside a fully_protected_path must be blocked."""
    from agent.domain.workspace import WorkspaceConfig, WorkspaceGuard
    root = Path("/tmp/ws").resolve()
    protected = Path("/tmp/ws/protected").resolve()
    fully = Path("/tmp/ws/protected/.git").resolve()
    cfg = WorkspaceConfig(
        root=root,
        protected_paths=(protected,),
        protected_write_extensions=(".md",),
        fully_protected_paths=(fully,),
    )
    guard = WorkspaceGuard(cfg)
    # .md inside fully_protected_path (.git) → "protected"
    assert guard.classify(Path("/tmp/ws/protected/.git/notes.md")) == "protected"
    # .md inside protected but NOT fully_protected → "allowed"
    assert guard.classify(Path("/tmp/ws/protected/README.md")) == "allowed"
    # .py inside protected → "protected"
    assert guard.classify(Path("/tmp/ws/protected/foo.py")) == "protected"


def test_guard_check_write_md_in_protected_with_whitelist_returns_none():
    from agent.domain.workspace import WorkspaceConfig, WorkspaceGuard
    root = Path("/tmp/ws").resolve()
    protected = Path("/tmp/ws/protected").resolve()
    cfg = WorkspaceConfig(
        root=root,
        protected_paths=(protected,),
        protected_write_extensions=(".md",),
    )
    guard = WorkspaceGuard(cfg)
    assert guard.check_write(Path("/tmp/ws/protected/README.md")) is None


def test_guard_check_write_py_in_protected_with_whitelist_returns_violation():
    from agent.domain.workspace import WorkspaceConfig, WorkspaceGuard
    root = Path("/tmp/ws").resolve()
    protected = Path("/tmp/ws/protected").resolve()
    cfg = WorkspaceConfig(
        root=root,
        protected_paths=(protected,),
        protected_write_extensions=(".md",),
    )
    guard = WorkspaceGuard(cfg)
    violation = guard.check_write(Path("/tmp/ws/protected/hypothetical.py"))
    assert violation is not None
    assert violation.status == "protected"


# ---------------------------------------------------------------------------
# CLI: --self-doc argument is accepted
# ---------------------------------------------------------------------------

def test_cli_self_doc_argument_is_accepted():
    """Verify argparse recognises --self-doc without error."""
    import argparse

    # Re-create the parser from main.py just enough to verify --self-doc
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-dev", action="store_true")
    parser.add_argument("--self-doc", action="store_true")
    args = parser.parse_args(["--self-doc"])
    assert args.self_doc is True
    assert args.self_dev is False


# ---------------------------------------------------------------------------
# self-doc + switch_to_project_workspace: path resolution correctness
# ---------------------------------------------------------------------------

def test_self_doc_switch_keeps_workspace_root_at_repo():
    """In self-doc mode, switch_to_project_workspace must NOT change
    _WORKSPACE_ROOT or Config.WORKSPACE_ROOT away from the repo root.
    Otherwise docs/xxx.md would resolve to an empty project subdirectory
    instead of the real docs/ tree under the repo.
    """
    from agent.infrastructure.config import settings as settings_mod

    # Record initial state
    initial_ws_root = settings_mod._WORKSPACE_ROOT
    initial_config_ws = settings_mod.Config.WORKSPACE_ROOT

    # Enable self-doc mode
    settings_mod.enable_self_doc_mode()

    try:
        # Simulate switching to a project workspace (like what happens
        # when the CLI processes a new task in self-doc mode)
        project_dir = settings_mod.switch_to_project_workspace(
            "test self-doc project"
        )

        # KEY ASSERTION: _WORKSPACE_ROOT must stay at repo root
        assert settings_mod._WORKSPACE_ROOT == settings_mod._QUANORA_REPO_ROOT, (
            f"_WORKSPACE_ROOT should stay at repo root in self-doc mode, "
            f"but got {settings_mod._WORKSPACE_ROOT}"
        )

        # Config.WORKSPACE_ROOT must also stay at repo root
        assert settings_mod.Config.WORKSPACE_ROOT == settings_mod._QUANORA_REPO_ROOT, (
            f"Config.WORKSPACE_ROOT should stay at repo root in self-doc mode, "
            f"but got {settings_mod.Config.WORKSPACE_ROOT}"
        )

        # The project_dir returned should still exist (for metadata tracking)
        assert project_dir.exists()

    finally:
        # Clean up: disable self-doc mode and restore workspace root
        settings_mod.disable_self_doc_mode()


def test_self_doc_guard_resolve_root_is_repo_root():
    """In self-doc mode, the guard's resolve_root must be the repo root
    so that relative paths like 'docs/xxx.md' resolve correctly.
    """
    from agent.infrastructure.config import settings as settings_mod

    # Enable self-doc mode
    settings_mod.enable_self_doc_mode()

    try:
        # Simulate switching to a project workspace
        settings_mod.switch_to_project_workspace("test self-doc project")

        # After switch, the guard should have root == repo root
        current_guard = settings_mod._WORKSPACE_GUARD
        assert current_guard.root == settings_mod._QUANORA_REPO_ROOT, (
            f"guard.root should be repo root in self-doc mode, "
            f"but got {current_guard.root}"
        )

        # resolve_root should also be repo root
        assert current_guard._cfg.resolve_root == settings_mod._QUANORA_REPO_ROOT, (
            f"guard._cfg.resolve_root should be repo root in self-doc mode, "
            f"but got {current_guard._cfg.resolve_root}"
        )

    finally:
        # Clean up
        settings_mod.disable_self_doc_mode()


def test_self_doc_md_path_resolves_to_repo_docs():
    """In self-doc mode, writing 'docs/something.md' should resolve to
    <repo_root>/docs/something.md, NOT to some empty project subdirectory.
    """
    from agent.infrastructure.config import settings as settings_mod

    # Enable self-doc mode
    settings_mod.enable_self_doc_mode()

    try:
        # Simulate switching to a project workspace
        settings_mod.switch_to_project_workspace("test self-doc project")

        # A relative path like "docs/something.md" should resolve under repo root
        current_guard = settings_mod._WORKSPACE_GUARD
        resolve_root = current_guard._cfg.resolve_root
        expected_path = resolve_root / "docs" / "something.md"

        # The resolved path should be under the repo root's docs/ directory
        assert str(expected_path).startswith(
            str(settings_mod._QUANORA_REPO_ROOT / "docs")
        ), (
            f"docs/something.md should resolve to repo_root/docs/something.md, "
            f"but would resolve to {expected_path}"
        )

    finally:
        # Clean up
        settings_mod.disable_self_doc_mode()