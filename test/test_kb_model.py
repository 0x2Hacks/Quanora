"""Tests for Feature 2: Knowledge Base model and repository."""

import json
import os
import tempfile
import pytest

from agent.domain.knowledge_base import ExperienceRecord, ExperienceKnowledgeBase
from agent.infrastructure.persistence.knowledge_base_repository import KnowledgeBaseRepository


# ── ExperienceRecord ──────────────────────────────────────────────────────

class TestExperienceRecord:
    def test_defaults(self):
        r = ExperienceRecord()
        assert r.id == ""
        assert r.task_type == ""
        assert r.experience_summary == ""
        assert r.key_decisions == []
        assert r.common_pitfalls == []
        assert r.optimization_suggestions == []
        assert r.success_indicators == []
        assert r.failure_indicators == []
        assert r.context_tags == []
        assert r.relevance_score == 0.0
        assert r.created_at == ""
        assert r.source_turn_id == ""

    def test_construction(self):
        r = ExperienceRecord(
            id="exp_1",
            task_type="code_generation",
            experience_summary="Use type hints for clarity",
            key_decisions=["decided to use type hints"],
            common_pitfalls=["forgot to import typing"],
            context_tags=["python", "typing"],
            relevance_score=0.8,
        )
        assert r.id == "exp_1"
        assert r.task_type == "code_generation"
        assert len(r.key_decisions) == 1

    def test_to_dict(self):
        r = ExperienceRecord(id="exp_1", task_type="debugging", relevance_score=0.5)
        d = r.to_dict()
        assert d["id"] == "exp_1"
        assert d["task_type"] == "debugging"
        assert d["relevance_score"] == 0.5

    def test_from_dict(self):
        data = {
            "id": "exp_2",
            "task_type": "refactoring",
            "experience_summary": "Extract common logic",
            "key_decisions": ["decided to extract utility"],
            "common_pitfalls": [],
            "optimization_suggestions": [],
            "success_indicators": [],
            "failure_indicators": [],
            "context_tags": [],
            "relevance_score": 0.7,
            "created_at": "2024-01-01",
            "updated_at": "2024-01-01",
            "source_turn_id": "",
            "source_session_id": "",
        }
        r = ExperienceRecord.from_dict(data)
        assert r.id == "exp_2"
        assert r.task_type == "refactoring"

    def test_from_dict_ignores_extra_keys(self):
        data = {"id": "exp_3", "task_type": "test", "extra_field": "ignored"}
        r = ExperienceRecord.from_dict(data)
        assert r.id == "exp_3"
        assert not hasattr(r, "extra_field")


# ── ExperienceKnowledgeBase ──────────────────────────────────────────────

class TestExperienceKnowledgeBase:
    def test_defaults(self):
        kb = ExperienceKnowledgeBase()
        assert kb.records == []
        assert kb.version == 0
        assert len(kb) == 0

    def test_add(self):
        kb = ExperienceKnowledgeBase()
        r = ExperienceRecord(task_type="debugging", experience_summary="test lesson")
        record_id = kb.add(r)
        assert record_id.startswith("exp_")
        assert len(kb) == 1
        assert kb.version == 1
        assert r.id == record_id
        assert r.created_at != ""

    def test_add_with_existing_id(self):
        kb = ExperienceKnowledgeBase()
        r = ExperienceRecord(id="my_custom_id", task_type="test")
        record_id = kb.add(r)
        assert record_id == "my_custom_id"

    def test_get(self):
        kb = ExperienceKnowledgeBase()
        r = ExperienceRecord(id="exp_1", task_type="debugging")
        kb.add(r)
        found = kb.get("exp_1")
        assert found is not None
        assert found.task_type == "debugging"

    def test_get_missing(self):
        kb = ExperienceKnowledgeBase()
        assert kb.get("nonexistent") is None

    def test_update(self):
        kb = ExperienceKnowledgeBase()
        r = ExperienceRecord(id="exp_1", task_type="debugging", relevance_score=0.5)
        kb.add(r)
        ok = kb.update("exp_1", {"relevance_score": 0.8, "experience_summary": "updated"})
        assert ok is True
        found = kb.get("exp_1")
        assert found.relevance_score == 0.8
        assert found.experience_summary == "updated"
        assert kb.version == 2

    def test_update_missing(self):
        kb = ExperienceKnowledgeBase()
        ok = kb.update("nonexistent", {"relevance_score": 0.8})
        assert ok is False

    def test_update_cannot_change_id(self):
        kb = ExperienceKnowledgeBase()
        r = ExperienceRecord(id="exp_1", task_type="test")
        kb.add(r)
        ok = kb.update("exp_1", {"id": "new_id"})
        assert ok is True
        # id should not change
        found = kb.get("exp_1")
        assert found is not None
        assert found.id == "exp_1"

    def test_remove(self):
        kb = ExperienceKnowledgeBase()
        r = ExperienceRecord(id="exp_1", task_type="debugging")
        kb.add(r)
        ok = kb.remove("exp_1")
        assert ok is True
        assert len(kb) == 0
        assert kb.version == 2

    def test_remove_missing(self):
        kb = ExperienceKnowledgeBase()
        ok = kb.remove("nonexistent")
        assert ok is False

    def test_query_by_task_type(self):
        kb = ExperienceKnowledgeBase()
        kb.add(ExperienceRecord(task_type="debugging", relevance_score=0.3))
        kb.add(ExperienceRecord(task_type="debugging", relevance_score=0.8))
        kb.add(ExperienceRecord(task_type="code_generation", relevance_score=0.5))
        results = kb.query_by_task_type("debugging")
        assert len(results) == 2
        # Sorted by relevance_score descending
        assert results[0].relevance_score == 0.8
        assert results[1].relevance_score == 0.3

    def test_query_by_task_type_empty(self):
        kb = ExperienceKnowledgeBase()
        kb.add(ExperienceRecord(task_type="debugging"))
        assert kb.query_by_task_type("code_generation") == []

    def test_query_by_tags(self):
        kb = ExperienceKnowledgeBase()
        kb.add(ExperienceRecord(context_tags=["python", "async"], relevance_score=0.5))
        kb.add(ExperienceRecord(context_tags=["python", "web"], relevance_score=0.3))
        kb.add(ExperienceRecord(context_tags=["rust"], relevance_score=0.7))
        results = kb.query_by_tags(["python"])
        assert len(results) == 2
        # "python, async" has overlap=1 with ["python"], same for "python, web"
        # Sorted by overlap count, both have overlap=1

    def test_query_top_k(self):
        kb = ExperienceKnowledgeBase()
        for i in range(10):
            kb.add(ExperienceRecord(task_type="debugging", relevance_score=i / 10.0))
        top3 = kb.query_top_k("debugging", k=3)
        assert len(top3) == 3
        assert top3[0].relevance_score >= top3[1].relevance_score

    def test_boost_relevance(self):
        kb = ExperienceKnowledgeBase()
        r = ExperienceRecord(id="exp_1", relevance_score=0.5)
        kb.add(r)
        ok = kb.boost_relevance("exp_1", 0.1)
        assert ok is True
        assert kb.get("exp_1").relevance_score == 0.6

    def test_to_dict_and_from_dict_roundtrip(self):
        kb = ExperienceKnowledgeBase()
        kb.add(ExperienceRecord(id="exp_1", task_type="debugging", relevance_score=0.7))
        d = kb.to_dict()
        kb2 = ExperienceKnowledgeBase.from_dict(d)
        assert len(kb2) == 1
        assert kb2.get("exp_1").task_type == "debugging"
        assert kb2.get("exp_1").relevance_score == 0.7


# ── KnowledgeBaseRepository ──────────────────────────────────────────────

class TestKnowledgeBaseRepository:
    def test_load_empty(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = KnowledgeBaseRepository(os.path.join(tmpdir, "kb.json"))
            kb = repo.load()
            assert len(kb) == 0

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = KnowledgeBaseRepository(os.path.join(tmpdir, "kb.json"))
            kb = ExperienceKnowledgeBase()
            kb.add(ExperienceRecord(id="exp_1", task_type="debugging", relevance_score=0.7))
            repo.save(kb)
            kb2 = repo.load()
            assert len(kb2) == 1
            assert kb2.get("exp_1").task_type == "debugging"

    def test_add_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = KnowledgeBaseRepository(os.path.join(tmpdir, "kb.json"))
            record_id = repo.add_record(ExperienceRecord(task_type="code_gen"))
            assert record_id != ""
            kb = repo.load()
            assert len(kb) == 1
            assert kb.get(record_id).task_type == "code_gen"

    def test_update_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = KnowledgeBaseRepository(os.path.join(tmpdir, "kb.json"))
            rid = repo.add_record(ExperienceRecord(task_type="test", relevance_score=0.5))
            ok = repo.update_record(rid, {"relevance_score": 0.8})
            assert ok is True
            kb = repo.load()
            assert kb.get(rid).relevance_score == 0.8

    def test_remove_record(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = KnowledgeBaseRepository(os.path.join(tmpdir, "kb.json"))
            rid = repo.add_record(ExperienceRecord(task_type="test"))
            ok = repo.remove_record(rid)
            assert ok is True
            assert len(repo.load()) == 0

    def test_query_by_task_type(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = KnowledgeBaseRepository(os.path.join(tmpdir, "kb.json"))
            repo.add_record(ExperienceRecord(task_type="debugging", relevance_score=0.8))
            repo.add_record(ExperienceRecord(task_type="code_gen", relevance_score=0.5))
            results = repo.query_by_task_type("debugging")
            assert len(results) == 1
            assert results[0].task_type == "debugging"

    def test_query_top_k(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = KnowledgeBaseRepository(os.path.join(tmpdir, "kb.json"))
            for i in range(5):
                repo.add_record(ExperienceRecord(task_type="debugging", relevance_score=i / 5.0))
            top3 = repo.query_top_k("debugging", k=3)
            assert len(top3) == 3

    def test_boost_relevance(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            repo = KnowledgeBaseRepository(os.path.join(tmpdir, "kb.json"))
            rid = repo.add_record(ExperienceRecord(task_type="test", relevance_score=0.5))
            ok = repo.boost_relevance(rid, 0.1)
            assert ok is True
            kb = repo.load()
            assert kb.get(rid).relevance_score == 0.6

    def test_load_corrupted_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "kb.json")
            with open(path, "w") as f:
                f.write("not valid json {{{")
            repo = KnowledgeBaseRepository(path)
            kb = repo.load()
            assert len(kb) == 0  # starts fresh on corrupted file