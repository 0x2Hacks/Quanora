"""Experience distillation service — the 'write-back' half of the experience loop.

After a turn completes, this service extracts lessons from the turn's events,
tool calls, and outcomes, then writes a new ExperienceRecord into the
KnowledgeBase.  This completes the feedback loop:
  inject experience → run turn → distill new experience → write back.
"""

from __future__ import annotations

import json
from typing import Any

from agent.domain.events import TurnCostReport, TurnCompletedEvent
from agent.domain.knowledge_base import ExperienceRecord, ExperienceKnowledgeBase
from agent.infrastructure.persistence.knowledge_base_repository import KnowledgeBaseRepository


class ExperienceDistillationService:
    """Distills experience from a completed turn and persists it to the KB."""

    def __init__(self, kb_repo: KnowledgeBaseRepository | None = None):
        self._kb_repo = kb_repo or KnowledgeBaseRepository()

    def distill_from_turn(
        self,
        task_type: str,
        turn_summary: str,
        tool_calls: list[dict[str, Any]] | None = None,
        cost_report: TurnCostReport | None = None,
        success: bool = True,
        session_id: str = "",
        turn_id: str = "",
        context_tags: list[str] | None = None,
    ) -> str | None:
        """Distill experience from a completed turn and write it to the KB.

        Args:
            task_type: What kind of task this was (e.g. skill name).
            turn_summary: Natural-language summary of what happened.
            tool_calls: List of tool call dicts with name, duration, etc.
            cost_report: Token/time cost data for this turn.
            success: Whether the turn completed successfully.
            session_id: The session this turn belongs to.
            turn_id: The specific turn identifier.
            context_tags: Additional tags for categorization.

        Returns:
            The record ID if written, or None if skipped.
        """
        # Skip distillation if there's nothing meaningful to learn
        if not turn_summary and not tool_calls:
            return None

        # Build the experience record
        record = ExperienceRecord(
            task_type=task_type,
            experience_summary=_summarize_experience(turn_summary, success, tool_calls, cost_report),
            key_decisions=_extract_key_decisions(turn_summary),
            common_pitfalls=_extract_pitfalls(turn_summary, success, tool_calls),
            optimization_suggestions=_extract_suggestions(turn_summary, success, cost_report),
            success_indicators=_extract_success_indicators(success, tool_calls, cost_report),
            failure_indicators=_extract_failure_indicators(success, tool_calls, cost_report),
            context_tags=context_tags or [],
            source_turn_id=turn_id,
            source_session_id=session_id,
        )

        # Persist
        return self._kb_repo.add_record(record)

    def distill_auto(
        self,
        event: TurnCompletedEvent,
        session_id: str = "",
        turn_id: str = "",
        active_skills: list[str] | None = None,
    ) -> str | None:
        """Auto-distill from a TurnCompletedEvent.

        Uses the event's cost_report and any available context to generate
        an experience record.
        """
        task_type = active_skills[0] if active_skills else "general"
        cost = getattr(event, 'cost_report', None)

        # Generate a brief summary from the cost data
        if cost:
            summary_parts = [
                f"Turn completed with {cost.num_tool_calls} tool calls and {cost.num_llm_calls} LLM calls.",
                f"Total tokens: {cost.total_tokens}.",
            ]
            if cost.total_tool_wall_seconds > 0:
                summary_parts.append(f"Tool execution took {cost.total_tool_wall_seconds:.1f}s.")
            turn_summary = " ".join(summary_parts)
        else:
            turn_summary = "Turn completed."

        return self.distill_from_turn(
            task_type=task_type,
            turn_summary=turn_summary,
            cost_report=cost,
            session_id=session_id,
            turn_id=turn_id,
            context_tags=active_skills or [],
        )


# ── Private helpers ──────────────────────────────────────────────────────

def _summarize_experience(
    summary: str,
    success: bool,
    tool_calls: list[dict] | None,
    cost: TurnCostReport | None,
) -> str:
    """Produce a concise experience summary."""
    status = "completed successfully" if success else "encountered issues"
    parts = [f"Task {status}."]
    if summary:
        parts.append(summary)
    if tool_calls:
        tool_names = [tc.get("tool", "unknown") for tc in tool_calls[:5]]
        parts.append(f"Used tools: {', '.join(tool_names)}.")
    return " ".join(parts)[:300]  # cap at 300 chars


def _extract_key_decisions(summary: str) -> list[str]:
    """Extract key decision points from the turn summary."""
    if not summary:
        return []
    # Simple heuristic: look for "decided to", "chose", "selected" phrases
    decisions = []
    for phrase in ["decided to", "chose to", "selected", "opted for"]:
        idx = summary.lower().find(phrase)
        if idx >= 0:
            decisions.append(summary[idx:idx + 80].strip())
    return decisions[:3]


def _extract_pitfalls(summary: str, success: bool, tool_calls: list[dict] | None) -> list[str]:
    """Extract common pitfalls from a turn."""
    pitfalls = []
    if not success:
        pitfalls.append("Turn did not complete successfully — review approach.")
    # Check for tool failures
    if tool_calls:
        for tc in tool_calls:
            if tc.get("status") == "error" or tc.get("error"):
                pitfalls.append(f"Tool {tc.get('tool', 'unknown')} encountered an error.")
    return pitfalls[:5]


def _extract_suggestions(summary: str, success: bool, cost: TurnCostReport | None) -> list[str]:
    """Extract optimization suggestions."""
    suggestions = []
    if cost:
        if cost.total_tokens > 50000:
            suggestions.append("Consider reducing context size to save tokens.")
        if cost.total_tool_wall_seconds > 60:
            suggestions.append("Tool execution was slow — consider caching or batching.")
        if cost.num_llm_calls > 3:
            suggestions.append("Multiple LLM calls in one turn — consider consolidating prompts.")
    return suggestions[:3]


def _extract_success_indicators(success: bool, tool_calls: list[dict] | None, cost: TurnCostReport | None) -> list[str]:
    """Extract signals that indicate the task went well."""
    indicators = []
    if success:
        indicators.append("Task completed without errors.")
    if cost and cost.total_tokens < 10000:
        indicators.append("Efficient token usage (<10k tokens).")
    if tool_calls and all(tc.get("status") != "error" for tc in tool_calls):
        indicators.append("All tool calls executed successfully.")
    return indicators[:3]


def _extract_failure_indicators(success: bool, tool_calls: list[dict] | None, cost: TurnCostReport | None) -> list[str]:
    """Extract signals that indicate the task went poorly."""
    indicators = []
    if not success:
        indicators.append("Turn ended with an error or cancellation.")
    if cost and cost.total_tokens > 80000:
        indicators.append("High token consumption (>80k tokens).")
    if cost and cost.num_tool_calls > 10:
        indicators.append("Excessive tool calls (>10) in one turn.")
    return indicators[:3]