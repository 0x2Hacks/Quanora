"""Application-level safe tool execution service."""

from __future__ import annotations

import traceback
import asyncio
from typing import AsyncIterator

from agent.application.ports import ToolRegistry
from agent.application.services.job_service import JobService
from agent.domain import looks_like_tool_payload, tool_error, tool_ok
from agent.domain.jobs import ToolExecutionResult, JobHandle, JobStatus
from agent.domain.events import RuntimeEvent, ToolProgressEvent, ToolResultEvent


class ToolExecutor:
    """Runs tool calls with standardized error handling and job semantics."""

    def __init__(self, registry: ToolRegistry, job_service: JobService | None = None):
        self._registry = registry
        self._job_service = job_service

    def execute(self, name: str, args: dict, raw_args: str | None = None) -> str:
        """Legacy synchronous execution returning a string payload."""
        result = self.execute_sync(name, args, raw_args)
        if result.status == "ok":
            if isinstance(result.result_str, str) and looks_like_tool_payload(result.result_str):
                return result.result_str
            return tool_ok(name, result.result_str)
        else:
            return tool_error(name, result.error_msg, result.error_type, meta=result.metadata)

    def execute_sync(self, name: str, args: dict, raw_args: str | None = None) -> ToolExecutionResult:
        """Synchronous execution returning a structured ToolExecutionResult."""
        if not self._registry.has(name):
            return ToolExecutionResult(
                status="error",
                error_msg=f"Unknown tool: {name}",
                error_type="ToolNotFound"
            )
        try:
            result = self._registry.call(name, args)
            return ToolExecutionResult(
                status="ok",
                result_str=result if isinstance(result, str) else str(result)
            )
        except TypeError as exc:
            meta = {"raw_args": (raw_args or "")[:2000]} if raw_args else {}
            return ToolExecutionResult(
                status="error",
                error_msg=str(exc),
                error_type=type(exc).__name__,
                metadata=meta
            )
        except Exception as exc:
            meta = {"traceback": traceback.format_exc()[-4000:]}
            if raw_args:
                meta["raw_args"] = raw_args[:2000]
            return ToolExecutionResult(
                status="error",
                error_msg=str(exc),
                error_type=type(exc).__name__,
                metadata=meta
            )

    # Alignment D: `start_job` and `stream_job_events` were transition stubs and have been
    # fully replaced by `AsyncToolCallProcessor`. This class is now strictly an execution bridge.
