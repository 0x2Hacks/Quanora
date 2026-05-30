"""
Tests for convert_html_to_pdf tool and its helper functions.

Tests cover:
- _split_multi_doctype_html helper (unit)
- _build_single_doc_html helper (unit)
- convert_html_to_pdf with mocked Playwright (integration)
- convert_html_to_pdf fallback when Playwright unavailable
- Error handling (file not found)
- Live PDF generation (when Playwright is available)
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from agent.infrastructure.tools.impl.tools.presentation import (
    _split_multi_doctype_html,
    _build_single_doc_html,
    convert_html_to_pdf,
    _resolve_workspace_path,
)


# ── Helpers ──────────────────────────────────────────────────────────

def _parse_result(raw):
    """Parse a tool_result JSON string into a dict."""
    if isinstance(raw, dict):
        return raw
    return json.loads(raw)


@pytest.fixture(autouse=True)
def _mock_workspace(tmp_path: Path, monkeypatch):
    """Redirect workspace resolution to a temp dir."""
    fake_guard = MagicMock()
    fake_guard.resolve_under_root = lambda p: str(tmp_path / p)
    fake_guard.check_write = MagicMock()
    monkeypatch.setattr(
        "agent.infrastructure.config.settings.get_workspace_guard",
        lambda: fake_guard,
    )
    return tmp_path


# ── Sample HTML fixtures ─────────────────────────────────────────────

@pytest.fixture
def simple_single_html(_mock_workspace: Path):
    """A minimal single-DOCTYPE HTML page."""
    path = str(_mock_workspace / "simple.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write("""<!DOCTYPE html>
<html><head><style>body { color: black; }</style></head>
<body><h1>Hello</h1><p>World</p></body></html>""")
    return path


@pytest.fixture
def multi_doctype_html(_mock_workspace: Path):
    """Three-DOCTYPE HTML (simulates PPT slides)."""
    slide_template = """<!DOCTYPE html>
<html>
<head>
<style>
.slide {{ background: #{color}; }}
</style>
</head>
<body>
<div class="slide" style="width:1280px;height:720px;">
  <h2>Slide {i}</h2>
  <p>Content of slide {i}.</p>
</div>
</body>
</html>"""
    colors = ["ff0000", "00ff00", "0000ff"]
    html = "\n".join(slide_template.format(i=i + 1, color=colors[i]) for i in range(3))
    path = str(_mock_workspace / "multi_slide.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


# ------------------------------------------------------------------ #
#  _split_multi_doctype_html
# ------------------------------------------------------------------ #

class TestSplitMultiDoctypeHtml:
    def test_single_doctype_returns_single_slide(self, simple_single_html):
        with open(simple_single_html, "r", encoding="utf-8") as f:
            html = f.read()
        slides = _split_multi_doctype_html(html)
        assert len(slides) == 1
        assert "Hello" in slides[0]["body"]

    def test_multi_doctype_returns_multiple_slides(self, multi_doctype_html):
        with open(multi_doctype_html, "r", encoding="utf-8") as f:
            html = f.read()
        slides = _split_multi_doctype_html(html)
        assert len(slides) == 3
        for i, s in enumerate(slides, 1):
            assert f"Slide {i}" in s["body"]

    def test_extracts_style(self, multi_doctype_html):
        with open(multi_doctype_html, "r", encoding="utf-8") as f:
            html = f.read()
        slides = _split_multi_doctype_html(html)
        # Each slide should have style content (may be empty or not)
        for s in slides:
            assert "style" in s

    def test_empty_input_returns_empty(self):
        assert _split_multi_doctype_html("") == []


# ------------------------------------------------------------------ #
#  _build_single_doc_html
# ------------------------------------------------------------------ #

class TestBuildSingleDocHtml:
    def test_produces_valid_html(self):
        slides = [
            {"body": "<div>Slide 1</div>", "style": "", "link": ""},
            {"body": "<div>Slide 2</div>", "style": "", "link": ""},
        ]
        result = _build_single_doc_html(slides, title="Test")
        assert "<!DOCTYPE html>" in result
        assert "Slide 1" in result
        assert "Slide 2" in result
        assert "slide-page" in result

    def test_includes_page_css(self):
        slides = [{"body": "<div>Test</div>", "style": "", "link": ""}]
        result = _build_single_doc_html(slides)
        assert "@page" in result
        assert "1280px 720px" in result

    def test_merges_unique_styles(self):
        slides = [
            {"body": "<div>1</div>", "style": "body { color: red; }", "link": ""},
            {"body": "<div>2</div>", "style": "body { color: blue; }", "link": ""},
            {"body": "<div>3</div>", "style": "body { color: red; }", "link": ""},
        ]
        result = _build_single_doc_html(slides)
        # Count occurrences of the styles (deduplicated)
        assert result.count("body { color: red; }") == 1
        assert result.count("body { color: blue; }") == 1

    def test_page_break_after_each_slide(self):
        slides = [
            {"body": "<div>A</div>", "style": "", "link": ""},
            {"body": "<div>B</div>", "style": "", "link": ""},
        ]
        result = _build_single_doc_html(slides)
        # page-break-after: always should be in CSS
        assert "page-break-after: always" in result


# ------------------------------------------------------------------ #
#  convert_html_to_pdf — mocked Playwright
# ------------------------------------------------------------------ #

class TestConvertHtmlToPdfMocked:
    def test_calls_playwright_pdf(self, simple_single_html, _mock_workspace: Path):
        mock_pdf_path = str(_mock_workspace / "simple.pdf")

        mock_page = MagicMock()
        mock_page.pdf = MagicMock()

        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_browser.close = MagicMock()

        mock_chromium = MagicMock()
        mock_chromium.launch.return_value = mock_browser

        mock_pw = MagicMock()
        mock_pw.chromium = mock_chromium
        mock_pw.__enter__ = MagicMock(return_value=mock_pw)
        mock_pw.__exit__ = MagicMock(return_value=False)

        # Patch _render_pdf_with_playwright to avoid needing real Playwright
        with patch(
            "agent.infrastructure.tools.impl.tools.presentation._render_pdf_with_playwright",
            return_value=(1, 1024),
        ) as mock_render:
            raw = convert_html_to_pdf(
                file_path="simple.html",
                output_path="simple.pdf",
            )
            result = _parse_result(raw)
            assert result["ok"] is True
            assert mock_render.called

    def test_mocked_pdf_dimensions(self, simple_single_html, _mock_workspace: Path):
        """Verify that the render function is called with the HTML content."""
        with patch(
            "agent.infrastructure.tools.impl.tools.presentation._render_pdf_with_playwright",
            return_value=(1, 1024),
        ) as mock_render:
            raw = convert_html_to_pdf(
                file_path="simple.html",
                output_path="simple.pdf",
            )
            result = _parse_result(raw)
            assert result["ok"] is True
            # Verify the HTML content was passed (just check it's not empty)
            call_args = mock_render.call_args[0]
            html_content = call_args[0]
            assert len(html_content) > 0
            assert "Hello" in html_content


# ------------------------------------------------------------------ #
#  convert_html_to_pdf — error handling
# ------------------------------------------------------------------ #

class TestConvertHtmlToPdfErrors:
    def test_file_not_found_returns_error(self, _mock_workspace: Path):
        nonexistent = str(_mock_workspace / "does_not_exist.html")
        raw = convert_html_to_pdf(
            file_path=nonexistent,
            output_path=str(_mock_workspace / "out.pdf"),
        )
        result = _parse_result(raw)
        assert result["ok"] is False
        assert "error" in result

    def test_empty_file_path_returns_error(self):
        raw = convert_html_to_pdf(file_path="")
        result = _parse_result(raw)
        assert result["ok"] is False


# ------------------------------------------------------------------ #
#  convert_html_to_pdf — live (skipped if no Playwright)
# ------------------------------------------------------------------ #

try:
    from playwright.sync_api import sync_playwright  # noqa: F401
    _HAS_PLAYWRIGHT = True
except ImportError:
    _HAS_PLAYWRIGHT = False


@pytest.mark.skipif(not _HAS_PLAYWRIGHT, reason="Playwright not installed")
class TestConvertHtmlToPdfLive:
    def test_generates_pdf_from_single_html(self, simple_single_html, _mock_workspace: Path):
        raw = convert_html_to_pdf(
            file_path="simple.html",
            output_path="simple.pdf",
        )
        result = _parse_result(raw)
        assert result["ok"] is True
        output = str(_mock_workspace / "simple.pdf")
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0

    def test_generates_multi_page_pdf(self, multi_doctype_html, _mock_workspace: Path):
        raw = convert_html_to_pdf(
            file_path="multi_slide.html",
            output_path="multi_slide.pdf",
        )
        result = _parse_result(raw)
        assert result["ok"] is True
        output = str(_mock_workspace / "multi_slide.pdf")
        assert os.path.exists(output)
        # Check for multiple pages
        with open(output, "rb") as f:
            content = f.read()
        page_count = content.count(b"/Type /Page")
        assert page_count >= 3, f"Expected >=3 /Type /Page for 3 slides, got {page_count}"

    def test_default_output_path_live(self, simple_single_html, _mock_workspace: Path):
        raw = convert_html_to_pdf(file_path=simple_single_html, output_path="")
        result = _parse_result(raw)
        assert result["ok"] is True
        expected_pdf = simple_single_html.replace(".html", ".pdf")
        assert os.path.exists(expected_pdf)
