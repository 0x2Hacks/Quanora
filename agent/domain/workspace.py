"""Workspace boundary — a framework-level domain concept.

The agent operates against a **project workspace** (e.g. `~/quanora-projects/my-quant-strategy`).
All code/files the agent writes MUST live under that workspace.

This module defines:

* :class:`WorkspaceConfig` — the immutable boundary description (root +
  protected paths).
* :class:`WorkspaceGuard` — pure-domain validator that classifies any
  absolute path as ``allowed`` / ``outside`` / ``protected``. Tools and
  the runtime use this to reject writes that would pollute the agent's
  own code base or escape the project sandbox.
* :class:`WorkspaceViolation` — the structured violation record returned
  to the runtime (lifted to ``WorkspaceViolationEvent`` for the CLI and
  to a ``tool_error`` for the model).

There is **no I/O in this module** — it is pure logic so it can be unit
tested in isolation and shared across infrastructure adapters.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional
from pathlib import Path, PurePath
from typing import Literal


PathStatus = Literal["allowed", "outside", "protected"]


@dataclass(frozen=True, slots=True)
class WorkspaceConfig:
    """Immutable workspace boundary.

    Attributes
    ----------
    root :
        Absolute, resolved path to the project workspace. Every write must
        land **inside** this directory.
    protected_paths :
        Absolute resolved paths that are inside ``root`` (or anywhere on
        disk) but must never be modified by the agent — typically the
        directories that contain the Quanora agent's own source code
        (``agent/``, ``test/``, ``.quanora/``…). Reads are still allowed.
        Files whose extension matches ``protected_write_extensions`` are
        exempt from this ban (see below).
    allow_outside_reads :
        Reads outside the workspace are allowed (the agent legitimately
        needs to read system files, libraries, etc.). This flag exists
        only to make the policy explicit.
    protected_write_extensions :
        File extensions that are **exempt** from the protected-path write
        ban. If a file's suffix matches one of these (e.g. ``".md"``),
        it can be written even inside a protected subtree — **unless**
        that subtree is also listed in ``fully_protected_paths``. This
        enables ``self-doc`` mode where the agent may edit documentation
        but not source code inside the Quanora repo. Extensions are
        compared case-insensitively.
    fully_protected_paths :
        Paths that are **always protected, regardless of file extension**.
        No extension whitelist applies here — even ``.md`` files inside
        a fully-protected path cannot be written. Typical entries:
        ``.git/`` and ``.env``. These paths must also appear in
        ``protected_paths`` (the overlap is intentional — classify()
        checks ``fully_protected_paths`` *before* the extension whitelist
        logic).
    """

    root: Path
    resolve_root: Optional[Path] = None
    protected_paths: tuple[Path, ...] = field(default_factory=tuple)
    allow_outside_reads: bool = True
    protected_write_extensions: tuple[str, ...] = field(default_factory=tuple)
    fully_protected_paths: tuple[Path, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:  # pragma: no cover - dataclass guard
        if not self.root.is_absolute():
            raise ValueError(f"WorkspaceConfig.root must be absolute, got {self.root!r}")
        # Default resolve_root to root
        if self.resolve_root is None:
            object.__setattr__(self, 'resolve_root', self.root)
        for p in self.protected_paths:
            if not p.is_absolute():
                raise ValueError(f"protected_paths must be absolute, got {p!r}")


@dataclass(frozen=True, slots=True)
class WorkspaceViolation:
    """Result of a guard check that failed."""

    path: str
    status: PathStatus  # never "allowed" — this is a violation record
    reason: str
    suggested_fix: str


def _is_under(child: Path, parent: Path) -> bool:
    """Return True iff ``child`` is ``parent`` or a descendant of ``parent``.

    Both paths are expected to be absolute. We compare on resolved string
    representations so a path that does not yet exist still works.
    """
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


class WorkspaceGuard:
    """Pure-domain workspace boundary validator.

    The guard is intentionally **read-only** — it never touches the
    filesystem. Callers resolve paths themselves; the guard classifies
    them.
    """

    def __init__(self, config: WorkspaceConfig):
        self._cfg = config

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def root(self) -> Path:
        return self._cfg.root

    @property
    def protected_paths(self) -> tuple[Path, ...]:
        return self._cfg.protected_paths

    def classify(self, path: str | PurePath) -> PathStatus:
        """Classify a path against the workspace policy.

        Returns one of:

        * ``"allowed"`` — path is inside the workspace and not protected,
          **or** inside a protected subtree but its extension matches one
          of ``protected_write_extensions`` (e.g. ``.md`` in self-doc mode)
          and the subtree is not in ``fully_protected_paths``.
        * ``"protected"`` — path is inside a protected subtree and its
          extension is not whitelisted, **or** the subtree is in
          ``fully_protected_paths`` (extension whitelist does not apply).
        * ``"outside"`` — path is not inside the workspace at all.
        """
        resolved = self._resolve(path)

        # Step 1: fully_protected_paths — NO extension whitelist applies.
        # .git/ and .env are always fully protected, even for .md files.
        for fp in self._cfg.fully_protected_paths:
            if _is_under(resolved, fp):
                return "protected"

        # Step 2: protected_paths — extension whitelist may exempt .md
        # files in self-doc mode (but fully_protected_paths were already
        # checked above, so .git/.env won't be bypassed).
        for prot in self._cfg.protected_paths:
            if _is_under(resolved, prot):
                # Check extension whitelist — .md files in protected areas
                # are allowed in self-doc mode.
                if self._cfg.protected_write_extensions:
                    suffix = resolved.suffix.lower()
                    allowed_exts = tuple(
                        e.lower() for e in self._cfg.protected_write_extensions
                    )
                    if suffix in allowed_exts:
                        return "allowed"
                return "protected"

        if _is_under(resolved, self._cfg.root):
            return "allowed"

        return "outside"

    def check_write(self, path: str | PurePath) -> WorkspaceViolation | None:
        """Return ``None`` if writing to ``path`` is allowed, otherwise a violation.

        This is the single entry point write tools (``write_file``,
        ``edit_file``, ``bash`` for redirects, etc.) call before touching
        the disk.
        """
        status = self.classify(path)
        if status == "allowed":
            return None

        resolved = self._resolve(path)
        if status == "protected":
            return WorkspaceViolation(
                path=str(resolved),
                status="protected",
                reason=(
                    f"Path '{resolved}' is inside a protected directory — this is the "
                    "Quanora agent's own source code or sandbox metadata, the agent "
                    "must NEVER modify it."
                ),
                suggested_fix=(
                    "If you are writing project code, put it under the workspace root: "
                    f"{self._cfg.root}. If you genuinely need to modify Quanora's own "
                    "code, ask the user to do it manually."
                ),
            )

        # status == "outside"
        return WorkspaceViolation(
            path=str(resolved),
            status="outside",
            reason=(
                f"Path '{resolved}' is outside the project workspace "
                f"'{self._cfg.root}'. The agent must keep all generated files "
                "inside the workspace so the user's project stays self-contained."
            ),
            suggested_fix=(
                f"Use a relative path (it will resolve under the workspace) or an "
                f"absolute path inside {self._cfg.root}."
            ),
        )

    def check_read(self, path: str | PurePath) -> WorkspaceViolation | None:
        """Reads are permissive by default. Returns ``None`` unless reads
        outside the workspace have been explicitly disabled."""
        if self._cfg.allow_outside_reads:
            return None
        status = self.classify(path)
        if status == "outside":
            resolved = self._resolve(path)
            return WorkspaceViolation(
                path=str(resolved),
                status="outside",
                reason=f"Reads outside the workspace are disabled.",
                suggested_fix=f"Move the file into {self._cfg.root} before reading.",
            )
        return None

    def resolve_under_root(self, path: str | PurePath) -> Path:
        """Resolve a (possibly relative) path **as if** the cwd is the workspace root.

        This is how tools should canonicalize user/agent-supplied paths
        before calling :meth:`check_write` so relative paths land inside
        the workspace rather than wherever the Python process happens to
        live.
        """
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self._cfg.resolve_root / p
        return p.resolve()

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    @staticmethod
    def _resolve(path: str | PurePath) -> Path:
        return Path(path).expanduser().resolve()
