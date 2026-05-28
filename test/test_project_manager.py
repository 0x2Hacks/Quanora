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
    list_unused_dirs,
    _DOC_ONLY_TYPES,
)


# ---------------------------------------------------------------------------
# _slugify
# ---------------------------------------------------------------------------


class TestSlugify:
    def test_ascii_text(self):
        assert _slugify("Hello World") == "hello_world"

    def test_special_chars(self):
        assert _slugify("Foo & Bar!") == "foo_bar"

    def test_multiple_underscores(self):
        assert _slugify("a---b") == "a_b"

    def test_chinese_text_pinyin_lossy(self):
        # Chinese chars stripped → could be empty → fallback
        result = _slugify("我的量化策略项目")
        # After NFKD + ASCII ignore, Chinese chars vanish → fallback to something
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_string(self):
        assert _slugify("") == "untitled"

    def test_leading_trailing_underscores(self):
        assert _slugify("-hello-") == "hello"

    def test_mixed_case(self):
        assert _slugify("HelloWORLD") == "helloworld"


# ---------------------------------------------------------------------------
# _detect_project_type
# ---------------------------------------------------------------------------


class TestDetectProjectType:
    def test_wq_alpha_type(self):
        type_id, cat_path, prefix = _detect_project_type("WorldQuant Brain alpha mining")
        assert type_id == "wq_alpha"
        assert cat_path == "alpha/wq"
        assert prefix == "wq"

    def test_wq_short_form(self):
        type_id, cat_path, prefix = _detect_project_type("WQ alpha研究")
        assert type_id == "wq_alpha"
        assert cat_path == "alpha/wq"
        assert prefix == "wq"

    def test_quant_backtest_type(self):
        type_id, cat_path, prefix = _detect_project_type("量化策略回测")
        assert type_id == "quant_backtest"
        assert cat_path == "backtest"
        assert prefix == "bt"

    def test_general_type(self):
        type_id, cat_path, prefix = _detect_project_type("随便写个东西")
        assert type_id == "general"
        assert cat_path == "projects"
        assert prefix == "proj"

    def test_data_pipeline_type(self):
        type_id, cat_path, prefix = _detect_project_type("ETL data pipeline for market data")
        assert type_id == "data_pipeline"
        assert cat_path == "data"
        assert prefix == "pipe"

    def test_wq_takes_priority_over_quant(self):
        # WQ rules come first in PROJECT_TYPE_RULES
        type_id, _, _ = _detect_project_type("WorldQuant quant research")
        assert type_id == "wq_alpha"

    def test_futures_doc_type(self):
        type_id, cat_path, prefix = _detect_project_type("期货合约 Binance OKX XAUUSD")
        assert type_id == "quant_md_futures"
        assert cat_path == "docs/futures"
        assert prefix == "spec"

    def test_fx_doc_type(self):
        type_id, cat_path, prefix = _detect_project_type("外汇 XAUUSD timeseries")
        assert type_id == "quant_md_fx"
        assert cat_path == "docs/fx"
        assert prefix == "spec"


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
        # Should be under a category path, not directly under workspace root
        assert result.parent != ws_root

    def test_exact_match_reuses_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        # Create the exact directory structure for a "general" type project
        category_dir = ws_root / "projects"
        category_dir.mkdir()
        existing = category_dir / "proj_my_new_project"
        existing.mkdir()

        result = find_or_create_project_dir(ws_root, "my new project")
        assert result == existing.resolve()

    def test_fuzzy_match_reuses_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        category_dir = ws_root / "projects"
        category_dir.mkdir()
        existing = category_dir / "proj_chain_peer_v2"
        existing.mkdir()

        # "chain peer v2" → slug will have "proj_" prefix
        result = find_or_create_project_dir(ws_root, "chain peer v2")
        assert result == existing.resolve()

    def test_no_match_creates_new(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        category_dir = ws_root / "projects"
        category_dir.mkdir()
        existing = category_dir / "totally_different"
        existing.mkdir()

        result = find_or_create_project_dir(ws_root, "brand new project")
        assert result != existing.resolve()
        assert result.is_dir()

    def test_skips_hidden_dirs(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        category_dir = ws_root / "projects"
        category_dir.mkdir()
        (category_dir / ".hidden").mkdir()

        result = find_or_create_project_dir(ws_root, "hidden project")
        # Should not reuse .hidden
        assert not result.name.startswith(".")

    def test_workspace_root_auto_created(self, tmp_path: Path):
        ws_root = tmp_path / "nonexistent_workspace"
        result = find_or_create_project_dir(ws_root, "test project")
        assert ws_root.is_dir()
        assert result.is_dir()

    def test_wq_type_hierarchy(self, tmp_path: Path):
        """WQ tasks should create alpha/wq/ hierarchy."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "WorldQuant Brain alpha mining session")
        assert "alpha" in result.parts
        assert "wq" in result.parts
        assert result.name.startswith("wq_")
        assert result.is_dir()

    def test_wq_type_reuses_existing_wq_dir(self, tmp_path: Path):
        """Two WQ sessions with similar descriptions should reuse the same dir."""
        ws_root = tmp_path / "workspace"

        # First session creates a WQ dir
        first = find_or_create_project_dir(ws_root, "WQ alpha mining momentum")
        assert first.name.startswith("wq_")

        # Second session with similar WQ task should reuse
        second = find_or_create_project_dir(ws_root, "WorldQuant alpha mining momentum")
        assert second == first

    def test_quant_type_hierarchy(self, tmp_path: Path):
        """Quant backtest tasks should create backtest/ hierarchy."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "量化策略回测")
        assert "backtest" in result.parts
        assert result.is_dir()

    def test_same_type_bonus_in_matching(self, tmp_path: Path):
        """Directories with same type prefix should get matching bonus."""
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()

        # Create the alpha/wq category dir
        category_dir = ws_root / "alpha" / "wq"
        category_dir.mkdir(parents=True)

        # Create a WQ dir
        wq_dir = category_dir / "wq_alpha_momentum"
        wq_dir.mkdir()

        # A new WQ task should find the WQ dir (fuzzy match)
        result = find_or_create_project_dir(ws_root, "WQ alpha momentum research")
        assert "wq" in result.parts

    def test_no_duplicate_prefix(self, tmp_path: Path):
        """Prefix should not be duplicated (e.g., not 'wq_wq_alpha')."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "WQ alpha")
        # Should NOT start with "wq_wq_"
        assert not result.name.startswith("wq_wq_")

    def test_project_skeleton_has_readme(self, tmp_path: Path):
        """New project dirs should have a README.md."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "WQ alpha mining test")
        assert (result / "README.md").exists()

    def test_futures_doc_hierarchy(self, tmp_path: Path):
        """Futures doc tasks should create docs/futures/ hierarchy."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "期货合约 Binance OKX XAUUSD timeseries")
        assert "docs" in result.parts
        assert "futures" in result.parts


# ---------------------------------------------------------------------------
# _DOC_ONLY_TYPES gate
# ---------------------------------------------------------------------------


class TestDocOnlyTypes:
    """Doc-only project types should NOT create skeleton sub-directories."""

    def test_doc_only_no_skeleton(self, tmp_path: Path):
        """quant_md_fx should create root dir but NOT data/ or output/."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "FX EUR/USD 日线分析")
        assert result.is_dir()
        # No data/ or output/ sub-directories should exist
        subdirs = [p.name for p in result.iterdir() if p.is_dir()]
        assert "data" not in subdirs
        assert "output" not in subdirs

    def test_code_type_has_skeleton(self, tmp_path: Path):
        """quant_backtest should still create skeleton sub-directories."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "MACD 策略回测")
        assert result.is_dir()
        subdirs = [p.name for p in result.iterdir() if p.is_dir()]
        assert "data" in subdirs
        assert "src" in subdirs
        assert "output" in subdirs

    def test_quant_research_no_skeleton(self, tmp_path: Path):
        """quant_research should create root dir only."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "统计套利研究笔记")
        assert result.is_dir()
        subdirs = [p.name for p in result.iterdir() if p.is_dir()]
        assert "data" not in subdirs
        assert "output" not in subdirs


# ---------------------------------------------------------------------------
# list_unused_dirs
# ---------------------------------------------------------------------------


class TestListUnusedDirs:
    """Test the auto-cleanup scanner for unused/skeleton-only directories."""

    def test_empty_dir_detected(self, tmp_path: Path):
        """Empty directories should be flagged as unused."""
        base = tmp_path / "workspace"
        (base / "empty_project").mkdir(parents=True)
        unused = list_unused_dirs(base)
        assert base / "empty_project" in unused

    def test_skeleton_only_detected(self, tmp_path: Path):
        """Directories with only .gitkeep and README.md should be flagged."""
        base = tmp_path / "workspace"
        proj = base / "skeleton_project"
        proj.mkdir(parents=True)
        (proj / ".gitkeep").touch()
        (proj / "README.md").write_text("# Skeleton\n")
        unused = list_unused_dirs(base)
        assert proj in unused

    def test_real_project_not_flagged(self, tmp_path: Path):
        """Directories with real content should NOT be flagged."""
        base = tmp_path / "workspace"
        proj = base / "real_project"
        proj.mkdir(parents=True)
        (proj / "src").mkdir()
        (proj / "src" / "main.py").write_text("print('hello')")
        unused = list_unused_dirs(base)
        assert proj not in unused

    def test_nonexistent_base(self, tmp_path: Path):
        """Non-existent base should return empty list."""
        unused = list_unused_dirs(tmp_path / "no_such_dir")
        assert unused == []

    def test_hidden_dirs_skipped(self, tmp_path: Path):
        """Hidden dirs (.quanora, .git) should be skipped."""
        base = tmp_path / "workspace"
        (base / ".quanora").mkdir(parents=True)
        unused = list_unused_dirs(base)
        assert base / ".quanora" not in unused
