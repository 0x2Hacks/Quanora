"""Presentation generation tools – PPT-style slides and timeline documents.

Provides three tools:
1. ``generate_ppt_html``  – create an HTML slide-deck file (1280×720 per slide)
2. ``generate_doc_html``  – create an HTML timeline-document file (1280×720 per page)
3. ``convert_html_to_pdf`` – render an HTML file to PDF using Playwright

Design follows the visual spec in ``html_format.txt``:
  • 1280 × 720 px fixed-viewport slides
  • Noto Sans SC / Noto Serif SC fonts via Google Fonts
  • Absolute-positioned layouts with thick dark dividers
  • Colour palette: #0A0A0A text, #A3A3A3 labels, #8B1E1E accent, #E5E7EB borders
"""

from __future__ import annotations

import html as html_mod
import os
import re
from datetime import datetime
from typing import Any

from agent.domain.tool_result import tool_error, tool_ok


# ──────────────────────────────────────────────────────────────────────
# Workspace path helper
# ──────────────────────────────────────────────────────────────────────

def _resolve_workspace_path(file_path: str) -> tuple[Any, str]:
    """Resolve *file_path* against the workspace root using WorkspaceGuard."""
    from agent.infrastructure.config.settings import get_workspace_guard
    guard = get_workspace_guard()
    path = guard.resolve_under_root(file_path)
    return guard, str(path)


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


# ──────────────────────────────────────────────────────────────────────
# Shared CSS – matches html_format.txt design spec
# ──────────────────────────────────────────────────────────────────────

_SHARED_FONT_LINKS = """\
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;600;700&family=Noto+Serif+SC:wght@400;600;700&display=swap" rel="stylesheet">"""

_SHARED_STYLE = """\
*, *::before, *::after { margin: 0; padding: 0; box-sizing: border-box; }
html { -webkit-print-color-adjust: exact !important; print-color-adjust: exact !important; }
body {
    font-family: 'Noto Sans SC', -apple-system, BlinkMacSystemFont, sans-serif;
    background: #FFFFFF;
    color: #0A0A0A;
    -webkit-font-smoothing: antialiased;
    -moz-osx-font-smoothing: grayscale;
}
"""

# ──────────────────────────────────────────────────────────────────────
# PPT HTML – slide templates
# ──────────────────────────────────────────────────────────────────────

_PPT_SLIDE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1280">
{font_links}
<style>
{shared_style}
@page {{
    size: 1280px 720px;
    margin: 0;
}}
.slide-page {{
    width: 1280px;
    height: 720px;
    position: relative;
    overflow: hidden;
    page-break-after: always;
    background: #FFFFFF;
}}
{slide_style}
</style>
</head>
<body>
<div class="slide-page">
{slide_body}
</div>
</body>
</html>"""

# ── Title Slide ──

_PPT_TITLE_BODY = """\
<!-- Title Slide -->
<div style="position:absolute; left:96px; top:0; width:680px; height:100%; display:flex; flex-direction:column; justify-content:center;">
    {section_badge}
    <h1 style="font-family:'Noto Serif SC',serif; font-size:48px; font-weight:700; line-height:1.3; color:#0A0A0A; letter-spacing:-0.02em;">{title}</h1>
    {subtitle_html}
</div>
<!-- Thick vertical divider -->
<div style="position:absolute; left:800px; top:80px; width:4px; height:560px; background:#0A0A0A; border-radius:2px;"></div>
<!-- Right info panel -->
<div style="position:absolute; left:840px; top:0; width:360px; height:100%; display:flex; flex-direction:column; justify-content:center;">
    {author_html}
    {date_html}
    {version_html}
    {target_html}
</div>"""

# ── Content Slide ──

_PPT_CONTENT_BODY = """\
<!-- Content Slide -->
<!-- Section label + thick horizontal divider -->
<div style="position:absolute; left:96px; top:40px; width:1088px;">
    {section_badge}
    <div style="height:4px; background:#0A0A0A; border-radius:2px; margin-top:8px;"></div>
</div>
<!-- Left column: section heading -->
<div style="position:absolute; left:96px; top:80px; width:380px;">
    {left_title_html}
    {left_subtitle_html}
</div>
<!-- Right column: bullet points -->
<div style="position:absolute; left:560px; top:80px; width:624px;">
    {points_html}
</div>"""

# ── End Slide ──

_PPT_END_BODY = """\
<!-- End Slide -->
<div style="position:absolute; left:0; top:0; width:100%; height:100%; display:flex; flex-direction:column; align-items:center; justify-content:center;">
    <h1 style="font-family:'Noto Serif SC',serif; font-size:56px; font-weight:700; color:#0A0A0A; letter-spacing:0.05em;">{end_text}</h1>
    {end_subtitle_html}
</div>"""


def _build_section_badge(label: str) -> str:
    if not label:
        return ""
    return (
        f'<span style="display:inline-block; font-size:14px; font-weight:600; '
        f'letter-spacing:2px; text-transform:uppercase; color:#A3A3A3; '
        f'padding:6px 16px; border:1.5px solid #E5E7EB; border-radius:4px; '
        f'margin-bottom:24px;">{html_mod.escape(label)}</span>'
    )


def _build_ppt_slides(
    title: str,
    subtitle: str,
    author: str,
    date_str: str,
    version: str,
    target: str,
    slides: list[dict[str, Any]],
    end_text: str,
    end_subtitle: str,
) -> list[str]:
    """Build a list of complete HTML documents (one per slide)."""

    result: list[str] = []

    # ── 1. Title slide ──
    section_badge = _build_section_badge("")
    subtitle_html = (
        f'<p style="font-size:18px; font-weight:400; color:#A3A3A3; margin-top:20px; line-height:1.6;">'
        f'{html_mod.escape(subtitle)}</p>'
    ) if subtitle else ""

    author_html = (
        f'<p style="font-size:15px; color:#A3A3A3; margin-bottom:8px;">{html_mod.escape(author)}</p>'
    ) if author else ""
    date_html = (
        f'<p style="font-size:14px; color:#A3A3A3; margin-bottom:8px;">{html_mod.escape(date_str)}</p>'
    ) if date_str else ""
    version_html = (
        f'<p style="font-size:14px; color:#A3A3A3; margin-bottom:8px;">Version {html_mod.escape(version)}</p>'
    ) if version else ""
    target_html = (
        f'<p style="font-size:14px; color:#8B1E1E; font-weight:500;">{html_mod.escape(target)}</p>'
    ) if target else ""

    title_body = _PPT_TITLE_BODY.format(
        section_badge=section_badge,
        title=html_mod.escape(title),
        subtitle_html=subtitle_html,
        author_html=author_html,
        date_html=date_html,
        version_html=version_html,
        target_html=target_html,
    )
    result.append(
        _PPT_SLIDE_TEMPLATE.format(
            font_links=_SHARED_FONT_LINKS,
            shared_style=_SHARED_STYLE,
            slide_style="",
            slide_body=title_body,
        )
    )

    # ── 2. Content slides ──
    for s in slides:
        s_label = s.get("section_label", "")
        l_title = s.get("left_title", "")
        l_sub = s.get("left_subtitle", "")
        r_title = s.get("right_title", "")
        r_sub = s.get("right_subtitle", "")
        points = s.get("points", [])

        s_badge = _build_section_badge(s_label)

        left_title_html = (
            f'<h2 style="font-family:\'Noto Serif SC\',serif; font-size:32px; font-weight:700; '
            f'color:#0A0A0A; line-height:1.4;">{html_mod.escape(l_title)}</h2>'
        ) if l_title else ""

        left_subtitle_html = (
            f'<p style="font-size:16px; color:#A3A3A3; margin-top:12px; line-height:1.6;">'
            f'{html_mod.escape(l_sub)}</p>'
        ) if l_sub else ""

        # Build points
        points_parts: list[str] = []
        if r_title:
            points_parts.append(
                f'<h3 style="font-family:\'Noto Serif SC\',serif; font-size:22px; font-weight:600; '
                f'color:#0A0A0A; margin-bottom:8px;">{html_mod.escape(r_title)}</h3>'
            )
        if r_sub:
            points_parts.append(
                f'<p style="font-size:14px; color:#A3A3A3; margin-bottom:20px; line-height:1.5;">'
                f'{html_mod.escape(r_sub)}</p>'
            )

        for pt in points:
            if isinstance(pt, str):
                text = pt
                is_accent = False
            elif isinstance(pt, dict):
                text = pt.get("text", str(pt))
                is_accent = pt.get("highlight", False) or pt.get("accent", False)
            else:
                text = str(pt)
                is_accent = False

            dot_color = "#8B1E1E" if is_accent else "#A3A3A3"
            text_weight = "600" if is_accent else "400"
            text_color = "#0A0A0A" if is_accent else "#374151"
            points_parts.append(
                f'<div style="display:flex; align-items:flex-start; margin-bottom:14px;">'
                f'<div style="width:8px; height:8px; border-radius:50%; background:{dot_color}; '
                f'margin-top:7px; margin-right:12px; flex-shrink:0;"></div>'
                f'<p style="font-size:16px; font-weight:{text_weight}; color:{text_color}; '
                f'line-height:1.6;">{html_mod.escape(text)}</p>'
                f'</div>'
            )

        points_html = "\n".join(points_parts)

        content_body = _PPT_CONTENT_BODY.format(
            section_badge=s_badge,
            left_title_html=left_title_html,
            left_subtitle_html=left_subtitle_html,
            points_html=points_html,
        )
        result.append(
            _PPT_SLIDE_TEMPLATE.format(
                font_links=_SHARED_FONT_LINKS,
                shared_style=_SHARED_STYLE,
                slide_style="",
                slide_body=content_body,
            )
        )

    # ── 3. End slide ──
    end_subtitle_html = (
        f'<p style="font-size:20px; color:#A3A3A3; margin-top:16px;">{html_mod.escape(end_subtitle)}</p>'
    ) if end_subtitle else ""

    end_body = _PPT_END_BODY.format(
        end_text=html_mod.escape(end_text),
        end_subtitle_html=end_subtitle_html,
    )
    result.append(
        _PPT_SLIDE_TEMPLATE.format(
            font_links=_SHARED_FONT_LINKS,
            shared_style=_SHARED_STYLE,
            slide_style="",
            slide_body=end_body,
        )
    )

    return result


# ──────────────────────────────────────────────────────────────────────
# Document HTML – timeline template
# ──────────────────────────────────────────────────────────────────────

_DOC_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1280">
{font_links}
<style>
{shared_style}
@page {{
    size: 1280px 720px;
    margin: 0;
}}
body {{
    width: 1280px;
    min-height: 720px;
}}

/* ── Page wrapper ── */
.doc-page {{
    width: 1280px;
    min-height: 720px;
    position: relative;
    padding: 48px 64px;
    background: #FFFFFF;
}}

/* ── Header area ── */
.doc-header {{
    margin-bottom: 8px;
}}
.doc-section-label {{
    font-size: 14px;
    font-weight: 600;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: #A3A3A3;
    margin-bottom: 8px;
}}
.doc-title {{
    font-family: 'Noto Serif SC', serif;
    font-size: 36px;
    font-weight: 700;
    color: #0A0A0A;
    line-height: 1.3;
    margin-bottom: 6px;
}}
.doc-subtitle {{
    font-size: 16px;
    color: #A3A3A3;
    line-height: 1.5;
}}

/* ── Thick divider ── */
.doc-divider {{
    height: 4px;
    background: #0A0A0A;
    border-radius: 2px;
    margin: 20px 0 28px 0;
}}

/* ── Timeline axis ── */
.timeline-axis {{
    position: relative;
    display: flex;
    align-items: flex-start;
    justify-content: space-between;
    padding: 0 20px;
    margin-bottom: 24px;
}}

/* ── Timeline nodes ── */
.timeline-node {{
    display: flex;
    flex-direction: column;
    align-items: center;
    position: relative;
    z-index: 2;
}}
.node-circle {{
    width: 40px;
    height: 40px;
    border-radius: 50%;
    background: #0A0A0A;
    color: #FFFFFF;
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 16px;
    font-weight: 600;
    border: 3px solid #FFFFFF;
    box-shadow: 0 2px 8px rgba(0,0,0,0.12);
}}
.node-circle.highlight {{
    background: #8B1E1E;
    border-color: #FFFFFF;
}}
.node-label {{
    font-size: 12px;
    color: #A3A3A3;
    margin-top: 8px;
    white-space: nowrap;
    font-weight: 500;
}}

/* ── Horizontal line behind nodes ── */
.timeline-line {{
    position: absolute;
    top: 20px;
    left: 40px;
    right: 40px;
    height: 3px;
    background: #E5E7EB;
    z-index: 1;
}}

/* ── Card grid ── */
.card-grid {{
    display: grid;
    grid-template-columns: repeat({grid_cols}, 1fr);
    gap: 16px;
    padding: 0 20px;
}}
.card-grid.single-column {{
    grid-template-columns: 1fr;
    max-width: 560px;
}}

/* ── Content card ── */
.content-card {{
    background: #F9FAFB;
    border: 1.5px solid #E5E7EB;
    border-radius: 8px;
    padding: 20px;
    transition: box-shadow 0.2s;
}}
.content-card.highlight {{
    border-color: #8B1E1E;
    background: #FEF2F2;
}}

.card-icon {{
    font-size: 22px;
    margin-bottom: 10px;
    color: #A3A3A3;
}}
.card-title {{
    font-family: 'Noto Serif SC', serif;
    font-size: 18px;
    font-weight: 600;
    color: #0A0A0A;
    margin-bottom: 8px;
    line-height: 1.4;
}}
.card-desc {{
    font-size: 14px;
    color: #374151;
    line-height: 1.6;
}}
.highlight-tag {{
    display: inline-block;
    font-size: 11px;
    font-weight: 600;
    color: #8B1E1E;
    background: #FEF2F2;
    border: 1px solid #8B1E1E;
    border-radius: 3px;
    padding: 2px 8px;
    margin-top: 10px;
}}

/* ── Footer ── */
.doc-footer {{
    position: absolute;
    bottom: 32px;
    left: 64px;
    right: 64px;
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 12px;
    color: #A3A3A3;
}}
</style>
</head>
<body>
<div class="doc-page">
    <!-- Header -->
    <div class="doc-header">
        {section_label_html}
        <h1 class="doc-title">{doc_title}</h1>
        {subtitle_html}
    </div>
    <div class="doc-divider"></div>

    <!-- Timeline axis -->
    <div class="timeline-axis">
        <div class="timeline-line"></div>
        {timeline_nodes_html}
    </div>

    <!-- Card grid -->
    <div class="card-grid {grid_class}">
        {timeline_items_html}
    </div>

    <!-- Footer -->
    <div class="doc-footer">
        <span>{gen_date}</span>
        <span>{item_count} items</span>
    </div>
</div>
</body>
</html>"""


# ──────────────────────────────────────────────────────────────────────
# generate_ppt_html tool
# ──────────────────────────────────────────────────────────────────────

def generate_ppt_html(
    file_path: str,
    title: str,
    subtitle: str = "",
    author: str = "",
    date: str = "",
    version: str = "",
    target: str = "",
    slides: list[dict[str, Any]] | None = None,
    end_text: str = "THANK YOU",
    end_subtitle: str = "",
) -> dict:
    """Generate a PPT-style HTML presentation file.

    Each slide is 1280×720 pixels. The output is a single HTML file containing
    multiple ``<!DOCTYPE html>`` blocks (one per slide) so that
    ``convert_html_to_pdf`` can split them into separate PDF pages.
    """
    if not title:
        return tool_error("generate_ppt_html", "title is required", "ValueError")

    date_str = date or datetime.now().strftime("%Y-%m-%d")
    slides = slides or []

    slide_htmls = _build_ppt_slides(
        title=title,
        subtitle=subtitle,
        author=author,
        date_str=date_str,
        version=version,
        target=target,
        slides=slides,
        end_text=end_text,
        end_subtitle=end_subtitle,
    )

    # Join all slides – each is a full HTML doc, which the PDF converter splits
    html_content = "\n".join(slide_htmls)

    # Write to file
    guard, resolved = _resolve_workspace_path(file_path)
    guard.check_write(resolved)
    _ensure_dir(resolved)
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(html_content)

    return tool_ok(
        "generate_ppt_html",
        data={"file_path": file_path, "size_bytes": os.path.getsize(resolved)},
        meta={"slide_count": len(slide_htmls)},
    )


# ──────────────────────────────────────────────────────────────────────
# generate_doc_html tool
# ──────────────────────────────────────────────────────────────────────

def generate_doc_html(
    file_path: str,
    title: str,
    subtitle: str = "",
    section_label: str = "",
    timeline_items: list[dict[str, Any]] | None = None,
) -> dict:
    """Generate a timeline-style document HTML file.

    Each page is 1280×720 pixels, containing a horizontal timeline axis with
    card-style content items below.
    """
    if not title:
        return tool_error("generate_doc_html", "title is required", "ValueError")

    timeline_items = timeline_items or []

    # Build timeline nodes (the circles on the axis)
    node_parts: list[str] = []
    for i, item in enumerate(timeline_items):
        num = i + 1
        is_hl = item.get("highlight", False)
        day_label = item.get("day_label", "")
        hl_class = " highlight" if is_hl else ""
        node_parts.append(
            f'<div class="timeline-node">'
            f'<div class="node-circle{hl_class}">{num}</div>'
            f'<div class="node-label">{html_mod.escape(day_label)}</div>'
            f'</div>'
        )
    timeline_nodes_html = "\n".join(node_parts)

    # Build content cards
    card_parts: list[str] = []
    for i, item in enumerate(timeline_items):
        is_hl = item.get("highlight", False)
        hl_class = " highlight" if is_hl else ""
        icon_str = item.get("icon", "")
        icon_html = f'<div class="card-icon">{html_mod.escape(icon_str)}</div>' if icon_str else ""
        item_title = item.get("item_title", "")
        desc = item.get("description", "")
        hl_tag = (
            f'<span class="highlight-tag">Key Event</span>'
            if is_hl else ""
        )
        card_parts.append(
            f'<div class="content-card{hl_class}">'
            f'{icon_html}'
            f'<div class="card-title">{html_mod.escape(item_title)}</div>'
            f'<div class="card-desc">{html_mod.escape(desc)}</div>'
            f'{hl_tag}'
            f'</div>'
        )
    timeline_items_html = "\n".join(card_parts)

    grid_cols = min(len(timeline_items), 5) if timeline_items else 1
    grid_class = "single-column" if len(timeline_items) <= 2 else ""
    item_count = len(timeline_items)
    gen_date = datetime.now().strftime("%Y-%m-%d")

    section_label_html = (
        f'<div class="doc-section-label">{html_mod.escape(section_label)}</div>'
    ) if section_label else ""
    subtitle_html = (
        f'<p class="doc-subtitle">{html_mod.escape(subtitle)}</p>'
    ) if subtitle else ""

    doc_html = _DOC_TEMPLATE.format(
        font_links=_SHARED_FONT_LINKS,
        shared_style=_SHARED_STYLE,
        doc_title=html_mod.escape(title),
        section_label_html=section_label_html,
        subtitle_html=subtitle_html,
        timeline_nodes_html=timeline_nodes_html,
        timeline_items_html=timeline_items_html,
        grid_class=grid_class,
        grid_cols=grid_cols,
        item_count=item_count,
        gen_date=gen_date,
    )

    guard, resolved = _resolve_workspace_path(file_path)
    guard.check_write(resolved)
    _ensure_dir(resolved)
    with open(resolved, "w", encoding="utf-8") as f:
        f.write(doc_html)

    return tool_ok(
        "generate_doc_html",
        data={"file_path": file_path, "size_bytes": os.path.getsize(resolved)},
        meta={"item_count": item_count},
    )


# ──────────────────────────────────────────────────────────────────────
# convert_html_to_pdf tool
# ──────────────────────────────────────────────────────────────────────

def convert_html_to_pdf(
    file_path: str,
    output_path: str = "",
) -> dict:
    """Convert an HTML file to PDF using Playwright (headless Chromium).

    Supports both:
    - **Multi-slide PPT HTML**: multiple ``<!DOCTYPE html>`` blocks, each
      rendered as a separate 1280×720 landscape page.
    - **Single-page Doc HTML**: one ``<!DOCTYPE html>`` block rendered as
      a single page.

    PDF pages are 1280×720 px (16:9 landscape) with zero margins, matching
    the HTML viewport exactly.
    """
    if not file_path:
        return tool_error("convert_html_to_pdf", "file_path is required", "ValueError")

    _, resolved_input = _resolve_workspace_path(file_path)

    if not os.path.isfile(resolved_input):
        return tool_error(
            "convert_html_to_pdf",
            f"HTML file not found: {file_path}",
            "FileNotFoundError",
        )

    if not output_path:
        base, _ = os.path.splitext(file_path)
        output_path = base + ".pdf"

    _, resolved_output = _resolve_workspace_path(output_path)
    _ensure_dir(resolved_output)

    # Read the HTML content
    with open(resolved_input, "r", encoding="utf-8") as f:
        html_content = f.read()

    # Detect if multi-DOCTYPE (PPT-style) or single-DOCTYPE (doc-style)
    doctype_count = html_content.count("<!DOCTYPE html>")

    if doctype_count > 1:
        # Multi-slide PPT HTML → split and recombine
        slides = _split_multi_doctype_html(html_content)
        if not slides:
            return tool_error(
                "convert_html_to_pdf",
                "No valid slide content found in the HTML file",
                "ParseError",
            )
        single_html = _build_single_doc_html(slides, title="Presentation")
    else:
        single_html = html_content

    # Render to PDF
    try:
        page_count, file_size = _render_pdf_with_playwright(single_html, resolved_output)
    except ImportError:
        return tool_error(
            "convert_html_to_pdf",
            "Playwright is not installed. Install with: pip install playwright && playwright install chromium",
            "ImportError",
        )
    except Exception as exc:
        return tool_error(
            "convert_html_to_pdf",
            f"PDF rendering failed: {exc}",
            "RuntimeError",
        )

    return tool_ok(
        "convert_html_to_pdf",
        data={"input_path": file_path, "output_path": output_path, "file_size_bytes": file_size},
        meta={"page_count": page_count},
    )


# ──────────────────────────────────────────────────────────────────────
# Internal helpers
# ──────────────────────────────────────────────────────────────────────

def _split_multi_doctype_html(html_content: str) -> list[dict[str, str]]:
    """Split a multi-DOCTYPE HTML string into per-slide dicts.

    Each dict has keys: ``body``, ``style``, ``link``.
    """
    # Split on <!DOCTYPE html>
    parts = re.split(r"<!DOCTYPE\s+html[^>]*>", html_content, flags=re.IGNORECASE)

    slides: list[dict[str, str]] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Extract <style> content
        style_match = re.search(r"<style[^>]*>(.*?)</style>", part, re.DOTALL | re.IGNORECASE)
        style_content = style_match.group(1).strip() if style_match else ""

        # Extract <link> tags (for fonts etc.)
        link_matches = re.findall(r"<link[^>]+rel=\"stylesheet\"[^>]*>", part, re.IGNORECASE)
        link_html = "\n".join(link_matches)

        # Extract <body> content – try <body> tag first
        body_match = re.search(r"<body[^>]*>(.*?)</body>", part, re.DOTALL | re.IGNORECASE)
        if body_match:
            body_content = body_match.group(1).strip()
        else:
            # Fallback: take everything after </head> or </style>
            after_head = re.split(r"</head>", part, flags=re.IGNORECASE)
            if len(after_head) > 1:
                body_content = after_head[1].strip()
            else:
                body_content = part.strip()
            # Remove trailing </html>
            body_content = re.sub(r"</html>\s*$", "", body_content, flags=re.IGNORECASE).strip()

        if not body_content:
            continue

        slides.append({
            "body": body_content,
            "style": style_content,
            "link": link_html,
        })

    return slides


def _build_single_doc_html(
    slides: list[dict[str, str]],
    title: str = "Presentation",
) -> str:
    """Rebuild a multi-DOCTYPE HTML into a single valid HTML document
    with CSS page-break rules for proper PDF pagination.

    Each slide's body content is wrapped in a ``<div class="slide-page">``
    and all unique styles are merged into a single ``<style>`` block.
    """
    # Merge all unique styles (deduplicate by content hash)
    seen_styles: set[str] = set()
    merged_styles: list[str] = []
    link_tags: list[str] = []

    for slide in slides:
        style_text = slide.get("style", "")
        if style_text and style_text not in seen_styles:
            seen_styles.add(style_text)
            merged_styles.append(style_text)

        link_html = slide.get("link", "")
        if link_html and link_html not in link_tags:
            link_tags.append(link_html)

    # Deduplicate Google Fonts links – keep only one set
    font_links_deduped: list[str] = []
    seen_font_urls: set[str] = set()
    for lnk in link_tags:
        for line in lnk.split("\n"):
            line = line.strip()
            if not line:
                continue
            # Extract href for dedup
            href_match = re.search(r'href="([^"]+)"', line)
            if href_match:
                href = href_match.group(1)
                if href in seen_font_urls:
                    continue
                seen_font_urls.add(href)
            font_links_deduped.append(line)

    # Build slide pages
    slide_pages: list[str] = []
    for slide in slides:
        body = slide.get("body", "")
        slide_pages.append(
            f'<div class="slide-page">\n{body}\n</div>'
        )

    all_styles = "\n".join(merged_styles)
    all_links = "\n".join(font_links_deduped)
    all_pages = "\n\n".join(slide_pages)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=1280">
{all_links}
<style>
{_SHARED_STYLE}
@page {{
    size: 1280px 720px;
    margin: 0;
}}
.slide-page {{
    width: 1280px;
    height: 720px;
    position: relative;
    overflow: hidden;
    page-break-after: always;
    background: #FFFFFF;
}}
{all_styles}
</style>
</head>
<body>
{all_pages}
</body>
</html>"""


def _render_pdf_with_playwright(html_content: str, output_path: str) -> tuple[int, int]:
    """Render *html_content* to a PDF file using Playwright.

    Each ``.slide-page`` div becomes one 1280×720 landscape page in the PDF.
    For documents without ``.slide-page``, the content is rendered as a single
    page whose size matches the document's natural dimensions.

    Returns (page_count, file_size_bytes).
    """
    from playwright.sync_api import sync_playwright

    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False, encoding="utf-8"
    ) as tmp:
        tmp.write(html_content)
        tmp_path = tmp.name

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(
                viewport={"width": 1280, "height": 720},
                device_scale_factor=2,  # High DPI for crisp output
            )
            page.goto(f"file://{tmp_path}", wait_until="networkidle")

            # Wait for fonts to load
            page.wait_for_timeout(800)

            page.pdf(
                path=output_path,
                width="1280px",
                height="720px",
                print_background=True,
                margin={"top": "0", "right": "0", "bottom": "0", "left": "0"},
            )
            browser.close()
    finally:
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass

    file_size = os.path.getsize(output_path)
    page_count = _count_pdf_pages(output_path)

    return page_count, file_size


def _count_pdf_pages(pdf_path: str) -> int:
    """Count the number of pages in a PDF file by reading its raw bytes.

    Uses a simple regex heuristic: count ``/Type /Page`` objects that are
    NOT ``/Type /Pages`` (the container).  Falls back to 1 if uncertain.
    """
    with open(pdf_path, "rb") as f:
        data = f.read()

    # Count /Type /Page but not /Type /Pages
    pages_pattern = rb"/Type\s*/Page[^s]"
    matches = re.findall(pages_pattern, data)
    if matches:
        return len(matches)

    # Fallback: count page-break markers in the HTML source
    return 1
