"""Command-line interface adapter."""

from __future__ import annotations

import asyncio

from agent.application.runtime.cancellation import CancellationTokenSource
from agent.application.services.experience_distillation_service import ExperienceDistillationService
from agent.domain.events import (
    RuntimeEvent,
    ToolCallStartedEvent,
    ToolProgressEvent,
    ToolResultEvent,
    TurnStartedEvent,
    ToolBatchStartedEvent,
    PlanSnapshotEvent,
    DataIntegrityWarningEvent,
    WorkspaceViolationEvent,
)
from agent.interfaces.cli.ui import print_rainbow_logo, render_markdown, StreamingRenderer
from prompt_toolkit import PromptSession
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console


class ChatCLI:
    """Interactive CLI that delegates core behavior to application runtime."""

    def __init__(self, runtime, session, debug: bool = False, self_dev: bool = False, self_quant: bool = False):
        self._runtime = runtime
        self._session = session
        self._session_store = session  # session implements AsyncSessionStore (persist_turn_cost etc.)
        self._debug = debug
        self._self_dev = self_dev
        self._self_quant = self_quant
        self._distill_service = ExperienceDistillationService()
        self._last_cost_report = None
        self._active_skills: list[str] = []
        self._assistant_buffer: list[str] = []
        self._console = Console()
        self._streaming_renderer = StreamingRenderer(self._console)
        self._prompt_session: PromptSession | None = None
        self._event_loop: asyncio.AbstractEventLoop | None = None
        self._current_cancel_source: CancellationTokenSource | None = None
        self._batch_tool_counter: dict[str, int] = {}   # {tool_name: seen_count_in_current_batch}
        self._batch_tool_totals: dict[str, int] = {}     # {tool_name: total_count_in_current_batch}

    def start(self) -> None:
        self._render_banner()

        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._event_loop = loop

        try:
            async def _init_session():
                try:
                    await self._session.initialize()
                except Exception as exc:
                    print(str(exc))
                    return False
                return True

            if not loop.run_until_complete(_init_session()):
                return

            # Print session ID so user can resume later
            sid = self._session.session_id
            if sid:
                self._console.print(
                    f"[dim cyan]Session ID: {sid}[/dim cyan]"
                )

            self._render_loaded_messages()
            self._loop()
        finally:
            try:
                self._shutdown_loop(loop)
            finally:
                if not loop.is_closed():
                    loop.close()
                self._event_loop = None

    def _render_banner(self) -> None:
        print_rainbow_logo()
        if self._debug:
            print("Quanora v0.1 (Debug Mode: True) 输入 'quit' 退出")
        else:
            print("Quanora v0.1")
            print("Welcome back!")
        if self._self_dev:
            # Loud, persistent banner so the user can never forget the agent
            # is currently authorised to edit its own source.
            try:
                from agent.infrastructure.config.settings import get_workspace_guard
                ws = str(get_workspace_guard().root)
            except Exception:
                ws = "(unknown)"
            self._console.print(
                "[bold white on red]"
                " 🛠  SELF-DEVELOPMENT MODE ACTIVE "
                "[/bold white on red]"
            )
            self._console.print(
                f"[yellow]    workspace = {ws}[/yellow]\n"
                "[yellow]    Quanora can now edit its own code, run its own tests,[/yellow]\n"
                "[yellow]    commit, push, and open pull requests. .git/ and .env stay protected.[/yellow]"
            )
        if self._self_quant:
            try:
                from agent.infrastructure.config.settings import get_workspace_guard
                ws = str(get_workspace_guard().root)
            except Exception:
                ws = "(unknown)"
            self._console.print(
                "[bold white on blue]"
                " 📊  QUANT-RESEARCH MODE ACTIVE "
                "[/bold white on blue]"
            )
            self._console.print(
                f"[cyan]    workspace = {ws}[/cyan]\n"
                "[cyan]    Systematic quant research workflow enabled. Follow the[/cyan]\n"
                "[cyan]    mandatory research lifecycle: Plan → Review → Hypothesize[/cyan]\n"
                "[cyan]    → Experiment → Distill. Data integrity is paramount.[/cyan]"
            )
        print("-" * 50)

    def _render_loaded_messages(self) -> None:
        messages = self._event_loop.run_until_complete(self._session.get_messages_slice())
        if len(messages) <= 1:
            return
            
        print("\n[历史会话]")
        for message in messages:
            role = message.get("role")
            content = message.get("content", "")
            if role in ("user", "assistant") and content:
                print(f"\n{role}:")
                render_markdown(content)

    def _loop(self) -> None:
        if hasattr(self._runtime, "set_retry_callback"):
            self._runtime.set_retry_callback(self._on_retry)

        # 是否已经切换到项目子目录（仅在首次输入时切换）
        _project_workspace_set = False

        # 恢复会话时自动还原 workspace（如果有 project_dir 元数据）
        if hasattr(self._session_store, 'get_project_dir'):
            saved_project_dir = self._session_store.get_project_dir()
            if saved_project_dir:
                from pathlib import Path
                if Path(saved_project_dir).exists():
                    try:
                        from agent.infrastructure.config.settings import switch_to_project_workspace
                        project_dir = switch_to_project_workspace(
                            Path(saved_project_dir).name
                        )
                        _project_workspace_set = True
                        self._console.print(
                            f"[dim]📁 已恢复项目目录: {project_dir}[/dim]\n"
                        )
                    except Exception as e:
                        self._console.print(
                            f"[dim yellow]⚠ 恢复项目目录失败: {e}[/dim yellow]\n"
                        )

        while True:
            try:
                user_input = self._read_user_input()
            except (KeyboardInterrupt, EOFError):
                print("\n再见！👋")
                break

            if user_input.lower() in {"quit", "exit", "q"}:
                print("再见！👋")
                break
            if not user_input:
                continue

            # 首次输入时自动切换到项目子目录
            if not _project_workspace_set:
                from agent.infrastructure.config.settings import switch_to_project_workspace
                project_dir = switch_to_project_workspace(user_input)
                _project_workspace_set = True
                # Persist project_dir to session metadata for task resume
                if hasattr(self._session_store, 'update_project_dir'):
                    try:
                        self._event_loop.run_until_complete(
                            self._session_store.update_project_dir(str(project_dir))
                        )
                    except Exception:
                        pass  # non-critical; best-effort persistence
                # 显示项目目录信息
                self._console.print(
                    f"[dim]📁 项目目录: {project_dir}[/dim]\n"
                )

            print("\nAgent:")
            self._assistant_buffer = []
            self._streaming_renderer = StreamingRenderer(self._console)

            try:
                self._event_loop.run_until_complete(self._run_turn_async(user_input))
                self._streaming_renderer.flush()
                print()
            except KeyboardInterrupt:
                if self._current_cancel_source:
                    self._current_cancel_source.cancel("User interrupted")
                self._streaming_renderer.flush()
                print("\n[User Interrupted: Session state preserved. You can resume later.]")
            except Exception as exc:
                self._streaming_renderer.flush()
                print(f"\nError: {exc}")

    def _read_user_input(self) -> str:
        if self._prompt_session is None:
            self._prompt_session = PromptSession(key_bindings=self._build_input_key_bindings(), multiline=True)
        return self._prompt_session.prompt("\n> ").strip()

    def _build_input_key_bindings(self) -> KeyBindings:
        bindings = KeyBindings()

        @bindings.add("c-m")
        def _(event):
            event.app.exit(result=event.app.current_buffer.text)

        @bindings.add("c-j")
        def _(event):
            event.app.current_buffer.insert_text("\n")

        for sequence in (
            ("escape", "c-m"),
            ("escape", "c-j"),
            ("escape", "[", "1", "3", ";", "2", "u"),
            ("escape", "[", "1", "3", ";", "2", "~"),
        ):
            @bindings.add(*sequence)
            def _(event):
                event.app.current_buffer.insert_text("\n")

        return bindings

    async def _run_turn_async(self, user_input: str) -> None:
        cancel_source = CancellationTokenSource()
        self._current_cancel_source = cancel_source
        self._last_cost_report = None
        self._last_turn_event = None
        self._active_skills = []
        event_stream = self._runtime.run_turn(query=user_input, cancellation_token=cancel_source.token)
        try:
            async for event in event_stream:
                self._on_event(event)
            # Persist cost data after turn completes
            if self._last_cost_report is not None and hasattr(self._session_store, 'persist_turn_cost'):
                try:
                    await self._session_store.persist_turn_cost(
                        turn_id=self._current_turn_id or "unknown",
                        cost_report=self._last_cost_report.summarize(),
                    )
                except Exception:
                    pass  # persistence failure is non-critical
            # Distill experience from this turn
            try:
                last_event = getattr(self, '_last_turn_event', None)
                if last_event is not None and isinstance(last_event, TurnCompletedEvent):
                    record_id = self._distill_service.distill_auto(
                        event=last_event,
                        session_id=self._session.session_id if hasattr(self._session, 'session_id') else "",
                        turn_id=self._current_turn_id or "",
                        active_skills=self._active_skills,
                    )
                    if record_id:
                        self._console.print(
                            f"[dim italic]📚 经验沉淀: 新记录 {record_id} (task: {self._active_skills[0] if self._active_skills else 'general'})[/dim italic]"
                        )
            except Exception:
                pass  # distillation failure is non-critical
        finally:
            self._current_cancel_source = None
            if not getattr(event_stream, "ag_running", False):
                aclose = getattr(event_stream, "aclose", None)
                if callable(aclose):
                    await aclose()

    def _shutdown_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if loop.is_closed():
            return
        pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        loop.run_until_complete(loop.shutdown_asyncgens())
        loop.run_until_complete(loop.shutdown_default_executor())
        loop.close()
            
    def _on_event(self, event: RuntimeEvent) -> None:
        from agent.domain.events import (
            AssistantDeltaEvent,
            AssistantMessageCompletedEvent,
            SkillActivatedEvent,
            ToolCallStartedEvent,
            ToolProgressEvent,
            ToolResultEvent,
            TurnCompletedEvent,
            TurnFailedEvent,
            TurnCancelledEvent,
            TurnStartedEvent,
            ToolBatchStartedEvent,
            PlanSnapshotEvent,
            DataIntegrityWarningEvent,
            WorkspaceViolationEvent,
        )

        if isinstance(event, TurnStartedEvent):
            # Early "thinking" indicator so the user never sees a silent gap.
            self._console.print("[dim]🤔 思考中…[/dim]")
            # Show experience hint if KB has records for the detected task type
            try:
                kb = self._distill_service._kb_repo.load()
                if len(kb) > 0:
                    # We don't know the task type yet, so show a generic hint
                    self._console.print("[dim italic]💡 基于历史经验分析[/dim italic]")
            except Exception:
                pass
        elif isinstance(event, AssistantDeltaEvent):
            self._assistant_buffer.append(event.text)
            self._streaming_renderer.append(event.text)
        elif isinstance(event, AssistantMessageCompletedEvent):
            self._streaming_renderer.finish_message()
        elif isinstance(event, SkillActivatedEvent):
            skill_name = getattr(event, 'skill_name', 'unknown')
            self._active_skills.append(skill_name)
            self._console.print(
                f"[dim italic]🧩 技能启用: {skill_name}"
                f" ({getattr(event, 'reason', '') or 'auto'})[/dim italic]"
            )
        elif isinstance(event, ToolBatchStartedEvent):
            # Flush any pending streaming text BEFORE the tool panel so the
            # batch announcement appears below the assistant's narration.
            self._streaming_renderer.flush()
            count = getattr(event, "count", 0)
            names = getattr(event, "tool_names", []) or []
            # Compact: list distinct names with counts (e.g. "bash×2, read_file")
            from collections import Counter
            tally = Counter(names)
            summary = ", ".join(f"{n}×{c}" if c > 1 else n for n, c in tally.items())
            self._console.print(f"[cyan]▶ 即将执行 {count} 个工具: {summary}[/cyan]")
            # Initialise batch tracking counters for grouped display
            self._batch_tool_totals = dict(tally)          # {tool_name: total_in_batch}
            self._batch_tool_counter = {n: 0 for n in tally}  # {tool_name: seen_so_far}
            self._batch_result_counter = {}                # {tool_name: results_seen_so_far}
        elif isinstance(event, ToolCallStartedEvent):
            self._streaming_renderer.flush()
            preview = getattr(event, "args_preview", "") or ""
            tool_name = getattr(event, "tool_name", "unknown")
            # Increment batch counter and show grouped index when tool appears >1 times
            idx = ""
            if tool_name in self._batch_tool_counter:
                self._batch_tool_counter[tool_name] += 1
                total = self._batch_tool_totals.get(tool_name, 1)
                if total > 1:
                    idx = f" ({self._batch_tool_counter[tool_name]}/{total})"
            line = f"[cyan]  🔧 {tool_name}{idx}[/cyan]"
            self._console.print(line)
            if preview:
                # Indent under the tool name; truncate to terminal-friendly width.
                self._console.print(f"[dim]     └─ {preview}[/dim]")
        elif isinstance(event, ToolProgressEvent):
            pass  # We let tool output print via bash thread for now
        elif isinstance(event, ToolResultEvent):
            status = getattr(event, "status", "unknown")
            summary = getattr(event, "summary", "") or ""
            duration_ms = getattr(event, "duration_ms", 0)
            duration_part = f" ({duration_ms}ms)" if duration_ms else ""
            if status == "ok":
                icon = "✅"
                color = "green"
            elif status == "error":
                icon = "❌"
                color = "red"
            else:
                icon = "•"
                color = "dim"
            tool_name = getattr(event, "tool_name", "unknown")
            # Show grouped index for tools that appear >1 times in batch
            idx = ""
            if tool_name in self._batch_tool_totals:
                self._batch_result_counter[tool_name] = self._batch_result_counter.get(tool_name, 0) + 1
                total = self._batch_tool_totals.get(tool_name, 1)
                if total > 1:
                    idx = f" ({self._batch_result_counter[tool_name]}/{total})"
            line = f"[{color}]     {icon} {tool_name}{idx}{duration_part}"
            if summary:
                line += f" — {summary}"
            line += f"[/{color}]"
            self._console.print(line)
        elif isinstance(event, PlanSnapshotEvent):
            # Render a compact one-block plan panel: counts + current focus.
            title = getattr(event, "title", "") or "(plan)"
            total = getattr(event, "total_steps", 0)
            done = getattr(event, "completed_steps", 0)
            ip = getattr(event, "in_progress_steps", 0)
            blocked = getattr(event, "blocked_steps", 0)
            focus = getattr(event, "current_focus", "") or "—"
            self._console.print(
                f"[magenta]📋 计划[/magenta] [bold]{title}[/bold]"
                f"  [green]✅ {done}/{total}[/green]"
                f"  [yellow]🔄 {ip}[/yellow]"
                + (f"  [red]🚫 {blocked}[/red]" if blocked else "")
                + f"   focus: [italic]{focus}[/italic]"
            )
        elif isinstance(event, DataIntegrityWarningEvent):
            # Loud, persistent banner — the agent is FORBIDDEN to fabricate
            # data, so we surface the source failure clearly to the user.
            tool_name = getattr(event, "tool_name", "?")
            reason = getattr(event, "reason", "data source failed")
            action = getattr(event, "suggested_action", "")
            self._console.print(
                "\n[bold red on yellow] ⚠ 数据完整性警告 [/bold red on yellow]"
                f" [yellow]{tool_name} 失败,Quanora 不会编造缺失数据[/yellow]"
            )
            self._console.print(f"[red]    原因: {reason}[/red]")
            if action:
                self._console.print(f"[yellow]    建议: {action}[/yellow]")
        elif isinstance(event, WorkspaceViolationEvent):
            # Loud banner — the agent tried to write outside the project
            # workspace (or into Quanora's own protected source tree). The
            # framework already blocked the write; this just makes the
            # attempt visible so the user can see the agent's intent.
            tool_name = getattr(event, "tool_name", "?")
            path = getattr(event, "path", "?")
            status = getattr(event, "status", "outside")
            reason = getattr(event, "reason", "workspace boundary violation")
            fix = getattr(event, "suggested_fix", "")
            label = "保护区写入" if status == "protected" else "越界写入"
            self._console.print(
                "\n[bold white on red] ⛔ 工作区边界违规 [/bold white on red]"
                f" [red]{tool_name} → {label}[/red]"
            )
            self._console.print(f"[red]    路径: {path}[/red]")
            self._console.print(f"[yellow]    原因: {reason}[/yellow]")
            if fix:
                self._console.print(f"[yellow]    建议: {fix}[/yellow]")
        elif isinstance(event, TurnFailedEvent):
            self._streaming_renderer.flush()
            message = getattr(event, "error", "") or getattr(event, "reason", "") or "unknown"
            print(f"\n[Error] Turn failed: {message}")
            cost = getattr(event, 'cost_report', None)
            if cost is not None:
                self._render_cost_report(cost)
        elif isinstance(event, TurnCompletedEvent):
            self._streaming_renderer.flush()
            self._last_turn_event = event  # save for distillation
            cost = getattr(event, 'cost_report', None)
            if cost is not None:
                self._render_cost_report(cost)
                self._last_cost_report = cost  # stored for async persist

            # Self-dev mode: auto push + PR after each turn with commits
            if self._self_dev:
                try:
                    from agent.infrastructure.config.settings import get_repo_root
                    from agent.infrastructure.git_hooks import on_turn_completed_self_dev
                    on_turn_completed_self_dev(get_repo_root())
                except Exception as exc:
                    # Never let the hook crash the CLI
                    print(f"\n[self-dev] ⚠ Push hook error: {exc}", file=sys.stderr)

        elif isinstance(event, TurnCancelledEvent):
            self._streaming_renderer.flush()
            print(f"\n[Cancelled] Turn cancelled: {getattr(event, 'reason', 'unknown')}")

    def _on_retry(self, attempt: int, exception: Exception) -> None:
        self._streaming_renderer.show_retry(attempt, exception)

    def _on_debug(self, message: str) -> None:
        print(f"\n[Debug] {message}")

    def _render_cost_report(self, cost_report) -> None:
        """Render a formatted cost report table at the end of a turn."""
        summary = cost_report.summarize()
        lines = []
        lines.append("")
        lines.append("┌─────────────────── Cost Report ───────────────────┐")
        lines.append(f"│ Turn wall time : {summary['turn_wall_s']}s")
        lines.append(f"│ LLM calls      : {summary['num_llm_calls']}")
        lines.append(f"│ Tool calls     : {summary['num_tool_calls']}")
        lines.append(f"│ Prompt tokens  : {summary['total_prompt_tokens']}")
        lines.append(f"│ Completion     : {summary['total_completion_tokens']}")
        lines.append(f"│ Total tokens   : {summary['total_tokens']}")
        lines.append(f"│ LLM latency    : {summary['total_llm_latency_s']}s")
        lines.append(f"│ Tool wall time : {summary['total_tool_wall_s']}s")

        if summary['llm_details']:
            lines.append("├──────────────── LLM Call Details ─────────────────┤")
            for i, d in enumerate(summary['llm_details'], 1):
                lines.append(f"│  #{i} model={d['model']}  p={d['prompt']} c={d['completion']} "
                             f"tot={d['total']}  lat={d['latency_s']}s")

        if summary['tool_details']:
            lines.append("├──────────────── Tool Call Details ────────────────┤")
            for i, d in enumerate(summary['tool_details'], 1):
                lines.append(f"│  #{i} {d['tool']}  wall={d['wall_s']}s  "
                             f"in={d['input_chars']}c out={d['output_chars']}c")

        lines.append("└───────────────────────────────────────────────────┘")
        lines.append("")
        print("\n".join(lines))
