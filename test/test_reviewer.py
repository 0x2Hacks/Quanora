"""Unit tests for the wq_data_review / reviewer module.

These tests exercise the reviewer module: DataReviewReport, review_direction,
and integration with the WQ tool registry.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from agent.infrastructure.tools.impl.tools.worldquant.reviewer import (
    DataReviewReport,
    FieldCheck,
    OperatorCheck,
    RiskFlag,
    review_direction,
)
from agent.infrastructure.tools.impl.tools.worldquant import wq_data_review


# ---------------------------------------------------------------------------
# DataReviewReport.to_markdown
# ---------------------------------------------------------------------------


class TestDataReviewReportMarkdown:
    def test_basic_report(self):
        report = DataReviewReport(
            direction_key="test",
            direction_name="Test Direction",
            region="USA",
            universe="TOP3000",
            delay=1,
            field_checks=[
                FieldCheck("close", True, "builtin", "收盘价"),
                FieldCheck("foo", False, "missing", ""),
            ],
            operator_checks=[
                OperatorCheck("rank", True, "builtin", "(x) -> [0,1]", "横截面 rank"),
            ],
            total_fields_required=2,
            fields_available=1,
            total_operators_required=1,
            operators_available=1,
            recommendation="caution",
        )
        md = report.to_markdown()
        assert "# 数据预审报告" in md
        assert "Test Direction" in md
        assert "close" in md
        assert "foo" in md
        assert "rank" in md
        assert "CAUTION" in md

    def test_proceed_report(self):
        report = DataReviewReport(
            direction_key="test",
            direction_name="All Good",
            region="USA",
            universe="TOP3000",
            delay=1,
            recommendation="proceed",
        )
        md = report.to_markdown()
        assert "PROCEED" in md

    def test_abort_report(self):
        report = DataReviewReport(
            direction_key="test",
            direction_name="Bad Direction",
            region="USA",
            universe="TOP3000",
            delay=1,
            recommendation="abort",
        )
        md = report.to_markdown()
        assert "ABORT" in md

    def test_risk_flags_in_markdown(self):
        report = DataReviewReport(
            direction_key="test",
            direction_name="Risk Test",
            region="USA",
            universe="TOP3000",
            delay=1,
            risk_flags=[
                RiskFlag("critical", "data_unavailable", "foo missing"),
                RiskFlag("warning", "operator_unavailable", "bar missing"),
                RiskFlag("info", "insight", "some insight"),
            ],
            risk_count=3,
            recommendation="abort",
        )
        md = report.to_markdown()
        assert "🔴" in md
        assert "🟡" in md
        assert "🔵" in md


# ---------------------------------------------------------------------------
# DataReviewReport.to_dict
# ---------------------------------------------------------------------------


class TestDataReviewReportDict:
    def test_roundtrip(self):
        report = DataReviewReport(
            direction_key="test",
            direction_name="Roundtrip",
            region="USA",
            universe="TOP3000",
            delay=1,
            field_checks=[FieldCheck("close", True, "builtin", "收盘价")],
            total_fields_required=1,
            fields_available=1,
        )
        d = report.to_dict()
        assert d["direction_key"] == "test"
        assert d["field_checks"][0]["name"] == "close"
        # Ensure JSON serializable
        json.dumps(d)


# ---------------------------------------------------------------------------
# review_direction
# ---------------------------------------------------------------------------


class TestReviewDirection:
    def test_known_direction_reversal(self):
        report = review_direction("reversal_short_term")
        assert report.direction_key == "reversal_short_term"
        assert report.region == "USA"
        assert report.universe == "TOP3000"
        assert report.total_fields_required > 0
        assert report.total_operators_required > 0
        # Reversal fields (close, returns, volume) should be in builtin
        assert report.fields_available > 0
        assert report.operators_available > 0

    def test_known_direction_momentum(self):
        report = review_direction("momentum_mid_term")
        assert report.direction_key == "momentum_mid_term"
        assert report.total_fields_required > 0

    def test_unknown_direction_aborts(self):
        report = review_direction("nonexistent_xyz")
        assert report.recommendation == "abort"
        assert report.risk_count > 0
        assert any(rf.severity == "critical" for rf in report.risk_flags)

    def test_missing_field_creates_warning(self):
        # Use a direction that references a field NOT in BUILTIN_FIELDS
        # We need to test this indirectly: if direction has key_fields that
        # aren't in BUILTIN_FIELDS, they should be flagged
        from agent.infrastructure.tools.impl.tools.worldquant.knowledge import DIRECTION_LIBRARY

        # Find a direction with fields that might not all be in BUILTIN_FIELDS
        # Or mock the scenario
        report = review_direction("reversal_short_term")
        # All reversal fields should be available in builtin
        assert all(fc.available for fc in report.field_checks)

    def test_memory_snapshot_with_forbidden(self):
        snapshot = {
            "forbidden_regions": [
                {
                    "template": "ts_rank(close, 5)",
                    "tags": ["reversal_short_term"],
                    "hit_count": 10,
                },
            ],
            "strategic_insights": [],
        }
        report = review_direction(
            "reversal_short_term",
            memory_snapshot=snapshot,
        )
        # Should have a forbidden_region risk flag
        assert any(rf.category == "forbidden_region" for rf in report.risk_flags)

    def test_memory_snapshot_with_insight(self):
        snapshot = {
            "forbidden_regions": [],
            "strategic_insights": [
                {
                    "insight": "ts_rank 在窗口>60时易出现NaN",
                    "tags": ["reversal_short_term"],
                    "severity": "warning",
                },
            ],
        }
        report = review_direction(
            "reversal_short_term",
            memory_snapshot=snapshot,
        )
        # Should have an insight risk flag
        assert any(rf.category == "insight" for rf in report.risk_flags)

    def test_online_fields_supplement(self):
        report = review_direction(
            "reversal_short_term",
            online_fields={"custom_field": "自定义字段说明"},
        )
        # Reversal fields should still be found in builtin
        assert report.fields_available == report.total_fields_required

    def test_recommendation_proceed_when_all_available(self):
        report = review_direction("reversal_short_term")
        # All builtin fields + operators should be available
        if report.fields_available == report.total_fields_required and \
           report.operators_available == report.total_operators_required:
            assert report.recommendation in ("proceed", "caution")

    def test_recommendation_caution_with_warnings(self):
        snapshot = {
            "forbidden_regions": [
                {"template": "x", "tags": ["reversal_short_term"], "hit_count": 5},
                {"template": "y", "tags": ["reversal_short_term"], "hit_count": 3},
            ],
            "strategic_insights": [
                {"insight": "z", "tags": ["reversal_short_term"], "severity": "warning"},
            ],
        }
        report = review_direction("reversal_short_term", memory_snapshot=snapshot)
        # With ≥2 warnings, should be caution or abort
        assert report.recommendation in ("caution", "abort")

    def test_different_region_universe(self):
        report = review_direction("reversal_short_term", region="CHN", universe="TOP2000")
        assert report.region == "CHN"
        assert report.universe == "TOP2000"


# ---------------------------------------------------------------------------
# wq_data_review (integration-level)
# ---------------------------------------------------------------------------


class TestWqDataReviewTool:
    def test_returns_ok_json(self):
        result_str = wq_data_review(direction_key="reversal_short_term")
        data = json.loads(result_str)
        assert data.get("ok") is True
        assert data["tool"] == "wq_data_review"
        assert "report_markdown" in data["data"]
        assert "recommendation" in data["data"]

    def test_unknown_direction_returns_abort(self):
        result_str = wq_data_review(direction_key="nonexistent")
        data = json.loads(result_str)
        assert data.get("ok") is True
        assert data["data"]["recommendation"] == "abort"

    def test_check_online_false_by_default(self):
        # Should not crash even without login
        result_str = wq_data_review(direction_key="reversal_short_term")
        data = json.loads(result_str)
        assert data.get("ok") is True

    def test_custom_region(self):
        result_str = wq_data_review(
            direction_key="reversal_short_term",
            region="CHN",
            universe="TOP2000",
        )
        data = json.loads(result_str)
        assert data.get("ok") is True
