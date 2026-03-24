"""Session persistence port for application/runtime layers."""

from __future__ import annotations

from typing import Protocol


class SessionStore(Protocol):
    loaded_existing: bool
    chat_history: list[dict]

    def now_iso(self) -> str: ...

    def ensure_session(self) -> None: ...

    def initialize_history(self) -> None: ...

    def persist_message(
        self,
        role: str,
        content: str,
        tool_call_id: str | None = None,
        tool_name: str | None = None,
        meta: dict | None = None,
    ) -> None: ...

    def persist_tool_call(
        self,
        call_id: str,
        name: str,
        args: dict,
        raw_args: str,
        ts_start: str,
        ts_end: str,
        result: str,
    ) -> None: ...
