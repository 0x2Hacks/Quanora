"""Research Experience domain model for quant-strategy knowledge persistence.

This extends the generic ExperienceKnowledgeBase with quant-specific fields
and project-level scoping.  Each ResearchExperience captures structured
insights from quant research — what worked, what didn't, and why — so that
future sessions on the same project can avoid repeating dead-end explorations
and build on proven patterns.

Storage is project-scoped (under <project_root>/.quanora/research_experience.json),
not user-scoped, because quant insights are tied to the instrument/universe/strategy
being researched, not to the researcher's generic preferences.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


class StrategyCategory(str, Enum):
    """Strategy classification categories."""
    MOMENTUM = "momentum"
    MEAN_REVERSION = "mean_reversion"
    BREAKOUT = "breakout"
    TREND_FOLLOWING = "trend_following"
    STATISTICAL_ARBITRAGE = "statistical_arbitrage"
    VOLATILITY = "volatility"
    SEASONALITY = "seasonality"
    MICROSTRUCTURE = "microstructure"
    MACHINE_LEARNING = "machine_learning"
    OTHER = "other"


class RegimeType(str, Enum):
    """Market regime at time of observation."""
    TRENDING_UP = "trending_up"
    TRENDING_DOWN = "trending_down"
    RANGING = "ranging"
    HIGH_VOLATILITY = "high_volatility"
    LOW_VOLATILITY = "low_volatility"
    UNKNOWN = "unknown"


class Outcome(str, Enum):
    """Research outcome classification."""
    SUCCESS = "success"           # Strategy meets performance criteria
    PARTIAL = "partial"           # Some promise but needs refinement
    FAILURE = "failure"           # Strategy does not work
    INCONCLUSIVE = "inconclusive" # Not enough evidence yet
    INSIGHT = "insight"           # No strategy tested, but gained understanding


@dataclass(slots=True)
class PerformanceMetrics:
    """Quantitative performance metrics from backtest or simulation."""
    sharpe: float | None = None
    sortino: float | None = None
    max_drawdown: float | None = None
    total_return: float | None = None
    win_rate: float | None = None
    profit_factor: float | None = None
    avg_trade_pnl: float | None = None
    num_trades: int | None = None
    fitness: float | None = None       # WorldQuant Brain fitness
    turnover: float | None = None      # WorldQuant Brain turnover
    custom: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> PerformanceMetrics:
        custom = d.pop("custom", {})
        return cls(**{k: v for k, v in d.items() if v is not None}, custom=custom)


@dataclass(slots=True)
class ResearchExperience:
    """A single quant-research experience entry.

    Captures the full context of a research finding: what was tested,
    on what instrument/universe, under what market conditions, and
    what was the outcome — including quantitative metrics when available.
    """
    # ── Identity ──
    id: str = ""                              # unique identifier
    project_id: str = ""                      # project/workspace identifier

    # ── What was tested ──
    strategy_name: str = ""                   # e.g. "dual_ma_crossover"
    strategy_category: str = ""               # StrategyCategory value
    expression: str = ""                      # alpha expression or strategy code snippet
    parameters: dict[str, Any] = field(default_factory=dict)  # key parameters

    # ── Where & When ──
    instrument: str = ""                      # e.g. "XAUUSD", "SPY"
    universe: str = ""                        # e.g. "TOP3000", "NASDAQ100"
    region: str = ""                          # e.g. "USA", "ASIAPAC"
    timeframe: str = ""                       # e.g. "M5", "H1", "daily"
    date_range: str = ""                      # e.g. "2024-01-01~2025-12-31"
    market_regime: str = ""                   # RegimeType value

    # ── Outcome ──
    outcome: str = ""                         # Outcome value
    performance: dict[str, Any] = field(default_factory=dict)  # PerformanceMetrics as dict

    # ── Lessons ──
    what_worked: str = ""                     # What worked well
    what_failed: str = ""                     # What didn't work and why
    key_insight: str = ""                     # Core takeaway in one sentence
    pitfalls: list[str] = field(default_factory=list)         # Pitfalls encountered
    next_steps: list[str] = field(default_factory=list)       # Suggested follow-up

    # ── Provenance ──
    source_session_id: str = ""
    source_turn_id: str = ""
    tags: list[str] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResearchExperience:
        # Filter out unknown fields for forward-compatibility
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in d.items() if k in valid_keys}
        return cls(**filtered)


@dataclass
class ResearchExperienceBook:
    """Collection of research experiences for a project.

    Supports querying by strategy category, instrument, outcome, tags,
    and full-text search on insights and what_worked/what_failed.
    """
    project_id: str = ""
    records: list[ResearchExperience] = field(default_factory=list)
    version: int = 1

    def __len__(self) -> int:
        return len(self.records)

    def add(self, record: ResearchExperience) -> str:
        """Add a record, returning its ID."""
        if not record.id:
            import uuid
            record.id = f"re_{uuid.uuid4().hex[:12]}"
        record.project_id = self.project_id
        self.records.append(record)
        return record.id

    def query_by_strategy(self, category: str) -> list[ResearchExperience]:
        """Return records matching a strategy category."""
        return [r for r in self.records if r.strategy_category == category]

    def query_by_instrument(self, instrument: str) -> list[ResearchExperience]:
        """Return records for a specific instrument."""
        inst_lower = instrument.lower()
        return [r for r in self.records if r.instrument.lower() == inst_lower]

    def query_by_outcome(self, outcome: str) -> list[ResearchExperience]:
        """Return records with a specific outcome."""
        return [r for r in self.records if r.outcome == outcome]

    def query_by_tags(self, tags: list[str]) -> list[ResearchExperience]:
        """Return records that have ALL specified tags."""
        tag_set = set(tags)
        return [r for r in self.records if tag_set.issubset(set(r.tags))]

    def query_top_insights(self, k: int = 5) -> list[ResearchExperience]:
        """Return the k most recent records with key_insight populated."""
        with_insight = [r for r in self.records if r.key_insight]
        with_insight.sort(key=lambda r: r.created_at, reverse=True)
        return with_insight[:k]

    def query_successes(self, k: int = 5) -> list[ResearchExperience]:
        """Return recent successful experiences."""
        successes = [r for r in self.records if r.outcome == Outcome.SUCCESS.value]
        successes.sort(key=lambda r: r.created_at, reverse=True)
        return successes[:k]

    def query_failures(self, k: int = 5) -> list[ResearchExperience]:
        """Return recent failure experiences (to avoid repeating)."""
        failures = [r for r in self.records if r.outcome == Outcome.FAILURE.value]
        failures.sort(key=lambda r: r.created_at, reverse=True)
        return failures[:k]

    def search(self, keyword: str, k: int = 10) -> list[ResearchExperience]:
        """Full-text search across key text fields."""
        kw = keyword.lower()
        results = []
        for r in self.records:
            text = " ".join([
                r.strategy_name, r.expression, r.what_worked,
                r.what_failed, r.key_insight,
                " ".join(r.pitfalls), " ".join(r.next_steps),
            ]).lower()
            if kw in text:
                results.append(r)
        results.sort(key=lambda r: r.created_at, reverse=True)
        return results[:k]

    def get_summary_stats(self) -> dict[str, Any]:
        """Return aggregate statistics about the experience book."""
        total = len(self.records)
        if total == 0:
            return {"total": 0}

        by_outcome: dict[str, int] = {}
        by_category: dict[str, int] = {}
        by_instrument: dict[str, int] = {}

        for r in self.records:
            by_outcome[r.outcome] = by_outcome.get(r.outcome, 0) + 1
            by_category[r.strategy_category] = by_category.get(r.strategy_category, 0) + 1
            by_instrument[r.instrument] = by_instrument.get(r.instrument, 0) + 1

        return {
            "total": total,
            "by_outcome": by_outcome,
            "by_strategy_category": by_category,
            "by_instrument": by_instrument,
        }

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "version": self.version,
            "records": [r.to_dict() for r in self.records],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> ResearchExperienceBook:
        records = [ResearchExperience.from_dict(rd) for rd in d.get("records", [])]
        return cls(
            project_id=d.get("project_id", ""),
            records=records,
            version=d.get("version", 1),
        )
