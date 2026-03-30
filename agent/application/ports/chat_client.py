"""Chat client port for application services."""

from __future__ import annotations

from typing import Any, Protocol


class ChatClient(Protocol):
    def create(self, messages: list[dict], tools: list[dict], stream: bool) -> Any: ...
