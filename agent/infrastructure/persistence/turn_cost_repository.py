"""Repository for persisting and querying TurnCostReport data.

Each turn's cost report is stored as a JSONL entry under the session directory,
enabling per-session and cross-session cost analysis.
"""

from __future__ import annotations

import json
from typing import Any

from agent.domain.events import TurnCostReport, LLMUsageRecord, ToolCallUsageRecord
from agent.infrastructure.persistence.session_files import SessionFiles


class TurnCostRepository:
    """Persists TurnCostReports per turn, stored as JSONL in the session dir."""

    def __init__(self, files: SessionFiles, path: str):
        self._files = files
        self._path = path

    # ── Persist ───────────────────────────────────────────────────────────

    def persist_cost(self, session_id: str, turn_id: str, cost_report: TurnCostReport) -> None:
        """Append a cost report entry to the JSONL file."""
        entry = {
            "session_id": session_id,
            "turn_id": turn_id,
            "cost": cost_report.summarize(),
        }
        self._files.append_jsonl(self._path, entry)

    # ── Query ─────────────────────────────────────────────────────────────

    def load_all(self) -> list[dict[str, Any]]:
        """Load all cost entries from the JSONL file."""
        return self._files.read_jsonl(self._path)

    def query_by_session(self, session_id: str) -> list[dict[str, Any]]:
        """Return all cost entries for a given session."""
        return [e for e in self.load_all() if e.get("session_id") == session_id]

    def query_by_turn(self, session_id: str, turn_id: str) -> dict[str, Any] | None:
        """Return the cost entry for a specific turn in a session."""
        for e in self.load_all():
            if e.get("session_id") == session_id and e.get("turn_id") == turn_id:
                return e
        return None

    def aggregate_session_totals(self, session_id: str) -> dict[str, Any]:
        """Aggregate total token/time costs for all turns in a session."""
        entries = self.query_by_session(session_id)
        total_prompt = sum(e.get("cost", {}).get("total_prompt_tokens", 0) for e in entries)
        total_completion = sum(e.get("cost", {}).get("total_completion_tokens", 0) for e in entries)
        total_tokens = sum(e.get("cost", {}).get("total_tokens", 0) for e in entries)
        total_llm_latency = sum(e.get("cost", {}).get("total_llm_latency_s", 0) for e in entries)
        total_tool_wall = sum(e.get("cost", {}).get("total_tool_wall_s", 0) for e in entries)
        total_turn_wall = sum(e.get("cost", {}).get("turn_wall_s", 0) for e in entries)
        return {
            "session_id": session_id,
            "num_turns": len(entries),
            "total_prompt_tokens": total_prompt,
            "total_completion_tokens": total_completion,
            "total_tokens": total_tokens,
            "total_llm_latency_s": round(total_llm_latency, 2),
            "total_tool_wall_s": round(total_tool_wall, 2),
            "total_turn_wall_s": round(total_turn_wall, 2),
        }