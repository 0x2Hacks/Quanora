"""Compatibility facade that wires layered architecture components."""

from __future__ import annotations

from agent.bootstrap import build_basic_agent_dependencies


class BasicAgent:
    """
    Backward-compatible entry facade.

    Exposes the same public methods (`run`, `chat`) while internally using
    interface/application/domain/infrastructure layering.
    """

    def __init__(
        self,
        tools=None,
        debug: bool = False,
        session_dir: str | None = None,
        session_id: str | None = None,
        resume_latest: bool = False,
        resume_mode: str = "summary",
    ):
        dependencies = build_basic_agent_dependencies(
            tools=tools,
            debug=debug,
            session_dir=session_dir,
            session_id=session_id,
            resume_latest=resume_latest,
            resume_mode=resume_mode,
        )
        self._tool_registry = dependencies["tool_registry"]
        self._tool_executor = dependencies["tool_executor"]
        self._chat_client = dependencies["chat_client"]
        self._runtime = dependencies["runtime"]
        self._session = dependencies["session"]
        self._cli = dependencies["cli"]
        self._api_service = dependencies["api_service"]

    def run(self, query: str) -> str:
        return self._api_service.chat(query)

    def chat(self) -> None:
        self._cli.start()
