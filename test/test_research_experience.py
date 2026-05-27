"""Tests for Research Experience domain model and repository."""

import json
import os
import tempfile
from pathlib import Path

import pytest

from agent.domain.research_experience import (
    Outcome,
    PerformanceMetrics,
    RegimeType,
    ResearchExperience,
    ResearchExperienceBook,
    StrategyCategory,
)
from agent.infrastructure.persistence.research_experience_repository import (
    ResearchExperienceRepository,
)


# ── PerformanceMetrics ──────────────────────────────────────────────

class TestPerformanceMetrics:
    def test_defaults(self):
        m = PerformanceMetrics()
        assert m.sharpe is None
        assert m.max_drawdown is None
        assert m.custom == {}

    def test_construction(self):
        m = PerformanceMetrics(sharpe=1.5, max_drawdown=0.12, win_rate=0.55)
        assert m.sharpe == 1.5
        assert m.max_drawdown == 0.12
        assert m.win_rate == 0.55

    def test_to_dict(self):
        m = PerformanceMetrics(sharpe=1.5, custom={"calmar": 2.0})
        d = m.to_dict()
        assert d["sharpe"] == 1.5
        assert d["custom"]["calmar"] == 2.0

    def test_from_dict(self):
        data = {"sharpe": 1.5, "max_drawdown": 0.12, "custom": {"calmar": 2.0}}
        m = PerformanceMetrics.from_dict(data)
        assert m.sharpe == 1.5
        assert m.custom["calmar"] == 2.0


# ── ResearchExperience ──────────────────────────────────────────────

class TestResearchExperience:
    def test_defaults(self):
        r = ResearchExperience()
        assert r.id == ""
        assert r.strategy_name == ""
        assert r.strategy_category == ""
        assert r.outcome == ""
        assert r.key_insight == ""
        assert r.pitfalls == []
        assert r.performance == {}

    def test_construction(self):
        r = ResearchExperience(
            strategy_name="dual_ma",
            strategy_category="trend_following",
            instrument="XAUUSD",
            outcome="failure",
            key_insight="双均线在XAUUSD M5上频繁假突破",
            performance={"sharpe": -0.3, "win_rate": 0.35},
        )
        assert r.strategy_name == "dual_ma"
        assert r.outcome == "failure"
        assert r.performance["sharpe"] == -0.3

    def test_to_dict(self):
        r = ResearchExperience(
            strategy_name="rsi_reversal",
            pitfalls=["过拟合", "滑点"],
            tags=["xauusd", "mean_reversion"],
        )
        d = r.to_dict()
        assert d["strategy_name"] == "rsi_reversal"
        assert d["pitfalls"] == ["过拟合", "滑点"]
        assert d["tags"] == ["xauusd", "mean_reversion"]

    def test_from_dict(self):
        data = {
            "id": "re_abc123",
            "strategy_name": "test",
            "outcome": "success",
            "pitfalls": ["a"],
            "extra_field": "should be ignored",
        }
        r = ResearchExperience.from_dict(data)
        assert r.id == "re_abc123"
        assert r.outcome == "success"
        assert not hasattr(r, "extra_field")

    def test_from_dict_handles_missing_fields(self):
        data = {"strategy_name": "minimal"}
        r = ResearchExperience.from_dict(data)
        assert r.strategy_name == "minimal"
        assert r.pitfalls == []


# ── ResearchExperienceBook ──────────────────────────────────────────

class TestResearchExperienceBook:
    def _make_record(self, **kwargs) -> ResearchExperience:
        defaults = {
            "strategy_name": "test_strategy",
            "strategy_category": "momentum",
            "instrument": "XAUUSD",
            "outcome": "success",
            "key_insight": "Test insight",
            "tags": ["test"],
        }
        defaults.update(kwargs)
        return ResearchExperience(**defaults)

    def test_empty_book(self):
        book = ResearchExperienceBook(project_id="test_proj")
        assert len(book) == 0
        assert book.project_id == "test_proj"

    def test_add_record(self):
        book = ResearchExperienceBook(project_id="test_proj")
        r = self._make_record()
        record_id = book.add(r)
        assert record_id.startswith("re_")
        assert len(book) == 1
        assert r.project_id == "test_proj"

    def test_add_with_custom_id(self):
        book = ResearchExperienceBook()
        r = self._make_record(id="custom_id")
        record_id = book.add(r)
        assert record_id == "custom_id"

    def test_query_by_strategy(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(strategy_category="momentum"))
        book.add(self._make_record(strategy_category="mean_reversion"))
        book.add(self._make_record(strategy_category="momentum"))

        results = book.query_by_strategy("momentum")
        assert len(results) == 2
        assert all(r.strategy_category == "momentum" for r in results)

    def test_query_by_instrument(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(instrument="XAUUSD"))
        book.add(self._make_record(instrument="SPY"))

        results = book.query_by_instrument("xauusd")  # case-insensitive
        assert len(results) == 1

    def test_query_by_outcome(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(outcome="success"))
        book.add(self._make_record(outcome="failure"))
        book.add(self._make_record(outcome="success"))

        results = book.query_by_outcome("success")
        assert len(results) == 2

    def test_query_by_tags(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(tags=["xauusd", "momentum"]))
        book.add(self._make_record(tags=["xauusd", "mean_reversion"]))
        book.add(self._make_record(tags=["spy", "momentum"]))

        # Must match ALL tags
        results = book.query_by_tags(["xauusd", "momentum"])
        assert len(results) == 1

    def test_query_top_insights(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(key_insight="insight1"))
        book.add(self._make_record(key_insight=""))  # no insight
        book.add(self._make_record(key_insight="insight2"))

        results = book.query_top_insights(k=5)
        assert len(results) == 2

    def test_query_successes(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(outcome="success", strategy_name="s1"))
        book.add(self._make_record(outcome="failure", strategy_name="s2"))

        results = book.query_successes(k=5)
        assert len(results) == 1
        assert results[0].strategy_name == "s1"

    def test_query_failures(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(outcome="failure", strategy_name="f1"))
        book.add(self._make_record(outcome="success", strategy_name="s1"))

        results = book.query_failures(k=5)
        assert len(results) == 1
        assert results[0].strategy_name == "f1"

    def test_search(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(
            strategy_name="dual_ma",
            key_insight="双均线在震荡市表现差",
        ))
        book.add(self._make_record(
            strategy_name="rsi_reversal",
            key_insight="RSI超卖反转有效",
        ))

        results = book.search("双均线")
        assert len(results) == 1
        assert results[0].strategy_name == "dual_ma"

    def test_search_case_insensitive(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(strategy_name="Dual_MA"))
        results = book.search("dual_ma")
        assert len(results) == 1

    def test_get_summary_stats_empty(self):
        book = ResearchExperienceBook()
        stats = book.get_summary_stats()
        assert stats["total"] == 0

    def test_get_summary_stats(self):
        book = ResearchExperienceBook()
        book.add(self._make_record(outcome="success", strategy_category="momentum", instrument="XAUUSD"))
        book.add(self._make_record(outcome="failure", strategy_category="momentum", instrument="SPY"))

        stats = book.get_summary_stats()
        assert stats["total"] == 2
        assert stats["by_outcome"]["success"] == 1
        assert stats["by_outcome"]["failure"] == 1
        assert stats["by_strategy_category"]["momentum"] == 2
        assert stats["by_instrument"]["XAUUSD"] == 1

    def test_to_dict_and_from_dict_roundtrip(self):
        book = ResearchExperienceBook(project_id="test_proj")
        book.add(self._make_record(
            strategy_name="roundtrip_test",
            performance={"sharpe": 1.5},
            pitfalls=["过拟合"],
        ))

        data = book.to_dict()
        json_str = json.dumps(data, ensure_ascii=False)  # must be JSON-serializable
        data2 = json.loads(json_str)
        book2 = ResearchExperienceBook.from_dict(data2)

        assert len(book2) == 1
        assert book2.project_id == "test_proj"
        assert book2.records[0].strategy_name == "roundtrip_test"
        assert book2.records[0].performance["sharpe"] == 1.5
        assert book2.records[0].pitfalls == ["过拟合"]


# ── ResearchExperienceRepository ────────────────────────────────────

class TestResearchExperienceRepository:
    def test_load_empty(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        book = repo.load()
        assert len(book) == 0
        assert book.project_id == tmp_path.name

    def test_save_and_load(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        book = ResearchExperienceBook(project_id=tmp_path.name)
        book.add(ResearchExperience(
            strategy_name="save_test",
            outcome="success",
            key_insight="Save/load works",
        ))
        repo.save(book)

        # Reload
        book2 = repo.load()
        assert len(book2) == 1
        assert book2.records[0].strategy_name == "save_test"

    def test_creates_quanora_dir(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        book = ResearchExperienceBook(project_id="test")
        repo.save(book)
        assert (tmp_path / ".quanora" / "research_experience.json").exists()

    def test_add_record_convenience(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        record_id = repo.add_record(ResearchExperience(
            strategy_name="convenience_test",
            outcome="partial",
        ))
        assert record_id.startswith("re_")

        book = repo.load()
        assert len(book) == 1
        assert book.records[0].strategy_name == "convenience_test"

    def test_get_top_insights(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        repo.add_record(ResearchExperience(key_insight="insight1", outcome="success"))
        repo.add_record(ResearchExperience(key_insight="insight2", outcome="failure"))

        insights = repo.get_top_insights(k=5)
        assert len(insights) == 2

    def test_get_successes(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        repo.add_record(ResearchExperience(outcome="success", strategy_name="s1"))
        repo.add_record(ResearchExperience(outcome="failure", strategy_name="f1"))

        successes = repo.get_successes(k=5)
        assert len(successes) == 1
        assert successes[0].strategy_name == "s1"

    def test_get_failures(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        repo.add_record(ResearchExperience(outcome="failure", strategy_name="f1"))
        repo.add_record(ResearchExperience(outcome="success", strategy_name="s1"))

        failures = repo.get_failures(k=5)
        assert len(failures) == 1
        assert failures[0].strategy_name == "f1"

    def test_get_summary(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        repo.add_record(ResearchExperience(
            outcome="success", strategy_category="momentum", instrument="XAUUSD"
        ))

        stats = repo.get_summary()
        assert stats["total"] == 1
        assert stats["by_outcome"]["success"] == 1

    def test_path_property(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        assert repo.path == tmp_path / ".quanora" / "research_experience.json"

    def test_exists(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        assert not repo.exists()
        repo.save(ResearchExperienceBook())
        assert repo.exists()

    def test_handles_corrupted_file(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        # Write corrupted JSON
        repo._path.parent.mkdir(parents=True, exist_ok=True)
        repo._path.write_text("{invalid json")
        book = repo.load()
        assert len(book) == 0  # graceful fallback

    def test_unicode_roundtrip(self, tmp_path):
        repo = ResearchExperienceRepository(tmp_path)
        repo.add_record(ResearchExperience(
            strategy_name="双均线交叉",
            key_insight="在震荡市频繁假突破",
            pitfalls=["过拟合风险", "滑点影响大"],
        ))

        book = repo.load()
        assert book.records[0].strategy_name == "双均线交叉"
        assert book.records[0].pitfalls == ["过拟合风险", "滑点影响大"]


# ── Research Experience Tools ───────────────────────────────────────

class TestResearchExperienceTools:
    """Test the tool functions directly."""

    def _parse_result(self, result_str: str) -> dict:
        """Parse tool_ok / tool_error JSON result."""
        return json.loads(result_str)

    def test_record_and_query(self, tmp_path, monkeypatch):
        from agent.infrastructure.config import Config
        monkeypatch.setattr(Config, "WORKSPACE_ROOT", str(tmp_path))

        from agent.infrastructure.tools.impl.tools.research_experience import (
            record_research_experience,
            query_research_experience,
            get_research_summary,
        )

        # Record an experience
        result = self._parse_result(
            record_research_experience(
                strategy_name="dual_ma_crossover",
                strategy_category="trend_following",
                instrument="XAUUSD",
                outcome="failure",
                key_insight="双均线在M5上假突破多",
                what_failed="短期均线交叉信号不可靠",
                tags='["xauusd","trend_following"]',
                performance='{"sharpe":-0.3}',
            )
        )
        assert result["ok"] is True
        assert "已记录" in result["data"]

        # Query it back
        result2 = self._parse_result(query_research_experience(instrument="XAUUSD"))
        assert result2["ok"] is True
        assert "dual_ma_crossover" in result2["data"]

        # Get summary
        result3 = self._parse_result(get_research_summary())
        assert result3["ok"] is True
        assert "1 条" in result3["data"]

    def test_query_empty(self, tmp_path, monkeypatch):
        from agent.infrastructure.config import Config
        monkeypatch.setattr(Config, "WORKSPACE_ROOT", str(tmp_path))

        from agent.infrastructure.tools.impl.tools.research_experience import (
            query_research_experience,
        )

        result = self._parse_result(query_research_experience())
        assert result["ok"] is True
        assert "为空" in result["data"]

    def test_invalid_outcome(self, tmp_path, monkeypatch):
        from agent.infrastructure.config import Config
        monkeypatch.setattr(Config, "WORKSPACE_ROOT", str(tmp_path))

        from agent.infrastructure.tools.impl.tools.research_experience import (
            record_research_experience,
        )

        result = self._parse_result(
            record_research_experience(
                strategy_name="test",
                outcome="invalid_outcome",
            )
        )
        assert result["ok"] is False
        assert "无效" in result["error"]

    def test_invalid_strategy_category(self, tmp_path, monkeypatch):
        from agent.infrastructure.config import Config
        monkeypatch.setattr(Config, "WORKSPACE_ROOT", str(tmp_path))

        from agent.infrastructure.tools.impl.tools.research_experience import (
            record_research_experience,
        )

        result = self._parse_result(
            record_research_experience(
                strategy_name="test",
                strategy_category="invalid_cat",
            )
        )
        assert result["ok"] is False
        assert "无效" in result["error"]

    def test_keyword_search(self, tmp_path, monkeypatch):
        from agent.infrastructure.config import Config
        monkeypatch.setattr(Config, "WORKSPACE_ROOT", str(tmp_path))

        from agent.infrastructure.tools.impl.tools.research_experience import (
            record_research_experience,
            query_research_experience,
        )

        record_research_experience(
            strategy_name="rsi_divergence",
            instrument="XAUUSD",
            outcome="partial",
            key_insight="RSI背离在趋势市需要确认",
        )

        result = self._parse_result(query_research_experience(keyword="RSI背离"))
        assert result["ok"] is True
        assert "rsi_divergence" in result["data"]

    def test_no_project_root(self, monkeypatch):
        from agent.infrastructure.config import Config
        monkeypatch.setattr(Config, "WORKSPACE_ROOT", None)

        from agent.infrastructure.tools.impl.tools.research_experience import (
            record_research_experience,
        )

        result = self._parse_result(record_research_experience(strategy_name="test"))
        assert result["ok"] is False
        assert "无法确定" in result["error"]
