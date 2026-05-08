"""Asynchronous tool scheduler and execution layer."""

from __future__ import annotations

import asyncio
from typing import AsyncIterator

from agent.application.ports.async_session_store import AsyncSessionStore
from agent.application.services.job_service import JobService
from agent.domain import ParsedToolCall, parse_tool_args, tool_error, tool_ok
from agent.domain.events import RuntimeEvent, ToolCallStartedEvent, ToolResultEvent, ToolProgressEvent
from agent.application.tool_executor import ToolExecutor
from agent.application.runtime.cancellation import CancellationToken


class AsyncToolCallProcessor:
    """
    Executes parsed tool calls asynchronously, enforcing concurrency rules
    and yielding an event stream. Replaces the legacy ToolCallProcessor.
    """

    def __init__(self, tool_executor: ToolExecutor, job_service: JobService):
        self._tool_executor = tool_executor
        self._job_service = job_service

    async def execute(
        self,
        session: AsyncSessionStore,
        tool_calls: list[ParsedToolCall],
        cancellation_token: CancellationToken | None = None,
    ) -> AsyncIterator[RuntimeEvent]:
        """
        Execute multiple tool calls asynchronously.
        Currently defaults to sequential execution, but respects the async event loop.
        In the future, concurrency_safe and exclusive rules can be applied here.
        """
        request_id = session.now_iso()
        
        for call in tool_calls:
            if cancellation_token and cancellation_token.is_cancelled:
                break
                
            yield ToolCallStartedEvent(tool_call_id=call.call_id, tool_name=call.name)

            parsed_args, parse_error = parse_tool_args(call.raw_args)
            ts_start = session.now_iso()
            
            if parse_error:
                tool_result_str = tool_error(
                    call.name,
                    f"Invalid tool arguments JSON: {parse_error}",
                    "ToolArgsJSONError",
                    meta={"raw_args": call.raw_args[:2000]},
                )
                yield ToolResultEvent(tool_call_id=call.call_id, tool_name=call.name, result=tool_result_str)
            else:
                try:
                    # In a fully async system, we would await a real async runner here.
                    # For Alignment B, we will rely on bash_runner.py's new async capabilities 
                    # or run standard tools in a thread pool.
                    
                    # We create the job record
                    handle = self._job_service.create_job(
                        session_id=session.session_id or "default",
                        request_id=request_id,
                        tool_call_id=call.call_id,
                        tool_name=call.name,
                        metadata={"args": parsed_args, "raw_args": call.raw_args}
                    )
                    self._job_service.update_status(handle.job_id, "running")
                    
                        # Execute tool asynchronously
                    def _sync_run():
                        return self._tool_executor.execute_sync(call.name, parsed_args, call.raw_args)
                        
                    if call.name == "bash":
                        # If bash is executed, we should ideally use the async bash runner directly
                        # But execute_sync delegates to registry which delegates to the tool function.
                        # For bash, the tool function usually resolves to bash_runner.run_sync or run_async.
                        # To truly wire up async bash without changing the tool registry interface right now,
                        # we can try to intercept it, or just use to_thread since we wrapped run_async in run_sync.
                        # But the goal of B is "bash uses asyncio.create_subprocess_exec". We did that in bash_runner.py.
                        # Since bash_runner.run_sync uses asyncio.run(), running it in to_thread is safe but nested.
                        # Let's just use to_thread for all for now, as the true async tool registry is part of D maybe?
                        # Actually, we can intercept bash here to pass the cancellation token directly.
                        if hasattr(self._tool_executor._registry, "get"):
                            tool_def = self._tool_executor._registry.get(call.name)
                            if tool_def and hasattr(tool_def, "__name__") and "bash" in tool_def.__name__:
                                # Import the bash runner from the registry's closure if possible
                                # This is hacky. Let's just use to_thread for now, bash_runner's run_sync uses asyncio.run().
                                pass
                                
                    # If we had a real async tool registry:
                    # result = await self._tool_executor.execute_async(..., cancellation_token)
                    
                    # For now, to unblock the UI:
                    result = await asyncio.to_thread(_sync_run)
                    
                    if result.status == "ok":
                        self._job_service.append_output(handle.job_id, result.result_str)
                        self._job_service.update_status(handle.job_id, "completed")
                    else:
                        self._job_service.append_output(handle.job_id, f"Error: {result.error_msg}")
                        self._job_service.update_status(handle.job_id, "failed", error=result.error_msg)
                        
                    content, _ = self._job_service.read_output(handle.job_id)
                    job = self._job_service.get_job(handle.job_id)
                    
                    if job and job.status == "failed":
                        tool_result_str = tool_error(call.name, job.metadata.get("error", "Unknown error"), "JobFailed")
                    else:
                        from agent.domain import looks_like_tool_payload
                        if looks_like_tool_payload(content):
                            tool_result_str = content
                        else:
                            tool_result_str = tool_ok(call.name, content)
                            
                except Exception as exc:
                    tool_result_str = tool_error(call.name, str(exc), type(exc).__name__)
                    
                yield ToolResultEvent(tool_call_id=call.call_id, tool_name=call.name, result=tool_result_str)

            ts_end = session.now_iso()

            await session.persist_tool_call(
                call.call_id,
                call.name,
                parsed_args,
                call.raw_args,
                ts_start,
                ts_end,
                tool_result_str,
            )
            await session.persist_message("tool", "", tool_call_id=call.call_id, tool_name=call.name)