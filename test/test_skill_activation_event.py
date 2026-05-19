import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.domain import ParsedToolCall
from agent.domain.events import AssistantDeltaEvent, SkillActivatedEvent


@pytest.mark.asyncio
async def test_skill_activation_event_precedes_assistant_delta() -> None:
    mock_client = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield MagicMock()

    mock_client.stream = mock_stream

    async def mock_consume(*args, **kwargs):
        on_content_async = args[1]
        await on_content_async("Hello")
        return "Hello", []

    mock_parser = MagicMock()
    mock_parser.consume_async_stream = mock_consume

    context = MagicMock(
        messages=[{"role": "system", "content": "sys"}],
        decisions={
            "active_skills": [
                {
                    "name": "demo",
                    "reason": "explicit_dollar_name",
                    "score": 100,
                    "source": "project",
                    "path": "/tmp/demo/SKILL.md",
                }
            ]
        },
    )
    mock_context = MagicMock()
    mock_context.build_messages_async = AsyncMock(return_value=context)

    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-19T00:00:00Z"
    mock_session.persist_message = AsyncMock()

    runner = AsyncTurnRunner(
        chat_client=mock_client,
        tool_processor=MagicMock(),
        stream_parser=mock_parser,
        tool_schemas=[],
        context_manager=mock_context,
    )

    events = []
    async for event in runner.run_turn(mock_session):
        events.append(event)

    if not isinstance(events[0], SkillActivatedEvent):
        raise AssertionError(f"Expected first event to be SkillActivatedEvent, got: {events}")
    if events[0].skill_name != "demo" or events[0].source != "project":
        raise AssertionError(f"Unexpected skill event payload: {events[0]}")

    first_delta = next(index for index, event in enumerate(events) if isinstance(event, AssistantDeltaEvent))
    if first_delta <= 0:
        raise AssertionError(f"Expected assistant delta after skill event, got: {events}")


@pytest.mark.asyncio
async def test_skill_activation_event_emitted_once_per_turn() -> None:
    mock_client = AsyncMock()

    async def mock_stream(*args, **kwargs):
        yield MagicMock()

    mock_client.stream = mock_stream

    consume_count = 0

    async def mock_consume(*args, **kwargs):
        nonlocal consume_count
        consume_count += 1
        on_content_async = args[1]
        await on_content_async("Hello")
        if consume_count == 1:
            return "Hello", [ParsedToolCall(call_id="call_1", name="write_file", raw_args="{}")]
        return "Hello", []

    mock_parser = MagicMock()
    mock_parser.consume_async_stream = mock_consume

    context = MagicMock(
        messages=[{"role": "system", "content": "sys"}],
        decisions={
            "active_skills": [
                {
                    "name": "demo",
                    "reason": "explicit_dollar_name",
                    "score": 100,
                    "source": "project",
                    "path": "/tmp/demo/SKILL.md",
                }
            ]
        },
    )

    build_count = 0

    async def build_messages_async(*args, **kwargs):
        nonlocal build_count
        build_count += 1
        return context

    mock_context = MagicMock()
    mock_context.build_messages_async = build_messages_async

    mock_session = MagicMock()
    mock_session.now_iso.return_value = "2026-05-19T00:00:00Z"
    mock_session.persist_message = AsyncMock()

    async def execute(*args, **kwargs):
        yield MagicMock()

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
    async for event in runner.run_turn(mock_session):
        events.append(event)

    skill_events = [event for event in events if isinstance(event, SkillActivatedEvent)]
    if len(skill_events) != 1:
        raise AssertionError(f"Expected one skill event per turn, got: {skill_events}")
    if build_count < 2:
        raise AssertionError(f"Expected multiple context builds due to tool call, got: {build_count}")


def main() -> int:
    import asyncio

    asyncio.run(test_skill_activation_event_precedes_assistant_delta())
    asyncio.run(test_skill_activation_event_emitted_once_per_turn())
    print("Skill activation event tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
