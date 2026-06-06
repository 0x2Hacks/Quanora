"""Composition root for wiring concrete adapters to application services."""

from __future__ import annotations

from agent.application import ContextManager, ToolExecutor, JobService
from agent.application.services.skill_selector import SkillSelector
from agent.application.runtime.async_runtime_facade import AsyncRuntimeFacade
from agent.application.runtime.async_turn_runner import AsyncTurnRunner
from agent.application.runtime.message_stream_parser import MessageStreamParser
from agent.application.ports.async_session_store import AsyncSessionStore
from agent.domain import looks_like_tool_payload
from agent.infrastructure.config import Config
from agent.infrastructure.llm.openai_async_chat_client import AsyncOpenAIChatClient
from agent.infrastructure.persistence import JobStoreJsonl, TaskOutputStoreFile
from agent.infrastructure.persistence.async_jsonl_session_store import AsyncJsonlSessionStore
from agent.infrastructure.plans import PlanContextProvider
from agent.infrastructure.skills import SkillRepository
from agent.infrastructure.tools import DefaultToolRegistry
from agent.interfaces.cli import ChatCLI
from agent.prompts import build_system_prompt


def build_basic_agent_dependencies(
    *,
    tools=None,
    debug: bool = False,
    session_dir: str | None = None,
    session_id: str | None = None,
    resume_latest: bool = False,
    self_dev: bool = False,
    self_doc: bool = False,
    self_quant: bool = False,
) -> dict[str, object]:
    """Wire layered dependencies.

    Parameters
    ----------
    self_dev :
        When True, the session is bootstrapped with the self-development
        addendum appended to the system prompt. The caller is expected to
        have ALSO switched the workspace guard via
        ``settings.enable_self_dev_mode()`` before calling this function —
        the prompt addendum only tells the model about the new permissions;
        the actual filesystem boundary is enforced by the guard.
    self_doc :
        When True, the session is bootstrapped with the self-documentation
        addendum appended to the system prompt. ``self_dev``, ``self_doc``,
        and ``self_quant`` are mutually exclusive; if more than one is True,
        ``self_dev`` takes precedence, then ``self_doc``. The caller should
        have ALSO switched the workspace guard via
        ``settings.enable_self_doc_mode()`` before calling this function.
    self_quant :
        When True, the session is bootstrapped with the quant-research
        addendum appended to the system prompt. The workspace guard should
        have been switched via ``settings.enable_self_quant_mode()`` before
        calling this function. ``self_dev`` and ``self_doc`` take precedence
        over ``self_quant``.
    """
    model = Config.DEFAULT_MODEL
    async_client = Config.get_async_client()

    # Mutual exclusion: self_dev > self_doc > self_quant
    system_prompt = build_system_prompt(
        self_dev=self_dev,
        self_doc=self_doc and not self_dev,
        self_quant=self_quant and not self_dev and not self_doc,
    )

    session: AsyncSessionStore = AsyncJsonlSessionStore(
        session_dir=session_dir,
        session_id=session_id,
        resume_latest=resume_latest,
        model=model,
        system_prompt=system_prompt,
    )
    
    store_dir = session._session_dir or getattr(session, "_default_session_root", lambda: "sessions")()
    job_store = JobStoreJsonl(directory=store_dir)
    output_store = TaskOutputStoreFile(directory=store_dir)
    job_service = JobService(job_store=job_store, output_store=output_store)

    tool_registry = DefaultToolRegistry(schemas=tools)
    tool_executor = ToolExecutor(registry=tool_registry, job_service=job_service)
    
    async_chat_client = AsyncOpenAIChatClient(async_client=async_client, model=model)
    plan_context_provider = PlanContextProvider(char_limit=2200)
    skill_repository = SkillRepository()
    skill_selector = SkillSelector(max_active_skills=2)
    
    # Alignment B replaces ToolCallProcessor with AsyncToolCallProcessor
    from agent.application.runtime.async_tool_call_processor import AsyncToolCallProcessor
    async_tool_processor = AsyncToolCallProcessor(tool_executor=tool_executor, job_service=job_service)
    
    stream_parser = MessageStreamParser()
    
    turn_runner = AsyncTurnRunner(
        chat_client=async_chat_client,
        tool_processor=async_tool_processor,
        stream_parser=stream_parser,
        tool_schemas=tool_registry.schemas,
        context_manager=ContextManager(
            skill_repository=skill_repository,
            skill_selector=skill_selector,
            plan_context_provider=plan_context_provider,
        ),
        debug=debug,
    )
    
    runtime = AsyncRuntimeFacade(turn_runner=turn_runner, session_store=session)
    
    cli = ChatCLI(runtime=runtime, session=session, debug=debug, self_dev=self_dev, self_quant=self_quant, self_doc=self_doc)

    return {
        "chat_client": async_chat_client,
        "session": session,
        "tool_registry": tool_registry,
        "runtime": runtime,
        "cli": cli,
        "job_service": job_service,
        "skill_repository": skill_repository,
        "skill_selector": skill_selector,
        "plan_context_provider": plan_context_provider,
    }
