"""Session-local plan file storage helpers."""

from __future__ import annotations

import json
import os
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_ACTIVE_SESSION_ROOT: ContextVar[str | None] = ContextVar("quanora_plan_session_root", default=None)
_ACTIVE_SESSION_ID: ContextVar[str | None] = ContextVar("quanora_plan_session_id", default=None)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def set_active_session_context(session_root: str, session_id: str) -> None:
    root = str(session_root or "").strip()
    sid = str(session_id or "").strip()
    if not root or not sid:
        return
    _ACTIVE_SESSION_ROOT.set(root)
    _ACTIVE_SESSION_ID.set(sid)


def resolve_session_base() -> tuple[Path, str]:
    context_root = _ACTIVE_SESSION_ROOT.get()
    context_id = _ACTIVE_SESSION_ID.get()
    if context_root and context_id:
        base = Path(context_root) / context_id
        if base.is_dir():
            return base, context_id

    env_root = os.getenv("AGENT_SESSION_ROOT")
    env_id = os.getenv("AGENT_SESSION_ID")
    if env_root and env_id:
        base = Path(env_root) / env_id
        if base.is_dir():
            return base, env_id
    raise FileNotFoundError(
        "No active session context found. Ensure session is initialized before using plan tools "
        "(missing task-local plan session context or AGENT_SESSION_ROOT / AGENT_SESSION_ID)."
    )


def plan_paths() -> tuple[Path, Path, str]:
    base, session_id = resolve_session_base()
    return base / "plan.json", base / "plan_events.jsonl", session_id


def load_plan() -> tuple[dict[str, Any], Path, Path]:
    plan_file, events_file, session_id = plan_paths()
    if not plan_file.exists():
        raise FileNotFoundError(f"No plan found in current session: {session_id}")
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Corrupted plan file: {exc}") from exc
    if not isinstance(plan, dict):
        raise ValueError("Corrupted plan file: expected object.")
    return plan, plan_file, events_file


def load_plan_if_exists() -> dict[str, Any] | None:
    plan_file, _, _ = plan_paths()
    if not plan_file.exists():
        return None
    try:
        plan = json.loads(plan_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise ValueError(f"Corrupted plan file: {exc}") from exc
    if not isinstance(plan, dict):
        raise ValueError("Corrupted plan file: expected object.")
    return plan


def append_event(events_file: Path, event: dict[str, Any]) -> None:
    line = json.dumps(event, ensure_ascii=False)
    with events_file.open("a", encoding="utf-8") as handle:
        handle.write(line + "\n")
        handle.flush()


def write_json_atomic(path: Path, data: dict[str, Any]) -> None:
    tmp = path.with_name(f"{path.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def archive_completed_plan(plan_file: Path, events_file: Path) -> Path | None:
    """Move a completed plan and its events into an archive subdirectory.

    Returns the archive directory path, or None if nothing to archive.
    """
    if not plan_file.exists():
        return None
    archive_dir = plan_file.parent / "archive"
    archive_dir.mkdir(parents=True, exist_ok=True)

    # Use a timestamp-based subdirectory to avoid collisions (microsecond precision)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    dest_dir = archive_dir / stamp
    # Handle rare case of same-microsecond collision by appending a counter
    counter = 0
    while dest_dir.exists():
        counter += 1
        dest_dir = archive_dir / f"{stamp}_{counter}"
    dest_dir.mkdir(parents=True, exist_ok=True)

    # Move plan.json
    dest_plan = dest_dir / plan_file.name
    os.replace(plan_file, dest_plan)

    # Move events file if it exists
    if events_file.exists():
        dest_events = dest_dir / events_file.name
        os.replace(events_file, dest_events)

    return dest_dir


def bump_version(plan: dict[str, Any]) -> tuple[int, int]:
    old = int(plan.get("version", 0))
    new = old + 1
    plan["version"] = new
    plan["updated_at"] = now_iso()
    return old, new


def persist_plan_update(
    *,
    plan: dict[str, Any],
    plan_file: Path,
    events_file: Path,
    event_type: str,
    payload: dict[str, Any],
) -> None:
    old_version, new_version = bump_version(plan)
    event = {
        "event_id": uuid.uuid4().hex,
        "ts": now_iso(),
        "actor": "agent",
        "plan_id": plan.get("plan_id"),
        "type": event_type,
        "payload": payload,
        "from_version": old_version,
        "to_version": new_version,
    }
    append_event(events_file, event)
    write_json_atomic(plan_file, plan)
