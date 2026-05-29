"""Unit tests for the project-level workspace partition manager.

These tests exercise the project_manager module: slugify, extract_project_name,
project type detection, fuzzy match scoring, and find_or_create_project_dir.
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
    list_unused_dirs,
    _DOC_ONLY_TYPES,
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
        # Multiple non-alphanumeric chars collapsed to single hyphen
        assert _slugify("a---b") == "a-b"

    def test_chinese_text_pinyin_lossy(self):
        # Pure Chinese → non-ASCII replaced with hyphen → "untitled"
        result = _slugify("我的量化策略项目")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_empty_string(self):
        assert _slugify("") == "untitled"

    def test_kebab_case_style(self):
        # Slugs use kebab-case (hyphen-separated)
        assert _slugify("XAUUSD Timeseries Signal") == "xauusd-timeseries-signal"

    def test_file_extension_removed(self):
        # .md extension should be removed
        assert "md" not in _slugify("report.md")
        assert _slugify("report.md") == "report"

    def test_file_extension_in_middle(self):
        # .md in the middle of text should also be removed
        slug = _slugify("tokenized_stock_funding.md backtest")
        assert ".md" not in slug
        assert "md" not in slug.split("-")

    def test_duplicate_words_removed(self):
        # Duplicate words should be deduplicated
        slug = _slugify("backtest momentum backtest")
        assert slug == "backtest-momentum"

    def test_max_length_truncation(self):
        # Very long slugs should be truncated to ~60 chars
        long_name = "a-" * 50 + "final"
        slug = _slugify(long_name)
        assert len(slug) <= 60


# ---------------------------------------------------------------------------
# extract_project_name
# ---------------------------------------------------------------------------


class TestExtractProjectName:
    def test_md_file_path(self):
        assert "tokenized_stock_funding" in extract_project_name(
            "tokenized_stock_funding.md"
        )

    def test_plain_description(self):
        result = extract_project_name("量化策略回测")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_url_path(self):
        result = extract_project_name("https://example.com/projects/alpha_v2")
        assert "alpha" in result.lower()


# ---------------------------------------------------------------------------
# _detect_project_type
# ---------------------------------------------------------------------------


class TestDetectProjectType:
    def test_wq_alpha_type(self):
        type_id, skeleton_dirs = _detect_project_type("WorldQuant Brain alpha mining")
        assert type_id == "wq_alpha"
        assert "src" in skeleton_dirs
        assert "output" in skeleton_dirs

    def test_wq_short_form(self):
        type_id, skeleton_dirs = _detect_project_type("WQ alpha研究")
        assert type_id == "wq_alpha"

    def test_quant_backtest_type(self):
        type_id, skeleton_dirs = _detect_project_type("量化策略回测")
        assert type_id == "quant_backtest"
        assert "src" in skeleton_dirs

    def test_general_type(self):
        type_id, skeleton_dirs = _detect_project_type("随便写个东西")
        assert type_id == "general"
        assert "src" in skeleton_dirs

    def test_data_pipeline_type(self):
        type_id, skeleton_dirs = _detect_project_type("ETL data pipeline for market data")
        assert type_id == "data_pipeline"
        assert "scripts" in skeleton_dirs

    def test_wq_takes_priority_over_quant(self):
        # WQ rules come first in PROJECT_TYPE_RULES
        type_id, _ = _detect_project_type("WorldQuant quant research")
        assert type_id == "wq_alpha"

    def test_futures_doc_type(self):
        type_id, skeleton_dirs = _detect_project_type("期货合约 Binance OKX XAUUSD")
        assert type_id == "quant_md_futures"
        assert "docs" in skeleton_dirs

    def test_fx_doc_type(self):
        type_id, skeleton_dirs = _detect_project_type("外汇 XAUUSD timeseries")
        assert type_id == "quant_md_fx"
        assert "docs" in skeleton_dirs


# ---------------------------------------------------------------------------
# fuzzy match
# ---------------------------------------------------------------------------


class TestFuzzyMatchScore:
    def test_identical_strings(self):
        assert _fuzzy_match_score("hello", "hello") == 1.0

    def test_completely_different(self):
        score = _fuzzy_match_score("abc", "xyz")
        assert score < 0.5

    def test_similar_strings(self):
        score = _fuzzy_match_score("chain-peer-v2", "chain-peer-v3")
        assert score > 0.6

    def test_case_insensitive(self):
        # _fuzzy_match_score compares kebab-case slugs; same letters in
        # different case still get high score
        score = _fuzzy_match_score("Hello", "hello")
        assert score > 0.5


class TestLevenshtein:
    def test_identical(self):
        assert _levenshtein("abc", "abc") == 0

    def test_empty(self):
        assert _levenshtein("", "abc") == 3

    def test_insertion(self):
        assert _levenshtein("abc", "abcd") == 1

    def test_deletion(self):
        assert _levenshtein("abcd", "abc") == 1


# ---------------------------------------------------------------------------
# find_or_create_project_dir
# ---------------------------------------------------------------------------


class TestFindOrCreateProjectDir:
    def test_new_project_creates_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "my new project")
        assert result.is_dir()
        # Should be directly under workspace_root (flat structure)
        assert result.parent == ws_root.resolve()

    def test_exact_match_reuses_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        # Create the exact directory for a "general" type project
        existing = ws_root / "my-new-project"
        existing.mkdir()

        result = find_or_create_project_dir(ws_root, "my new project")
        assert result == existing.resolve()

    def test_fuzzy_match_reuses_dir(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        ws_root.mkdir()
        existing = ws_root / "chain-peer-v2"
        existing.mkdir()

        # "chain peer v3" should fuzzy-match "chain-peer-v2"
        result = find_or_create_project_dir(ws_root, "chain peer v3", threshold=0.4)
        assert result == existing.resolve()

    def test_flat_structure_no_category_dir(self, tmp_path: Path):
        """Project directories should be directly under workspace_root,
        not nested inside category directories like 'backtest/' or 'alpha/'."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "量化策略回测")
        assert result.is_dir()
        # Direct child of workspace_root (flat)
        assert result.parent == ws_root.resolve()

    def test_no_type_prefix_in_slug(self, tmp_path: Path):
        """Project slug should NOT have type prefix like 'bt_' or 'wq_'."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "tokenized stock funding backtest")
        assert result.is_dir()
        name = result.name
        # Should NOT start with 'bt_' or 'wq_' type prefix
        assert not name.startswith("bt_")
        assert not name.startswith("wq_")

    def test_skeleton_subdirs_created(self, tmp_path: Path):
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(ws_root, "量化策略回测")
        subdirs = {p.name for p in result.iterdir() if p.is_dir()}
        # quant_backtest type should have src, output, data, scripts, docs
        assert "src" in subdirs
        assert "output" in subdirs
        assert "data" in subdirs

    def test_doc_only_types_no_skeleton(self, tmp_path: Path):
        """Doc-only types should create root dir but NOT data/ or output/."""
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

    def test_kebab_case_directory_name(self, tmp_path: Path):
        """Directory name should use kebab-case."""
        ws_root = tmp_path / "workspace"
        result = find_or_create_project_dir(
            ws_root, "XAUUSD Timeseries Signal Backtest"
        )
        name = result.name
        # Should use hyphens, not underscores
        assert "-" in name
        assert "_" not in name


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
