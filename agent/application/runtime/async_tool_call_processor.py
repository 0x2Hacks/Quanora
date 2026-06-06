"""Asynchronous tool scheduler and execution layer."""

from __future__ import annotations

import asyncio
import json
import time
from dataclasses import dataclass
from typing import AsyncIterator

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.domain import ParsedToolCall, looks_like_tool_payload, parse_tool_args, tool_error, tool_ok
from agent.domain.events import RuntimeEvent, ToolCallStartedEvent, ToolResultEvent, event_meta
from agent.application.tool_executor import ToolExecutor
from agent.application.runtime.cancellation import CancellationToken
from agent.application.services.tool_result_normalizer import ToolResultNormalizer


@dataclass(slots=True)
class _ToolCallOutcome:
    status: str
    result: str
    error_type: str = ""


class AsyncToolCallProcessor:
    """Executes parsed tool calls and yields runtime events."""

    def __init__(self, tool_executor: ToolExecutor, tool_result_normalizer: ToolResultNormalizer | None = None):
        self._tool_executor = tool_executor
        self._tool_result_normalizer = tool_result_normalizer or ToolResultNormalizer()
        self._empty_bash_output_counts_by_turn: dict[str, dict[str, int]] = {}

    async def execute(
        self,
        session: AsyncSessionStore,
        tool_calls: list[ParsedToolCall],
        cancellation_token: CancellationToken | None = None,
        turn_id: str = "",
    ) -> AsyncIterator[RuntimeEvent]:
        """
        Execute multiple tool calls asynchronously.
        Async tools (like bash) are awaited directly; sync tools run in a thread.
        """
        empty_bash_output_counts = self._counts_for_turn(turn_id)
        for call in tool_calls:
            if cancellation_token and cancellation_token.is_cancelled:
                break

            started_at = time.perf_counter()
            parsed_args, parse_error = parse_tool_args(call.raw_args)
            ts_start = session.now_iso()

            if parse_error:
                outcome = _ToolCallOutcome(
                    status="failed",
                    error_type="ToolArgsJSONError",
                    result=tool_error(
                        call.name,
                        f"Invalid tool arguments JSON: {parse_error}",
                        "ToolArgsJSONError",
                        meta={"raw_args": call.raw_args[:2000]},
                    ),
                )
            else:
                blocked_poll = self._empty_bash_output_pre_guard(call.name, parsed_args, empty_bash_output_counts)
                if blocked_poll:
                    outcome = _ToolCallOutcome(status="failed", error_type="RepeatedEmptyPoll", result=blocked_poll)
                else:
                    yield ToolCallStartedEvent(
                        **event_meta(session, turn_id),
                        tool_call_id=call.call_id,
                        tool_name=call.name,
                    )
                    outcome = await self._run_tool_call(
                        call=call,
                        parsed_args=parsed_args,
                        cancellation_token=cancellation_token,
                        empty_bash_output_counts=empty_bash_output_counts,
                    )

            ts_end = session.now_iso()
            try:
                await self._persist_tool_result(
                    session=session,
                    call=call,
                    parsed_args=parsed_args,
                    ts_start=ts_start,
                    ts_end=ts_end,
                    tool_result_str=outcome.result,
                )
                persist_error = None
            except Exception as exc:
                persist_error = exc
                outcome = _ToolCallOutcome(
                    status="failed",
                    error_type=type(exc).__name__,
                    result=tool_error(call.name, f"Failed to persist tool result: {exc}", type(exc).__name__),
                )

            duration_ms = int((time.perf_counter() - started_at) * 1000)
            yield ToolResultEvent(
                **event_meta(session, turn_id),
                tool_call_id=call.call_id,
                tool_name=call.name,
                status=outcome.status,
                result=outcome.result,
                error_type=outcome.error_type,
                duration_ms=duration_ms,
            )
            if persist_error is not None:
                raise RuntimeError(f"Failed to persist tool result for {call.call_id}: {persist_error}") from persist_error

    async def _run_tool_call(
        self,
        *,
        call: ParsedToolCall,
        parsed_args: dict,
        cancellation_token: CancellationToken | None,
        empty_bash_output_counts: dict[str, int],
    ) -> _ToolCallOutcome:
        try:
            if self._tool_executor.is_async_tool(call.name):
                execution_args = parsed_args
                if call.name == "bash":
                    execution_args = {**parsed_args, "_cancellation_token": cancellation_token}
                result = await self._tool_executor.execute_async(call.name, execution_args, call.raw_args)
            else:
                def _sync_run():
                    return self._tool_executor.execute_sync(call.name, parsed_args, call.raw_args)

                result = await asyncio.to_thread(_sync_run)

            if result.status == "ok":
                tool_result_str = result.result_str
                if not looks_like_tool_payload(tool_result_str):
                    tool_result_str = tool_ok(call.name, tool_result_str)
                self._record_bash_output_observation(
                    call.name,
                    tool_result_str,
                    empty_bash_output_counts,
                )
                return _ToolCallOutcome(status="completed", result=tool_result_str)

            error_type = result.error_type or "ToolExecutionError"
            return _ToolCallOutcome(
                status="failed",
                error_type=error_type,
                result=tool_error(call.name, result.error_msg, error_type),
            )
        except Exception as exc:
            error_type = type(exc).__name__
            return _ToolCallOutcome(
                status="failed",
                error_type=error_type,
                result=tool_error(call.name, str(exc), error_type),
            )

    async def _persist_tool_result(
        self,
        *,
        session: AsyncSessionStore,
        call: ParsedToolCall,
        parsed_args: dict,
        ts_start: str,
        ts_end: str,
        tool_result_str: str,
    ) -> None:
        normalized_result = self._tool_result_normalizer.normalize(tool_result_str)
        await session.persist_tool_call(
            call.call_id,
            call.name,
            dict(parsed_args),
            call.raw_args,
            ts_start,
            ts_end,
            tool_result_str,
            model_content=normalized_result.model_content,
            model_content_format=normalized_result.model_content_format,
            model_content_policy=normalized_result.model_content_policy,
            artifact_ref=normalized_result.artifact_ref,
        )
        await session.persist_message("tool", "", tool_call_id=call.call_id, tool_name=call.name)

    def _counts_for_turn(self, turn_id: str) -> dict[str, int]:
        if not turn_id:
            return {}
        key = turn_id or "__default__"
        if len(self._empty_bash_output_counts_by_turn) > 32:
            self._empty_bash_output_counts_by_turn.clear()
        return self._empty_bash_output_counts_by_turn.setdefault(key, {})

    def _empty_bash_output_pre_guard(
        self,
        tool_name: str,
        parsed_args: dict,
        counts: dict[str, int],
    ) -> str | None:
        if tool_name != "bash_output":
            return None
        bg_id = str(parsed_args.get("bg_id") or "")
        if not bg_id or counts.get(bg_id, 0) < 3:
            return None
        counts[bg_id] = counts.get(bg_id, 0) + 1
        return self._repeated_empty_poll_error(bg_id, counts[bg_id])

    def _record_bash_output_observation(
        self,
        tool_name: str,
        tool_result_str: str,
        counts: dict[str, int],
    ) -> None:
        if tool_name != "bash_output":
            return
        try:
            payload = json.loads(tool_result_str)
        except Exception:
            return
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            return
        data = payload.get("data")
        if not isinstance(data, dict):
            return
        bg_id = str(data.get("bg_id") or "")
        if not bg_id:
            return
        empty_running = (
            data.get("status") == "running"
            and data.get("no_new_output") is True
            and not data.get("stdout")
            and not data.get("stderr")
        )
        if not empty_running:
            counts[bg_id] = 0
            return
        counts[bg_id] = counts.get(bg_id, 0) + 1

    def _repeated_empty_poll_error(self, bg_id: str, count: int) -> str:
        return tool_error(
            "bash_output",
            f"Repeated empty bash_output polling for {bg_id}. Wait longer before checking again, or continue independent work.",
            "RepeatedEmptyPoll",
            meta={
                "bg_id": bg_id,
                "empty_observation_count": count,
                "suggested_next_wait_ms": self._suggested_wait_ms_for_empty_count(count),
            },
        )

    def _suggested_wait_ms_for_empty_count(self, count: int) -> int:
        if count <= 1:
            return 5000
        if count <= 3:
            return 15000
        if count <= 6:
            return 30000
        return 60000
