"""Experience Knowledge Base domain model for task-type-based learning loops.

Each record captures lessons learned from past turns of a particular task type,
including key decisions, common pitfalls, and optimization suggestions.  These
records are loaded at turn-start to inject relevant experience into the LLM's
context, and written back at turn-end after distilling new observations.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any


@dataclass(slots=True)
class ExperienceRecord:
    """A single experience entry within the knowledge base."""
    id: str = ""                          # unique identifier (uuid-like)
    task_type: str = ""                   # e.g. "code_generation", "refactoring", "debugging", "alpha_mining"
    experience_summary: str = ""          # concise human-readable summary of the lesson
    key_decisions: list[str] = field(default_factory=list)   # important decision points made
    common_pitfalls: list[str] = field(default_factory=list) # known traps for this task type
    optimization_suggestions: list[str] = field(default_factory=list)  # actionable improvements
    success_indicators: list[str] = field(default_factory=list)  # signals that the task went well
    failure_indicators: list[str] = field(default_factory=list)  # signals that the task went poorly
    context_tags: list[str] = field(default_factory=list)  # e.g. ["python", "async", "refactor"]
    relevance_score: float = 0.0          # how useful this record was (updated on reuse)
    created_at: str = ""                  # ISO timestamp when first written
    updated_at: str = ""                  # ISO timestamp when last updated
    source_turn_id: str = ""              # which turn/session produced this record
    source_session_id: str = ""           # which session produced this record

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperienceRecord:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass(slots=True)
class ExperienceKnowledgeBase:
    """The full knowledge base, containing all experience records.

    Provides CRUD operations and task-type-based queries.
    """
    records: list[ExperienceRecord] = field(default_factory=list)
    version: int = 0                      # incremented on each write
    created_at: str = ""
    updated_at: str = ""

    # ── CRUD ──────────────────────────────────────────────────────────────

    def add(self, record: ExperienceRecord) -> str:
        """Add a new experience record and return its id."""
        if not record.id:
            record.id = f"exp_{int(time.time() * 1000)}"
        if not record.created_at:
            record.created_at = _now_iso()
        record.updated_at = _now_iso()
        self.records.append(record)
        self.version += 1
        self.updated_at = _now_iso()
        return record.id

    def get(self, record_id: str) -> ExperienceRecord | None:
        """Retrieve a record by id."""
        for r in self.records:
            if r.id == record_id:
                return r
        return None

    def update(self, record_id: str, updates: dict[str, Any]) -> bool:
        """Update fields of an existing record. Returns True if found."""
        record = self.get(record_id)
        if record is None:
            return False
        for k, v in updates.items():
            if k in ExperienceRecord.__dataclass_fields__ and k != "id":
                setattr(record, k, v)
        record.updated_at = _now_iso()
        self.version += 1
        self.updated_at = _now_iso()
        return True

    def remove(self, record_id: str) -> bool:
        """Remove a record by id. Returns True if found."""
        for i, r in enumerate(self.records):
            if r.id == record_id:
                self.records.pop(i)
                self.version += 1
                self.updated_at = _now_iso()
                return True
        return False

    # ── Query ─────────────────────────────────────────────────────────────

    def query_by_task_type(self, task_type: str) -> list[ExperienceRecord]:
        """Return all records matching a task type, sorted by relevance_score."""
        return sorted(
            [r for r in self.records if r.task_type == task_type],
            key=lambda r: r.relevance_score,
            reverse=True,
        )

    def query_by_tags(self, tags: list[str]) -> list[ExperienceRecord]:
        """Return records whose context_tags overlap with the given tags."""
        matching = []
        for r in self.records:
            overlap = len(set(r.context_tags) & set(tags))
            if overlap > 0:
                matching.append((overlap, r))
        matching.sort(key=lambda x: x[0], reverse=True)
        return [r for _, r in matching]

    def query_top_k(self, task_type: str, k: int = 5) -> list[ExperienceRecord]:
        """Return top-k most relevant records for a task type."""
        all_matching = self.query_by_task_type(task_type)
        return all_matching[:k]

    def boost_relevance(self, record_id: str, delta: float = 0.1) -> bool:
        """Increase a record's relevance score (positive feedback)."""
        record = self.get(record_id)
        if record is None:
            return False
        record.relevance_score += delta
        record.updated_at = _now_iso()
        self.version += 1
        return True

    # ── Serialization ─────────────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": self.version,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "records": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ExperienceKnowledgeBase:
        kb = cls()
        kb.version = data.get("version", 0)
        kb.created_at = data.get("created_at", "")
        kb.updated_at = data.get("updated_at", "")
        for r_data in data.get("records", []):
            kb.records.append(ExperienceRecord.from_dict(r_data))
        return kb

    def __len__(self) -> int:
        return len(self.records)


def _now_iso() -> str:
    """Return current UTC time in ISO format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()