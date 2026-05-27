"""Context construction service for model-facing conversation state."""

from __future__ import annotations

from dataclasses import dataclass, field

from agent.domain.skills import render_active_skill_instructions
from agent.domain.knowledge_base import ExperienceKnowledgeBase
from agent.infrastructure.persistence.knowledge_base_repository import KnowledgeBaseRepository
from agent.infrastructure.persistence.research_experience_repository import ResearchExperienceRepository

from .context_estimator import ContextEstimator
from .conversation_summary_service import ConversationSummaryService
from .tool_context_policy import ToolContextPolicy


@dataclass(slots=True)
class ContextSnapshot:
    """Lightweight snapshot of context segments used to build model input."""

    system_message: dict | None = None
    recent_messages: list[dict] = field(default_factory=list)
    summary_messages: list[dict] = field(default_factory=list)
    tool_messages: list[dict] = field(default_factory=list)


@dataclass(slots=True)
class ContextBuildResult:
    """Result of building messages for a model request."""

    messages: list[dict]
    stats: dict = field(default_factory=dict)
    decisions: dict = field(default_factory=dict)
    snapshot: ContextSnapshot | None = None


class ContextManager:
    """Builds the model-facing message list from persisted session state."""

    def __init__(
        self,
        estimator: ContextEstimator | None = None,
        summary_service: ConversationSummaryService | None = None,
        tool_context_policy: ToolContextPolicy | None = None,
        hot_message_limit: int = 6,
        summary_step_threshold: int = 6,
        skill_repository=None,
        skill_selector=None,
        plan_context_provider=None,
        skill_index_char_limit: int = 0,
        active_skill_char_limit: int = 12000,
    ):
        self._estimator = estimator or ContextEstimator()
        self._summary_service = summary_service or ConversationSummaryService()
        self._tool_context_policy = tool_context_policy or ToolContextPolicy()
        self._hot_message_limit = max(1, int(hot_message_limit))
        self._summary_step_threshold = max(1, int(summary_step_threshold))
        self._skill_repository = skill_repository
        self._skill_selector = skill_selector
        self._plan_context_provider = plan_context_provider
        self._active_skill_char_limit = max(0, int(active_skill_char_limit))
        self._kb_repo = KnowledgeBaseRepository()
        self._research_exp_repo: ResearchExperienceRepository | None = None  # lazy-init

    async def build_messages_async(
        self,
        session,
        pending_messages: list[dict] | None = None,
        active_skill_matches: list | None = None,
    ) -> ContextBuildResult:
        persisted_messages = [dict(message) for message in await session.get_messages_slice()]
        pending = [dict(message) for message in (pending_messages or [])]
        budget = self._estimator.budget
        full_messages = await self._apply_tool_context_policy_async(
            messages=persisted_messages + pending,
            session=session,
            tool_char_budget=budget.tool_budget_tokens * 4,
        )
        plan_messages, plan_stats, plan_decisions = self._build_plan_messages()
        skill_messages, skill_stats, skill_decisions = self._build_skill_messages(active_skill_matches)
        knowledge_messages, knowledge_stats = self._build_knowledge_cache_messages()
        research_exp_messages, research_exp_stats = self._build_research_experience_messages()
        extra_messages = plan_messages + skill_messages + knowledge_messages + research_exp_messages
        if extra_messages:
            full_messages = self._insert_after_first_system(full_messages, extra_messages)

        initial_estimate = self._estimator.estimate_messages(full_messages)
        messages = list(full_messages)
        summary_messages: list[dict] = []
        cold_compacted_message_count = 0
        summary_generated = False
        hot_message_count = min(
            self._hot_message_limit,
            len([message for message in full_messages if self._is_conversation_message(message)]),
        )

        if initial_estimate.conversation_tokens >= budget.conversation_budget_tokens:
            messages, summary_messages, cold_compacted_message_count, summary_generated = await self._compact_cold_conversation_async(
                messages=full_messages,
                session=session,
            )

        final_messages = [self._strip_internal_fields(message) for message in messages]
        final_messages = self._normalize_messages(final_messages)
        final_estimate = self._estimator.estimate_messages(final_messages)
        
        dropped_count = 0
        while final_estimate.over_hard_limit and len(final_messages) > 2:
            messages, final_messages = self.rescue_context(messages, final_messages)
            final_estimate = self._estimator.estimate_messages(final_messages)
            dropped_count += 1
            if dropped_count > 50:
                break
                
        system_message = next((dict(message) for message in final_messages if message.get("role") == "system"), None)
        non_system_messages = [dict(message) for message in final_messages if message.get("role") != "system"]
        internal_tool_messages = [dict(message) for message in messages if message.get("role") == "tool"]
        tool_messages = [self._strip_internal_fields(message) for message in internal_tool_messages]
        snapshot = ContextSnapshot(
            system_message=system_message,
            recent_messages=non_system_messages,
            summary_messages=[dict(message) for message in summary_messages],
            tool_messages=tool_messages,
        )

        stats = {
            "message_count": len(messages),
            "persisted_message_count": len(persisted_messages),
            "pending_message_count": len(pending),
            "tool_message_count": len(tool_messages),
            "hot_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "hot"]),
            "warm_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "warm"]),
            "cold_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "cold"]),
            "summary_message_count": len(summary_messages),
            "hot_message_count": hot_message_count,
            "cold_compacted_message_count": cold_compacted_message_count,
            "estimated_input_tokens": final_estimate.estimated_input_tokens,
            "estimated_chars": final_estimate.estimated_chars,
            "system_tokens": final_estimate.system_tokens,
            "conversation_tokens": final_estimate.conversation_tokens,
            "tool_tokens": final_estimate.tool_tokens,
            "pre_compaction_estimated_input_tokens": initial_estimate.estimated_input_tokens,
            "pre_compaction_estimated_chars": initial_estimate.estimated_chars,
            "pre_compaction_system_tokens": initial_estimate.system_tokens,
            "pre_compaction_conversation_tokens": initial_estimate.conversation_tokens,
            "pre_compaction_tool_tokens": initial_estimate.tool_tokens,
            "budget": budget.to_dict(),
            **plan_stats,
            **skill_stats,
            **knowledge_stats,
            **research_exp_stats,
        }
        decisions = {
            "mode": "session_backed",
            "source": "session_queries",
            "uses_pending_overlay": bool(pending),
            "over_hard_limit": final_estimate.over_hard_limit,
            "over_conversation_budget": final_estimate.conversation_tokens >= budget.conversation_budget_tokens,
            "over_tool_budget": final_estimate.tool_tokens >= budget.tool_budget_tokens,
            "over_system_budget": final_estimate.system_tokens >= budget.system_budget_tokens,
            "compact_recommended": initial_estimate.conversation_tokens >= budget.conversation_budget_tokens,
            "compact_required": initial_estimate.over_hard_limit,
            "rolling_summary_applied": bool(summary_messages),
            "rolling_summary_generated": summary_generated,
            "hot_message_limit": self._hot_message_limit,
            "tool_policy_applied": True,
            **plan_decisions,
            **skill_decisions,
        }
        result = ContextBuildResult(messages=final_messages, stats=stats, decisions=decisions, snapshot=snapshot)
        await session.persist_context_snapshot(
            {
                "message_count": len(messages),
                "final_message_count": len(final_messages),
                "persisted_message_count": len(persisted_messages),
                "pending_message_count": len(pending),
                "tool_message_count": len(tool_messages),
                "hot_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "hot"]),
                "warm_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "warm"]),
                "cold_tool_message_count": len([message for message in internal_tool_messages if message.get("_tool_temperature") == "cold"]),
                "summary_message_count": len(summary_messages),
                "hot_message_count": hot_message_count,
                "cold_compacted_message_count": cold_compacted_message_count,
                "estimated_input_tokens": final_estimate.estimated_input_tokens,
                "estimated_chars": final_estimate.estimated_chars,
                "system_tokens": final_estimate.system_tokens,
                "conversation_tokens": final_estimate.conversation_tokens,
                "tool_tokens": final_estimate.tool_tokens,
                "pre_compaction_estimated_input_tokens": initial_estimate.estimated_input_tokens,
                "pre_compaction_estimated_chars": initial_estimate.estimated_chars,
                "pre_compaction_system_tokens": initial_estimate.system_tokens,
                "pre_compaction_conversation_tokens": initial_estimate.conversation_tokens,
                "pre_compaction_tool_tokens": initial_estimate.tool_tokens,
                "over_hard_limit": final_estimate.over_hard_limit,
                "budget": budget.to_dict(),
                "decisions": decisions,
                **plan_stats,
                **skill_stats,
                **knowledge_stats,
            }
        )
        return result

    def reduce_hard_limit(self, factor: float = 0.8) -> int:
        """Reduce the hard token limit by a factor and return the new value."""
        self._estimator.budget.hard_limit_tokens = int(
            self._estimator.budget.hard_limit_tokens * factor
        )
        return self._estimator.budget.hard_limit_tokens

    def rescue_context(self, internal_messages: list[dict], final_messages: list[dict]) -> tuple[list[dict], list[dict]]:
        """Surgical Context Rescue: Drops the oldest cold/tool messages instead of blindly shrinking budgets."""
        # Find oldest non-system message that isn't already dropped
        target_idx = -1
        for i, msg in enumerate(final_messages):
            if msg.get("role") != "system" and msg.get("content") != "[DROPPED FOR CONTEXT RESCUE]":
                # Do not drop the very last few hot messages
                if i < len(final_messages) - 2:
                    target_idx = i
                    break
                    
        if target_idx != -1:
            internal_messages[target_idx]["content"] = "[DROPPED FOR CONTEXT RESCUE]"
            final_messages[target_idx]["content"] = "[DROPPED FOR CONTEXT RESCUE]"
            
        return internal_messages, final_messages

    async def _apply_tool_context_policy_async(self, messages: list[dict], session, tool_char_budget: int | None = None) -> list[dict]:
        tool_call_ids = [message.get("tool_call_id") for message in messages if message.get("role") == "tool" and message.get("tool_call_id")]
        if not tool_call_ids:
            return [dict(message) for message in messages]

        tool_batches = self._collect_tool_batches(messages)
        temperatures = self._tool_context_policy.classify_temperatures(tool_batches)
        tool_records_list = await session.get_tool_records(call_ids=tool_call_ids)
        tool_records = {
            record.get("id"): dict(record)
            for record in tool_records_list
            if isinstance(record, dict) and record.get("id")
        }
        tool_summaries = await session.get_tool_summaries(call_ids=tool_call_ids)
        rendered_messages: list[dict] = []
        call_ids_in_order = self._tool_call_ids_in_order(messages)
        prioritized_call_ids = self._prioritize_tool_call_ids(call_ids_in_order, temperatures)
        remaining_tool_chars = tool_char_budget
        rendered_tool_content: dict[str, str] = {}

        for call_id in prioritized_call_ids:
            tool_record = tool_records.get(call_id)
            temperature = temperatures.get(call_id, "cold")
            summary_record = tool_summaries.get(call_id)
            if temperature in {"warm", "cold"} and tool_record and not summary_record:
                summary_record = self._tool_context_policy.build_tool_summary_record(tool_record)
                await session.persist_tool_summary(summary_record)
                tool_summaries[call_id] = summary_record
            rendered_content = self._tool_context_policy.render_tool_message(
                tool_record,
                summary_record,
                temperature,
                available_chars=remaining_tool_chars,
            )
            rendered_tool_content[call_id] = rendered_content
            if remaining_tool_chars is not None:
                remaining_tool_chars = max(0, remaining_tool_chars - len(rendered_content))

        for message in messages:
            rendered = dict(message)
            if rendered.get("role") == "tool" and rendered.get("tool_call_id"):
                call_id = rendered.get("tool_call_id")
                rendered["content"] = rendered_tool_content.get(call_id, "")
                rendered["_tool_temperature"] = temperatures.get(call_id, "cold")
            rendered_messages.append(rendered)
        return rendered_messages

    def _tool_call_ids_in_order(self, messages: list[dict]) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        for message in messages:
            if message.get("role") != "tool":
                continue
            call_id = message.get("tool_call_id")
            if not call_id or call_id in seen:
                continue
            ordered.append(call_id)
            seen.add(call_id)
        return ordered

    def _prioritize_tool_call_ids(self, call_ids: list[str], temperatures: dict[str, str]) -> list[str]:
        rank = {"hot": 0, "warm": 1, "cold": 2}
        position = {call_id: idx for idx, call_id in enumerate(call_ids)}
        return sorted(
            call_ids,
            key=lambda call_id: (rank.get(temperatures.get(call_id, "cold"), 2), position[call_id]),
        )

    def _collect_tool_batches(self, messages: list[dict]) -> list[list[str]]:
        batches: list[list[str]] = []
        for message in messages:
            if message.get("role") != "assistant":
                continue
            tool_calls = message.get("tool_calls")
            if not isinstance(tool_calls, list):
                continue
            batch = [item.get("id") for item in tool_calls if isinstance(item, dict) and item.get("id")]
            if batch:
                batches.append(batch)
        return batches

    def _strip_internal_fields(self, message: dict) -> dict:
        return {key: value for key, value in dict(message).items() if not key.startswith("_")}

    @staticmethod
    def _normalize_messages(messages: list[dict]) -> list[dict]:
        """Normalize messages to ensure they conform to LLM API requirements.

        The OpenAI-compatible API requires that messages alternate roles
        (system can appear multiple times, but user/assistant/tool must not
        appear consecutively with the same role).  This method fixes common
        violations:

        1. Drops empty assistant messages that have NO tool_calls.
        2. Drops empty tool messages (empty content + no useful data).
        3. Merges consecutive user messages by concatenating content.
        4. Merges consecutive assistant messages that both have text content
           (but NOT assistant messages that carry tool_calls).
        5. Never merges tool messages — each must match a tool_call_id.
        6. Inserts a dummy user message if the sequence would otherwise start
           with an assistant/tool message.
        """
        if not messages:
            return messages

        # ---- Step 1: Filter out clearly invalid messages ----
        filtered: list[dict] = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            has_tool_calls = bool(msg.get("tool_calls"))

            # Empty assistant with no tool_calls is useless — drop it
            if role == "assistant" and not has_tool_calls:
                if isinstance(content, str) and content.strip() == "":
                    continue
                if isinstance(content, list) and len(content) == 0:
                    continue

            # Empty tool content is common (some tools return "") — keep it
            # because it is paired with a tool_call_id.
            # But if a tool msg has NO content AND no tool_call_id, drop it.
            if role == "tool":
                if not msg.get("tool_call_id") and not msg.get("name"):
                    if isinstance(content, str) and content.strip() == "":
                        continue
                    if isinstance(content, list) and len(content) == 0:
                        continue

            # Empty user content (non-tool, non-assistant) — drop
            if role == "user":
                if isinstance(content, str) and content.strip() == "":
                    continue
                if isinstance(content, list) and len(content) == 0:
                    continue

            filtered.append(msg)

        if not filtered:
            return filtered

        # ---- Step 2: Merge consecutive same-role messages ----
        # Rules:
        #   - system: never merge (multiple system messages are allowed)
        #   - user: merge by concatenating content
        #   - assistant with text only: merge by concatenating content
        #   - assistant with tool_calls: NEVER merge (API expects 1:1 pairing)
        #   - tool: NEVER merge (must match tool_call_id)
        normalized: list[dict] = [filtered[0]]
        for msg in filtered[1:]:
            prev = normalized[-1]
            prev_role = prev.get("role", "")
            curr_role = msg.get("role", "")

            if prev_role != curr_role:
                normalized.append(msg)
                continue

            # Same role from here on
            if curr_role == "system":
                # Multiple system messages are OK
                normalized.append(msg)
            elif curr_role == "user":
                # Merge user content
                prev_content = prev.get("content", "")
                curr_content = msg.get("content", "")
                if isinstance(prev_content, str) and isinstance(curr_content, str):
                    prev["content"] = prev_content + "\n" + curr_content
                elif isinstance(prev_content, list) and isinstance(curr_content, list):
                    prev["content"] = prev_content + curr_content
                else:
                    prev["content"] = str(prev_content) + "\n" + str(curr_content)
            elif curr_role == "assistant":
                # Only merge if BOTH are text-only (no tool_calls)
                prev_has_tc = bool(prev.get("tool_calls"))
                curr_has_tc = bool(msg.get("tool_calls"))
                if not prev_has_tc and not curr_has_tc:
                    prev_content = prev.get("content", "")
                    curr_content = msg.get("content", "")
                    if isinstance(prev_content, str) and isinstance(curr_content, str):
                        prev["content"] = prev_content + "\n" + curr_content
                    elif isinstance(prev_content, list) and isinstance(curr_content, list):
                        prev["content"] = prev_content + curr_content
                    else:
                        prev["content"] = str(prev_content) + "\n" + str(curr_content)
                else:
                    # At least one has tool_calls — cannot merge.
                    # This is a genuine API violation.  We insert a dummy
                    # user message to break the sequence.
                    normalized.append({"role": "user", "content": "[continuation]"})
                    normalized.append(msg)
            elif curr_role == "tool":
                # Tool messages must not be merged (each has a unique
                # tool_call_id).  Insert a dummy assistant to break.
                normalized.append({"role": "assistant", "content": ""})
                normalized.append(msg)
            else:
                normalized.append(msg)

        # ---- Step 3: Ensure sequence starts with system or user ----
        if normalized and normalized[0].get("role") not in ("system", "user"):
            normalized.insert(0, {"role": "user", "content": "[start]"})

        # ---- Step 4: Remove trailing assistant with empty content & no tool_calls ----
        while normalized:
            last = normalized[-1]
            if last.get("role") == "assistant" and not last.get("tool_calls"):
                lc = last.get("content", "")
                if (isinstance(lc, str) and lc.strip() == "") or (isinstance(lc, list) and len(lc) == 0):
                    normalized.pop()
                    continue
            break

        return normalized


    def select_active_skills_for_turn(self, user_message: str) -> list:
        if not self._skill_repository or not self._skill_selector:
            return []
        try:
            skills = list(self._skill_repository.list_skills())
            return list(self._skill_selector.select(user_message, skills))
        except Exception:
            return []

    def _build_plan_messages(self) -> tuple[list[dict], dict, dict]:
        stats = {
            "plan_summary_chars": 0,
            "plan_open": False,
            "plan_step_count": 0,
            "plan_unfinished_step_count": 0,
        }
        decisions = {
            "plan_summary_injected": False,
            "plan_id": None,
            "plan_version": None,
            "plan_state": "none",
        }
        if not self._plan_context_provider:
            return [], stats, decisions
        try:
            return self._plan_context_provider.build_context()
        except Exception:
            decisions["plan_state"] = "error"
            return [], stats, decisions

    def _build_skill_messages(self, active_skill_matches: list | None = None) -> tuple[list[dict], dict, dict]:
        stats = {
            "skill_count": 0,
            "active_skill_count": 0,
            "skill_index_chars": 0,
            "active_skill_chars": 0,
        }
        decisions = {
            "skills_available": False,
            "active_skills": [],
            "skill_injection_applied": False,
        }
        if not self._skill_repository:
            return [], stats, decisions

        try:
            skills = list(self._skill_repository.list_skills())
        except Exception:
            return [], stats, decisions
        if not skills:
            return [], stats, decisions

        active_matches = list(active_skill_matches or [])
        messages: list[dict] = []

        active_content = ""
        if active_matches:
            active_content = render_active_skill_instructions(active_matches, self._active_skill_char_limit)
            if active_content:
                messages.append({"role": "system", "content": active_content})

        stats.update(
            {
                "skill_count": len(skills),
                "active_skill_count": len(active_matches),
                "skill_index_chars": 0,
                "active_skill_chars": len(active_content),
            }
        )
        decisions.update(
            {
                "skills_available": True,
                "active_skills": [
                    {
                        "name": match.skill.name,
                        "reason": match.reason,
                        "score": match.score,
                        "source": match.skill.source,
                        "path": match.skill.path,
                    }
                    for match in active_matches
                ],
                "skill_injection_applied": bool(messages),
            }
        )

        # ── Experience Knowledge Injection ────────────────────────────
        # Load relevant experience records from the KB and inject them as
        # an additional system message alongside skill instructions.
        try:
            kb = self._kb_repo.load()
            if len(kb) > 0 and active_matches:
                # Use the first active skill's name as a task_type hint
                task_type = active_matches[0].skill.name if active_matches else ""
                top_records = kb.query_top_k(task_type, k=3)
                if top_records:
                    exp_lines = ["[Experience Knowledge — lessons from past tasks]"]
                    for rec in top_records:
                        exp_lines.append(f"• {rec.experience_summary}")
                        if rec.common_pitfalls:
                            exp_lines.append(f"  Pitfalls: {', '.join(rec.common_pitfalls[:3])}")
                        if rec.optimization_suggestions:
                            exp_lines.append(f"  Suggestions: {', '.join(rec.optimization_suggestions[:3])}")
                    exp_content = "\n".join(exp_lines)
                    messages.append({"role": "system", "content": exp_content})
                    decisions["experience_injection_applied"] = True
                    decisions["experience_records_used"] = len(top_records)
                    # Boost relevance of used records
                    for rec in top_records:
                        self._kb_repo.boost_relevance(rec.id, 0.05)
                else:
                    decisions["experience_injection_applied"] = False
                    decisions["experience_records_used"] = 0
            else:
                decisions["experience_injection_applied"] = False
                decisions["experience_records_used"] = 0
        except Exception:
            decisions["experience_injection_applied"] = False
            decisions["experience_records_used"] = 0

        return messages, stats, decisions

    def _build_knowledge_cache_messages(self) -> tuple[list[dict], dict]:
        """尝试加载项目知识缓存并注入为上下文消息.

        如果缓存存在且有效，将 context_boost 注入为一条 system 消息，
        让 agent 在新会话中无需从头探索项目。
        """
        stats = {"knowledge_cache_status": "none"}
        messages: list[dict] = []

        try:
            from agent.infrastructure.config import Config
            from agent.infrastructure.persistence.project_knowledge_cache import (
                build_context_boost_from_cache,
                get_cache_path,
                is_cache_stale,
                load_knowledge_cache,
            )

            project_root = Config.WORKSPACE_ROOT
            cache_path = get_cache_path(project_root)
            cache = load_knowledge_cache(cache_path)

            if cache is None:
                stats["knowledge_cache_status"] = "miss"
                return messages, stats

            if is_cache_stale(cache, project_root):
                stats["knowledge_cache_status"] = "stale"
                stats["knowledge_cache_old_head"] = cache.get("git_head")
                # stale 缓存仍然注入，但标记为可能过时
                context_boost = build_context_boost_from_cache(cache)
                messages.append({
                    "role": "system",
                    "content": (
                        f"[项目知识缓存 — 可能已过时，git HEAD 或关键文件已变更]\n\n"
                        f"{context_boost}\n\n"
                        f"⚠ 此缓存可能已过时。如果发现信息不准确，请重新探索项目并调用 generate_project_knowledge 更新缓存。"
                    ),
                })
                return messages, stats

            # 缓存有效
            stats["knowledge_cache_status"] = "hit"
            stats["knowledge_cache_generated_at"] = cache.get("generated_at")
            stats["knowledge_cache_git_head"] = cache.get("git_head")

            context_boost = build_context_boost_from_cache(cache)
            messages.append({
                "role": "system",
                "content": (
                    f"[项目知识缓存 — 已加载]\n\n"
                    f"{context_boost}\n\n"
                    f"💡 此为上次探索项目的压缩缓存。如需深入了解某文件，仍可使用 read_file / grep。"
                ),
            })

        except Exception:
            # 知识缓存加载不应阻断主流程
            stats["knowledge_cache_status"] = "error"

        return messages, stats

    def _build_research_experience_messages(self) -> tuple[list[dict], dict]:
        """Build system messages injecting project-level quant research experience.

        This is separate from the generic KnowledgeBase (which is user-scoped and
        task-type-oriented).  Research experience is project-scoped and contains
        structured quant-specific fields (strategy category, instrument, regime,
        performance metrics, what worked / what failed).

        The injection format is designed to be concise yet actionable:
        - Top insights: one-liners that steer the agent away from dead ends
        - Recent successes: proven patterns to build on
        - Recent failures: anti-patterns to avoid
        """
        stats = {"research_experience_status": "none"}
        messages: list[dict] = []

        try:
            from agent.infrastructure.config import Config

            project_root = Config.WORKSPACE_ROOT
            if not project_root:
                return messages, stats

            # Lazy-init the repo (only when we actually have a project)
            if self._research_exp_repo is None:
                self._research_exp_repo = ResearchExperienceRepository(project_root)

            book = self._research_exp_repo.load()

            if len(book) == 0:
                stats["research_experience_status"] = "empty"
                return messages, stats

            stats["research_experience_status"] = "hit"
            stats["research_experience_count"] = len(book)

            # Build concise injection
            parts: list[str] = [
                "[项目量化研究经验 — 已加载]",
                f"本项目共 {len(book)} 条研究经验记录。",
                "",
            ]

            # Top insights
            insights = book.query_top_insights(k=5)
            if insights:
                parts.append("### 关键洞察")
                for r in insights:
                    parts.append(f"- [{r.outcome.upper()}] {r.strategy_name or r.strategy_category}: {r.key_insight}")
                parts.append("")

            # Recent successes
            successes = book.query_successes(k=3)
            if successes:
                parts.append("### 近期成功策略")
                for r in successes:
                    perf_str = ""
                    if r.performance:
                        sharpe = r.performance.get("sharpe")
                        if sharpe is not None:
                            perf_str = f" (Sharpe={sharpe:.2f})"
                    parts.append(f"- {r.strategy_name}{perf_str}: {r.what_worked}")
                parts.append("")

            # Recent failures (anti-patterns)
            failures = book.query_failures(k=3)
            if failures:
                parts.append("### 近期失败教训（避免重复）")
                for r in failures:
                    parts.append(f"- {r.strategy_name}: {r.what_failed}")
                parts.append("")

            parts.append(
                "💡 以上是本项目历史研究经验的自动摘要。在新研究开始前，"
                "请优先参考这些经验以避免重复探索已知死路。"
                "完成研究后，请使用 research_experience 工具总结新经验。"
            )

            messages.append({
                "role": "system",
                "content": "\n".join(parts),
            })

        except Exception:
            # Research experience injection should never block main flow
            stats["research_experience_status"] = "error"

        return messages, stats

    def _insert_after_first_system(self, messages: list[dict], extra_messages: list[dict]) -> list[dict]:
        if not extra_messages:
            return list(messages)
        result: list[dict] = []
        inserted = False
        for message in messages:
            result.append(dict(message))
            if not inserted and message.get("role") == "system":
                result.extend(dict(item) for item in extra_messages)
                inserted = True
        if not inserted:
            result = [dict(item) for item in extra_messages] + result
        return result

    async def _compact_cold_conversation_async(self, messages: list[dict], session) -> tuple[list[dict], list[dict], int, bool]:
        hot_indices = self._hot_message_indices(messages)
        cold_indices = [
            index
            for index, message in enumerate(messages)
            if index not in hot_indices and self._is_summarizable_cold_message(message)
        ]
        if not cold_indices:
            return list(messages), [], 0, False

        cold_messages = [dict(messages[index]) for index in cold_indices]
        try:
            latest_summary = await session.get_latest_conversation_summary()
            summary_generated = False
            covered_count = 0
            if self._can_reuse_summary(latest_summary, cold_messages):
                summary = dict(latest_summary)
                covered_count = int(summary.get("source_message_count") or 0)
            else:
                summary = self._summary_service.summarize(cold_messages)
                await session.persist_conversation_summary(summary)
                summary_generated = True
                covered_count = len(cold_messages)
            summary_message = self._summary_service.render_summary_message(summary)
        except Exception:
            return list(messages), [], 0, False

        compacted_messages: list[dict] = []
        inserted_summary = False
        cold_index_set = set(cold_indices)
        
        skipped_cold_messages = 0
        
        for index, message in enumerate(messages):
            if index in cold_index_set:
                if not inserted_summary:
                    compacted_messages.append(dict(summary_message))
                    inserted_summary = True
                
                if skipped_cold_messages < covered_count:
                    skipped_cold_messages += 1
                    continue
                
                compacted_messages.append(dict(message))
                continue
            compacted_messages.append(dict(message))
            
        return compacted_messages, [dict(summary_message)], covered_count, summary_generated

    def _hot_message_indices(self, messages: list[dict]) -> set[int]:
        conversation_indices = [
            index
            for index, message in enumerate(messages)
            if self._is_conversation_message(message)
        ]
        return set(conversation_indices[-self._hot_message_limit :])

    def _is_summarizable_cold_message(self, message: dict) -> bool:
        return self._is_conversation_message(message)

    def _is_conversation_message(self, message: dict) -> bool:
        if message.get("role") not in {"user", "assistant"}:
            return False
        if message.get("tool_calls"):
            return False
        content = message.get("content", "")
        return isinstance(content, str) and bool(content.strip())

    def _can_reuse_summary(self, summary: dict | None, cold_messages: list[dict]) -> bool:
        if not isinstance(summary, dict):
            return False
        
        # We reuse the summary if the number of new cold messages since the last summary
        # is less than the summary_step_threshold.
        last_count = int(summary.get("source_message_count") or 0)
        current_count = len(cold_messages)
        
        # Must have at least as many messages as before (we don't reuse if history was deleted somehow)
        if current_count < last_count:
            return False
            
        return (current_count - last_count) < self._summary_step_threshold
