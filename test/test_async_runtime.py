import pytest
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.runtime.async_runtime_facade import AsyncRuntimeFacade
from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.domain import ParsedToolCall
from agent.domain.events import (
    AssistantDeltaEvent, 
    AssistantMessageCompletedEvent, 
    ContextBuiltEvent,
    ToolRequestedEvent,
    ToolResultEvent,
    TurnStartedEvent,
    TurnCompletedEvent,
    TurnCancelledEvent,
    TurnFailedEvent
)
from agent.application.runtime.cancellation import CancellationTokenSource

@pytest.mark.asyncio
async def test_async_turn_runner_stream():
    mock_client = AsyncMock()
    
    # Mock stream response
    async def mock_stream(*args, **kwargs):
        class MockDelta:
            def __init__(self, content):
                self.content = content
                self.tool_calls = None
        class MockChoice:
            def __init__(self, content):
                self.delta = MockDelta(content)
        class MockChunk:
            def __init__(self, content):
                self.choices = [MockChoice(content)]
                
        yield MockChunk("Hello ")
        yield MockChunk("World!")
        
    mock_client.stream = mock_stream
    
    mock_processor = MagicMock()
    mock_processor.execute_tool_calls = MagicMock()
    
    mock_parser = MagicMock()
    mock_parser.parse_tool_calls_from_message.return_value = []
    
    # We must mock consume_async_stream because AsyncTurnRunner uses it
    async def mock_consume(*args, **kwargs):
        on_content_async = args[1]
        await on_content_async("Hello ")
        await on_content_async("World!")
        return "Hello World!", []
    mock_parser.consume_async_stream = mock_consume
    
    mock_context = MagicMock()
    mock_context_async_method = AsyncMock()
    mock_context_async_method.return_value = MagicMock(messages=[], stats={}, decisions={})
    mock_context.build_messages_async = mock_context_async_method
    mock_context.select_active_skills_for_turn = None
    
    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-08T00:00:00Z"
    mock_session.persist_message = AsyncMock()
    
    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=mock_processor,
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context
    )
    
    events = []
    async for event in runner.run_turn(mock_session):
        events.append(event)
        
    assert len(events) == 5
    assert isinstance(events[0], ContextBuiltEvent)
    assert isinstance(events[1], AssistantDeltaEvent)
    assert events[1].text == "Hello "
    assert isinstance(events[2], AssistantDeltaEvent)
    assert events[2].text == "World!"
    assert isinstance(events[3], AssistantMessageCompletedEvent)
    assert events[3].content_chars == len("Hello World!")
    assert isinstance(events[4], TurnCompletedEvent)

@pytest.mark.asyncio
async def test_async_turn_runner_cancellation():
    mock_client = AsyncMock()
    
    async def mock_stream(*args, **kwargs):
        yield MagicMock()
        await asyncio.sleep(0.1) # Simulate delay
        
    mock_client.stream = mock_stream
    
    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=MagicMock(),
        tool_schemas=[],
        context_manager=MagicMock()
    )
    
    source = CancellationTokenSource()
    source.cancel("User cancelled")
    
    events = []
    async for event in runner.run_turn(MagicMock(), cancellation_token=source.token):
        events.append(event)
        
    assert len(events) == 1
    assert isinstance(events[0], TurnCancelledEvent)
    assert events[0].reason == "User cancelled"


@pytest.mark.asyncio
async def test_async_turn_runner_stream_cancelled_error_is_cancelled_event():
    mock_client = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield MagicMock()

    mock_client.stream = mock_stream

    mock_parser = MagicMock()

    async def mock_consume(*args, **kwargs):
        raise asyncio.CancelledError("stream cancelled")

    mock_parser.consume_async_stream = mock_consume

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(return_value=MagicMock(messages=[], decisions={}))
    mock_context.select_active_skills_for_turn = None

    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-08T00:00:00Z"

    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context
    )

    events = []
    async for event in runner.run_turn(mock_session):
        events.append(event)

    assert len(events) == 2
    assert isinstance(events[0], ContextBuiltEvent)
    assert isinstance(events[1], TurnCancelledEvent)
    assert events[1].reason == "stream cancelled"
    assert not any(isinstance(event, TurnFailedEvent) for event in events)


@pytest.mark.asyncio
async def test_async_runtime_facade_emits_turn_started_first():
    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.persisted = []

        async def initialize(self):
            return None

        async def persist_message(self, role, content, **kwargs):
            self.persisted.append((role, content, kwargs))

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

    class FakeRunner:
        async def run_turn(self, session, cancellation_token=None, turn_id=""):
            yield TurnCompletedEvent(turn_id=turn_id)

    session = FakeSession()
    facade = AsyncRuntimeFacade(turn_runner=FakeRunner(), session_store=session)

    events = [event async for event in facade.run_turn(query="hello")]

    assert isinstance(events[0], TurnStartedEvent)
    assert events[0].session_id == "session_1"
    assert events[0].user_message_chars == len("hello")
    assert events[0].turn_id
    assert events[1].turn_id == events[0].turn_id
    assert session.persisted == [("user", "hello", {})]


@pytest.mark.asyncio
async def test_async_turn_runner_emits_tool_requested_before_tool_execution():
    mock_client = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield MagicMock()

    mock_client.stream = mock_stream

    calls = [
        ({"content": "Need tool", "calls": [ParsedToolCall(call_id="call_1", name="bash", raw_args='{"command":"date"}')]}),
        ({"content": "Done", "calls": []}),
    ]

    async def mock_consume(*args, **kwargs):
        on_content_async = args[1]
        item = calls.pop(0)
        await on_content_async(item["content"])
        return item["content"], item["calls"]

    mock_parser = MagicMock()
    mock_parser.consume_async_stream = mock_consume

    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(return_value=MagicMock(messages=[], stats={}, decisions={}))
    mock_context.select_active_skills_for_turn = None

    class FakeSession:
        session_id = "session_1"

        def __init__(self):
            self.persisted = []

        def now_iso(self):
            return "2026-05-08T00:00:00Z"

        async def persist_message(self, *args, **kwargs):
            self.persisted.append((args, kwargs))

    async def execute(*args, **kwargs):
        yield ToolResultEvent(
            tool_call_id="call_1",
            tool_name="bash",
            status="completed",
            turn_id=kwargs.get("turn_id", ""),
        )

    mock_processor = MagicMock()
    mock_processor.execute = execute

    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=mock_processor,
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = []
    async for event in runner.run_turn(FakeSession(), turn_id="turn_1"):
        events.append(event)

    requested_index = next(index for index, event in enumerate(events) if isinstance(event, ToolRequestedEvent))
    result_index = next(index for index, event in enumerate(events) if isinstance(event, ToolResultEvent))
    assert requested_index < result_index
    assert events[requested_index].args_preview == '{"command":"date"}'
    assert events[requested_index].turn_id == "turn_1"


def main() -> int:
    asyncio.run(test_async_turn_runner_stream())
    asyncio.run(test_async_turn_runner_cancellation())
    asyncio.run(test_async_turn_runner_stream_cancelled_error_is_cancelled_event())
    asyncio.run(test_async_runtime_facade_emits_turn_started_first())
    asyncio.run(test_async_turn_runner_emits_tool_requested_before_tool_execution())
    print("Async runtime tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
