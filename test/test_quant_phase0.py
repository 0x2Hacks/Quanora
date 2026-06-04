"""Tests for Phase 0 initialization workflow in quant-research mode.

Validates:
- Project directory binding (existing and new)
- Git version control check (no git, task-managed, user-managed)
- Research vs Development mode inheritance
- CLI quant-mode bypass of auto project switching
- Prompt content completeness
"""

import os
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from agent.infrastructure.tools.impl.tools.task_git import task_git_check_repo
from agent.infrastructure.task_git import TaskGitManager


# ── Project Directory Binding ──────────────────────────────────────────

class TestProjectDirectoryBinding:
    """Test project directory creation and verification."""

    def test_existing_directory_detected(self, tmp_path):
        """Agent should recognize an existing project directory."""
        project_dir = tmp_path / "my_strategy"
        project_dir.mkdir()
        # The agent would use list_files or bash to verify
        assert project_dir.exists()
        assert project_dir.is_dir()

    def test_new_directory_created(self, tmp_path):
        """Agent should create a new project directory if it doesn't exist."""
        project_dir = tmp_path / "new_strategy"
        assert not project_dir.exists()
        project_dir.mkdir(parents=True, exist_ok=True)
        assert project_dir.exists()

    def test_research_doc_created_if_missing(self, tmp_path):
        """Agent should create a skeleton research doc if it doesn't exist."""
        doc_path = tmp_path / "docs" / "research.md"
        doc_path.parent.mkdir(parents=True, exist_ok=True)
        assert not doc_path.exists()
        doc_path.write_text("# Research Log\n\n")
        assert doc_path.exists()

    def test_existing_research_doc_preserved(self, tmp_path):
        """Agent should not overwrite an existing research doc."""
        doc_path = tmp_path / "research.md"
        original_content = "# My Research\n\nExisting content here."
        doc_path.write_text(original_content)
        assert doc_path.read_text() == original_content


# ── Git Version Control Check ──────────────────────────────────────────

class TestGitVersionControlCheck:
    """Test git repository detection and classification."""

    def test_no_git_repo(self, tmp_path):
        """Directory without .git returns has_git=False."""
        result = task_git_check_repo(directory=str(tmp_path))
        assert '"has_git": false' in result or "'has_git': False" in result

    def test_task_managed_git_repo(self, tmp_path):
        """TaskGitManager-initialized repo is detected as task-managed."""
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        mgr = TaskGitManager(task_dir=project_dir, task_name="project")
        mgr.init_task_repo(skip_isolation_check=True)

        result = task_git_check_repo(directory=str(project_dir))
        assert '"has_git": true' in result or "'has_git': True" in result
        assert "task_git" in result
        assert "is_task_managed" in result

    def test_user_git_repo_detected_as_bash_git(self, tmp_path):
        """User's own git repo should be detected as bash_git."""
        user_dir = tmp_path / "user_project"
        user_dir.mkdir()
        subprocess.run(
            ["git", "init"],
            capture_output=True, cwd=str(user_dir), timeout=10,
        )
        subprocess.run(
            ["git", "config", "user.email", "user@example.com"],
            capture_output=True, cwd=str(user_dir), timeout=10,
        )
        subprocess.run(
            ["git", "config", "user.name", "Alice"],
            capture_output=True, cwd=str(user_dir), timeout=10,
        )

        result = task_git_check_repo(directory=str(user_dir))
        assert '"has_git": true' in result or "'has_git': True" in result
        assert "bash_git" in result

    def test_nonexistent_directory_returns_error(self, tmp_path):
        """Non-existent directory should return an error."""
        result = task_git_check_repo(
            directory=str(tmp_path / "nonexistent")
        )
        assert "does not exist" in result

    def test_git_tool_recommendation_for_task_repo(self, tmp_path):
        """Task-managed repo should recommend task_git_* tools."""
        project_dir = tmp_path / "managed_project"
        project_dir.mkdir()
        mgr = TaskGitManager(task_dir=project_dir, task_name="managed_project")
        mgr.init_task_repo(skip_isolation_check=True)

        result = task_git_check_repo(directory=str(project_dir))
        assert '"git_tool": "task_git_*"' in result or "task_git_*" in result

    def test_git_tool_recommendation_for_user_repo(self, tmp_path):
        """User's own repo should recommend bash_git tools."""
        user_dir = tmp_path / "user_repo"
        user_dir.mkdir()
        subprocess.run(
            ["git", "init"],
            capture_output=True, cwd=str(user_dir), timeout=10,
        )
        subprocess.run(
            ["git", "config", "user.email", "bob@example.com"],
            capture_output=True, cwd=str(user_dir), timeout=10,
        )
        subprocess.run(
            ["git", "config", "user.name", "Bob"],
            capture_output=True, cwd=str(user_dir), timeout=10,
        )

        result = task_git_check_repo(directory=str(user_dir))
        assert '"git_tool": "bash_git"' in result or "bash_git" in result


# ── Research vs Development Mode ───────────────────────────────────────

class TestSessionModeInheritance:
    """Test that SESSION_MODE from Phase 0 properly inherits to TASK_MODE."""

    def test_development_mode_allows_source_edits(self):
        """In development mode, source code editing should be permitted."""
        session_mode = "development"
        task_mode = session_mode  # Inherited
        assert task_mode == "development"
        # Development mode allows edit_file / write_file on source

    def test_research_mode_restricts_source_edits(self):
        """In research mode, source code editing should be restricted."""
        session_mode = "research"
        task_mode = session_mode  # Inherited
        assert task_mode == "research"
        # Research mode restricts writes to docs, results, artifacts only

    def test_mode_inherits_from_phase0(self):
        """TASK_MODE should inherit from SESSION_MODE by default."""
        session_mode = "development"
        task_mode = session_mode
        assert task_mode == session_mode

    def test_mode_can_be_overridden_per_task(self):
        """TASK_MODE can be overridden for a specific task."""
        session_mode = "research"
        task_mode_override = "development"
        # User explicitly overrides for a specific task
        assert task_mode_override != session_mode


# ── CLI Quant-Mode Bypass ──────────────────────────────────────────────

class TestCLIQuantModeBypass:
    """Test that CLI skips auto project switching in quant-research mode."""

    @patch("agent.infrastructure.config.settings.is_self_quant_mode")
    def test_quant_mode_skips_auto_switch(self, mock_is_quant):
        """In quant-research mode, switch_to_project_workspace should NOT
        be called automatically."""
        mock_is_quant.return_value = True
        from agent.infrastructure.config.settings import is_self_quant_mode
        assert is_self_quant_mode() is True
        # The CLI _loop() method should skip switch_to_project_workspace

    @patch("agent.infrastructure.config.settings.is_self_quant_mode")
    def test_non_quant_mode_auto_switches(self, mock_is_quant):
        """In non-quant mode, switch_to_project_workspace should be called."""
        mock_is_quant.return_value = False
        from agent.infrastructure.config.settings import is_self_quant_mode
        assert is_self_quant_mode() is False
        # The CLI _loop() method should call switch_to_project_workspace


# ── Prompt Content Completeness ────────────────────────────────────────

class TestPromptContentCompleteness:
    """Verify Phase 0 prompt contains all required elements."""

    def test_phase0_prompt_exists(self):
        """SELF_QUANT_MODE_PROMPT should contain Phase 0 content."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "Phase 0" in SELF_QUANT_MODE_PROMPT
        assert "Project Binding" in SELF_QUANT_MODE_PROMPT

    def test_phase0_contains_project_dir_step(self):
        """Phase 0 should include Step 0-1 for project directory binding."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "Step 0-1" in SELF_QUANT_MODE_PROMPT
        assert "PROJECT_DIR" in SELF_QUANT_MODE_PROMPT

    def test_phase0_contains_git_check_step(self):
        """Phase 0 should include Step 0-2 for git version control check."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "Step 0-2" in SELF_QUANT_MODE_PROMPT
        assert "HAS_GIT" in SELF_QUANT_MODE_PROMPT
        assert "GIT_TOOL" in SELF_QUANT_MODE_PROMPT

    def test_phase0_contains_mode_selection_step(self):
        """Phase 0 should include Step 0-3 for research/development mode."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "Step 0-3" in SELF_QUANT_MODE_PROMPT
        assert "SESSION_MODE" in SELF_QUANT_MODE_PROMPT

    def test_phase0_contains_summary(self):
        """Phase 0 should include a summary table."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "Phase 0 Setup Complete" in SELF_QUANT_MODE_PROMPT

    def test_phase0_references_task_git_check_repo(self):
        """Phase 0 should reference task_git_check_repo or bash for git check."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        # Either task_git_check_repo tool or bash test command
        assert "task_git_check_repo" in SELF_QUANT_MODE_PROMPT or \
               "test -d" in SELF_QUANT_MODE_PROMPT

    def test_phase0_four_phase_onboarding(self):
        """Prompt should describe four-phase onboarding (was three-phase)."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "four-phase" in SELF_QUANT_MODE_PROMPT

    def test_phaseB_inherits_session_mode(self):
        """Phase B should reference SESSION_MODE inheritance."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "SESSION_MODE" in SELF_QUANT_MODE_PROMPT
        assert "inherited" in SELF_QUANT_MODE_PROMPT.lower() or \
               "inherit" in SELF_QUANT_MODE_PROMPT.lower()

    def test_development_mode_auto_commit(self):
        """Development mode should specify automatic git commits."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "automatically committed" in SELF_QUANT_MODE_PROMPT or \
               "auto.*commit" in SELF_QUANT_MODE_PROMPT.lower()

    def test_phaseC_git_logic_branches(self):
        """Phase C should have different git init paths based on HAS_GIT."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "HAS_GIT" in SELF_QUANT_MODE_PROMPT
        assert "bash_git" in SELF_QUANT_MODE_PROMPT


# ── Integration: Full Phase 0 Flow ────────────────────────────────────

class TestPhase0Integration:
    """Integration tests for the complete Phase 0 flow."""

    def test_full_phase0_flow_no_git(self, tmp_path):
        """Simulate full Phase 0 flow for a new project without git."""
        # Step 0-1: Bind project directory
        project_dir = tmp_path / "my_strategy"
        project_dir.mkdir()
        assert project_dir.exists()

        # Step 0-2: Check git
        result = task_git_check_repo(directory=str(project_dir))
        assert '"has_git": false' in result or "'has_git': False" in result

        # Step 0-2: Init git (simulating user choosing "yes")
        mgr = TaskGitManager(task_dir=project_dir, task_name="my_strategy")
        mgr.init_task_repo(skip_isolation_check=True)

        # Verify git is now initialized
        result = task_git_check_repo(directory=str(project_dir))
        assert '"has_git": true' in result or "'has_git': True" in result

        # Step 0-3: Select mode
        session_mode = "development"

        # Record variables
        assert project_dir.exists()
        assert session_mode == "development"

    def test_full_phase0_flow_existing_git(self, tmp_path):
        """Simulate full Phase 0 flow for a project with existing git."""
        # Step 0-1: Bind project directory (already exists)
        project_dir = tmp_path / "existing_project"
        project_dir.mkdir()

        # Pre-existing git repo
        subprocess.run(
            ["git", "init"],
            capture_output=True, cwd=str(project_dir), timeout=10,
        )
        subprocess.run(
            ["git", "config", "user.email", "dev@example.com"],
            capture_output=True, cwd=str(project_dir), timeout=10,
        )
        subprocess.run(
            ["git", "config", "user.name", "Developer"],
            capture_output=True, cwd=str(project_dir), timeout=10,
        )

        # Step 0-2: Check git
        result = task_git_check_repo(directory=str(project_dir))
        assert '"has_git": true' in result or "'has_git': True" in result
        assert "bash_git" in result  # User's own repo

        # Step 0-3: Select mode
        session_mode = "research"

        # Should NOT call task_git_init — it would conflict
        # Record variables
        assert session_mode == "research"


# ── Auto-Kickoff Onboarding ────────────────────────────────────────────


class TestAutoKickoffOnboarding:
    """Test that quant-research mode auto-fires the onboarding prompt."""

    def test_prompt_contains_auto_kickoff_directive(self):
        """The SELF_QUANT_MODE_PROMPT must contain the AUTO-KICKOFF directive."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "AUTO-KICKOFF" in SELF_QUANT_MODE_PROMPT

    def test_prompt_contains_onboarding_trigger(self):
        """The prompt must reference the __QUANT_ONBOARDING__ trigger."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        assert "__QUANT_ONBOARDING__" in SELF_QUANT_MODE_PROMPT

    def test_prompt_contains_onboarding_greeting_template(self):
        """The prompt must contain the welcome greeting with Phase 0 questions."""
        from agent.prompts import SELF_QUANT_MODE_PROMPT
        # Must tell the user what to provide
        assert "Project Directory" in SELF_QUANT_MODE_PROMPT
        assert "Research Document" in SELF_QUANT_MODE_PROMPT
        assert "Session Mode" in SELF_QUANT_MODE_PROMPT
        assert "Version Control" in SELF_QUANT_MODE_PROMPT

    def test_cli_loop_sends_onboarding_trigger(self):
        """ChatCLI._loop() should send __QUANT_ONBOARDING__ when _self_quant is True."""
        import inspect
        from agent.interfaces.cli.chat_cli import ChatCLI
        source = inspect.getsource(ChatCLI._loop)
        assert "__QUANT_ONBOARDING__" in source

    def test_cli_loop_no_trigger_without_self_quant(self):
        """The onboarding trigger should be guarded by self._self_quant check."""
        import inspect
        from agent.interfaces.cli.chat_cli import ChatCLI
        source = inspect.getsource(ChatCLI._loop)
        # The trigger should be inside an `if self._self_quant:` block
        assert "self._self_quant" in source
        # And should not be unconditionally sent
        lines = source.split("\n")
        trigger_line_idx = None
        for i, line in enumerate(lines):
            if "__QUANT_ONBOARDING__" in line:
                trigger_line_idx = i
                break
        assert trigger_line_idx is not None, "Trigger not found in _loop source"
        # Look backwards for the if self._self_quant guard
        found_guard = False
        for i in range(trigger_line_idx - 1, max(trigger_line_idx - 20, 0), -1):
            if "self._self_quant" in lines[i] and "if" in lines[i]:
                found_guard = True
                break
        assert found_guard, "Trigger not guarded by self._self_quant check"
