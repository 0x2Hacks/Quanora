"""Compatibility facade that wires layered architecture components."""

from __future__ import annotations

from config.settings import Config
from session import SessionManager

from agent.application import AgentRuntime, ToolExecutor
from agent.domain import looks_like_tool_payload
from agent.infrastructure.llm import OpenAIChatClient
from agent.infrastructure.tools import DefaultToolRegistry
from agent.interfaces.api import AgentAPIService
from agent.interfaces.cli import ChatCLI
from agent.prompts import SYSTEM_PROMPT


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
        model = Config.DEFAULT_MODEL
        client = Config.get_client()

        self._tool_registry = DefaultToolRegistry(schemas=tools)
        self._tool_executor = ToolExecutor(registry=self._tool_registry)
        self._chat_client = OpenAIChatClient(client=client, model=model)
        self._runtime = AgentRuntime(
            chat_client=self._chat_client,
            tool_executor=self._tool_executor,
            tool_schemas=self._tool_registry.schemas,
            debug=debug,
        )
        self._session = SessionManager(
            session_dir=session_dir,
            session_id=session_id,
            resume_latest=resume_latest,
            resume_mode=resume_mode,
            model=model,
            system_prompt=SYSTEM_PROMPT,
            looks_like_tool_payload=looks_like_tool_payload,
        )
        self._cli = ChatCLI(runtime=self._runtime, session=self._session, debug=debug)
        self._api_service = AgentAPIService(runtime=self._runtime, system_prompt=SYSTEM_PROMPT)

    def run(self, query: str) -> str:
        return self._api_service.chat(query)

    def chat(self) -> None:
        self._cli.start()
