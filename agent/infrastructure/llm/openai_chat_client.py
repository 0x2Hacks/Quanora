"""OpenAI chat-completions adapter."""

from __future__ import annotations

from typing import Any


class OpenAIChatClient:
    """Small wrapper around OpenAI chat.completions API."""

    def __init__(self, client: Any, model: str):
        self._client = client
        self._model = model

    def create(self, messages: list[dict], tools: list[dict], stream: bool):
        return self._client.chat.completions.create(
            model=self._model,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            stream=stream,
        )
