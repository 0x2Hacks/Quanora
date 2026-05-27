"""Research Experience persistence repository.

Stores ResearchExperienceBook at the **project level** under
<project_root>/.quanora/research_experience.json.

This is intentionally separate from the user-level KnowledgeBaseRepository
because quant research insights are tied to the project's instrument/universe/
strategy context, not to the researcher's generic task preferences.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from agent.domain.research_experience import ResearchExperienceBook, ResearchExperience

logger = logging.getLogger(__name__)


class ResearchExperienceRepository:
    """Project-scoped repository for quant research experiences.

    Usage::

        repo = ResearchExperienceRepository(project_root="/path/to/project")
        book = repo.load()
        book.add(record)
        repo.save(book)
    """

    FILENAME = "research_experience.json"

    def __init__(self, project_root: str | Path):
        self._project_root = Path(project_root)
        self._path = self._project_root / ".quanora" / self.FILENAME

    # ── Read ──

    def load(self) -> ResearchExperienceBook:
        """Load the experience book from disk.

        Returns an empty book if the file doesn't exist yet.
        """
        if not self._path.exists():
            logger.debug("No research experience file at %s — returning empty book", self._path)
            return ResearchExperienceBook(
                project_id=self._project_root.name,
            )

        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)
            book = ResearchExperienceBook.from_dict(data)
            return book
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            logger.warning("Failed to parse %s: %s — returning empty book", self._path, exc)
            return ResearchExperienceBook(
                project_id=self._project_root.name,
            )

    # ── Write ──

    def save(self, book: ResearchExperienceBook) -> None:
        """Persist the experience book to disk.

        Creates the .quanora directory if it doesn't exist.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)

        # Ensure project_id is set
        if not book.project_id:
            book.project_id = self._project_root.name

        data = book.to_dict()
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

        logger.info("Saved %d research experience records to %s", len(book), self._path)

    # ── Convenience: add a single record ──

    def add_record(self, record: ResearchExperience) -> str:
        """Load → add → save in one call. Returns the record ID."""
        book = self.load()
        record_id = book.add(record)
        self.save(book)
        return record_id

    # ── Convenience: query shortcuts ──

    def get_top_insights(self, k: int = 5) -> list[ResearchExperience]:
        """Get the k most recent insights."""
        return self.load().query_top_insights(k=k)

    def get_successes(self, k: int = 5) -> list[ResearchExperience]:
        """Get recent successful strategies."""
        return self.load().query_successes(k=k)

    def get_failures(self, k: int = 5) -> list[ResearchExperience]:
        """Get recent failed strategies (to avoid repeating)."""
        return self.load().query_failures(k=k)

    def get_summary(self) -> dict:
        """Get aggregate statistics."""
        return self.load().get_summary_stats()

    # ── Path accessor ──

    @property
    def path(self) -> Path:
        return self._path

    def exists(self) -> bool:
        return self._path.exists()
