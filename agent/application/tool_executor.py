"""Application-level safe tool execution service."""

from __future__ import annotations

import traceback

from agent.domain import looks_like_tool_payload
from agent.infrastructure.tools.impl.core.base import tool_error, tool_ok


class ToolExecutor:
    """Runs tool calls with standardized error handling."""

    def __init__(self, registry):
        self._registry = registry

    def execute(self, name: str, args: dict, raw_args: str | None = None) -> str:
        if not self._registry.has(name):
            return tool_error(name, f"Unknown tool: {name}", "ToolNotFound")
        try:
            result = self._registry.call(name, args)
            if isinstance(result, str) and looks_like_tool_payload(result):
                return result
            return tool_ok(name, result)
        except TypeError as exc:
            meta = {"raw_args": (raw_args or "")[:2000]} if raw_args else None
            return tool_error(name, str(exc), type(exc).__name__, meta=meta)
        except Exception as exc:
            meta = {"traceback": traceback.format_exc()[-4000:]}
            if raw_args:
                meta["raw_args"] = raw_args[:2000]
            return tool_error(name, str(exc), type(exc).__name__, meta=meta)
