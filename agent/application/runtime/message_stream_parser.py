"""Parses LLM responses, including streaming chunks and tool calls."""

from __future__ import annotations

import asyncio
from typing import Callable, AsyncIterator, Any

from agent.domain import ParsedToolCall
from agent.domain.events import LLMUsageRecord
from agent.application.runtime.cancellation import CancellationToken


class MessageStreamParser:
    """Parses OpenAI-compatible message streams and structures."""

    def parse_tool_calls_from_message(self, assistant_message) -> list[ParsedToolCall]:
        """Extract tool calls from a non-streaming assistant message."""
        calls: list[ParsedToolCall] = []
        if not assistant_message.tool_calls:
            return calls
        for item in assistant_message.tool_calls:
            calls.append(
                ParsedToolCall(
                    call_id=item.id,
                    name=item.function.name,
                    raw_args=item.function.arguments or "",
                )
            )
        return calls

    async def consume_async_stream(
        self,
        response: AsyncIterator[Any],
        on_content_async: Callable[[str], Any],
        cancellation_token: CancellationToken | None = None
    ) -> tuple[str, list[ParsedToolCall], LLMUsageRecord | None]:
        """Consume a streaming response asynchronously, reassembling text and tool calls.

        Returns (text, tool_calls, usage_record).  The usage_record is extracted
        from the final chunk's `usage` field when stream_options.include_usage is
        enabled (which our OpenAI client already requests).
        """
        text_parts: list[str] = []
        merged_tool_calls: list[dict] = []
        usage_record: LLMUsageRecord | None = None

        async for chunk in response:
            if cancellation_token and cancellation_token.is_cancelled:
                raise asyncio.CancelledError(cancellation_token.reason)

            # Extract usage from the final chunk (OpenAI sends it last)
            if hasattr(chunk, 'usage') and chunk.usage is not None:
                usage_record = LLMUsageRecord(
                    prompt_tokens=chunk.usage.prompt_tokens or 0,
                    completion_tokens=chunk.usage.completion_tokens or 0,
                    total_tokens=chunk.usage.total_tokens or 0,
                )

            if not chunk.choices:
                continue

            delta = chunk.choices[0].delta
            if delta.content:
                await on_content_async(delta.content)
                text_parts.append(delta.content)
            if delta.tool_calls:
                for item in delta.tool_calls:
                    index = item.index
                    while len(merged_tool_calls) <= index:
                        merged_tool_calls.append({"id": "", "name": "", "arguments": ""})
                    if item.id:
                        merged_tool_calls[index]["id"] = item.id
                    if item.function:
                        if item.function.name:
                            merged_tool_calls[index]["name"] = item.function.name
                        if item.function.arguments:
                            merged_tool_calls[index]["arguments"] += item.function.arguments

        calls = [
            ParsedToolCall(call_id=item["id"], name=item["name"], raw_args=item["arguments"])
            for item in merged_tool_calls
            if item["id"] and item["name"]
        ]
        return "".join(text_parts), calls, usage_record
