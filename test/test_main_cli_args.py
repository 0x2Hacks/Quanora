import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)


def test_resume_mode_flag_is_removed() -> None:
    result = subprocess.run(
        [sys.executable, "main.py", "--resume-mode", "summary"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )

    if result.returncode == 0:
        raise AssertionError("Expected main.py to reject the removed --resume-mode flag.")
    combined = f"{result.stdout}\n{result.stderr}"
    if "unrecognized arguments: --resume-mode summary" not in combined:
        raise AssertionError(f"Expected argparse unknown-flag error, got: {combined}")


# ── Quant-research mode tests ───────────────────────────────────────────

def test_quant_research_flag_accepted() -> None:
    """--quant-research should be a valid CLI flag (not rejected by argparse)."""
    result = subprocess.run(
        [sys.executable, "main.py", "--help"],
        cwd=PROJECT_ROOT,
        capture_output=True,
        text=True,
    )
    assert "--quant-research" in result.stdout, (
        "Expected --quant-research in --help output"
    )


def test_quant_research_mode_in_settings() -> None:
    """enable_self_quant_mode / is_self_quant_mode should work correctly."""
    from agent.infrastructure.config.settings import (
        is_self_quant_mode,
        enable_self_quant_mode,
        disable_self_quant_mode,
    )

    assert not is_self_quant_mode(), "should be False initially"
    enable_self_quant_mode()
    assert is_self_quant_mode(), "should be True after enable"
    disable_self_quant_mode()
    assert not is_self_quant_mode(), "should be False after disable"


def test_quant_research_mode_mutual_exclusion() -> None:
    """Only one of self_dev / self_doc / self_quant should be active at once."""
    from agent.infrastructure.config.settings import (
        is_self_quant_mode,
        is_self_dev_mode,
        is_self_doc_mode,
        enable_self_quant_mode,
        enable_self_dev_mode,
        enable_self_doc_mode,
        disable_self_dev_mode,
        disable_self_doc_mode,
        disable_self_quant_mode,
    )

    # Clean state
    disable_self_dev_mode()
    disable_self_doc_mode()
    disable_self_quant_mode()
    assert not any([is_self_dev_mode(), is_self_doc_mode(), is_self_quant_mode()])

    # Enable quant -> disables dev and doc
    enable_self_quant_mode()
    assert is_self_quant_mode() and not is_self_dev_mode() and not is_self_doc_mode()

    # Enable dev -> disables quant and doc
    enable_self_dev_mode()
    assert is_self_dev_mode() and not is_self_quant_mode() and not is_self_doc_mode()

    # Enable doc -> disables dev and quant
    enable_self_doc_mode()
    assert is_self_doc_mode() and not is_self_dev_mode() and not is_self_quant_mode()


def test_quant_research_prompt_injected() -> None:
    """build_system_prompt(self_quant=True) should include the defaults guard
    but NOT the full self_quant_mode prompt (that is printed to console)."""
    from agent.prompts import build_system_prompt

    prompt = build_system_prompt(self_quant=True)
    # The full SELF_QUANT_MODE_PROMPT is printed to console, not in LLM prompt
    assert "self_quant_mode" not in prompt, "Full <self_quant_mode> should NOT be in LLM prompt"
    # But the compact defaults guard IS injected
    assert "quant_defaults_guard" in prompt, "Missing <quant_defaults_guard> tag"
    assert "PROHIBITED without explicit user request" in prompt, "Missing defaults guard rules"


def test_quant_research_prompt_exclusivity() -> None:
    """self_quant and self_dev should be mutually exclusive in prompt.
    self_dev no longer injects its prompt; self_quant injects the guard."""
    from agent.prompts import build_system_prompt

    # self_dev takes precedence — neither self_quant_mode nor guard present
    p = build_system_prompt(self_dev=True, self_quant=True)
    assert "self_dev_mode" not in p and "self_quant_mode" not in p
    assert "quant_defaults_guard" not in p

    # self_doc takes precedence over self_quant
    p = build_system_prompt(self_doc=True, self_quant=True)
    assert "self_doc_mode" in p and "self_quant_mode" not in p

    # self_quant alone — guard present, no full mode prompts
    p = build_system_prompt(self_quant=True)
    assert "self_quant_mode" not in p and "self_dev_mode" not in p and "self_doc_mode" not in p
    assert "quant_defaults_guard" in p


def test_container_accepts_self_quant() -> None:
    """build_basic_agent_dependencies should accept self_quant parameter."""
    from agent.bootstrap.container import build_basic_agent_dependencies

    # Should not raise
    deps = build_basic_agent_dependencies(self_quant=True, debug=True)
    assert isinstance(deps, dict)


def main() -> int:
    test_resume_mode_flag_is_removed()
    test_quant_research_flag_accepted()
    test_quant_research_mode_in_settings()
    test_quant_research_mode_mutual_exclusion()
    test_quant_research_prompt_injected()
    test_quant_research_prompt_exclusivity()
    test_container_accepts_self_quant()
    print("All CLI arg and quant-research mode tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
