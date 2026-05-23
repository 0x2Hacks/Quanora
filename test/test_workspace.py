"""Unit tests for the workspace boundary domain logic.

These tests are filesystem-light: they exercise WorkspaceGuard against
synthetic paths only, no actual writes. The integration test that proves
write_file/edit_file honour the guard lives in
``test_workspace_integration.py``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.domain.workspace import (
    WorkspaceConfig,
    WorkspaceGuard,
    WorkspaceViolation,
)


def _guard(tmp_path: Path) -> WorkspaceGuard:
    """Build a guard with workspace = tmp_path/ws and protected = tmp_path/protected."""
    workspace = (tmp_path / "ws").resolve()
    workspace.mkdir()
    protected = (tmp_path / "protected").resolve()
    protected.mkdir()
    cfg = WorkspaceConfig(root=workspace, protected_paths=(protected,))
    return WorkspaceGuard(cfg)


# ---------------------------------------------------------------------------
# classify()
# ---------------------------------------------------------------------------

def test_classify_inside_workspace_is_allowed(tmp_path):
    g = _guard(tmp_path)
    assert g.classify(g.root / "foo.py") == "allowed"
    assert g.classify(g.root / "sub" / "deep" / "file.txt") == "allowed"


def test_classify_outside_workspace_is_outside(tmp_path):
    g = _guard(tmp_path)
    assert g.classify("/tmp/foo") == "outside"


def test_classify_protected_path_is_protected(tmp_path):
    g = _guard(tmp_path)
    protected_file = tmp_path / "protected" / "agent.py"
    assert g.classify(protected_file) == "protected"


def test_classify_workspace_root_itself_is_allowed(tmp_path):
    g = _guard(tmp_path)
    assert g.classify(g.root) == "allowed"


# ---------------------------------------------------------------------------
# check_write()
# ---------------------------------------------------------------------------

def test_check_write_allowed_returns_none(tmp_path):
    g = _guard(tmp_path)
    assert g.check_write(g.root / "ok.py") is None


def test_check_write_outside_returns_violation(tmp_path):
    g = _guard(tmp_path)
    v = g.check_write("/tmp/escape.py")
    assert isinstance(v, WorkspaceViolation)
    assert v.status == "outside"
    assert "/tmp/escape.py" in v.path
    assert "outside" in v.reason.lower()
    assert str(g.root) in v.suggested_fix


def test_check_write_protected_returns_violation(tmp_path):
    g = _guard(tmp_path)
    target = tmp_path / "protected" / "agent.py"
    v = g.check_write(target)
    assert isinstance(v, WorkspaceViolation)
    assert v.status == "protected"
    assert "protected" in v.reason.lower() or "never modify" in v.reason.lower()


def test_check_write_relative_path_resolves_against_cwd_NOT_workspace(tmp_path):
    """check_write does not auto-resolve relative paths; callers must use
    resolve_under_root first. This documents the contract."""
    g = _guard(tmp_path)
    # A bare relative path resolves against the process cwd, which is almost
    # certainly NOT the workspace in production. Without resolve_under_root
    # it would be classified as 'outside' (because the test cwd is not the
    # workspace). The point: tools MUST call resolve_under_root.
    v = g.check_write("foo.py")
    # Either outside or — if pytest cwd happens to be inside the test ws —
    # allowed. The contract is just that no crash and a deterministic result.
    assert v is None or v.status in ("outside", "protected")


# ---------------------------------------------------------------------------
# resolve_under_root()
# ---------------------------------------------------------------------------

def test_resolve_under_root_makes_relative_absolute_under_workspace(tmp_path):
    g = _guard(tmp_path)
    resolved = g.resolve_under_root("foo/bar.py")
    assert resolved == (g.root / "foo" / "bar.py").resolve()


def test_resolve_under_root_keeps_absolute_path_intact(tmp_path):
    g = _guard(tmp_path)
    abs_inside = g.root / "x.py"
    assert g.resolve_under_root(abs_inside) == abs_inside.resolve()
    abs_outside = Path("/tmp/x.py")
    assert g.resolve_under_root(abs_outside) == abs_outside.resolve()


def test_resolve_under_root_expands_tilde(tmp_path, monkeypatch):
    g = _guard(tmp_path)
    monkeypatch.setenv("HOME", str(tmp_path))
    resolved = g.resolve_under_root("~/foo.py")
    assert resolved == (tmp_path / "foo.py").resolve()


def test_resolve_then_check_write_blocks_dotdot_escape(tmp_path):
    """A `../../etc/passwd` style escape must be caught after resolution."""
    g = _guard(tmp_path)
    escaping = g.resolve_under_root("../../../tmp/escape.py")
    v = g.check_write(escaping)
    assert v is not None
    assert v.status == "outside"


# ---------------------------------------------------------------------------
# check_read() — permissive by default
# ---------------------------------------------------------------------------

def test_check_read_allows_outside_by_default(tmp_path):
    g = _guard(tmp_path)
    assert g.check_read("/etc/passwd") is None
    assert g.check_read("/tmp/foo") is None


def test_check_read_can_be_strict(tmp_path):
    workspace = (tmp_path / "ws").resolve()
    workspace.mkdir()
    cfg = WorkspaceConfig(root=workspace, allow_outside_reads=False)
    g = WorkspaceGuard(cfg)
    assert g.check_read("/tmp/foo") is not None
    assert g.check_read(workspace / "ok.py") is None


# ---------------------------------------------------------------------------
# Config invariants
# ---------------------------------------------------------------------------

def test_workspace_config_rejects_relative_root():
    with pytest.raises(ValueError):
        WorkspaceConfig(root=Path("relative/ws"))


def test_workspace_config_rejects_relative_protected():
    with pytest.raises(ValueError):
        WorkspaceConfig(root=Path("/tmp/ws"), protected_paths=(Path("rel/path"),))


# ---------------------------------------------------------------------------
# Integration with write_file / edit_file (using settings override)
# ---------------------------------------------------------------------------

def test_write_file_respects_guard(tmp_path, monkeypatch):
    from agent.infrastructure.config import settings as settings_mod
    from agent.infrastructure.tools.impl.tools.file_ops import write_file
    import json

    ws = (tmp_path / "project").resolve()
    ws.mkdir()
    protected = (tmp_path / "agent_code").resolve()
    protected.mkdir()
    cfg = WorkspaceConfig(root=ws, protected_paths=(protected,))
    g = WorkspaceGuard(cfg)
    monkeypatch.setattr(settings_mod, "_WORKSPACE_GUARD", g)

    # Allowed: relative path resolves under ws
    r = json.loads(write_file("hello.py", "print(1)"))
    assert r["ok"] is True, r
    assert (ws / "hello.py").exists()

    # Outside: rejected
    r = json.loads(write_file("/tmp/outside.py", "x"))
    assert r["ok"] is False
    assert r["error_type"] == "WorkspaceViolation"
    assert r["meta"]["violation_status"] == "outside"

    # Protected: rejected
    r = json.loads(write_file(str(protected / "foo.py"), "x"))
    assert r["ok"] is False
    assert r["error_type"] == "WorkspaceViolation"
    assert r["meta"]["violation_status"] == "protected"


def test_edit_file_respects_guard(tmp_path, monkeypatch):
    from agent.infrastructure.config import settings as settings_mod
    from agent.infrastructure.tools.impl.tools.file_ops import edit_file
    import json

    ws = (tmp_path / "project").resolve()
    ws.mkdir()
    protected = (tmp_path / "agent_code").resolve()
    protected.mkdir()
    # Create a real protected file so the test exercises the boundary check,
    # not the "file does not exist" check.
    (protected / "real.py").write_text("hello world", encoding="utf-8")
    cfg = WorkspaceConfig(root=ws, protected_paths=(protected,))
    g = WorkspaceGuard(cfg)
    monkeypatch.setattr(settings_mod, "_WORKSPACE_GUARD", g)

    r = json.loads(edit_file(str(protected / "real.py"), "hello", "bye"))
    assert r["ok"] is False
    assert r["error_type"] == "WorkspaceViolation"
    # The file content must be untouched.
    assert (protected / "real.py").read_text(encoding="utf-8") == "hello world"


# ---------------------------------------------------------------------------
# detect_workspace_violation() telemetry helper
# ---------------------------------------------------------------------------

def test_detect_workspace_violation_fires_on_error_type():
    from agent.application.runtime.tool_telemetry import detect_workspace_violation
    parsed = {
        "status": "error",
        "summary": "Error: WORKSPACE BOUNDARY VIOLATION: ...",
        "error_type": "WorkspaceViolation",
        "meta": {
            "path": "/tmp/foo.py",
            "violation_status": "outside",
            "suggested_fix": "use a relative path",
        },
    }
    out = detect_workspace_violation("write_file", parsed)
    assert out is not None
    assert out["tool_name"] == "write_file"
    assert out["status"] == "outside"
    assert out["path"] == "/tmp/foo.py"
    assert "relative" in out["suggested_fix"]


def test_detect_workspace_violation_silent_on_other_errors():
    from agent.application.runtime.tool_telemetry import detect_workspace_violation
    parsed = {"status": "error", "summary": "Error: file not found", "error_type": "NotFound"}
    assert detect_workspace_violation("write_file", parsed) is None


def test_detect_workspace_violation_silent_on_success():
    from agent.application.runtime.tool_telemetry import detect_workspace_violation
    parsed = {"status": "ok", "summary": "wrote 100 chars"}
    assert detect_workspace_violation("write_file", parsed) is None
