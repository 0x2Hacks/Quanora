"""Tests for Feature 1: CLI cost report rendering and Feature 2: experience loop."""

import pytest

from agent.domain.events import (
    LLMUsageRecord,
    ToolCallUsageRecord,
    TurnCostReport,
    TurnCompletedEvent,
)
from agent.application.runtime.tool_telemetry import render_cost_report_text
from agent.application.services.experience_distillation_service import (
    ExperienceDistillationService,
    _summarize_experience,
    _extract_pitfalls,
    _extract_suggestions,
)
from agent.domain.knowledge_base import ExperienceRecord, ExperienceKnowledgeBase


# ── Cost Report Rendering ────────────────────────────────────────────────

class TestCostReportRendering:
    def test_render_empty_report(self):
        report = TurnCostReport()
        text = render_cost_report_text(report)
        assert "Cost Report" in text
        assert "LLM calls      : 0" in text
        assert "Tool calls     : 0" in text

    def test_render_with_llm_details(self):
        report = TurnCostReport()
        report.accumulate_llm(LLMUsageRecord(
            prompt_tokens=500, completion_tokens=200, total_tokens=700,
            latency_seconds=1.5, model="gpt-4o"
        ))
        text = render_cost_report_text(report)
        assert "gpt-4o" in text
        assert "p=500" in text
        assert "c=200" in text
        assert "LLM Call Details" in text

    def test_render_with_tool_details(self):
        report = TurnCostReport()
        report.accumulate_tool(ToolCallUsageRecord(
            tool_name="read_file", wall_seconds=2.5, output_chars=500
        ))
        text = render_cost_report_text(report)
        assert "read_file" in text
        assert "Tool Call Details" in text
        assert "out=500c" in text

    def test_render_with_both(self):
        report = TurnCostReport()
        report.accumulate_llm(LLMUsageRecord(prompt_tokens=1000, model="gpt-4o"))
        report.accumulate_tool(ToolCallUsageRecord(tool_name="bash", wall_seconds=3.0))
        report.turn_wall_seconds = 10.0
        text = render_cost_report_text(report)
        assert "gpt-4o" in text
        assert "bash" in text
        assert "Turn wall time : 10.0s" in text


# ── Experience Distillation ──────────────────────────────────────────────

class TestExperienceDistillation:
    def test_distill_from_turn_success(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "kb.json")
            service = ExperienceDistillationService(
                kb_repo=__import__("agent.infrastructure.persistence.knowledge_base_repository",
                                   fromlist=["KnowledgeBaseRepository"])
                .KnowledgeBaseRepository(path)
            )
            cost = TurnCostReport()
            cost.accumulate_llm(LLMUsageRecord(prompt_tokens=5000, total_tokens=7000))
            record_id = service.distill_from_turn(
                task_type="code_generation",
                turn_summary="Generated Python module with type hints.",
                cost_report=cost,
                success=True,
                session_id="sess_1",
                turn_id="turn_1",
                context_tags=["python", "typing"],
            )
            assert record_id is not None
            assert record_id.startswith("exp_")

    def test_distill_from_turn_empty_summary(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "kb.json")
            service = ExperienceDistillationService(
                kb_repo=__import__("agent.infrastructure.persistence.knowledge_base_repository",
                                   fromlist=["KnowledgeBaseRepository"])
                .KnowledgeBaseRepository(path)
            )
            # Empty summary and no tool_calls should skip distillation
            record_id = service.distill_from_turn(
                task_type="general",
                turn_summary="",
                tool_calls=None,
                cost_report=None,
            )
            assert record_id is None

    def test_distill_auto(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "kb.json")
            service = ExperienceDistillationService(
                kb_repo=__import__("agent.infrastructure.persistence.knowledge_base_repository",
                                   fromlist=["KnowledgeBaseRepository"])
                .KnowledgeBaseRepository(path)
            )
            event = TurnCompletedEvent(ts="2024-01-01", cost_report=TurnCostReport())
            record_id = service.distill_auto(event, active_skills=["debugging"])
            assert record_id is not None

    def test_distill_auto_no_skills(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "kb.json")
            service = ExperienceDistillationService(
                kb_repo=__import__("agent.infrastructure.persistence.knowledge_base_repository",
                                   fromlist=["KnowledgeBaseRepository"])
                .KnowledgeBaseRepository(path)
            )
            event = TurnCompletedEvent(ts="2024-01-01")
            record_id = service.distill_auto(event)
            assert record_id is not None


# ── Distillation helpers ────────────────────────────────────────────────

class TestDistillationHelpers:
    def test_summarize_experience_success(self):
        s = _summarize_experience("Fixed async bug", True, None, None)
        assert "completed successfully" in s
        assert "Fixed async bug" in s

    def test_summarize_experience_failure(self):
        s = _summarize_experience("Crash on import", False, None, None)
        assert "encountered issues" in s

    def test_summarize_experience_with_tools(self):
        tools = [{"tool": "bash"}, {"tool": "read_file"}]
        s = _summarize_experience("Ran tests", True, tools, None)
        assert "bash, read_file" in s

    def test_summarize_experience_length_cap(self):
        s = _summarize_experience("A" * 500, True, None, None)
        assert len(s) <= 300

    def test_extract_pitfalls_failure(self):
        p = _extract_pitfalls("", False, None)
        assert len(p) > 0

    def test_extract_pitfalls_tool_error(self):
        tools = [{"tool": "bash", "status": "error", "error": "timeout"}]
        p = _extract_pitfalls("", True, tools)
        assert any("bash" in pit for pit in p)

    def test_extract_suggestions_high_tokens(self):
        cost = TurnCostReport()
        cost.total_tokens = 60000
        suggestions = _extract_suggestions("", True, cost)
        assert any("reducing context" in s for s in suggestions)

    def test_extract_suggestions_slow_tools(self):
        cost = TurnCostReport()
        cost.total_tool_wall_seconds = 120
        suggestions = _extract_suggestions("", True, cost)
        assert any("slow" in s.lower() or "caching" in s for s in suggestions)


# ── Experience Loop Integration ──────────────────────────────────────────

class TestExperienceLoopIntegration:
    """Test the full inject → run → distill → query cycle."""

    def test_inject_then_distill_then_query(self):
        import tempfile, os
        with tempfile.TemporaryDirectory() as tmpdir:
            kb_path = os.path.join(tmpdir, "kb.json")
            from agent.infrastructure.persistence.knowledge_base_repository import KnowledgeBaseRepository

            # Step 1: Pre-seed some experience
            kb_repo = KnowledgeBaseRepository(kb_path)
            kb_repo.add_record(ExperienceRecord(
                task_type="debugging",
                experience_summary="Use logging instead of print for async code.",
                common_pitfalls=["print() doesn't work well with async"],
                context_tags=["python", "async"],
                relevance_score=0.9,
            ))

            # Step 2: Inject experience (simulated — normally done in context_manager)
            kb = kb_repo.load()
            results = kb.query_top_k("debugging", k=3)
            assert len(results) == 1
            assert "logging" in results[0].experience_summary

            # Step 3: Distill new experience after a turn
            service = ExperienceDistillationService(kb_repo=kb_repo)
            cost = TurnCostReport()
            cost.accumulate_llm(LLMUsageRecord(prompt_tokens=3000))
            record_id = service.distill_from_turn(
                task_type="debugging",
                turn_summary="Found async logging bug, fixed with proper logging module.",
                cost_report=cost,
                context_tags=["python", "async"],
            )
            assert record_id is not None

            # Step 4: Query — should now have 2 records
            kb = kb_repo.load()
            assert len(kb) == 2
            results = kb.query_top_k("debugging", k=5)
            assert len(results) == 2