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


def get_repo_root() -> Path:
    """Return the absolute path to the Quanora repository root."""
    return _QUANORA_REPO_ROOT


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
    * **workspace/ directory is fully protected** — in self-dev mode the
      agent must not write into the user's project workspace. All writes
      should go to the Quanora repo source tree instead.
    * Global flag :func:`is_self_dev_mode` returns True so other layers
      (system prompt, CLI banner, skills) can branch on it.

    Returns the new workspace guard so callers can verify the swap.

    This is intentionally a runtime switch (not a separate process or
    config file) so the same Python process boots either way. Tests
    can call this in setup and reset with :func:`disable_self_dev_mode`.
    """
    global _SELF_DEV_MODE, _WORKSPACE_GUARD, _WORKSPACE_ROOT
    _SELF_DEV_MODE = True
    # Keep project sub-directories organised under workspace/ rather than
    # littering the repo root.  The guard still grants write access to the
    # whole repo (agent/, test/, docs/, …) so self-dev edits work.
    _WORKSPACE_ROOT = _QUANORA_REPO_ROOT / "workspace"

    # In self-dev mode .git is the only thing that stays off-limits. We
    # protect a few read-only files (.env containing secrets) as well, to
    # avoid the agent accidentally rewriting credentials.
    protected: list[Path] = []
    fully_protected: list[Path] = []
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

    # In self-dev mode, the workspace/ directory (user project directory)
    # must be FULLY protected — no writes allowed. This prevents the agent
    # from accidentally creating files in the user's project when it should
    # be editing its own source tree. fully_protected_paths blocks ALL
    # writes regardless of file extension.
    # NOTE: We add the path unconditionally — _is_under() uses string
    # prefix matching, so even if the directory doesn't exist yet we still
    # want to block writes that would create it.
    workspace_dir = _WORKSPACE_ROOT.resolve()
    fully_protected.append(workspace_dir)

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
        fully_protected_paths=tuple(fully_protected),
        allow_outside_reads=True,
    )
    _WORKSPACE_GUARD = WorkspaceGuard(new_cfg)
    return _WORKSPACE_GUARD


def _resolve_protected_paths_for_mode(workspace_root: Path) -> tuple[Path, ...]:
    """根据当前模式（self-dev / self-doc / 普通）计算受保护路径。

    - self-dev 模式：仅保护 .git/ 和 .env（允许修改 agent/ 等自身代码）
    - self-doc 模式：保护所有源代码目录，但允许 .md 文件写入
    - 普通模式：保护所有源代码目录和文件
    """
    if _SELF_DEV_MODE:
        return (
            _QUANORA_REPO_ROOT / ".git",
            _QUANORA_REPO_ROOT / ".env",
        )
    if _SELF_DOC_MODE:
        return _resolve_protected_paths(workspace_root)
    return _resolve_protected_paths(workspace_root)


def switch_to_project_workspace(task_description: str) -> Path:
    """根据任务描述动态切换 workspace 到项目子目录。

    在当前 workspace_root 下按项目名建立子目录（如 xauusd_timeseries_signal_backtest_spec/），
    并更新全局 workspace_guard 使所有后续写入定向到该目录。

    注意：使用 _WORKSPACE_ROOT（而非 _WORKSPACE_BASE）作为父目录，
    这样在 self-dev/self-doc 模式下项目子目录会正确地创建在 repo root 下，
    而不是在 workspace/ 下产生额外嵌套。

    :param task_description: 用户任务描述（如文件名、需求描述）
    :returns: 新的项目子目录路径
    """
    global _WORKSPACE_ROOT, _WORKSPACE_GUARD

    # In self-doc mode, there is no need to create a project sub-directory —
    # the agent edits .md files under the repo root (e.g. docs/xxx.md).
    # Skip find_or_create_project_dir entirely to avoid littering the repo
    # root with empty folders like "tokenized-stock-funding-backtest-md/".
    if _SELF_DOC_MODE:
        project_dir = _QUANORA_REPO_ROOT
    else:
        project_dir = find_or_create_project_dir(
            workspace_root=_WORKSPACE_ROOT,
            task_description=task_description,
        )
        _WORKSPACE_ROOT = project_dir
    protected = _resolve_protected_paths_for_mode(project_dir)
    # In self-doc mode, .md files in protected areas should still be writable
    write_ext = (".md",) if _SELF_DOC_MODE else ()
    # In self-dev mode, guard root should remain repo root so agent/ etc.
    # remain writable; resolve_root is the project dir so relative paths
    # (like write_file("data.csv")) land in the project folder.
    # In self-doc mode, both guard_root and resolve_root should remain repo
    # root — the whole point of self-doc is to write into docs/ under the
    # repo, NOT to switch into an empty project sub-directory.  Previously
    # self-doc mistakenly set guard_root=project_dir (a new empty dir) and
    # resolve_root=None, causing .md writes to land in the empty dir instead
    # of the real docs/ tree.
    if _SELF_DEV_MODE:
        guard_root = _QUANORA_REPO_ROOT
        resolve_root = project_dir
    elif _SELF_DOC_MODE:
        # self-doc: keep repo root for both guard and resolve so docs/xxx.md
        # resolves correctly.  project_dir is only used for metadata tracking.
        guard_root = _QUANORA_REPO_ROOT
        resolve_root = _QUANORA_REPO_ROOT
    else:
        guard_root = project_dir
        resolve_root = None
    _WORKSPACE_GUARD = WorkspaceGuard(
        WorkspaceConfig(
            root=guard_root,
            resolve_root=resolve_root,
            protected_paths=protected,
            allow_outside_reads=True,
            protected_write_extensions=write_ext,
        )
    )
    # 同步 Config 类属性，使 runtime 等模块读取时拿到新值
    # In self-doc mode, keep Config.WORKSPACE_ROOT at repo root
    if not _SELF_DOC_MODE:
        Config.WORKSPACE_ROOT = project_dir
    return project_dir


def disable_self_dev_mode() -> WorkspaceGuard:
    """Restore the default (non-self-dev) workspace guard. Test-only."""
    global _SELF_DEV_MODE, _WORKSPACE_GUARD, _WORKSPACE_ROOT
    _SELF_DEV_MODE = False
    _WORKSPACE_ROOT = _WORKSPACE_BASE
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
    global _SELF_DOC_MODE, _WORKSPACE_GUARD, _WORKSPACE_ROOT
    _SELF_DOC_MODE = True
    _WORKSPACE_ROOT = _QUANORA_REPO_ROOT
    Config.WORKSPACE_ROOT = _QUANORA_REPO_ROOT

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
    global _SELF_DOC_MODE, _WORKSPACE_GUARD, _WORKSPACE_ROOT
    _SELF_DOC_MODE = False
    _WORKSPACE_ROOT = _WORKSPACE_BASE
    Config.WORKSPACE_ROOT = _WORKSPACE_BASE
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
