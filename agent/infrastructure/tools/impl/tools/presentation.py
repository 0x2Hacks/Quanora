"""
HTML PPT & Document Generation Tools for Quanora Agent.

Provides two tool functions:
- generate_ppt_html: Create multi-slide PPT-style HTML files
- generate_doc_html: Create timeline-style document HTML files

Both tools write the output file to the workspace and return a tool_ok result.
"""

from __future__ import annotations

import html as html_mod
import os
import re
from datetime import datetime
from typing import Any

from agent.domain import tool_error, tool_ok

# ---------------------------------------------------------------------------
# Workspace helper
# ---------------------------------------------------------------------------

def _resolve_workspace_path(file_path: str) -> tuple[Any, str]:
    """Resolve *file_path* against the workspace root using WorkspaceGuard.

    Returns (guard, resolved_path) so the caller can also do boundary checks.
    """
    from agent.infrastructure.config.settings import get_workspace_guard
    guard = get_workspace_guard()
    path = guard.resolve_under_root(file_path)
    return guard, str(path)


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


# ===================================================================
#  PPT HTML Generation
# ===================================================================

_PPT_TITLE_TEMPLATE = """\
<!DOCTYPE html>
<html data-theme="light" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@400;700&display=swap" rel="stylesheet"/>
<style>
    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}
    body {{
        background-color: #FFFFFF;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }}
    .slide-container {{
        position: relative;
        width: 1280px;
        height: 720px;
        overflow: hidden;
        background: #1a3d32;
    }}
</style>
</head>
<body style="user-select: none;">
<div class="slide-container">
<!-- 左侧金色装饰条 -->
<div style="position: absolute; top: 0; left: 0; width: 6px; height: 720px; background: #D4A574;"></div>
<!-- 左侧区域：大标题 -->
<div style="position: absolute; top: 180px; left: 80px; width: 600px; height: 360px;">
<p style="font-family: 'Noto Serif SC', serif; font-weight: 700; font-size: 42px; color: #FFFFFF; line-height: 1.3; letter-spacing: 1px;">{title_line1}</p>
{title_line2}
<div style="width: 48px; height: 3px; background: #D4A574; margin-top: 28px;"></div>
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 16px; color: #D4A574; margin-top: 20px; line-height: 1.6; max-width: 500px;">{subtitle}</p>
</div>
<!-- 右侧区域：信息卡片 -->
<div style="position: absolute; top: 200px; left: 760px; width: 460px; height: 300px;">
<!-- 日期 -->
<div style="margin-bottom: 24px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 2px; color: #D4A574; text-transform: uppercase;">DATE</p>
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 15px; color: rgba(255,255,255,0.8); margin-top: 6px;">{date}</p>
</div>
<!-- 目标受众 -->
<div style="margin-bottom: 24px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 2px; color: #D4A574; text-transform: uppercase;">TARGET</p>
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 15px; color: rgba(255,255,255,0.8); margin-top: 6px;">{target}</p>
</div>
<!-- 版本 -->
<div style="margin-bottom: 24px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 2px; color: #D4A574; text-transform: uppercase;">VERSION</p>
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 15px; color: rgba(255,255,255,0.8); margin-top: 6px;">{version}</p>
</div>
<!-- 作者 -->
<div>
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 2px; color: #D4A574; text-transform: uppercase;">AUTHOR</p>
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 15px; color: rgba(255,255,255,0.8); margin-top: 6px;">{author}</p>
</div>
</div>
<!-- 底部装饰线 -->
<div style="position: absolute; bottom: 40px; left: 80px; width: 1120px; height: 1px; background: rgba(212,165,116,0.3);"></div>
<!-- 底部标识 -->
<div style="position: absolute; bottom: 18px; left: 80px; width: 1120px; height: 20px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 11px; color: rgba(255,255,255,0.3); text-align: right; letter-spacing: 1px;">{tag_line}</p>
</div>
</div>
</body>
</html>
"""

_PPT_CONTENT_TEMPLATE = """\
<!DOCTYPE html>
<html data-theme="light" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{slide_title}</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@400;700&display=swap" rel="stylesheet"/>
<style>
    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}
    body {{
        background-color: #FFFFFF;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }}
    .slide-container {{
        position: relative;
        width: 1280px;
        height: 720px;
        overflow: hidden;
        background: #FFFFFF;
    }}
</style>
</head>
<body style="user-select: none;">
<div class="slide-container">
<!-- 章节标签 -->
<div style="position: absolute; top: 30px; left: 40px; width: 400px; height: 20px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 2px; color: #A3A3A3; text-transform: uppercase;">{section_label}</p>
</div>
<!-- 顶部装饰线 -->
<div style="position: absolute; top: 56px; left: 40px; width: 1200px; height: 1px; background: #E5E7EB;"></div>
<!-- 左侧面板 -->
<div style="position: absolute; top: 76px; left: 40px; width: 360px; height: 560px;">
<p style="font-family: 'Noto Serif SC', serif; font-weight: 700; font-size: 24px; color: #0A0A0A; line-height: 1.3;">{left_title}</p>
{left_subtitle}
</div>
<!-- 左侧分隔线 -->
<div style="position: absolute; top: 76px; left: 420px; width: 1px; height: 560px; background: #E5E7EB;"></div>
<!-- 右侧面板 -->
<div style="position: absolute; top: 76px; left: 450px; width: 790px; height: 560px;">
{right_content}
</div>
<!-- 底部分隔线 -->
<div style="position: absolute; bottom: 50px; left: 40px; width: 1200px; height: 1px; background: #E5E7EB;"></div>
<!-- 页脚 -->
<div style="position: absolute; bottom: 14px; left: 40px; width: 1200px; height: 20px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 10px; color: #6B7280;">{footer_text}</p>
</div>
</div>
</body>
</html>
"""

_PPT_END_TEMPLATE = """\
<!DOCTYPE html>
<html data-theme="light" lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>End</title>
<link rel="preconnect" href="https://fonts.googleapis.com"/>
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@400;500;700&family=Noto+Serif+SC:wght@400;700&display=swap" rel="stylesheet"/>
<style>
    * {{
        margin: 0;
        padding: 0;
        box-sizing: border-box;
    }}
    body {{
        background-color: #FFFFFF;
        margin: 0;
        padding: 0;
        overflow: hidden;
    }}
    .slide-container {{
        position: relative;
        width: 1280px;
        height: 720px;
        overflow: hidden;
        background: #1a3d32;
    }}
</style>
</head>
<body style="user-select: none;">
<div class="slide-container">
<!-- 左侧金色装饰条 -->
<div style="position: absolute; top: 0; left: 0; width: 6px; height: 720px; background: #D4A574;"></div>
<!-- 居中内容 -->
<div style="position: absolute; top: 0; left: 0; width: 1280px; height: 720px; display: flex; flex-direction: column; align-items: center; justify-content: center;">
<p style="font-family: 'Noto Serif SC', serif; font-weight: 700; font-size: 48px; color: #FFFFFF; letter-spacing: 2px;">{end_text}</p>
<div style="width: 48px; height: 3px; background: #D4A574; margin-top: 28px;"></div>
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 16px; color: #D4A574; margin-top: 20px; line-height: 1.6; max-width: 500px; text-align: center;">{end_subtitle}</p>
</div>
<!-- 底部装饰线 -->
<div style="position: absolute; bottom: 40px; left: 80px; width: 1120px; height: 1px; background: rgba(212,165,116,0.3);"></div>
<!-- 底部标识 -->
<div style="position: absolute; bottom: 18px; left: 80px; width: 1120px; height: 20px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 11px; color: rgba(255,255,255,0.3); text-align: right; letter-spacing: 1px;">{tag_line}</p>
</div>
</div>
</body>
</html>
"""

def _build_right_content(
    case_title: str,
    case_subtitle: str,
    points: list[str],
) -> str:
    """Build the right-side content area for a content slide.

    Layout matches html_format.txt reference:
    - Right title (Noto Sans SC 700, 20px)
    - Right subtitle (Noto Sans SC 400, 13px, #6B7280)
    - Points as bullet items with custom dot markers
    """
    parts: list[str] = []

    # Right title
    if case_title:
        parts.append(
            "<p style=\"font-family: 'Noto Sans SC', sans-serif; font-weight: 700; "
            "font-size: 20px; color: #0A0A0A; margin-bottom: 6px;\">"
            + case_title
            + "</p>"
        )

    # Right subtitle
    if case_subtitle:
        parts.append(
            "<p style=\"font-family: 'Noto Sans SC', sans-serif; font-weight: 400; "
            "font-size: 13px; color: #6B7280; margin-bottom: 20px; line-height: 1.5;\">"
            + case_subtitle
            + "</p>"
        )

    # Points with styled dot markers
    if points:
        for pt in points:
            safe_pt = html_mod.escape(pt)
            parts.append(
                '<div style="display: flex; align-items: flex-start; margin-bottom: 12px;">'
                '<div style="width: 6px; height: 6px; border-radius: 50%; background: #1a3d32; '
                'margin-top: 7px; margin-right: 10px; flex-shrink: 0;"></div>'
                "<p style=\"font-family: 'Noto Sans SC', sans-serif; font-weight: 400; "
                "font-size: 13px; color: #374151; line-height: 1.6; margin: 0;\">"
                + safe_pt
                + "</p></div>"
            )

    return "\n".join(parts)

def generate_ppt_html(
    file_path: str,
    title: str,
    subtitle: str = "",
    author: str = "",
    date: str = "",
    target: str = "",
    version: str = "",
    slides: list[dict[str, Any]] | None = None,
    end_text: str = "THANK YOU",
    end_subtitle: str = "",
) -> dict:
    """Generate a PPT-style HTML presentation file.

    Each slide is rendered as a 1280×720 px container.  The file is written
    to *file_path* (relative to workspace root).

    Parameters
    ----------
    file_path : str
        Output HTML file path (relative to workspace root).
    title : str
        Presentation title (shown on title slide).
    subtitle : str
        Subtitle shown below the main title.
    author : str
        Author name shown on title slide.
    date : str
        Date string shown on title slide.
    target : str
        Target audience (shown on title slide right panel).
    version : str
        Version string (shown on title slide right panel).
    slides : list[dict]
        List of content slides.  Each dict may contain:
          - section_label (str): e.g. "02 / 风险全景"
          - left_title (str): Large text on dark left panel
          - left_subtitle (str): Small text on dark left panel
          - right_title (str): Category label above right content
          - right_subtitle (str): Bold heading on right side
          - points (list[str]): Bullet points on right side
    end_text : str
        Text for the final slide (default "THANK YOU").
    end_subtitle : str
        Subtitle for the final slide.

    Returns
    -------
    dict
        tool_ok / tool_error result.
    """
    try:
        guard, resolved = _resolve_workspace_path(file_path)
        _ensure_dir(resolved)

        # Workspace boundary check
        violation = guard.check_write(resolved)
        if violation is not None:
            return tool_error(
                "generate_ppt_html",
                f"WORKSPACE BOUNDARY VIOLATION: {violation.reason} | Fix: {violation.suggested_fix}",
                "WorkspaceViolation",
                meta={"path": str(violation.path)},
            )

        # --- Build title slide ---
        # Auto-split title into two lines if it's long
        title_len = len(title)
        if title_len > 14:
            mid = title_len // 2
            # Try to split at a natural break
            for offset in range(min(5, mid)):
                if mid + offset < title_len and title[mid + offset] in " ·—–,，":
                    mid = mid + offset + 1
                    break
                if mid - offset > 0 and title[mid - offset] in " ·—–,，":
                    mid = mid - offset + 1
                    break
            title_line1 = html_mod.escape(title[:mid])
            title_line2 = html_mod.escape(title[mid:])
        else:
            title_line1 = html_mod.escape(title)
            title_line2 = ""

        tag_line = html_mod.escape(title.upper()[:60])

        title_html = _PPT_TITLE_TEMPLATE.format(
            title=html_mod.escape(title),
            tag_line=tag_line,
            title_line1=title_line1,
            title_line2=title_line2,
            subtitle=html_mod.escape(subtitle),
            date=html_mod.escape(date),
            target=html_mod.escape(target),
            version=html_mod.escape(version),
            author=html_mod.escape(author),
        )

        # --- Build content slides ---
        content_slides_html = ""
        if slides:
            for idx, sl in enumerate(slides):
                section_label = html_mod.escape(sl.get("section_label", f"{idx+2:02d}"))
                left_title = html_mod.escape(sl.get("left_title", ""))
                left_subtitle = html_mod.escape(sl.get("left_subtitle", ""))
                right_title = html_mod.escape(sl.get("right_title", ""))
                right_subtitle = html_mod.escape(sl.get("right_subtitle", ""))
                points = sl.get("points", [])

                right_content = _build_right_content(right_title, right_subtitle, points)

                slide_html = _PPT_CONTENT_TEMPLATE.format(
                    slide_title=html_mod.escape(sl.get("left_title", f"Slide {idx+2}")),
                    section_label=section_label,
                    left_title=left_title,
                    left_subtitle=left_subtitle,
                    right_content=right_content,
                    footer_text=html_mod.escape(title),
                )
                content_slides_html += "\n" + slide_html

        # --- Build end slide ---
        end_html = _PPT_END_TEMPLATE.format(
            end_text=html_mod.escape(end_text),
            end_subtitle=html_mod.escape(end_subtitle),
            tag_line=tag_line,
        )

        # --- Combine all slides into one file ---
        full_html = title_html + content_slides_html + end_html

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(full_html)

        slide_count = 1 + (len(slides) if slides else 0) + 1  # title + content + end
        return tool_ok(
            "generate_ppt_html",
            f"Generated PPT HTML with {slide_count} slides → {file_path}",
            meta={"file_path": file_path, "slide_count": slide_count, "bytes": len(full_html)},
        )
    except Exception as exc:
        return tool_error("generate_ppt_html", f"generate_ppt_html failed: {exc}", type(exc).__name__)


# ===================================================================
#  Document HTML Generation
# ===================================================================

_DOC_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>{doc_title}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&family=Noto+Serif+SC:wght@400;600;700;900&display=swap" rel="stylesheet"/>
<link href="https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.4.0/css/all.min.css" rel="stylesheet"/>
<style>
    * {{ margin: 0; padding: 0; box-sizing: border-box; }}
    body {{
        margin: 0;
        padding: 0;
        background: #FFFFFF;
        -webkit-font-smoothing: antialiased;
    }}
    .doc-page {{
        width: 1280px;
        height: 720px;
        position: relative;
        overflow: hidden;
        background: #FFFFFF;
        font-family: 'Noto Sans SC', sans-serif;
    }}
    .doc-left-panel {{
        position: absolute;
        top: 0; left: 0;
        width: 380px; height: 720px;
        background: #0A0A0A;
        padding: 60px 40px;
        display: flex;
        flex-direction: column;
        justify-content: center;
    }}
    .doc-left-panel .section-tag {{
        display: inline-block;
        font-family: 'Noto Sans SC', sans-serif;
        font-weight: 500;
        font-size: 11px;
        color: #1a3d32;
        background: rgba(26,61,50,0.15);
        border: 1px solid rgba(26,61,50,0.3);
        padding: 4px 14px;
        border-radius: 20px;
        letter-spacing: 2px;
        text-transform: uppercase;
        margin-bottom: 24px;
        width: fit-content;
    }}
    .doc-left-panel h1 {{
        font-family: 'Noto Serif SC', serif;
        font-weight: 900;
        font-size: 42px;
        color: #FFFFFF;
        line-height: 1.25;
        margin-bottom: 16px;
    }}
    .doc-left-panel .subtitle {{
        font-family: 'Noto Sans SC', sans-serif;
        font-weight: 300;
        font-size: 14px;
        color: #A3A3A3;
        line-height: 1.6;
    }}
    .doc-left-panel .deco-line {{
        width: 60px; height: 4px;
        background: #1a3d32;
        border-radius: 2px;
        margin-bottom: 28px;
    }}
    .doc-right-panel {{
        position: absolute;
        top: 0; left: 380px; right: 0; bottom: 0;
        padding: 48px 48px 80px 48px;
        overflow-y: auto;
    }}
    .doc-right-panel::before {{
        content: '';
        position: absolute;
        top: 40px; left: 0;
        width: 1px; height: calc(100% - 80px);
        background: #E5E7EB;
    }}
    .cards-grid {{
        display: grid;
        grid-template-columns: repeat(2, 1fr);
        gap: 20px;
    }}
    .cards-grid.single-column {{
        grid-template-columns: 1fr;
    }}
    .content-card {{
        background: #FAFAFA;
        border-radius: 10px;
        padding: 22px 20px;
        position: relative;
        border-left: 3px solid #1a3d32;
        transition: transform 0.2s ease, box-shadow 0.2s ease;
    }}
    .content-card:hover {{
        transform: translateY(-2px);
        box-shadow: 0 6px 20px rgba(0,0,0,0.06);
    }}
    .content-card.highlight {{
        border-left-color: #D4A574;
        background: #FFFBF5;
    }}
    .card-header {{
        display: flex;
        align-items: center;
        gap: 10px;
        margin-bottom: 10px;
    }}
    .card-day-label {{
        font-family: 'Noto Sans SC', sans-serif;
        font-weight: 700;
        font-size: 10px;
        color: #1a3d32;
        background: #E8F0ED;
        padding: 3px 10px;
        border-radius: 10px;
        letter-spacing: 1px;
    }}
    .content-card.highlight .card-day-label {{
        color: #D4A574;
        background: #FFF3E6;
    }}
    .card-number {{
        width: 24px; height: 24px;
        border-radius: 50%;
        background: #1a3d32;
        color: #FFFFFF;
        font-family: 'Noto Sans SC', sans-serif;
        font-weight: 700;
        font-size: 11px;
        display: flex;
        align-items: center;
        justify-content: center;
        margin-left: auto;
    }}
    .content-card.highlight .card-number {{
        background: #D4A574;
    }}
    .card-icon {{
        font-size: 16px;
        color: #1a3d32;
        margin-bottom: 6px;
    }}
    .content-card.highlight .card-icon {{
        color: #D4A574;
    }}
    .card-title {{
        font-family: 'Noto Serif SC', serif;
        font-weight: 700;
        font-size: 14px;
        color: #0A0A0A;
        line-height: 1.3;
        margin-bottom: 6px;
    }}
    .card-desc {{
        font-family: 'Noto Sans SC', sans-serif;
        font-weight: 400;
        font-size: 12px;
        color: #4B5563;
        line-height: 1.6;
    }}
    .card-highlight-tag {{
        display: inline-block;
        font-family: 'Noto Sans SC', sans-serif;
        font-weight: 500;
        font-size: 10px;
        color: #D4A574;
        background: #FFF3E6;
        padding: 2px 8px;
        border-radius: 4px;
        margin-top: 8px;
    }}
    .doc-insight-bar {{
        position: absolute;
        bottom: 20px; left: 380px; right: 0;
        padding: 0 48px;
    }}
    .doc-insight-inner {{
        background: #F9FAFB;
        border-left: 3px solid #1a3d32;
        border-radius: 0 8px 8px 0;
        padding: 10px 16px;
    }}
    .doc-insight-inner .insight-label {{
        font-family: 'Noto Sans SC', sans-serif;
        font-weight: 700;
        font-size: 10px;
        color: #1a3d32;
        letter-spacing: 1px;
        text-transform: uppercase;
        margin-bottom: 2px;
    }}
    .doc-insight-inner .insight-text {{
        font-family: 'Noto Sans SC', sans-serif;
        font-weight: 400;
        font-size: 11px;
        color: #4B5563;
        line-height: 1.4;
    }}
    .doc-footer {{
        position: absolute;
        bottom: 12px; left: 40px;
        font-family: 'Noto Sans SC', sans-serif;
        font-weight: 400;
        font-size: 9px;
        color: #4B5563;
    }}
</style>
</head>
<body>
<div class="doc-page" data-object="doc-page">
    <div class="doc-left-panel" data-object="left-panel">
        <div class="section-tag" data-object="section-tag">{section_label}</div>
        <div class="deco-line" data-object="deco-line"></div>
        <h1 data-object="title">{title}</h1>
        <p class="subtitle" data-object="subtitle">{subtitle}</p>
    </div>
    <div class="doc-right-panel" data-object="right-panel">
        <div class="cards-grid {grid_class}" data-object="cards-grid">
            {timeline_items_html}
        </div>
    </div>
    <div class="doc-insight-bar" data-object="insight-bar">
        <div class="doc-insight-inner">
            <div class="insight-label">Insight</div>
            <div class="insight-text">{item_count} items · {gen_date}</div>
        </div>
    </div>
    <div class="doc-footer" data-object="footer">Generated by Quanora</div>
</div>
</body>
</html>"""

_TIMELINE_ITEM_TEMPLATE = """\
<!-- {day_label} -->
<div class="content-card {highlight_class}" data-object="card-{card_index}">
    <div class="card-header">
        <span class="card-day-label">{day_label}</span>
        <span class="card-number">{circle_number}</span>
    </div>
    <div class="card-icon"><i class="{icon_class}"></i></div>
    <div class="card-title">{item_title}</div>
    <div class="card-desc">{item_desc}</div>
    {highlight_tag}
</div>"""


def generate_doc_html(
    file_path: str,
    title: str,
    subtitle: str = "",
    section_label: str = "",
    timeline_items: list[dict[str, Any]] | None = None,
) -> dict:
    """Generate a PPT-style document HTML file.

    Each page is a 1280×720 px container with a left dark panel
    and right content cards grid.

    Parameters
    ----------
    file_path : str
        Output HTML file path (relative to workspace root).
    title : str
        Document title.
    subtitle : str
        Subtitle below the title.
    section_label : str
        Section label shown at top-left (e.g. "03 / 攻击拆解").
    timeline_items : list[dict]
        List of content entries.  Each dict may contain:
          - day_label (str): e.g. "DAY 01", "Phase 1"
          - number (int/str): Number in the circle badge
          - icon (str): FontAwesome icon class, e.g. "fa-solid fa-crosshairs"
          - item_title (str): Bold title for the card
          - description (str): Description text
          - highlight (bool or str): If True, use accent style; if str, use
            accent style and show the string as a highlight tag

    Returns
    -------
    dict
        tool_ok / tool_error result.
    """
    try:
        guard, resolved = _resolve_workspace_path(file_path)
        _ensure_dir(resolved)

        # Workspace boundary check
        violation = guard.check_write(resolved)
        if violation is not None:
            return tool_error(
                "generate_doc_html",
                f"WORKSPACE BOUNDARY VIOLATION: {violation.reason} | Fix: {violation.suggested_fix}",
                "WorkspaceViolation",
                meta={"path": str(violation.path)},
            )

        # Build timeline items HTML
        items_html_parts: list[str] = []
        if timeline_items:
            for idx, item in enumerate(timeline_items):
                day_label = html_mod.escape(str(item.get("day_label", f"#{idx+1}")))
                number = item.get("number", idx + 1)
                icon_class = html_mod.escape(item.get("icon", "fa-solid fa-circle"))
                item_title = html_mod.escape(str(item.get("item_title", "")))
                item_desc = html_mod.escape(str(item.get("description", "")))
                highlight = item.get("highlight", False)

                highlight_class = "highlight" if highlight else ""
                highlight_tag_html = (
                    f'<span class="card-highlight-tag">{html_mod.escape(str(highlight))}</span>'
                    if highlight and isinstance(highlight, str)
                    else ""
                )

                item_html = _TIMELINE_ITEM_TEMPLATE.format(
                    day_label=day_label,
                    highlight_class=highlight_class,
                    card_index=idx,
                    circle_number=html_mod.escape(str(number)),
                    icon_class=icon_class,
                    item_title=item_title,
                    item_desc=item_desc,
                    highlight_tag=highlight_tag_html,
                )
                items_html_parts.append(item_html)

        timeline_items_html = "\n".join(items_html_parts)
        grid_class = "single-column" if timeline_items and len(timeline_items) <= 2 else ""
        item_count = len(timeline_items) if timeline_items else 0
        gen_date = datetime.now().strftime("%Y-%m-%d")

        doc_html = _DOC_TEMPLATE.format(
            doc_title=html_mod.escape(title),
            section_label=html_mod.escape(section_label),
            title=html_mod.escape(title),
            subtitle=html_mod.escape(subtitle),
            timeline_items_html=timeline_items_html,
            grid_class=grid_class,
            item_count=item_count,
            gen_date=gen_date,
        )

        with open(resolved, "w", encoding="utf-8") as f:
            f.write(doc_html)

        item_count = len(timeline_items) if timeline_items else 0
        return tool_ok(
            "generate_doc_html",
            f"Generated document HTML with {item_count} timeline items → {file_path}",
            meta={"file_path": file_path, "item_count": item_count, "bytes": len(doc_html)},
        )
    except Exception as exc:
        return tool_error("generate_doc_html", f"generate_doc_html failed: {exc}", type(exc).__name__)


# ===================================================================
#  HTML → PDF Conversion
# ===================================================================

# Page size matching our 1280×720 slide design, converted to mm at 96 DPI.
# 1280px / 96 * 25.4 ≈ 338.67mm,  720px / 96 * 25.4 ≈ 190.5mm
_PDF_PAGE_WIDTH_MM = 338.67
_PDF_PAGE_HEIGHT_MM = 190.50

_PDF_WRAPPER_TEMPLATE = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>{title}</title>
<style>
@page {{
    size: 1280px 720px;
    margin: 0;
}}
html, body {{
    margin: 0;
    padding: 0;
    background: #FFFFFF;
    -webkit-print-color-adjust: exact;
    print-color-adjust: exact;
}}
.slide-page {{
    width: 1280px;
    height: 720px;
    page-break-after: always;
    page-break-inside: avoid;
    break-after: page;
    break-inside: avoid;
    overflow: hidden;
    position: relative;
    box-sizing: border-box;
}}
.slide-page:last-child {{
    page-break-after: auto;
    break-after: auto;
}}
</style>
{head_extras}
</head>
<body>
{slide_pages}
</body>
</html>"""


def _split_multi_doctype_html(html_content: str) -> list[dict[str, str]]:
    """Split a multi-DOCTYPE HTML file into individual slide parts.

    Returns a list of dicts with keys:
      - ``body``: the inner content of each <body> tag
      - ``style``: any <style> content from each <head> tag (first occurrence used)
      - ``link``: any <link> tags from the <head>
    """
    # Split on DOCTYPE boundaries
    parts = re.split(r"<!DOCTYPE\s+html\s*>", html_content, flags=re.IGNORECASE)
    slides: list[dict[str, str]] = []

    for part in parts:
        part = part.strip()
        if not part:
            continue

        # Extract <body>…</body> content
        body_match = re.search(
            r"<body[^>]*>(.*?)</body>", part, re.DOTALL | re.IGNORECASE
        )
        if not body_match:
            continue

        body_content = body_match.group(1).strip()
        if not body_content:
            continue

        # Extract <style>…</style> from <head>
        style_match = re.search(
            r"<style[^>]*>(.*?)</style>", part, re.DOTALL | re.IGNORECASE
        )
        style_content = style_match.group(1).strip() if style_match else ""

        # Extract <link> tags (e.g., fonts, icons)
        link_tags = re.findall(r"<link[^>]+/>", part, re.IGNORECASE)
        link_html = "\n".join(link_tags)

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

    for sl in slides:
        if sl["style"]:
            # Normalise whitespace for dedup
            key = re.sub(r"\s+", " ", sl["style"]).strip()
            if key not in seen_styles:
                seen_styles.add(key)
                merged_styles.append(sl["style"])
        if sl["link"]:
            for tag in sl["link"].split("\n"):
                tag = tag.strip()
                if tag and tag not in link_tags:
                    link_tags.append(tag)

    # Build slide pages HTML
    slide_pages_parts: list[str] = []
    for sl in slides:
        slide_pages_parts.append(
            f'<div class="slide-page">\n{sl["body"]}\n</div>'
        )

    slide_pages_html = "\n".join(slide_pages_parts)
    head_extras = "\n".join(link_tags)
    if merged_styles:
        head_extras += "\n<style>\n" + "\n".join(merged_styles) + "\n</style>"

    return _PDF_WRAPPER_TEMPLATE.format(
        title=html_mod.escape(title),
        head_extras=head_extras,
        slide_pages=slide_pages_html,
    )


def convert_html_to_pdf(
    file_path: str,
    output_path: str = "",
) -> dict:
    """Convert an HTML file (generated by generate_ppt_html or generate_doc_html)
    to a PDF file, preserving the exact layout and styling.

    The function handles multi-DOCTYPE HTML files (where each slide is a
    separate HTML document) by recombining them into a single paginated
    document with CSS ``@page`` rules and ``page-break-after``.

    Uses Playwright (headless Chromium) for pixel-perfect rendering.

    Parameters
    ----------
    file_path : str
        Input HTML file path (relative to workspace root).
    output_path : str
        Output PDF file path (relative to workspace root).
        If empty, replaces the input extension with ``.pdf``.

    Returns
    -------
    dict
        tool_ok / tool_error result with metadata including page count and bytes.
    """
    try:
        guard, resolved_input = _resolve_workspace_path(file_path)

        if not output_path:
            base, _ = os.path.splitext(file_path)
            output_path = base + ".pdf"
        guard_out, resolved_output = _resolve_workspace_path(output_path)

        # Workspace boundary checks
        violation = guard.check_write(resolved_output)
        if violation is not None:
            return tool_error(
                "convert_html_to_pdf",
                f"WORKSPACE BOUNDARY VIOLATION: {violation.reason} | Fix: {violation.suggested_fix}",
                "WorkspaceViolation",
                meta={"path": str(violation.path)},
            )

        if not os.path.isfile(resolved_input):
            return tool_error(
                "convert_html_to_pdf",
                f"Input file not found: {file_path}",
                "FileNotFound",
            )

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
            # Single-DOCTYPE doc HTML → inject @page CSS
            single_html = _inject_page_css(html_content)

        # Ensure output directory exists
        _ensure_dir(resolved_output)

        # Render with Playwright
        page_count, pdf_bytes = _render_pdf_with_playwright(
            single_html, resolved_output
        )

        return tool_ok(
            "convert_html_to_pdf",
            f"Converted {file_path} → {output_path} ({page_count} pages, {pdf_bytes:,} bytes)",
            meta={
                "file_path": output_path,
                "page_count": page_count,
                "bytes": pdf_bytes,
                "input_file": file_path,
            },
        )
    except ImportError:
        return tool_error(
            "convert_html_to_pdf",
            "Playwright is not installed. Run: pip install playwright && playwright install chromium",
            "DependencyMissing",
        )
    except Exception as exc:
        return tool_error("convert_html_to_pdf", f"convert_html_to_pdf failed: {exc}", type(exc).__name__)


def _inject_page_css(html_content: str) -> str:
    """Inject @page CSS rules into a single-DOCTYPE HTML for proper PDF sizing.

    For documents generated by generate_doc_html (single page, 1280×720).
    """
    page_css = (
        f"@page {{ size: 1280px 720px; margin: 0; }}\n"
        "html, body { margin: 0 !important; padding: 0 !important; "
        "-webkit-print-color-adjust: exact; "
        "print-color-adjust: exact; "
        "}\n"
    )

    if "</style>" in html_content:
        # Insert before the closing </style> tag
        html_content = html_content.replace(
            "</style>", page_css + "</style>", 1
        )
    else:
        # No <style> tag — inject one in <head>
        page_block = f"<style>\n{page_css}</style>"
        if "</head>" in html_content:
            html_content = html_content.replace(
                "</head>", page_block + "\n</head>", 1
            )
        else:
            html_content = page_block + html_content

    return html_content


def _render_pdf_with_playwright(html_content: str, output_path: str) -> tuple[int, int]:
    """Render *html_content* to a PDF file using Playwright.

    Returns (page_count, file_size_bytes).
    """
    from playwright.sync_api import sync_playwright

    # Convert html_content to a file:// URI for Playwright
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
            page.wait_for_timeout(500)

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
    # Count pages by reading PDF metadata (simple heuristic)
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
    # In well-formed PDFs, each page has /Type /Page
    pages_pattern = rb"/Type\s*/Page[^s]"
    matches = re.findall(pages_pattern, data)
    if matches:
        return len(matches)

    # Fallback: count page-break markers in the HTML source
    return 1
