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

        # ── Quant-Research auto-onboarding ──────────────────────────
        # Instead of silently waiting for user input, automatically
        # inject a trigger message so the agent starts the Phase 0
        # onboarding dialog right away.
        if self._self_quant:
            try:
                self._event_loop.run_until_complete(
                    self._run_turn_async("__QUANT_ONBOARDING__")
                )
            except Exception:
                pass  # non-fatal; user can still type normally

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

            # 首次输入时检查是否需要切换项目目录
            if not _project_workspace_set:
                from agent.infrastructure.config.settings import is_self_quant_mode
                if is_self_quant_mode():
                    # In quant-research mode, project binding is handled by
                    # Phase 0 onboarding (prompt-driven).  Don't auto-switch.
                    _project_workspace_set = True
                else:
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
            # Self-dev mode: even on failure, push any committed code
            self._maybe_self_dev_push("TurnFailedEvent")
        elif isinstance(event, TurnCompletedEvent):
            self._streaming_renderer.flush()
            self._last_turn_event = event  # save for distillation
            cost = getattr(event, 'cost_report', None)
            if cost is not None:
                self._render_cost_report(cost)
                self._last_cost_report = cost  # stored for async persist

            # Self-dev mode: auto push + PR after each turn with commits
            self._maybe_self_dev_push("TurnCompletedEvent")

        elif isinstance(event, TurnCancelledEvent):
            self._streaming_renderer.flush()
            print(f"\n[Cancelled] Turn cancelled: {getattr(event, 'reason', 'unknown')}")
            # Self-dev mode: even on cancellation, push any committed code
            self._maybe_self_dev_push("TurnCancelledEvent")

    def _on_retry(self, attempt: int, exception: Exception) -> None:
        self._streaming_renderer.show_retry(attempt, exception)

    def _on_debug(self, message: str) -> None:
        print(f"\n[Debug] {message}")

    # ── Self-dev push hook ────────────────────────────────────────────

    def _maybe_self_dev_push(self, trigger: str) -> None:
        """If running in self-dev mode, attempt the auto push+PR hook.

        This is called on TurnCompletedEvent, TurnFailedEvent, and
        TurnCancelledEvent so that any commits made during the turn are
        always pushed, regardless of how the turn ended.
        """
        if not self._self_dev:
            return

        try:
            from agent.infrastructure.config.settings import get_repo_root
            from agent.infrastructure.git_hooks import on_turn_completed_self_dev

            on_turn_completed_self_dev(get_repo_root(), trigger=trigger)
        except Exception as exc:
            # Never let the hook crash the CLI, but be loud about failures
            # so the user can diagnose and manually push if needed.
            import traceback
            print(
                f"\n[self-dev] ⚠ Push hook error (trigger={trigger}): {exc}",
                file=sys.stderr,
            )
            print(traceback.format_exc(), file=sys.stderr)
            print(
                "[self-dev] You may need to manually: git push origin genspark_ai_developer",
                file=sys.stderr,
            )

    # ── Cost analysis helpers ───────────────────────────────────────────

    @staticmethod
    def _efficiency_grade(
        *,
        total_tokens: int,
        turn_wall_s: float,
        num_tool_calls: int,
        num_llm_calls: int,
    ) -> tuple[str, str]:
        """Return (grade, comment) summarising this turn's efficiency.

        Heuristics (tuned for typical LLM-agent workloads):
        - Tokens / wall-second  → throughput efficiency
        - Tools / LLM-call ratio → tool utilisation
        - Absolute latency      → user-experience signal
        """
        # Throughput: tokens produced per wall-second
        throughput = total_tokens / max(turn_wall_s, 0.01)
        if throughput > 500:
            t_grade, t_comment = "A", "高吞吐"
        elif throughput > 200:
            t_grade, t_comment = "B", "吞吐正常"
        elif throughput > 80:
            t_grade, t_comment = "C", "吞吐偏低"
        else:
            t_grade, t_comment = "D", "吞吐过低，大量等待"

        # Latency: is the user waiting too long?
        if turn_wall_s < 5:
            l_grade, l_comment = "A", "响应迅速"
        elif turn_wall_s < 15:
            l_grade, l_comment = "B", "延迟可接受"
        elif turn_wall_s < 30:
            l_grade, l_comment = "C", "延迟较高"
        else:
            l_grade, l_comment = "D", "延迟过长，需优化"

        # Tool utilisation: tools per LLM call
        tool_ratio = num_tool_calls / max(num_llm_calls, 1)
        if tool_ratio >= 1.5:
            r_grade, r_comment = "A", "工具利用充分"
        elif tool_ratio >= 0.8:
            r_grade, r_comment = "B", "工具利用合理"
        elif tool_ratio >= 0.3:
            r_grade, r_comment = "C", "工具调用偏少"
        else:
            r_grade, r_comment = "D", "LLM 空转多，缺乏工具配合"

        # Overall: worst sub-grade dominates
        grades = {"A": 4, "B": 3, "C": 2, "D": 1}
        overall = min(t_grade, l_grade, r_grade, key=lambda g: grades[g])
        comment_parts = [t_comment, l_comment, r_comment]
        return overall, " | ".join(comment_parts)

    @staticmethod
    def _identify_bottlenecks(summary: dict) -> list[str]:
        """Return a list of bottleneck descriptions."""
        bottlenecks: list[str] = []

        llm_latency = summary["total_llm_latency_s"]
        tool_wall = summary["total_tool_wall_s"]
        turn_wall = summary["turn_wall_s"]

        # Is LLM the bottleneck?
        if llm_latency > 0 and turn_wall > 0:
            llm_pct = llm_latency / max(turn_wall, 0.01)
            if llm_pct > 0.7:
                bottlenecks.append(
                    f"LLM 推理占总时间 {llm_pct:.0%}，是主要瓶颈"
                )

        # Is tool execution the bottleneck?
        if tool_wall > 0 and turn_wall > 0:
            tool_pct = tool_wall / max(turn_wall, 0.01)
            if tool_pct > 0.7:
                bottlenecks.append(
                    f"工具执行占总时间 {tool_pct:.0%}，是主要瓶颈"
                )

        # Too many LLM calls with few tools?
        num_llm = summary["num_llm_calls"]
        num_tools = summary["num_tool_calls"]
        if num_llm > 5 and num_tools < 2:
            bottlenecks.append(
                f"LLM 调用 {num_llm} 次但仅 {num_tools} 次工具调用，可能存在冗余推理轮次"
            )

        # Token bloat: prompt tokens >> completion tokens
        prompt_tok = summary["total_prompt_tokens"]
        comp_tok = summary["total_completion_tokens"]
        if prompt_tok > 5000 and comp_tok > 0 and prompt_tok / comp_tok > 10:
            bottlenecks.append(
                f"Prompt/Completion 比达 {prompt_tok / comp_tok:.0f}:1，上下文过长"
            )

        return bottlenecks

    @staticmethod
    def _optimization_suggestions(summary: dict, bottlenecks: list[str]) -> list[str]:
        """Return actionable optimisation suggestions."""
        suggestions: list[str] = []

        prompt_tok = summary["total_prompt_tokens"]
        comp_tok = summary["total_completion_tokens"]
        num_llm = summary["num_llm_calls"]
        num_tools = summary["num_tool_calls"]
        llm_latency = summary["total_llm_latency_s"]
        tool_wall = summary["total_tool_wall_s"]

        # Context length reduction
        if prompt_tok > 8000:
            suggestions.append(
                "💡 缩减上下文：精简 system prompt 或减少历史消息，当前 prompt 占 "
                f"{prompt_tok} tokens"
            )
        elif prompt_tok > 4000:
            suggestions.append(
                "💡 考虑精简 prompt：当前 {p} tokens，适当压缩可降低延迟和成本".format(
                    p=prompt_tok
                )
            )

        # Batch tool calls
        if num_tools >= 4:
            suggestions.append(
                "💡 合并工具调用：多个独立工具调用可并行执行以减少等待"
            )

        # Reduce LLM round-trips
        if num_llm > 3 and num_tools / max(num_llm, 1) < 0.5:
            suggestions.append(
                "💡 减少推理轮次：当前 " + str(num_llm) +
                " 次 LLM 调用，尝试在单轮中完成更多决策"
            )

        # Slow tool identification
        if summary["tool_details"]:
            slow_tools = [
                d for d in summary["tool_details"] if d["wall_s"] > 5
            ]
            for st in slow_tools:
                suggestions.append(
                    f"💡 优化慢工具：{st['tool']} 耗时 {st['wall_s']}s，考虑缓存或异步执行"
                )

        # LLM model switch hint
        if llm_latency > 0 and summary["llm_details"]:
            for d in summary["llm_details"]:
                if d["latency_s"] > 10 and d["completion"] < 500:
                    suggestions.append(
                        f"💡 低产出高延迟：{d['model']} 产出 {d['completion']} tokens "
                        f"却耗时 {d['latency_s']}s，考虑换用更快的模型"
                    )

        return suggestions

    # ── Cost report rendering ──────────────────────────────────────────

    def _render_cost_report(self, cost_report) -> None:
        """Render a summarised cost report with efficiency grade and
        optimisation suggestions at the end of a turn."""
        summary = cost_report.summarize()

        # ── Core metrics (compact single-line) ──
        turn_wall = summary["turn_wall_s"]
        total_tokens = summary["total_tokens"]
        prompt_tok = summary["total_prompt_tokens"]
        comp_tok = summary["total_completion_tokens"]
        num_llm = summary["num_llm_calls"]
        num_tools = summary["num_tool_calls"]

        # ── Efficiency analysis ──
        grade, grade_comment = self._efficiency_grade(
            total_tokens=total_tokens,
            turn_wall_s=turn_wall,
            num_tool_calls=num_tools,
            num_llm_calls=num_llm,
        )
        grade_colors = {"A": "green", "B": "cyan", "C": "yellow", "D": "red"}
        grade_icons = {"A": "🟢", "B": "🔵", "C": "🟡", "D": "🔴"}

        bottlenecks = self._identify_bottlenecks(summary)
        suggestions = self._optimization_suggestions(summary, bottlenecks)

        # ── Render ──
        lines: list[str] = []
        lines.append("")
        lines.append("┌─────────────── Cost Summary ───────────────────┐")

        # Core metrics
        lines.append(
            f"│ ⏱ {turn_wall}s  ·  📊 {total_tokens} tokens "
            f"(in {prompt_tok} / out {comp_tok})  ·  "
            f"🔄 {num_llm} LLM + {num_tools} tool calls"
        )

        # Efficiency grade
        icon = grade_icons.get(grade, "⚪")
        lines.append(f"│ {icon} 效率评级: {grade} — {grade_comment}")

        # Time breakdown
        llm_lat = summary["total_llm_latency_s"]
        tool_wall = summary["total_tool_wall_s"]
        overhead = max(turn_wall - llm_lat - tool_wall, 0)
        lines.append(
            f"│ ⏳ 时间分布: LLM {llm_lat}s  |  工具 {tool_wall}s  |  调度 {overhead:.1f}s"
        )

        # Bottlenecks
        if bottlenecks:
            lines.append("├─────────────── 瓶颈分析 ───────────────────────┤")
            for b in bottlenecks:
                lines.append(f"│ ⚠ {b}")

        # Optimisation suggestions
        if suggestions:
            lines.append("├─────────────── 优化建议 ───────────────────────┤")
            for s in suggestions:
                lines.append(f"│ {s}")

        # Detailed breakdown (collapsed, only if multiple LLM or tool calls)
        if num_llm > 1 and summary["llm_details"]:
            lines.append("├─────────────── LLM 明细 ───────────────────────┤")
            for i, d in enumerate(summary["llm_details"], 1):
                lines.append(
                    f"│  #{i} {d['model']}  "
                    f"in={d['prompt']} out={d['completion']}  "
                    f"lat={d['latency_s']}s"
                )

        if num_tools > 1 and summary["tool_details"]:
            lines.append("├─────────────── Tool 明细 ──────────────────────┤")
            for i, d in enumerate(summary["tool_details"], 1):
                lines.append(
                    f"│  #{i} {d['tool']}  "
                    f"wall={d['wall_s']}s  "
                    f"io={d['input_chars']}→{d['output_chars']}c"
                )

        lines.append("└───────────────────────────────────────────────────┘")
        lines.append("")
        print("\n".join(lines))
