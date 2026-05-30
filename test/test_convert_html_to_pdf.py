"""
Tests for convert_html_to_pdf tool and its helper functions.

Tests cover:
- _split_multi_doctype_html helper (unit)
- _inject_page_css helper (unit)
- _PDF_WRAPPER_TEMPLATE rendering (unit)
- convert_html_to_pdf with mocked Playwright (integration)
- convert_html_to_pdf fallback when Playwright unavailable
- Error handling (file not found)
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
    _inject_page_css,
    _PDF_PAGE_WIDTH_MM,
    _PDF_PAGE_HEIGHT_MM,
    _PDF_WRAPPER_TEMPLATE,
    convert_html_to_pdf,
)


def _parse_result(raw: str) -> dict:
    """Tool results are JSON strings from tool_ok/tool_error. Parse them."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pytest.fail(f"Tool returned non-JSON: {raw!r}")


# Minimal valid PDF bytes for mocking page.pdf()
_DUMMY_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj<</Type/Catalog/Pages 2 0 R>>endobj\n"
    b"2 0 obj<</Type/Pages/Kids[3 0 R]/Count 1>>endobj\n"
    b"3 0 obj<</Type/Page/MediaBox[0 0 612 792]/Parent 2 0 R>>endobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n0000000009 00000 n \n0000000058 00000 n \n0000000115 00000 n \n"
    b"trailer<</Size 4/Root 1 0 R>>\nstartxref\n190\n%%EOF"
)


def _make_mock_playwright():
    """Build a mock sync_playwright that writes a dummy PDF via page.pdf()."""
    mock_pw = MagicMock()
    mock_browser = MagicMock()
    mock_page = MagicMock()

    def fake_pdf(**kwargs):
        path = kwargs.get("path", "/tmp/dummy.pdf")
        with open(path, "wb") as f:
            f.write(_DUMMY_PDF)

    mock_page.pdf = fake_pdf
    mock_browser.new_page.return_value = mock_page
    mock_pw.chromium.launch.return_value = mock_browser

    ctx_manager = MagicMock()
    ctx_manager.__enter__ = MagicMock(return_value=mock_pw)
    ctx_manager.__exit__ = MagicMock(return_value=False)

    return ctx_manager


# ------------------------------------------------------------------ #
#  Fixtures
# ------------------------------------------------------------------ #

@pytest.fixture(autouse=True)
def _mock_workspace(tmp_path: Path):
    """Mock the workspace guard so writes land in tmp_path."""
    from agent.domain.workspace import WorkspaceConfig, WorkspaceGuard

    cfg = WorkspaceConfig(root=tmp_path)
    guard = WorkspaceGuard(cfg)

    with patch(
        "agent.infrastructure.config.settings.get_workspace_guard",
        return_value=guard,
    ):
        yield tmp_path


@pytest.fixture
def simple_single_html(_mock_workspace: Path):
    """A minimal single-DOCTYPE HTML file (like generate_doc_html output)."""
    html = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>Test Doc</title>
<style>
body { background: #f0f0f0; }
</style>
</head>
<body>
<div class="timeline-container">
  <h1>Hello World</h1>
  <p>This is a test document.</p>
</div>
</body>
</html>"""
    path = str(_mock_workspace / "simple_doc.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(html)
    return path


@pytest.fixture
def multi_doctype_html(_mock_workspace: Path):
    """A multi-DOCTYPE HTML file (like generate_ppt_html output) with 3 slides."""
    slide_template = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>Slide {i}</title>
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
        with open(simple_single_html, "r") as f:
            content = f.read()
        slides = _split_multi_doctype_html(content)
        assert len(slides) == 1
        assert "Hello World" in slides[0]["body"]
        assert "background: #f0f0f0" in slides[0]["style"]

    def test_multi_doctype_returns_three_slides(self, multi_doctype_html):
        with open(multi_doctype_html, "r") as f:
            content = f.read()
        slides = _split_multi_doctype_html(content)
        assert len(slides) == 3
        for i, sl in enumerate(slides, 1):
            assert f"Slide {i}" in sl["body"]
            assert f"Content of slide {i}." in sl["body"]

    def test_empty_string_returns_empty_list(self):
        assert _split_multi_doctype_html("") == []

    def test_doctype_without_body_is_skipped(self):
        """A DOCTYPE segment without <body> is skipped (empty body slides are filtered)."""
        html = "<!DOCTYPE html>\n<html><head><style>h1{}</style></head></html>"
        slides = _split_multi_doctype_html(html)
        assert len(slides) == 0

    def test_link_tags_extracted(self):
        html = """\
<!DOCTYPE html>
<html><head>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans" rel="stylesheet"/>
<style>body { font-family: 'Noto Sans'; }</style>
</head>
<body><p>Slide</p></body></html>"""
        slides = _split_multi_doctype_html(html)
        assert len(slides) == 1
        assert "fonts.googleapis.com" in slides[0]["link"]

    def test_each_slide_body_contains_own_content(self, multi_doctype_html):
        with open(multi_doctype_html, "r") as f:
            content = f.read()
        slides = _split_multi_doctype_html(content)
        assert "Slide 1" not in slides[1]["body"]
        assert "Slide 2" in slides[1]["body"]

    def test_styles_deduplicated(self):
        """If two slides share the same <style> content, dedup logic applies."""
        style_block = "<style>.slide { font-size: 14px; }</style>"
        html = f"""\
<!DOCTYPE html>
<html><head>{style_block}</head>
<body><div class="slide">Slide 1</div></body></html>

<!DOCTYPE html>
<html><head>{style_block}</head>
<body><div class="slide">Slide 2</div></body></html>"""
        slides = _split_multi_doctype_html(html)
        assert len(slides) == 2
        for sl in slides:
            assert "font-size: 14px" in sl["style"]


# ------------------------------------------------------------------ #
#  _inject_page_css
# ------------------------------------------------------------------ #

class TestInjectPageCss:
    def test_injects_into_existing_style_tag(self):
        html = "<html><head><style>body { color: red; }</style></head><body></body></html>"
        result = _inject_page_css(html)
        assert "@page" in result
        assert "1280px 720px" in result
        assert "margin: 0 !important" in result
        assert "padding: 0 !important" in result
        assert "-webkit-print-color-adjust: exact" in result
        assert result.index("@page") < result.index("</style>")

    def test_injects_style_tag_when_none_exists(self):
        html = "<html><head></head><body></body></html>"
        result = _inject_page_css(html)
        assert "@page" in result
        assert "<style>" in result

    def test_preserves_existing_content(self):
        html = "<html><head><style>body { color: red; }</style></head><body><p>Hello</p></body></html>"
        result = _inject_page_css(html)
        assert "body { color: red; }" in result
        assert "<p>Hello</p>" in result


# ------------------------------------------------------------------ #
#  _PDF_WRAPPER_TEMPLATE
# ------------------------------------------------------------------ #

class TestPdfWrapperTemplate:
    def test_template_contains_required_css(self):
        rendered = _PDF_WRAPPER_TEMPLATE.format(
            title="Test",
            width_mm=_PDF_PAGE_WIDTH_MM,
            height_mm=_PDF_PAGE_HEIGHT_MM,
            head_extras="",
            slide_pages="<div class='slide-page'>content</div>",
        )
        assert "@page" in rendered
        assert "page-break-after: always" in rendered
        assert "slide-page" in rendered
        assert "1280px" in rendered
        assert "720px" in rendered

    def test_template_renders_slide_pages(self):
        rendered = _PDF_WRAPPER_TEMPLATE.format(
            title="Test",
            width_mm=_PDF_PAGE_WIDTH_MM,
            height_mm=_PDF_PAGE_HEIGHT_MM,
            head_extras="",
            slide_pages='<div class="slide-page">Slide 1</div><div class="slide-page">Slide 2</div>',
        )
        assert "Slide 1" in rendered
        assert "Slide 2" in rendered


# ------------------------------------------------------------------ #
#  convert_html_to_pdf — mocked Playwright integration
# ------------------------------------------------------------------ #

class TestConvertHtmlToPdfMocked:
    """Integration tests with Playwright mocked to avoid needing a real browser."""

    def test_single_page_html_to_pdf(self, simple_single_html, _mock_workspace: Path):
        output = str(_mock_workspace / "simple_doc.pdf")

        with patch("playwright.sync_api.sync_playwright", return_value=_make_mock_playwright()):
            raw = convert_html_to_pdf(file_path=simple_single_html, output_path=output)

        result = _parse_result(raw)
        assert result["ok"] is True
        assert os.path.exists(output)
        with open(output, "rb") as f:
            assert f.read(5) == b"%PDF-"

    def test_multi_slide_html_to_pdf(self, multi_doctype_html, _mock_workspace: Path):
        output = str(_mock_workspace / "multi_slide.pdf")

        with patch("playwright.sync_api.sync_playwright", return_value=_make_mock_playwright()):
            raw = convert_html_to_pdf(file_path=multi_doctype_html, output_path=output)

        result = _parse_result(raw)
        assert result["ok"] is True
        assert os.path.exists(output)

    def test_default_output_path(self, simple_single_html, _mock_workspace: Path):
        """When output_path is empty, the PDF should be written next to the HTML file."""

        with patch("playwright.sync_api.sync_playwright", return_value=_make_mock_playwright()):
            raw = convert_html_to_pdf(file_path=simple_single_html, output_path="")

        result = _parse_result(raw)
        assert result["ok"] is True
        expected_pdf = simple_single_html.replace(".html", ".pdf")
        assert os.path.exists(expected_pdf)


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

    def test_playwright_import_error_returns_error(self, simple_single_html, _mock_workspace: Path):
        """When playwright import fails, the tool should return an error."""
        with patch.dict("sys.modules", {"playwright": None, "playwright.sync_api": None}):
            raw = convert_html_to_pdf(
                file_path=simple_single_html,
                output_path=str(_mock_workspace / "out.pdf"),
            )
            result = _parse_result(raw)
            assert result["ok"] is False

    def test_playwright_runtime_error(self, simple_single_html, _mock_workspace: Path):
        """When Playwright throws a runtime error, the tool should return an error."""
        mock_pw = MagicMock()
        mock_pw.chromium.launch.side_effect = RuntimeError("Browser not found")

        ctx_manager = MagicMock()
        ctx_manager.__enter__ = MagicMock(return_value=mock_pw)
        ctx_manager.__exit__ = MagicMock(return_value=False)

        with patch("playwright.sync_api.sync_playwright", return_value=ctx_manager):
            raw = convert_html_to_pdf(
                file_path=simple_single_html,
                output_path=str(_mock_workspace / "out.pdf"),
            )
            result = _parse_result(raw)
            assert result["ok"] is False


# ------------------------------------------------------------------ #
#  convert_html_to_pdf — live integration (requires real Playwright + Chromium)
# ------------------------------------------------------------------ #

class TestConvertHtmlToPdfLive:
    """Live integration tests that actually render PDFs with Playwright.

    These are automatically skipped if Playwright or Chromium are not available.
    """

    @pytest.fixture(autouse=True)
    def _check_playwright(self):
        """Skip if Playwright/Chromium is not functional."""
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch()
                browser.close()
        except Exception as e:
            pytest.skip(f"Playwright/Chromium not functional: {e}")

    def test_single_page_live(self, simple_single_html, _mock_workspace: Path):
        output = str(_mock_workspace / "simple_doc.pdf")
        raw = convert_html_to_pdf(file_path=simple_single_html, output_path=output)
        result = _parse_result(raw)
        assert result["ok"] is True
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0
        with open(output, "rb") as f:
            header = f.read(5)
        assert header == b"%PDF-"

    def test_multi_slide_live(self, multi_doctype_html, _mock_workspace: Path):
        output = str(_mock_workspace / "multi_slide.pdf")
        raw = convert_html_to_pdf(file_path=multi_doctype_html, output_path=output)
        result = _parse_result(raw)
        assert result["ok"] is True
        assert os.path.exists(output)
        assert os.path.getsize(output) > 0
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
