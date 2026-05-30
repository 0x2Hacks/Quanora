"""Unit tests for generate_ppt_html and generate_doc_html tools.

Tests cover:
- Normal PPT generation with various slide counts
- Normal document generation with timeline items
- Edge cases (no slides, empty timeline, special characters)
- File write success and HTML structure validation
- Tool registry integration
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent.infrastructure.tools.impl.tools.presentation import (
    generate_ppt_html,
    generate_doc_html,
)


def _parse_result(raw: str) -> dict:
    """Tool results are JSON strings from tool_ok/tool_error. Parse them."""
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"raw": raw}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def _mock_workspace(tmp_path: Path):
    """Mock the workspace guard so writes land in tmp_path."""
    from agent.domain.workspace import WorkspaceConfig, WorkspaceGuard, WorkspaceViolation

    cfg = WorkspaceConfig(root=tmp_path)
    guard = WorkspaceGuard(cfg)

    # Patch the import inside _resolve_workspace_path
    with patch(
        "agent.infrastructure.config.settings.get_workspace_guard",
        return_value=guard,
    ):
        yield tmp_path


# ---------------------------------------------------------------------------
# generate_ppt_html tests
# ---------------------------------------------------------------------------

class TestGeneratePptHtml:
    """Tests for the generate_ppt_html tool."""

    def test_basic_ppt_with_one_slide(self, _mock_workspace: Path):
        """Minimal PPT: title + 1 content slide + end = 3 slides."""
        result = generate_ppt_html(
            file_path="output/ppt.html",
            title="My Presentation",
            subtitle="A Test",
            author="Test Author",
            date="2026-01-01",
            slides=[
                {
                    "left_title": "Background",
                    "points": ["Point A", "Point B"],
                },
            ],
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True
        assert parsed["meta"]["slide_count"] == 3

        # Verify file exists and is non-empty HTML
        fpath = _mock_workspace / "output" / "ppt.html"
        assert fpath.exists()
        content = fpath.read_text(encoding="utf-8")
        assert "<!DOCTYPE html>" in content
        assert "My Presentation" in content

    def test_ppt_with_no_content_slides(self, _mock_workspace: Path):
        """PPT with only title + end = 2 slides."""
        result = generate_ppt_html(
            file_path="minimal.html",
            title="Minimal",
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True
        assert parsed["meta"]["slide_count"] == 2

    def test_ppt_with_multiple_slides(self, _mock_workspace: Path):
        """PPT with 3 content slides = 5 total."""
        slides = [
            {"left_title": f"Slide {i}", "points": [f"Point {i}"]}
            for i in range(1, 4)
        ]
        result = generate_ppt_html(
            file_path="multi.html",
            title="Multi",
            slides=slides,
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True
        assert parsed["meta"]["slide_count"] == 5

    def test_ppt_custom_end_text(self, _mock_workspace: Path):
        """Custom end slide text."""
        result = generate_ppt_html(
            file_path="custom_end.html",
            title="Custom End",
            end_text="FIN",
            end_subtitle="See you next time",
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True

        fpath = _mock_workspace / "custom_end.html"
        content = fpath.read_text(encoding="utf-8")
        assert "FIN" in content
        assert "See you next time" in content

    def test_ppt_html_escaping(self, _mock_workspace: Path):
        """HTML special characters in title/content are escaped."""
        result = generate_ppt_html(
            file_path="escape.html",
            title="<script>alert('xss')</script>",
            slides=[
                {"left_title": "A & B", "points": ["<b>bold</b>"]},
            ],
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True

        fpath = _mock_workspace / "escape.html"
        content = fpath.read_text(encoding="utf-8")
        # Should NOT contain raw <script> tag
        assert "<script>alert" not in content
        # Should contain escaped version
        assert "&lt;script&gt;" in content

    def test_ppt_long_title_auto_split(self, _mock_workspace: Path):
        """Long title gets auto-split into two lines."""
        long_title = "这是一个非常非常长的演示文稿标题需要自动换行"
        result = generate_ppt_html(
            file_path="long_title.html",
            title=long_title,
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True

    def test_ppt_all_fields_populated(self, _mock_workspace: Path):
        """All optional fields are used."""
        result = generate_ppt_html(
            file_path="full.html",
            title="Full Deck",
            subtitle="Complete test",
            author="Author Name",
            date="2026-06-15",
            target="Engineers",
            version="v3.1",
            slides=[
                {
                    "section_label": "02 / Overview",
                    "left_title": "Overview",
                    "left_subtitle": "Key concepts",
                    "right_title": "Category",
                    "right_subtitle": "Details here",
                    "points": ["Item 1", "Item 2", "Item 3"],
                },
            ],
            end_text="THANKS",
            end_subtitle="Questions?",
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True

        fpath = _mock_workspace / "full.html"
        content = fpath.read_text(encoding="utf-8")
        assert "Author Name" in content
        assert "2026-06-15" in content
        assert "Engineers" in content
        assert "v3.1" in content

    def test_ppt_contains_multiple_doctypes(self, _mock_workspace: Path):
        """Each slide is a full HTML document, so multiple DOCTYPEs exist."""
        result = generate_ppt_html(
            file_path="doctypes.html",
            title="Multi DocType",
            slides=[
                {"left_title": "Slide 1", "points": ["a"]},
                {"left_title": "Slide 2", "points": ["b"]},
            ],
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True

        fpath = _mock_workspace / "doctypes.html"
        content = fpath.read_text(encoding="utf-8")
        # title slide + 2 content slides + end slide = 4 DOCTYPEs
        assert content.count("<!DOCTYPE html>") == 4


# ---------------------------------------------------------------------------
# generate_doc_html tests
# ---------------------------------------------------------------------------

class TestGenerateDocHtml:
    """Tests for the generate_doc_html tool."""

    def test_basic_doc_with_items(self, _mock_workspace: Path):
        """Simple document with 3 timeline items."""
        result = generate_doc_html(
            file_path="output/doc.html",
            title="Attack Analysis",
            subtitle="7-day breakdown",
            section_label="03 / Analysis",
            timeline_items=[
                {"day_label": "DAY 01", "number": 1, "icon": "fa-solid fa-crosshairs", "item_title": "Recon", "description": "Port scan", "highlight": True},
                {"day_label": "DAY 02", "number": 2, "icon": "fa-solid fa-key", "item_title": "Creds", "description": "Phishing"},
                {"day_label": "DAY 03", "number": 3, "icon": "fa-solid fa-network-wired", "item_title": "Lateral", "description": "Internal spread"},
            ],
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True
        assert parsed["meta"]["item_count"] == 3

        fpath = _mock_workspace / "output" / "doc.html"
        assert fpath.exists()
        content = fpath.read_text(encoding="utf-8")
        assert "Attack Analysis" in content
        assert "fa-solid fa-crosshairs" in content

    def test_doc_no_timeline_items(self, _mock_workspace: Path):
        """Document with no timeline items (empty timeline)."""
        result = generate_doc_html(
            file_path="empty_timeline.html",
            title="Empty Timeline",
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True
        assert parsed["meta"]["item_count"] == 0

    def test_doc_highlight_vs_normal(self, _mock_workspace: Path):
        """Highlighted items use accent CSS class; normal items don't."""
        result = generate_doc_html(
            file_path="highlight.html",
            title="Highlight Test",
            timeline_items=[
                {"day_label": "DAY 01", "number": 1, "icon": "fa-solid fa-bug", "item_title": "Highlighted", "description": "Accent card", "highlight": True},
                {"day_label": "DAY 02", "number": 2, "icon": "fa-solid fa-shield-halved", "item_title": "Normal", "description": "Default card", "highlight": False},
            ],
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True

        fpath = _mock_workspace / "highlight.html"
        content = fpath.read_text(encoding="utf-8")
        # Highlighted card should have "highlight" CSS class
        assert "content-card highlight" in content

    def test_doc_html_escaping(self, _mock_workspace: Path):
        """HTML special characters are escaped in doc output."""
        result = generate_doc_html(
            file_path="escape_doc.html",
            title="<script>alert('xss')</script>",
            timeline_items=[
                {"day_label": "DAY 01", "number": 1, "icon": "fa-solid fa-bug", "item_title": "A & B", "description": "<img src=x>"},
            ],
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True

        fpath = _mock_workspace / "escape_doc.html"
        content = fpath.read_text(encoding="utf-8")
        assert "<script>alert" not in content
        assert "&lt;script&gt;" in content

    def test_doc_all_fields(self, _mock_workspace: Path):
        """All optional fields populated."""
        result = generate_doc_html(
            file_path="full_doc.html",
            title="Full Doc",
            subtitle="Complete subtitle",
            section_label="05 / Roadmap",
            timeline_items=[
                {"day_label": "Phase 1", "number": 1, "icon": "fa-solid fa-rocket", "item_title": "Launch", "description": "Initial deployment", "highlight": True},
            ],
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True

        fpath = _mock_workspace / "full_doc.html"
        content = fpath.read_text(encoding="utf-8")
        assert "Full Doc" in content
        assert "Complete subtitle" in content
        assert "05 / Roadmap" in content
        assert "fa-solid fa-rocket" in content

    def test_doc_timeline_item_defaults(self, _mock_workspace: Path):
        """Timeline items with minimal fields use defaults."""
        result = generate_doc_html(
            file_path="defaults.html",
            title="Defaults",
            timeline_items=[
                {},  # All defaults
                {"item_title": "Only Title"},  # Partial
            ],
        )
        parsed = _parse_result(result)
        assert parsed["ok"] is True

        fpath = _mock_workspace / "defaults.html"
        content = fpath.read_text(encoding="utf-8")
        assert "Defaults" in content


# ---------------------------------------------------------------------------
# Integration: Tool registry
# ---------------------------------------------------------------------------

class TestToolRegistry:
    """Ensure tools are properly registered in the tool registry."""

    def test_ppt_in_tools_dict(self):
        from agent.infrastructure.tools.impl import TOOLS
        assert "generate_ppt_html" in TOOLS
        assert callable(TOOLS["generate_ppt_html"])

    def test_doc_in_tools_dict(self):
        from agent.infrastructure.tools.impl import TOOLS
        assert "generate_doc_html" in TOOLS
        assert callable(TOOLS["generate_doc_html"])

    def test_ppt_has_schema_meta(self):
        from agent.infrastructure.tools.impl import _TOOL_SCHEMA_META
        assert "generate_ppt_html" in _TOOL_SCHEMA_META
        meta = _TOOL_SCHEMA_META["generate_ppt_html"]
        assert "description" in meta
        assert "param_descriptions" in meta
        assert "file_path" in meta["param_descriptions"]
        assert "title" in meta["param_descriptions"]

    def test_doc_has_schema_meta(self):
        from agent.infrastructure.tools.impl import _TOOL_SCHEMA_META
        assert "generate_doc_html" in _TOOL_SCHEMA_META
        meta = _TOOL_SCHEMA_META["generate_doc_html"]
        assert "description" in meta
        assert "param_descriptions" in meta
        assert "file_path" in meta["param_descriptions"]
        assert "title" in meta["param_descriptions"]
