"""Tests for Feature 1: Token/time usage tracking model and events."""

import pytest
from agent.domain.events import (
    LLMUsageRecord,
    ToolCallUsageRecord,
    TurnCostReport,
    TurnCompletedEvent,
    TurnFailedEvent,
    TurnCancelledEvent,
)


# ── LLMUsageRecord ──────────────────────────────────────────────────────

class TestLLMUsageRecord:
    def test_defaults(self):
        r = LLMUsageRecord()
        assert r.prompt_tokens == 0
        assert r.completion_tokens == 0
        assert r.total_tokens == 0
        assert r.latency_seconds == 0.0
        assert r.model == ""

    def test_construction(self):
        r = LLMUsageRecord(prompt_tokens=100, completion_tokens=50, total_tokens=150,
                           latency_seconds=1.5, model="gpt-4o")
        assert r.prompt_tokens == 100
        assert r.completion_tokens == 50
        assert r.total_tokens == 150


# ── ToolCallUsageRecord ──────────────────────────────────────────────────

class TestToolCallUsageRecord:
    def test_defaults(self):
        r = ToolCallUsageRecord()
        assert r.tool_name == ""
        assert r.call_id == ""
        assert r.wall_seconds == 0.0
        assert r.input_chars == 0
        assert r.output_chars == 0

    def test_construction(self):
        r = ToolCallUsageRecord(tool_name="read_file", call_id="call_123",
                                wall_seconds=2.5, input_chars=100, output_chars=500)
        assert r.tool_name == "read_file"
        assert r.wall_seconds == 2.5


# ── TurnCostReport ───────────────────────────────────────────────────────

class TestTurnCostReport:
    def test_defaults(self):
        report = TurnCostReport()
        assert report.llm_calls == []
        assert report.tool_calls == []
        assert report.total_prompt_tokens == 0
        assert report.total_completion_tokens == 0
        assert report.total_tokens == 0
        assert report.total_llm_latency_seconds == 0.0
        assert report.total_tool_wall_seconds == 0.0
        assert report.turn_wall_seconds == 0.0
        assert report.num_llm_calls == 0
        assert report.num_tool_calls == 0

    def test_accumulate_llm(self):
        report = TurnCostReport()
        r1 = LLMUsageRecord(prompt_tokens=100, completion_tokens=50, total_tokens=150,
                            latency_seconds=1.5, model="gpt-4o")
        report.accumulate_llm(r1)
        assert report.total_prompt_tokens == 100
        assert report.total_completion_tokens == 50
        assert report.total_tokens == 150
        assert report.total_llm_latency_seconds == 1.5
        assert report.num_llm_calls == 1
        assert len(report.llm_calls) == 1

    def test_accumulate_multiple_llm_calls(self):
        report = TurnCostReport()
        r1 = LLMUsageRecord(prompt_tokens=100, completion_tokens=50, total_tokens=150,
                            latency_seconds=1.0)
        r2 = LLMUsageRecord(prompt_tokens=200, completion_tokens=80, total_tokens=280,
                            latency_seconds=2.0)
        report.accumulate_llm(r1)
        report.accumulate_llm(r2)
        assert report.total_prompt_tokens == 300
        assert report.total_completion_tokens == 130
        assert report.total_tokens == 430
        assert report.total_llm_latency_seconds == 3.0
        assert report.num_llm_calls == 2

    def test_accumulate_tool(self):
        report = TurnCostReport()
        t1 = ToolCallUsageRecord(tool_name="read_file", wall_seconds=2.5, output_chars=500)
        report.accumulate_tool(t1)
        assert report.total_tool_wall_seconds == 2.5
        assert report.num_tool_calls == 1
        assert len(report.tool_calls) == 1

    def test_accumulate_multiple_tool_calls(self):
        report = TurnCostReport()
        t1 = ToolCallUsageRecord(tool_name="read_file", wall_seconds=2.5, output_chars=500)
        t2 = ToolCallUsageRecord(tool_name="bash", wall_seconds=1.0, output_chars=200)
        report.accumulate_tool(t1)
        report.accumulate_tool(t2)
        assert report.total_tool_wall_seconds == 3.5
        assert report.num_tool_calls == 2

    def test_summarize(self):
        report = TurnCostReport()
        report.accumulate_llm(LLMUsageRecord(prompt_tokens=100, completion_tokens=50,
                                             total_tokens=150, latency_seconds=1.5, model="gpt-4o"))
        report.accumulate_tool(ToolCallUsageRecord(tool_name="read_file", wall_seconds=2.5,
                                                   output_chars=500))
        report.turn_wall_seconds = 5.0
        summary = report.summarize()
        assert summary["total_prompt_tokens"] == 100
        assert summary["total_completion_tokens"] == 50
        assert summary["total_tokens"] == 150
        assert summary["total_llm_latency_s"] == 1.5
        assert summary["total_tool_wall_s"] == 2.5
        assert summary["turn_wall_s"] == 5.0
        assert summary["num_llm_calls"] == 1
        assert summary["num_tool_calls"] == 1
        assert len(summary["llm_details"]) == 1
        assert len(summary["tool_details"]) == 1
        assert summary["llm_details"][0]["model"] == "gpt-4o"
        assert summary["tool_details"][0]["tool"] == "read_file"

    def test_summarize_rounding(self):
        report = TurnCostReport()
        report.accumulate_llm(LLMUsageRecord(latency_seconds=1.555))
        report.accumulate_tool(ToolCallUsageRecord(wall_seconds=2.555))
        report.turn_wall_seconds = 5.555
        summary = report.summarize()
        assert summary["total_llm_latency_s"] == round(1.555, 2)
        assert summary["total_tool_wall_s"] == round(2.555, 2)
        assert summary["turn_wall_s"] == round(5.555, 2)


# ── Events with cost_report ──────────────────────────────────────────────

class TestEventsWithCostReport:
    def test_turn_completed_with_cost(self):
        report = TurnCostReport()
        report.accumulate_llm(LLMUsageRecord(prompt_tokens=100))
        event = TurnCompletedEvent(ts="2024-01-01", cost_report=report)
        assert event.type == "turn_completed"
        assert event.cost_report.total_prompt_tokens == 100

    def test_turn_failed_with_partial_cost(self):
        report = TurnCostReport()
        report.accumulate_llm(LLMUsageRecord(prompt_tokens=50))
        event = TurnFailedEvent(ts="2024-01-01", error="test error", cost_report=report)
        assert event.cost_report.total_prompt_tokens == 50

    def test_turn_cancelled_with_partial_cost(self):
        report = TurnCostReport()
        event = TurnCancelledEvent(ts="2024-01-01", reason="user cancel", cost_report=report)
        assert event.cost_report.total_tokens == 0

    def test_turn_completed_default_cost(self):
        event = TurnCompletedEvent(ts="2024-01-01")
        assert event.cost_report.total_tokens == 0
        assert isinstance(event.cost_report, TurnCostReport)