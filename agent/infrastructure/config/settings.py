"""配置模块"""
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI, AsyncOpenAI

from agent.domain import WorkspaceConfig, WorkspaceGuard
from agent.domain.project_manager import find_or_create_project_dir

load_dotenv()


# ---------------------------------------------------------------------------
# Workspace boundary
# ---------------------------------------------------------------------------
#
# Quanora is an autonomous coding agent: when it writes code for a user's
# project, that code MUST land in the user's project directory — never in
# Quanora's own source tree.
#
# Two paths matter:
#
#   * QUANORA_WORKSPACE  — the project directory the agent is working on.
#                          Default: ./workspace (resolved relative to the
#                          process cwd). All writes are confined here.
#   * QUANORA_HOME       — Quanora's own install root (defaults to the
#                          directory containing this file's grandparent's
#                          parent, i.e. the repo root). Marked PROTECTED so
#                          the agent cannot modify it.

_QUANORA_REPO_ROOT = Path(__file__).resolve().parents[3]  # .../webapp


def _resolve_workspace_root() -> Path:
    raw = os.getenv("QUANORA_WORKSPACE")
    if raw:
        return Path(raw).expanduser().resolve()
    # Default: a sibling "workspace" directory next to Quanora itself. We
    # deliberately do NOT default to the repo root — that's where Quanora's
    # own code lives.
    return (_QUANORA_REPO_ROOT / "workspace").resolve()


def _resolve_protected_paths(workspace_root: Path) -> tuple[Path, ...]:
    """Return paths the agent must never write into.

    Quanora's own source code (``agent/``, ``test/``, ``.quanora/``,
    ``scripts/``) is always protected. If the user happens to point
    ``QUANORA_WORKSPACE`` at the repo root, these still hold — the agent
    can write to new sibling files but cannot touch the existing source.
    """
    protected = [
        _QUANORA_REPO_ROOT / "agent",
        _QUANORA_REPO_ROOT / "test",
        _QUANORA_REPO_ROOT / ".quanora",
        _QUANORA_REPO_ROOT / "scripts",
        _QUANORA_REPO_ROOT / "docs",
        _QUANORA_REPO_ROOT / ".git",
        _QUANORA_REPO_ROOT / "main.py",
        _QUANORA_REPO_ROOT / "requirements.txt",
        _QUANORA_REPO_ROOT / ".env",
        _QUANORA_REPO_ROOT / ".env.example",
    ]
    # Honour an optional, comma-separated env override that adds extra
    # protected paths (e.g. another in-house library the user mounts but
    # does not want touched).
    extra = os.getenv("QUANORA_PROTECTED_PATHS", "").strip()
    if extra:
        for entry in extra.split(","):
            entry = entry.strip()
            if entry:
                protected.append(Path(entry).expanduser().resolve())
    # De-dupe and resolve. Skip entries that don't exist on disk so we don't
    # accidentally protect random typos.
    seen: set[Path] = set()
    out: list[Path] = []
    for p in protected:
        try:
            rp = p.resolve()
        except OSError:
            continue
        if rp in seen:
            continue
        seen.add(rp)
        out.append(rp)
    return tuple(out)


_WORKSPACE_BASE = _resolve_workspace_root()
# ── 项目级 workspace 分区 ──
# 如果设置了 QUANORA_PROJECT_NAME 环境变量，workspace 将在
# _WORKSPACE_BASE/<project_slug> 子目录中创建；否则退回默认行为。
_PROJECT_NAME = os.environ.get("QUANORA_PROJECT_NAME", "")
if _PROJECT_NAME:
    _WORKSPACE_ROOT = find_or_create_project_dir(
        workspace_root=_WORKSPACE_BASE,
        task_description=_PROJECT_NAME,
    )
else:
    _WORKSPACE_ROOT = _WORKSPACE_BASE
# Create the workspace dir on first import so the agent has somewhere to write
# from the moment it boots. We do NOT touch protected paths.
try:
    _WORKSPACE_ROOT.mkdir(parents=True, exist_ok=True)
except OSError:
    # Read-only filesystem or permission issue — leave to the guard to report.
    pass

_WORKSPACE_CONFIG = WorkspaceConfig(
    root=_WORKSPACE_ROOT,
    protected_paths=_resolve_protected_paths(_WORKSPACE_ROOT),
    allow_outside_reads=True,
)
_WORKSPACE_GUARD = WorkspaceGuard(_WORKSPACE_CONFIG)

# Self-dev mode flag. When True the workspace is rebuilt to point at the
# Quanora repo root, with only .git protected — so the agent can edit its
# own source code, run its own tests, and commit/push the result.
_SELF_DEV_MODE: bool = False

# Self-doc mode flag. When True the workspace points at the Quanora repo
# root, with the full repo tree protected — but ``.md`` files are exempt
# via the ``protected_write_extensions`` whitelist. This allows the agent
# to read and improve its own documentation without touching source code.
_SELF_DOC_MODE: bool = False


def get_workspace_guard() -> WorkspaceGuard:
    """Return the process-wide workspace guard.

    Tools call this to validate paths before any write. Tests may replace
    the guard via :func:`set_workspace_guard` for isolation.
    """
    return _WORKSPACE_GUARD


def set_workspace_guard(guard: WorkspaceGuard) -> None:
    """Override the process-wide guard (test-only seam)."""
    global _WORKSPACE_GUARD
    _WORKSPACE_GUARD = guard


def is_self_dev_mode() -> bool:
    """Return True when the agent is running in self-development mode."""
    return _SELF_DEV_MODE


def enable_self_dev_mode() -> WorkspaceGuard:
    """Switch the agent into self-development mode.

    Effects:

    * Workspace root → the Quanora repo root. All file writes now land
      in Quanora's own source tree by default.
    * Protected paths → reduced to ``.git/`` only. The agent can now edit
      ``agent/``, ``test/``, ``main.py``, ``.quanora/skills/``, prompts,
      docs, etc. ``.git/`` stays protected so the agent uses ``git``
      commands (via ``bash``) rather than tampering with git internals.
    * Global flag :func:`is_self_dev_mode` returns True so other layers
      (system prompt, CLI banner, skills) can branch on it.

    Returns the new workspace guard so callers can verify the swap.

    This is intentionally a runtime switch (not a separate process or
    config file) so the same Python process boots either way. Tests
    can call this in setup and reset with :func:`disable_self_dev_mode`.
    """
    global _SELF_DEV_MODE, _WORKSPACE_GUARD
    _SELF_DEV_MODE = True

    # In self-dev mode .git is the only thing that stays off-limits. We
    # protect a few read-only files (.env containing secrets) as well, to
    # avoid the agent accidentally rewriting credentials.
    protected: list[Path] = []
    for candidate in (
        _QUANORA_REPO_ROOT / ".git",
        _QUANORA_REPO_ROOT / ".env",
    ):
        try:
            rp = candidate.resolve()
        except OSError:
            continue
        if rp.exists():
            protected.append(rp)

    # Honour optional extra protected paths from the environment.
    extra = os.getenv("QUANORA_PROTECTED_PATHS", "").strip()
    if extra:
        for entry in extra.split(","):
            entry = entry.strip()
            if entry:
                try:
                    rp = Path(entry).expanduser().resolve()
                except OSError:
                    continue
                if rp not in protected:
                    protected.append(rp)

    new_cfg = WorkspaceConfig(
        root=_QUANORA_REPO_ROOT,
        protected_paths=tuple(protected),
        allow_outside_reads=True,
    )
    _WORKSPACE_GUARD = WorkspaceGuard(new_cfg)
    return _WORKSPACE_GUARD


def switch_to_project_workspace(task_description: str) -> Path:
    """根据任务描述动态切换 workspace 到项目子目录。

    在 _WORKSPACE_BASE 下按项目名建立子目录（如 xauusd_timeseries_signal_backtest_spec/），
    并更新全局 workspace_guard 使所有后续写入定向到该目录。

    :param task_description: 用户任务描述（如文件名、需求描述）
    :returns: 新的项目子目录路径
    """
    global _WORKSPACE_ROOT, _WORKSPACE_GUARD

    project_dir = find_or_create_project_dir(
        workspace_root=_WORKSPACE_BASE,
        task_description=task_description,
    )

    _WORKSPACE_ROOT = project_dir
    _WORKSPACE_GUARD = WorkspaceGuard(
        WorkspaceConfig(
            root=project_dir,
            protected_paths=_resolve_protected_paths(project_dir),
            allow_outside_reads=True,
        )
    )
    # 同步 Config 类属性，使 runtime 等模块读取时拿到新值
    Config.WORKSPACE_ROOT = project_dir
    return project_dir


def disable_self_dev_mode() -> WorkspaceGuard:
    """Restore the default (non-self-dev) workspace guard. Test-only."""
    global _SELF_DEV_MODE, _WORKSPACE_GUARD
    _SELF_DEV_MODE = False
    _WORKSPACE_GUARD = WorkspaceGuard(
        WorkspaceConfig(
            root=_WORKSPACE_ROOT,
            protected_paths=_resolve_protected_paths(_WORKSPACE_ROOT),
            allow_outside_reads=True,
        )
    )
    return _WORKSPACE_GUARD


# ---------------------------------------------------------------------------
# Self-doc mode
# ---------------------------------------------------------------------------

def is_self_doc_mode() -> bool:
    """Return whether the agent is running in *self-doc* (markdown-only) mode."""
    return _SELF_DOC_MODE


def enable_self_doc_mode() -> WorkspaceGuard:
    """Switch the agent into *self-doc* (markdown-only editing) mode.

    Effects:

    * Workspace root → the Quanora repo root, same as self-dev.
    * Protected paths → the *full* Quanora repo tree (``agent/``, ``test/``,
      ``main.py``, ``.quanora/``, etc.). However, files whose extension is
      ``.md`` are **exempt** from the write ban via
      ``protected_write_extensions``. This allows the agent to read and
      improve its own documentation (README, docs/, .quanora/skills/*/SKILL.md,
      etc.) without touching source code.
    * ``.git/`` and ``.env`` stay fully protected — even ``.md`` inside
      ``.git/`` must not be written.
    * Global flag :func:`is_self_doc_mode` returns True so other layers
      (system prompt, CLI banner) can branch on it.

    Returns the new workspace guard so callers can verify the swap.
    """
    global _SELF_DOC_MODE, _WORKSPACE_GUARD
    _SELF_DOC_MODE = True

    # Protect the entire Quanora repo tree. .md files will be exempted
    # via protected_write_extensions, but .git and .env are fully
    # off-limits (no .md exemption for those).
    protected: list[Path] = []
    for candidate in (
        _QUANORA_REPO_ROOT,          # the whole repo tree
        _QUANORA_REPO_ROOT / ".git",  # git internals — always fully protected
        _QUANORA_REPO_ROOT / ".env",  # secrets — always fully protected
    ):
        try:
            rp = candidate.resolve()
        except OSError:
            continue
        if rp.exists():
            protected.append(rp)

    # Remove duplicates — .git and .env are under the repo root, but
    # we want to be explicit about them.
    protected = list(dict.fromkeys(protected))

    # .git/ and .env are "fully protected" — no extension whitelist
    # exemption applies there, even for .md files.
    fully_protected: list[Path] = []
    for candidate in (
        _QUANORA_REPO_ROOT / ".git",  # git internals — always fully protected
        _QUANORA_REPO_ROOT / ".env",  # secrets — always fully protected
    ):
        try:
            rp = candidate.resolve()
        except OSError:
            continue
        if rp.exists():
            fully_protected.append(rp)

    # Remove duplicates
    fully_protected = list(dict.fromkeys(fully_protected))

    new_cfg = WorkspaceConfig(
        root=_QUANORA_REPO_ROOT,
        protected_paths=tuple(protected),
        allow_outside_reads=True,
        protected_write_extensions=(".md",),
        fully_protected_paths=tuple(fully_protected),
    )
    _WORKSPACE_GUARD = WorkspaceGuard(new_cfg)
    return _WORKSPACE_GUARD


def disable_self_doc_mode() -> WorkspaceGuard:
    """Restore the default (non-self-doc) workspace guard. Test-only."""
    global _SELF_DOC_MODE, _WORKSPACE_GUARD
    _SELF_DOC_MODE = False
    _WORKSPACE_GUARD = WorkspaceGuard(
        WorkspaceConfig(
            root=_WORKSPACE_ROOT,
            protected_paths=_resolve_protected_paths(_WORKSPACE_ROOT),
            allow_outside_reads=True,
        )
    )
    return _WORKSPACE_GUARD


class Config:
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_API_BASE = os.getenv("OPENAI_API_BASE", "https://api.openai.com/v1")
    DEFAULT_MODEL = os.getenv("DEFAULT_MODEL", "gpt-4o-mini")
    TEMPERATURE = float(os.getenv("TEMPERATURE", "0.7"))
    MAX_TOKENS = int(os.getenv("MAX_TOKENS", "2000"))

    # Workspace boundary (resolved at import time).
    WORKSPACE_ROOT = _WORKSPACE_ROOT
    QUANORA_HOME = _QUANORA_REPO_ROOT

    @classmethod
    def validate(cls):
        if not cls.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is required")
        return True

    @classmethod
    def get_client(cls) -> OpenAI:
        return OpenAI(api_key=cls.OPENAI_API_KEY, base_url=cls.OPENAI_API_BASE)

    @classmethod
    def get_async_client(cls) -> AsyncOpenAI:
        return AsyncOpenAI(api_key=cls.OPENAI_API_KEY, base_url=cls.OPENAI_API_BASE)
