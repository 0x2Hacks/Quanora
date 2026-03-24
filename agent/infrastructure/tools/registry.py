"""Default tool registry adapter."""

from __future__ import annotations

from typing import Callable

from tools import TOOLS, TOOL_SCHEMAS


class DefaultToolRegistry:
    """Adapter to expose tool implementations/schemas to application layer."""

    def __init__(self, tool_map: dict[str, Callable] | None = None, schemas: list[dict] | None = None):
        self._tool_map = tool_map or TOOLS
        self._schemas = schemas or TOOL_SCHEMAS

    @property
    def schemas(self) -> list[dict]:
        return self._schemas

    def has(self, name: str) -> bool:
        return name in self._tool_map

    def call(self, name: str, args: dict):
        return self._tool_map[name](**args)
