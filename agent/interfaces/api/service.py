"""Service interface for future HTTP/API adapters."""

from __future__ import annotations


class AgentAPIService:
    """
    Transport-agnostic API facade.

    This class is intentionally framework-neutral so it can be mounted by
    FastAPI/Flask or other transports later without leaking web concerns into
    application/domain layers.
    """

    def __init__(self, runtime, system_prompt: str):
        self._runtime = runtime
        self._system_prompt = system_prompt

    def chat(self, query: str) -> str:
        return self._runtime.run_query(system_prompt=self._system_prompt, query=query)
