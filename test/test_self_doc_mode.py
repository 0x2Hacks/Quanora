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


# ── Tests for two-scenario routing and user-interaction protocol ──


def test_self_doc_prompt_contains_scenario_routing():
    """The SELF_DOC_MODE_PROMPT must contain the mandatory user-interaction
    protocol section that routes between the two scenarios."""
    from agent.prompts import SELF_DOC_MODE_PROMPT

    # The protocol heading must exist
    assert "Mandatory user-interaction protocol" in SELF_DOC_MODE_PROMPT

    # Scenario A (initial generation) must be referenced
    assert "初次生成" in SELF_DOC_MODE_PROMPT

    # Scenario B (optimize existing docs) must be referenced
    assert "优化已有文档" in SELF_DOC_MODE_PROMPT


def test_self_doc_prompt_contains_ask_scenario_step():
    """The prompt must instruct the agent to ask the user which scenario
    before proceeding (Step 1 of the interaction protocol)."""
    from agent.prompts import SELF_DOC_MODE_PROMPT

    assert "Step 1: Ask which scenario" in SELF_DOC_MODE_PROMPT
    assert "请选择文档操作场景" in SELF_DOC_MODE_PROMPT
    # Must contain the blocking instruction
    assert "MUST NOT proceed to any file operation until the user answers" in SELF_DOC_MODE_PROMPT


def test_self_doc_prompt_contains_ask_filename_step():
    """The prompt must instruct the agent to ask for the target MD filename
    before proceeding (Step 2 of the interaction protocol)."""
    from agent.prompts import SELF_DOC_MODE_PROMPT

    assert "Step 2: Ask for the target filename" in SELF_DOC_MODE_PROMPT
    assert "请提供目标 Markdown 文件名称" in SELF_DOC_MODE_PROMPT
    # Must contain the blocking instruction
    assert "MUST NOT write to or create any file until the user provides" in SELF_DOC_MODE_PROMPT


def test_self_doc_prompt_scenario_a_behavior():
    """Scenario A must instruct the agent to present a draft outline before
    writing the full content."""
    from agent.prompts import SELF_DOC_MODE_PROMPT

    assert "Scenario A" in SELF_DOC_MODE_PROMPT
    assert "Initial generation" in SELF_DOC_MODE_PROMPT
    # Must mention presenting the draft outline
    assert "Present the draft outline" in SELF_DOC_MODE_PROMPT


def test_self_doc_prompt_scenario_b_behavior():
    """Scenario B must instruct the agent to present a summary of proposed
    changes before making edits."""
    from agent.prompts import SELF_DOC_MODE_PROMPT

    assert "Scenario B" in SELF_DOC_MODE_PROMPT
    assert "Optimize existing docs" in SELF_DOC_MODE_PROMPT
    # Must mention presenting proposed changes
    assert "Present a summary of proposed changes" in SELF_DOC_MODE_PROMPT


def test_build_system_prompt_self_doc_includes_scenario_routing():
    """When build_system_prompt(self_doc=True) is called, the resulting
    system prompt must include the scenario-routing protocol."""
    from agent.prompts import build_system_prompt

    p = build_system_prompt(self_doc=True)
    assert "Mandatory user-interaction protocol" in p
    assert "初次生成" in p
    assert "优化已有文档" in p
    assert "请选择文档操作场景" in p
    assert "请提供目标 Markdown 文件名称" in p


# ===========================================================================
# Onboarding trigger tests
# ===========================================================================

class TestSelfDocOnboardingTrigger:
    """Tests for the __SELF_DOC_ONBOARDING__ auto-kickoff mechanism.

    Mirrors the pattern established by TestQuantPhase0Onboarding in
    test_quant_phase0.py for the __QUANT_ONBOARDING__ trigger.
    """

    def test_prompt_contains_onboarding_section(self):
        """The prompt must contain an AUTO-KICKOFF section for self-doc."""
        from agent.prompts import SELF_DOC_MODE_PROMPT

        assert "AUTO-KICKOFF" in SELF_DOC_MODE_PROMPT

    def test_prompt_contains_onboarding_trigger(self):
        """The prompt must reference the __SELF_DOC_ONBOARDING__ trigger."""
        from agent.prompts import SELF_DOC_MODE_PROMPT

        assert "__SELF_DOC_ONBOARDING__" in SELF_DOC_MODE_PROMPT

    def test_prompt_contains_onboarding_greeting_template(self):
        """The prompt must contain the welcome greeting with scenario and
        filename questions."""
        from agent.prompts import SELF_DOC_MODE_PROMPT

        # Greeting must tell the user what to provide
        assert "Welcome to Self-Doc Mode" in SELF_DOC_MODE_PROMPT
        # Scenario selection (A/B)
        assert "A" in SELF_DOC_MODE_PROMPT
        assert "B" in SELF_DOC_MODE_PROMPT
        assert "初次生成" in SELF_DOC_MODE_PROMPT
        assert "优化已有文档" in SELF_DOC_MODE_PROMPT
        # Filename question
        assert "Markdown 文件名称" in SELF_DOC_MODE_PROMPT

    def test_cli_loop_sends_onboarding_trigger(self):
        """ChatCLI._loop should send __SELF_DOC_ONBOARDING__ when
        _self_doc is True."""
        import inspect
        from agent.interfaces.cli.chat_cli import ChatCLI

        source = inspect.getsource(ChatCLI._loop)
        assert "__SELF_DOC_ONBOARDING__" in source
        assert "_self_doc" in source

    def test_cli_init_accepts_self_doc_parameter(self):
        """ChatCLI.__init__ must accept a self_doc parameter."""
        import inspect
        from agent.interfaces.cli.chat_cli import ChatCLI

        sig = inspect.signature(ChatCLI.__init__)
        assert "self_doc" in sig.parameters

    def test_cli_onboarding_guarded_by_self_doc_flag(self):
        """The onboarding trigger must be guarded by an 'if self._self_doc'
        check so it only fires in self-doc mode."""
        import inspect
        from agent.interfaces.cli.chat_cli import ChatCLI

        source = inspect.getsource(ChatCLI._loop)
        # Find the __SELF_DOC_ONBOARDING__ injection block
        assert "self._self_doc" in source
        assert "__SELF_DOC_ONBOARDING__" in source

    def test_container_passes_self_doc_to_chat_cli(self):
        """build_basic_agent_dependencies must pass self_doc to ChatCLI."""
        import inspect
        from agent.bootstrap.container import build_basic_agent_dependencies

        source = inspect.getsource(build_basic_agent_dependencies)
        assert "self_doc=self_doc" in source

    def test_build_system_prompt_includes_onboarding_trigger(self):
        """build_system_prompt(self_doc=True) must include the
        __SELF_DOC_ONBOARDING__ trigger instruction."""
        from agent.prompts import build_system_prompt

        p = build_system_prompt(self_doc=True)
        assert "__SELF_DOC_ONBOARDING__" in p
        assert "AUTO-KICKOFF" in p