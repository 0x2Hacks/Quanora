"""Unit tests for the project-level workspace partition manager.

These tests exercise the project_manager module: slugify, extract_project_name,
project type detection, semantic normalization, fuzzy match scoring, and
find_or_create_project_dir.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.domain.project_manager import (
    _slugify,
    extract_project_name,
    _fuzzy_match_score,
    _levenshtein,
    find_or_create_project_dir,
    _detect_project_type,
    _normalize_semantic,
)


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_ascii_text(self):
        assert _slugify("Hello World") == "hello-world"

    def test_special_chars(self):
        assert _slugify("Foo & Bar!") == "foo-bar"

    def test_multiple_hyphens(self):
        assert _slugify("a---b") == "a-b"

    def test_chinese_text_pinyin_lossy(self):
        # Chinese chars stripped → could be empty → fallback
        result = _slugify("我的量化策略项目")
        # After NFKD + ASCII ignore, Chinese chars vanish → fallback to something
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_string(self):
        assert _slugify("") == "untitled"

    def test_leading_trailing_hyphens(self):
        assert _slugify("-hello-") == "hello"

    def test_mixed_case(self):
        assert _slugify("HelloWORLD") == "helloworld"


# ---------------------------------------------------------------------------
# _detect_project_type
# ---------------------------------------------------------------------------


class TestDetectProjectType:
    def test_wq_alpha_type(self):
        type_id, prefix = _detect_project_type("WorldQuant Brain alpha mining")
        assert type_id == "wq_alpha"
        assert prefix == "wq"

    def test_wq_short_form(self):
        type_id, prefix = _detect_project_type("WQ alpha研究")
        assert type_id == "wq_alpha"
        assert prefix == "wq"

    def test_quant_research_type(self):
        type_id, prefix = _detect_project_type("量化策略回测")
        assert type_id == "quant_research"
        assert prefix == "quant"

    def test_general_type(self):
        type_id, prefix = _detect_project_type("随便写个东西")
        assert type_id == "general"
        assert prefix == "proj"

    def test_data_pipeline_type(self):
        type_id, prefix = _detect_project_type("ETL data pipeline for market data")
        assert type_id == "data_pipeline"
        assert prefix == "data"

    def test_wq_takes_priority_over_quant(self):
        # WQ rules come first in PROJECT_TYPE_RULES
        type_id, _ = _detect_project_type("WorldQuant quant research")
        assert type_id == "wq_alpha"


# ---------------------------------------------------------------------------
# _normalize_semantic
# ---------------------------------------------------------------------------


class TestNormalizeSemantic:
    def test_wq_variants(self):
        assert "worldquant" in _normalize_semantic("WQ alpha mining")

    def test_brain_variants(self):
        assert "worldquant" in _normalize_semantic("Brain alpha mining")

    def test_quant_variants(self):
        assert "quant" in _normalize_semantic("量化策略")

    def test_backtest_variants(self):
        assert "backtest" in _normalize_semantic("回测")

    def test_no_change_for_unknown(self):
        assert _normalize_semantic("hello world") == "hello world"


# ---------------------------------------------------------------------------
# extract_project_name
# ---------------------------------------------------------------------------


class TestExtractProjectName:
    def test_project_line(self):
        assert extract_project_name("project: My Alpha Strategy") == "My Alpha Strategy"

    def test_project_line_chinese(self):
        assert extract_project_name("项目：量化回测") == "量化回测"

    def test_md_heading(self):
        assert extract_project_name("# ChainPeer") == "ChainPeer"

    def test_quoted_name(self):
        assert extract_project_name('Use "AlphaGen" for this task') == "AlphaGen"

    def test_fallback_to_snippet(self):
        result = extract_project_name("build a momentum factor strategy")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_returns_untitled(self):
        assert extract_project_name("") == "untitled-project"


# ---------------------------------------------------------------------------
# _levenshtein
# ---------------------------------------------------------------------------


class TestLevenshtein:
    def test_same_string(self):
        assert _levenshtein("abc", "abc") == 0

    def test_one_deletion(self):
        assert _levenshtein("abcd", "abc") == 1

    def test_one_insertion(self):
        assert _levenshtein("abc", "abcd") == 1

    def test_one_substitution(self):
        assert _levenshtein("abc", "axc") == 1

    def test_empty_strings(self):
        assert _levenshtein("", "") == 0
        assert _levenshtein("abc", "") == 3
        assert _levenshtein("", "abc") == 3


# ---------------------------------------------------------------------------
# _fuzzy_match_score
# ---------------------------------------------------------------------------


class TestFuzzyMatchScore:
    def test_identical_strings(self):
        assert _fuzzy_match_score("wq-alpha-mining", "wq-alpha-mining") == pytest.approx(1.0)

    def test_similar_strings(self):
        score = _fuzzy_match_score("wq-alpha-mining", "wq-alpha-research")
        assert 0.4 < score < 1.0

    def test_very_different_strings(self):
        score = _fuzzy_match_score("wq-alpha-mining", "web-dashboard")
        assert score < 0.5

    def test_semantic_equivalence(self):
        # "wq" normalizes to "worldquant", so these should score higher
        # than a completely different slug
        score_wq = _fuzzy_match_score("wq-alpha", "worldquant-alpha")
        score_diff = _fuzzy_match_score("wq-alpha", "web-dashboard")
        assert score_wq > score_diff

    def test_keyword_overlap(self):
        score = _fuzzy_match_score("wq-alpha-mining", "wq-alpha-backtest")
        # Two keywords overlap: "wq", "alpha"
        assert score > 0.5


# ---------------------------------------------------------------------------
# find_or_create_project_dir
# ---------------------------------------------------------------------------


class TestFindOrCreateProjectDir:
    def test_new_project_creates_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "my new project")
        assert result.is_dir()
        assert result.parent == ws_root

    def test_exact_match_reuses_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        existing = ws_root / "proj-my-new-project"
        existing.mkdir()

        result = find_or_create_project_dir(ws_root, "my new project")
        assert result == existing.resolve()

    def test_fuzzy_match_reuses_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        existing = ws_root / "proj-chain-peer-v2"
        existing.mkdir()

        # "chain peer v2" → slug will have "proj-" prefix
        result = find_or_create_project_dir(ws_root, "chain peer v2")
        assert result == existing.resolve()

    def test_no_match_creates_new(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        existing = ws_root / "totally-different"
        existing.mkdir()

        result = find_or_create_project_dir(ws_root, "brand new project")
        assert result != existing.resolve()
        assert result.is_dir()

    def test_skips_hidden_dirs(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        (ws_root / ".hidden").mkdir()

        result = find_or_create_project_dir(ws_root, "hidden project")
        # Should not reuse .hidden
        assert not result.name.startswith(".")

    def test_workspace_root_auto_created(self, tmp_path: Path):
        ws_root = tmp_path / "nonexistent_workspace"
        result = find_or_create_project_dir(ws_root, "test project")
        assert ws_root.is_dir()
        assert result.is_dir()

    def test_wq_type_prefix(self, tmp_path: Path):
        """WQ tasks should get 'wq-' prefix in their directory name."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "WorldQuant Brain alpha mining session")
        assert result.name.startswith("wq-")
        assert result.is_dir()

    def test_wq_type_reuses_existing_wq_dir(self, tmp_path: Path):
        """Two WQ sessions with similar descriptions should reuse the same dir."""
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()

        # First session creates a WQ dir
        first = find_or_create_project_dir(ws_root, "WQ alpha mining momentum")
        assert first.name.startswith("wq-")

        # Second session with similar WQ task should reuse
        second = find_or_create_project_dir(ws_root, "WorldQuant alpha mining momentum")
        assert second == first

    def test_quant_type_prefix(self, tmp_path: Path):
        """Quant research tasks should get 'quant-' prefix."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "量化策略回测")
        assert result.name.startswith("quant-")
        assert result.is_dir()

    def test_same_type_bonus_in_matching(self, tmp_path: Path):
        """Directories with same type prefix should get matching bonus."""
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()

        # Create a WQ dir
        wq_dir = ws_root / "wq-alpha-momentum"
        wq_dir.mkdir()

        # Also create a quant dir that might have some keyword overlap
        quant_dir = ws_root / "quant-alpha-momentum"
        quant_dir.mkdir()

        # A new WQ task should prefer the WQ dir
        result = find_or_create_project_dir(ws_root, "WQ alpha momentum research")
        assert result.name.startswith("wq-")

    def test_no_duplicate_prefix(self, tmp_path: Path):
        """Prefix should not be duplicated (e.g., not 'wq-wq-alpha')."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "WQ alpha")
        # Should be "wq-alpha" not "wq-wq-alpha"
        assert not result.name.startswith("wq-wq-")
