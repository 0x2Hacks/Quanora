"""Asynchronous turn runner coordinating the turn lifecycle via event streams."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator
import openai
from tenacity import RetryError

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.application.ports.async_chat_client import AsyncChatClient
from agent.application.services import ContextManager
from agent.application.runtime.cancellation import CancellationToken
from agent.domain.events import (
    RuntimeEvent,
    AssistantDeltaEvent,
    AssistantMessageCompletedEvent,
    SkillActivatedEvent,
    ToolBatchStartedEvent,
    ToolResultEvent,
    TurnCompletedEvent,
    TurnFailedEvent,
    TurnCancelledEvent,
    TurnCostReport,
    LLMUsageRecord,
    ToolCallUsageRecord,
)

from .message_stream_parser import MessageStreamParser
from agent.application.runtime.async_tool_call_processor import AsyncToolCallProcessor

class AsyncTurnRunner:
    """Manages the execution of a single conversational turn asynchronously."""

    def __init__(
        self,
        chat_client: AsyncChatClient,
        tool_processor: AsyncToolCallProcessor,
        stream_parser: MessageStreamParser,
        tool_schemas: list[dict],
        context_manager: ContextManager,
        debug: bool = False,
    ):
        self._chat_client = chat_client
        self._tool_processor = tool_processor
        self._stream_parser = stream_parser
        self._tool_schemas = tool_schemas
        self._context_manager = context_manager
        self._debug = debug

    def set_retry_callback(self, callback) -> None:
        """Set a callback invoked on LLM API retries: (attempt: int, exception: Exception) -> None."""
        if hasattr(self._chat_client, "on_retry"):
            self._chat_client.on_retry = callback

    async def run_turn(
        self,
        session: AsyncSessionStore,
        cancellation_token: CancellationToken | None = None
    ) -> AsyncIterator[RuntimeEvent]:
        """Run the main conversation loop for a user turn asynchronously, yielding events."""
        turn_start_time = time.monotonic()
        cost_report = TurnCostReport()
        
        try:
            emitted_skill_names: set[str] = set()
            turn_active_skill_matches: list | None = None
            while True:
                if cancellation_token and cancellation_token.is_cancelled:
                    cost_report.turn_wall_seconds = time.monotonic() - turn_start_time
                    yield TurnCancelledEvent(ts=session.now_iso(), reason=cancellation_token.reason, cost_report=cost_report)
                    return

                if turn_active_skill_matches is None:
                    turn_active_skill_matches = await self._resolve_turn_active_skills(session)

                context = await self._context_manager.build_messages_async(
                    session=session,
                    active_skill_matches=turn_active_skill_matches,
                )
                context_decisions = context.decisions if isinstance(getattr(context, "decisions", None), dict) else {}
                for item in context_decisions.get("active_skills") or []:
                    skill_name = str(item.get("name") or "")
                    skill_key = skill_name.lower()
                    if not skill_key or skill_key in emitted_skill_names:
                        continue
                    emitted_skill_names.add(skill_key)
                    yield SkillActivatedEvent(
                        ts=session.now_iso(),
                        skill_name=skill_name,
                        reason=str(item.get("reason") or ""),
                        score=int(item.get("score") or 0),
                        source=str(item.get("source") or ""),
                        path=str(item.get("path") or ""),
                    )
                
                try:
                    # We always use stream=True for the async runner to provide real-time events
                    stream_response = self._chat_client.stream(
                        messages=context.messages,
                        tools=self._tool_schemas,
                        cancellation_token=cancellation_token
                    )
                    
                    # Use the parser to consume the async stream and handle merging tool call chunks
                    async def _on_content(text: str):
                        yield AssistantDeltaEvent(ts=session.now_iso(), text=text)

                    # We can't directly yield from inside a callback easily without an async generator queue.
                    # Let's collect them directly in an async generator wrapper or just use the parser logic.
                    # Since we want to yield events *as* they arrive, we'll write a small adapter for the stream parser.
                    # To keep it clean, we'll iterate through the stream, manually emitting DeltaEvents,
                    # but delegating the chunk merging to the stream_parser's unified logic.
                    
                    # Queue-based bridge: producer consumes the async stream, consumer yields events.
                    # Sentinel (None) is guaranteed via put_nowait in finally to survive CancelledError.
                    event_queue = asyncio.Queue()

                    async def _consume():
                        try:
                            async def _on_content_async(text: str):
                                await event_queue.put(AssistantDeltaEvent(ts=session.now_iso(), text=text))

                            # Make sure we AWAIT consume_async_stream, not just return the coroutine!
                            llm_start_time = time.monotonic()
                            content, calls, usage_record = await self._stream_parser.consume_async_stream(
                                stream_response,
                                _on_content_async,
                                cancellation_token
                            )
                            # Populate latency and model in the usage record
                            if usage_record is not None:
                                usage_record.latency_seconds = time.monotonic() - llm_start_time
                                usage_record.model = getattr(self._chat_client, '_model', '')
                            return content, calls, usage_record
                        except asyncio.CancelledError:
                            raise
                        except Exception as e:
                            await event_queue.put(e)
                            return "", []
                        finally:
                            try:
                                await event_queue.put(None)
                            except asyncio.CancelledError:
                                event_queue.put_nowait(None)

                    consume_task = asyncio.create_task(_consume())

                    try:
                        while True:
                            event = await event_queue.get()
                            if event is None:
                                break
                            if isinstance(event, Exception):
                                raise event
                            yield event
                    finally:
                        if not consume_task.done():
                            consume_task.cancel()
                            try:
                                await consume_task
                            except (asyncio.CancelledError, Exception):
                                pass

                    content_text, parsed_tool_calls, usage_record = consume_task.result()
                    
                    # Accumulate LLM usage into cost report
                    if usage_record is not None:
                        cost_report.accumulate_llm(usage_record)
                    
                    if content_text:
                        await session.persist_message("assistant", content_text)
                        yield AssistantMessageCompletedEvent(ts=session.now_iso())
                        
                except openai.BadRequestError as e:
                    if "context_length_exceeded" in str(e) or "maximum context length" in str(e).lower():
                        self._context_manager.reduce_hard_limit(factor=0.8)
                        continue
                    # Handle non-fatal BadRequestErrors (e.g., code 1214: invalid messages
                    # parameter) gracefully instead of crashing.  The _normalize_messages
                    # in context_manager.py should prevent most of these; this is a safety
                    # net for edge cases.
                    error_code = ""
                    if hasattr(e, "body") and isinstance(e.body, dict):
                        error_info = e.body.get("error", {})
                        error_code = str(error_info.get("code", ""))
                    error_msg = str(e)
                    is_messages_param_error = (
                        error_code == "1214"
                        or ("messages" in error_msg.lower() and "param" in error_msg.lower())
                    )
                    if is_messages_param_error:
                        logger.warning("BadRequestError 1214 (invalid messages param), attempting retry with normalized messages: %s", error_msg)
                        # Retry: rebuild messages with normalization and try once more.
                        # We use the while-loop's retry mechanism by reducing context
                        # and continuing — the next iteration will call build_messages_async
                        # which now includes _normalize_messages.
                        self._context_manager.reduce_hard_limit(factor=0.9)
                        retry_count_1214 = getattr(self, "_retry_count_1214", 0)
                        if retry_count_1214 < 2:
                            self._retry_count_1214 = retry_count_1214 + 1
                            continue
                        # Exhausted retries — graceful degradation
                        logger.error("BadRequestError 1214 persisted after %d retries: %s", retry_count_1214, error_msg)
                        self._retry_count_1214 = 0
                        yield AssistantDeltaEvent(ts=session.now_iso(), text=f"\n\n[BadRequestError 1214: messages parameter invalid after retries. {error_msg}]")
                        yield TurnFailedEvent(ts=session.now_iso(), error=error_msg)
                        return
                    else:
                        # Other BadRequestError — graceful degradation instead of crash
                        logger.error("Unhandled BadRequestError: %s", error_msg)
                        yield AssistantDeltaEvent(ts=session.now_iso(), text=f"\n\n[BadRequestError: {error_msg}]")
                        yield TurnFailedEvent(ts=session.now_iso(), error=error_msg)
                        return
                except RetryError as e:
                    error_msg = f"\n\n[APIUnavailableError: The AI provider is currently unreachable after multiple retries. Error: {e.last_attempt.exception()}]"
                    yield AssistantDeltaEvent(ts=session.now_iso(), text=error_msg)
                    yield TurnFailedEvent(ts=session.now_iso(), error=error_msg)
                    return

                if not parsed_tool_calls:
                    break
                    
                await session.persist_message(
                    "assistant",
                    "",
                    meta={"tool_calls": [{"id": item.call_id, "name": item.name} for item in parsed_tool_calls]},
                )

                # Framework-level UX: announce the upcoming tool batch so the CLI
                # can render "executing N tools..." instead of going silent.
                yield ToolBatchStartedEvent(
                    ts=session.now_iso(),
                    count=len(parsed_tool_calls),
                    tool_names=[item.name for item in parsed_tool_calls],
                )

                # Execute tools and yield their events
                request_id = session.now_iso()
                
                async for event in self._tool_processor.execute(
                    session=session,
                    tool_calls=parsed_tool_calls,
                    cancellation_token=cancellation_token
                ):
                    # Capture tool call timing for cost report
                    if isinstance(event, ToolResultEvent):
                        cost_report.accumulate_tool(ToolCallUsageRecord(
                            tool_name=event.tool_name,
                            call_id=event.tool_call_id,
                            wall_seconds=event.duration_ms / 1000.0,
                            input_chars=0,
                            output_chars=len(event.result) if event.result else 0,
                        ))
                    yield event
                        
            # Finalize cost report timing
            cost_report.turn_wall_seconds = time.monotonic() - turn_start_time
            yield TurnCompletedEvent(ts=session.now_iso(), cost_report=cost_report)
            
        except asyncio.CancelledError as e:
            cost_report.turn_wall_seconds = time.monotonic() - turn_start_time
            yield TurnCancelledEvent(ts=session.now_iso(), reason=str(e), cost_report=cost_report)
        except Exception as e:
            # We don't have session.now_iso() guaranteed here, but we try
            ts = session.now_iso() if hasattr(session, 'now_iso') else "unknown"
            cost_report.turn_wall_seconds = time.monotonic() - turn_start_time
            yield TurnFailedEvent(ts=ts, error=str(e), cost_report=cost_report)

    async def _resolve_turn_active_skills(self, session: AsyncSessionStore) -> list:
        selector = getattr(self._context_manager, "select_active_skills_for_turn", None)
        if not callable(selector):
            return []
        user_message = await self._latest_user_content(session)
        try:
            return list(selector(user_message))
        except Exception:
            return []

    async def _latest_user_content(self, session: AsyncSessionStore) -> str:
        try:
            messages = await session.get_messages_slice()
        except Exception:
            return ""
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
        return ""
