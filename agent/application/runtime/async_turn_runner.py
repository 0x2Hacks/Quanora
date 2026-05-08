"""Asynchronous turn runner coordinating the turn lifecycle via event streams."""

from __future__ import annotations

import asyncio
import time
from typing import AsyncIterator
import openai
from tenacity import RetryError

from agent.application.ports import SessionStore
from agent.application.ports.async_chat_client import AsyncChatClient
from agent.application.services import ContextManager
from agent.application.runtime.cancellation import CancellationToken
from agent.domain.events import (
    RuntimeEvent,
    AssistantDeltaEvent,
    AssistantMessageCompletedEvent,
    TurnCompletedEvent,
    TurnFailedEvent,
    TurnCancelledEvent
)

from .message_stream_parser import MessageStreamParser
from .tool_call_processor import ToolCallProcessor


class AsyncTurnRunner:
    """Manages the execution of a single conversational turn asynchronously."""

    def __init__(
        self,
        chat_client: AsyncChatClient,
        tool_processor: ToolCallProcessor,
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

    async def run_turn(
        self,
        session: SessionStore,
        cancellation_token: CancellationToken | None = None
    ) -> AsyncIterator[RuntimeEvent]:
        """Run the main conversation loop for a user turn asynchronously, yielding events."""
        
        try:
            while True:
                if cancellation_token and cancellation_token.is_cancelled:
                    yield TurnCancelledEvent(ts=session.now_iso(), reason=cancellation_token.reason)
                    return
                
                context = self._context_manager.build_messages(session=session)
                
                try:
                    # We always use stream=True for the async runner to provide real-time events
                    stream_response = self._chat_client.stream(
                        messages=context.messages,
                        tools=self._tool_schemas,
                        cancellation_token=cancellation_token
                    )
                    
                    content_text = ""
                    tool_calls = []
                    
                    async for chunk in stream_response:
                        if cancellation_token and cancellation_token.is_cancelled:
                            yield TurnCancelledEvent(ts=session.now_iso(), reason=cancellation_token.reason)
                            return
                            
                        if not chunk.choices:
                            continue
                            
                        delta = chunk.choices[0].delta
                        
                        if delta.content:
                            content_text += delta.content
                            yield AssistantDeltaEvent(ts=session.now_iso(), text=delta.content)
                            
                        if delta.tool_calls:
                            # We delegate the chunk merging to stream_parser.
                            # For simplicity here, we assume stream_parser has a stateful or stateless
                            # way to accumulate tool calls from deltas.
                            # The original stream_parser.consume_stream_response takes the whole response.
                            # We'll adapt it here inline for the async stream.
                            for tc_chunk in delta.tool_calls:
                                # Expand tool_calls list if needed
                                while len(tool_calls) <= tc_chunk.index:
                                    tool_calls.append({
                                        "id": "",
                                        "type": "function",
                                        "function": {"name": "", "arguments": ""}
                                    })
                                
                                if tc_chunk.id:
                                    tool_calls[tc_chunk.index]["id"] = tc_chunk.id
                                if tc_chunk.function.name:
                                    tool_calls[tc_chunk.index]["function"]["name"] = tc_chunk.function.name
                                if tc_chunk.function.arguments:
                                    tool_calls[tc_chunk.index]["function"]["arguments"] += tc_chunk.function.arguments
                                    
                    # Reconstruct the message format expected by stream_parser
                    mock_msg = type('obj', (object,), {
                        'content': content_text,
                        'tool_calls': [
                            type('obj', (object,), {
                                'id': tc['id'],
                                'type': tc['type'],
                                'function': type('obj', (object,), {
                                    'name': tc['function']['name'],
                                    'arguments': tc['function']['arguments']
                                })
                            }) for tc in tool_calls
                        ] if tool_calls else None
                    })
                    
                    parsed_tool_calls = self._stream_parser.parse_tool_calls_from_message(mock_msg)
                    
                    if content_text:
                        session.persist_message("assistant", content_text)
                        yield AssistantMessageCompletedEvent(ts=session.now_iso())
                        
                except openai.BadRequestError as e:
                    if "context_length_exceeded" in str(e) or "maximum context length" in str(e).lower():
                        old_hard_limit = self._context_manager._estimator.budget.hard_limit_tokens
                        self._context_manager._estimator.budget.hard_limit_tokens = int(old_hard_limit * 0.8)
                        continue
                    raise
                except RetryError as e:
                    error_msg = f"\n\n[APIUnavailableError: The AI provider is currently unreachable after multiple retries. Error: {e.last_attempt.exception()}]"
                    yield AssistantDeltaEvent(ts=session.now_iso(), text=error_msg)
                    yield TurnFailedEvent(ts=session.now_iso(), reason=error_msg)
                    return

                if not parsed_tool_calls:
                    break
                    
                session.persist_message(
                    "assistant",
                    "",
                    meta={"tool_calls": [{"id": item.call_id, "name": item.name} for item in parsed_tool_calls]},
                )
                
                # Execute tools and yield their events
                request_id = session.now_iso()
                for call in parsed_tool_calls:
                    if cancellation_token and cancellation_token.is_cancelled:
                        yield TurnCancelledEvent(ts=session.now_iso(), reason=cancellation_token.reason)
                        return
                        
                    # Here we adapt the synchronous ToolCallProcessor to yield events.
                    # In Phase 3, we still use the synchronous executor inside the async loop,
                    # but we bridge its events out.
                    # We will collect events using a callback.
                    event_queue = []
                    def _on_event(evt):
                        event_queue.append(evt)
                        
                    # We run the processor synchronously but it will call our on_event hook.
                    # In a fully async ToolCallProcessor, this would be `await processor.execute_tool_calls(...)`
                    self._tool_processor.execute_tool_calls(
                        session=session,
                        tool_calls=[call],
                        on_event=_on_event
                    )
                    
                    # Yield the collected events
                    for evt in event_queue:
                        yield evt
                        
            yield TurnCompletedEvent(ts=session.now_iso())
            
        except asyncio.CancelledError as e:
            yield TurnCancelledEvent(ts=session.now_iso(), reason=str(e))
        except Exception as e:
            # We don't have session.now_iso() guaranteed here, but we try
            ts = session.now_iso() if hasattr(session, 'now_iso') else "unknown"
            yield TurnFailedEvent(ts=ts, reason=str(e))
