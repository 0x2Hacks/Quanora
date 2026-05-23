"""JSON-file-based repository for persisting the Experience Knowledge Base.

The knowledge base is stored as a single JSON file under the session data
directory.  This provides simple, human-readable persistence with atomic
write via temp-file + rename.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from agent.domain.knowledge_base import ExperienceKnowledgeBase, ExperienceRecord


class KnowledgeBaseRepository:
    """File-based repository that loads/saves an ExperienceKnowledgeBase to JSON."""

    def __init__(self, file_path: str | Path | None = None):
        if file_path is None:
            # Default location: ~/.quanora/knowledge_base.json
            home = Path.home()
            quanora_dir = home / ".quanora"
            quanora_dir.mkdir(parents=True, exist_ok=True)
            file_path = quanora_dir / "knowledge_base.json"
        self._path = Path(file_path)

    # ── Load / Save ───────────────────────────────────────────────────────

    def load(self) -> ExperienceKnowledgeBase:
        """Load the knowledge base from disk.  Returns an empty KB if file missing."""
        if not self._path.exists():
            return ExperienceKnowledgeBase()
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return ExperienceKnowledgeBase.from_dict(data)
        except (json.JSONDecodeError, KeyError, TypeError):
            # Corrupted file — start fresh
            return ExperienceKnowledgeBase()

    def save(self, kb: ExperienceKnowledgeBase) -> None:
        """Save the knowledge base to disk with atomic write."""
        data = kb.to_dict()
        tmp_path = self._path.with_suffix(".tmp")
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_path, self._path)

    # ── Convenience methods ───────────────────────────────────────────────

    def add_record(self, record: ExperienceRecord) -> str:
        """Add a record and persist immediately."""
        kb = self.load()
        record_id = kb.add(record)
        self.save(kb)
        return record_id

    def update_record(self, record_id: str, updates: dict[str, Any]) -> bool:
        """Update a record and persist immediately."""
        kb = self.load()
        ok = kb.update(record_id, updates)
        if ok:
            self.save(kb)
        return ok

    def remove_record(self, record_id: str) -> bool:
        """Remove a record and persist immediately."""
        kb = self.load()
        ok = kb.remove(record_id)
        if ok:
            self.save(kb)
        return ok

    def query_by_task_type(self, task_type: str) -> list[ExperienceRecord]:
        """Load KB and query by task type."""
        kb = self.load()
        return kb.query_by_task_type(task_type)

    def query_top_k(self, task_type: str, k: int = 5) -> list[ExperienceRecord]:
        """Load KB and return top-k records for a task type."""
        kb = self.load()
        return kb.query_top_k(task_type, k)

    def boost_relevance(self, record_id: str, delta: float = 0.1) -> bool:
        """Boost a record's relevance score and persist."""
        kb = self.load()
        ok = kb.boost_relevance(record_id, delta)
        if ok:
            self.save(kb)
        return ok