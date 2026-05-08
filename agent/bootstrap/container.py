"""Composition root for wiring concrete adapters to application services."""

from __future__ import annotations

from agent.application import ContextManager, ToolExecutor, JobService
from agent.application.runtime.async_runtime_facade import AsyncRuntimeFacade
from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.application.runtime.message_stream_parser import MessageStreamParser
from agent.application.runtime.tool_call_processor import ToolCallProcessor
from agent.application.ports import SessionStore
from agent.application.ports.async_session_store import AsyncSessionStore
from agent.domain import looks_like_tool_payload
from agent.infrastructure.config import Config
from agent.infrastructure.llm import OpenAIChatClient
from agent.infrastructure.llm.openai_async_chat_client import AsyncOpenAIChatClient
from agent.infrastructure.persistence import JsonlSessionStore, JobStoreJsonl, TaskOutputStoreFile
from agent.infrastructure.persistence.async_jsonl_session_store import AsyncJsonlSessionStoreFacade
from agent.infrastructure.tools import DefaultToolRegistry
from agent.interfaces.api import AgentAPIService
from agent.interfaces.cli import ChatCLI
from agent.prompts import SYSTEM_PROMPT


def build_basic_agent_dependencies(
    *,
    tools=None,
    debug: bool = False,
    session_dir: str | None = None,
    session_id: str | None = None,
    resume_latest: bool = False,
) -> dict[str, object]:
    model = Config.DEFAULT_MODEL
    client = Config.get_client()
    async_client = Config.get_async_client()

    sync_session: SessionStore = JsonlSessionStore(
        session_dir=session_dir,
        session_id=session_id,
        resume_latest=resume_latest,
        model=model,
        system_prompt=SYSTEM_PROMPT,
        looks_like_tool_payload=looks_like_tool_payload,
    )
    session: AsyncSessionStore = AsyncJsonlSessionStoreFacade(sync_store=sync_session)
    
    store_dir = sync_session.session_dir or getattr(sync_session, "_default_session_root", lambda: "sessions")()
    job_store = JobStoreJsonl(directory=store_dir)
    output_store = TaskOutputStoreFile(directory=store_dir)
    job_service = JobService(job_store=job_store, output_store=output_store)

    tool_registry = DefaultToolRegistry(schemas=tools)
    tool_executor = ToolExecutor(registry=tool_registry, job_service=job_service)
    
    chat_client = OpenAIChatClient(client=client, model=model)
    async_chat_client = AsyncOpenAIChatClient(async_client=async_client, model=model)
    
    # Alignment B replaces ToolCallProcessor with AsyncToolCallProcessor
    from agent.application.runtime.async_tool_call_processor import AsyncToolCallProcessor
    async_tool_processor = AsyncToolCallProcessor(tool_executor=tool_executor, job_service=job_service)
    
    stream_parser = MessageStreamParser()
    
    turn_runner = AsyncTurnRunner(
        chat_client=async_chat_client,
        tool_processor=async_tool_processor,
        stream_parser=stream_parser,
        tool_schemas=tool_registry.schemas,
        context_manager=ContextManager(),
        debug=debug,
    )
    
    runtime = AsyncRuntimeFacade(turn_runner=turn_runner, session_store=session)
    
    cli = ChatCLI(runtime=runtime, session=session, debug=debug)
    
    # We pass the sync runtime to AgentAPIService for now if it requires it,
    # or pass AsyncRuntimeFacade if AgentAPIService is refactored.
    # The instructions say: "If some legacy callers still depend on sync objects, we can bridge it. But default injected is async."
    # Let's just pass runtime and if api_service breaks, we'll see.
    from agent.application import AgentRuntime
    sync_runtime = AgentRuntime(
        chat_client=chat_client,
        tool_executor=tool_executor,
        tool_schemas=tool_registry.schemas,
        context_manager=ContextManager(),
        debug=debug,
    )
    api_service = AgentAPIService(runtime=sync_runtime, system_prompt=SYSTEM_PROMPT)

    return {
        "tool_registry": tool_registry,
        "tool_executor": tool_executor,
        "chat_client": chat_client,
        "async_chat_client": async_chat_client,
        "runtime": runtime,
        "sync_runtime": sync_runtime,
        "session": session,
        "sync_session": sync_session,
        "cli": cli,
        "api_service": api_service,
        "job_service": job_service,
    }
