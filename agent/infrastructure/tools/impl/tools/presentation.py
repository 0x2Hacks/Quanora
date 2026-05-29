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
            background-color: #FFFFFF;
        }}
    </style>
</head>
<body style="user-select: none;">
<div class="slide-container">
<!-- 左侧深色大标题区域 -->
<div data-object="true" data-object-type="shape" style="position: absolute; top: 0px; left: 0px; width: 700px; height: 720px; background: linear-gradient(135deg, #0A0A0A 0%, #2D2D2D 100%);"></div>
<!-- 顶部细装饰线 -->
<div data-object="true" data-object-type="shape" style="position: absolute; top: 80px; left: 60px; width: 60px; height: 3px; background-color: #FFFFFF;"></div>
<!-- 英文小标题 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 100px; left: 60px; width: 600px; height: 30px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 3px; color: #FFFFFF; opacity: 0.6;">{tag_line}</p>
</div>
<!-- 主标题 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 160px; left: 60px; width: 600px; height: 180px;">
<p style="font-family: 'Noto Serif SC', serif; font-weight: 900; font-size: 48px; color: #FFFFFF; line-height: 1.3; letter-spacing: 2px;">{title_line1}</p>
<p style="font-family: 'Noto Serif SC', serif; font-weight: 900; font-size: 48px; color: #FFFFFF; line-height: 1.3; letter-spacing: 2px; margin-top: 8px;">{title_line2}</p>
</div>
<!-- 副标题 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 380px; left: 60px; width: 600px; height: 40px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 18px; color: #FFFFFF; opacity: 0.7; letter-spacing: 1px;">{subtitle}</p>
</div>
<!-- 日期 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 460px; left: 60px; width: 200px; height: 30px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 500; font-size: 16px; color: #FFFFFF; opacity: 0.5;">{date}</p>
</div>
<!-- 右侧信息区 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 200px; left: 760px; width: 460px; height: 30px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 3px; color: #0A0A0A; opacity: 0.3;">TARGET</p>
</div>
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 230px; left: 760px; width: 460px; height: 30px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 500; font-size: 16px; color: #0A0A0A; opacity: 0.7;">{target}</p>
</div>
<div data-object="true" data-object-type="shape" style="position: absolute; top: 280px; left: 760px; width: 30px; height: 1px; background-color: #0A0A0A; opacity: 0.2;"></div>
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 300px; left: 760px; width: 460px; height: 30px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 3px; color: #0A0A0A; opacity: 0.3;">VERSION</p>
</div>
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 330px; left: 760px; width: 460px; height: 30px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 500; font-size: 16px; color: #0A0A0A; opacity: 0.7;">{version}</p>
</div>
<div data-object="true" data-object-type="shape" style="position: absolute; top: 380px; left: 760px; width: 30px; height: 1px; background-color: #0A0A0A; opacity: 0.2;"></div>
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 400px; left: 760px; width: 460px; height: 30px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 3px; color: #0A0A0A; opacity: 0.3;">AUTHOR</p>
</div>
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 430px; left: 760px; width: 460px; height: 30px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 500; font-size: 16px; color: #0A0A0A; opacity: 0.7;">{author}</p>
</div>
</div>
</body>
</html>"""

_PPT_CONTENT_TEMPLATE = """\
<!DOCTYPE html>

<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<meta content="width=device-width, initial-scale=1.0" name="viewport"/>
<title>{slide_title}</title>
<link href="https://fonts.googleapis.com/css2?family=Noto+Sans+SC:wght@300;400;500;700&family=Noto+Serif+SC:wght@400;600;700;900&display=swap" rel="stylesheet"/>
<style>
        body {{
            margin: 0;
            padding: 0;
            overflow: hidden;
            background-color: #FFFFFF;
        }}
        .slide-container {{
            position: relative;
            width: 1280px;
            height: 720px;
            overflow: hidden;
            background-color: #FFFFFF;
        }}
    </style>
</head>
<body>
<div class="slide-container">
<!-- 左侧深色面板 -->
<div data-object="true" data-object-type="shape" style="position: absolute; top: 0px; left: 0px; width: 420px; height: 720px; background: linear-gradient(180deg, #0A0A0A 0%, #1A1A1A 100%);"></div>
<!-- 左侧章节小标签 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 60px; left: 50px; width: 320px; height: 25px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 3px; color: #FFFFFF; opacity: 0.5;">{section_label}</p>
</div>
<!-- 左侧大标题 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 110px; left: 50px; width: 320px; height: 200px;">
<p style="font-family: 'Noto Serif SC', serif; font-weight: 900; font-size: 36px; color: #FFFFFF; line-height: 1.3; letter-spacing: 1px;">{left_title}</p>
</div>
<!-- 左侧副标题 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 320px; left: 50px; width: 320px; height: 80px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 14px; color: #FFFFFF; opacity: 0.6; line-height: 1.6;">{left_subtitle}</p>
</div>
<!-- 右侧内容区 -->
{right_content}
</div>
</body>
</html>"""

_PPT_END_TEMPLATE = """\
<!DOCTYPE html>

<html lang="zh-CN">
<head>
<meta charset="utf-8"/>
<title>Thank You</title>
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
            background: linear-gradient(135deg, #0A0A0A 0%, #2D2D2D 100%);
        }}
    </style>
</head>
<body style="user-select: none;">
<div class="slide-container">
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 280px; left: 0px; width: 1280px; height: 80px; text-align: center;">
<p style="font-family: 'Noto Serif SC', serif; font-weight: 900; font-size: 56px; color: #FFFFFF; letter-spacing: 8px;">{end_text}</p>
</div>
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 400px; left: 0px; width: 1280px; height: 40px; text-align: center;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 18px; color: #FFFFFF; opacity: 0.5; letter-spacing: 2px;">{end_subtitle}</p>
</div>
</div>
</body>
</html>"""


def _build_right_content(
    case_title: str,
    case_subtitle: str,
    points: list[str],
) -> str:
    """Build the right-side content block for a PPT content slide."""
    # Build points HTML
    points_html = ""
    for pt in points:
        safe_pt = html_mod.escape(pt)
        points_html += (
            '<p style="font-family: \'Noto Sans SC\', sans-serif; font-weight: 400; '
            'font-size: 13px; color: #333333; line-height: 1.6; margin-top: 6px;">'
            f'· {safe_pt}</p>\n'
        )

    return f"""\
<!-- 右侧顶部标题区 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 60px; left: 480px; width: 740px; height: 30px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 2px; color: #0A0A0A; opacity: 0.4;">{html_mod.escape(case_title)}</p>
</div>
<!-- 右侧大标题 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 100px; left: 480px; width: 740px; height: 60px;">
<p style="font-family: 'Noto Serif SC', serif; font-weight: 700; font-size: 28px; color: #0A0A0A; line-height: 1.3;">{html_mod.escape(case_subtitle)}</p>
</div>
<!-- 右侧分割线 -->
<div data-object="true" data-object-type="shape" style="position: absolute; top: 175px; left: 480px; width: 60px; height: 2px; background-color: #0A0A0A;"></div>
<!-- 右侧要点列表 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 200px; left: 480px; width: 740px; height: 480px;">
{points_html}
</div>"""


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
                )
                content_slides_html += "\n" + slide_html

        # --- Build end slide ---
        end_html = _PPT_END_TEMPLATE.format(
            end_text=html_mod.escape(end_text),
            end_subtitle=html_mod.escape(end_subtitle),
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
        body {{
            margin: 0;
            padding: 0;
            overflow: hidden;
            background-color: #FFFFFF;
        }}
        .slide-container {{
            position: relative;
            width: 1280px;
            height: 720px;
            overflow: hidden;
            background-color: #FFFFFF;
        }}
        p {{ margin: 0; padding: 0; }}
    </style>
</head>
<body>
<div class="slide-container">
<!-- 章节小标签 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 40px; left: 60px; width: 200px; height: 20px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 14px; letter-spacing: 2px; color: #0A0A0A;">{section_label}</p>
</div>
<!-- 顶部粗分割线 -->
<div data-object="true" data-object-type="shape" style="position: absolute; top: 70px; left: 0px; width: 1280px; height: 2px; background-color: #0A0A0A;"></div>
<!-- 标题 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 100px; left: 60px; width: 1160px; height: 60px;">
<p style="font-family: 'Noto Serif SC', serif; font-weight: 900; font-size: 42px; letter-spacing: 1px; color: #0A0A0A; line-height: 1.2;">{title}</p>
</div>
<!-- 副标题 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 165px; left: 60px; width: 1160px; height: 35px;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 20px; color: #6B7280; line-height: 1.5;">{subtitle}</p>
</div>
<!-- 水平时间轴 -->
<div data-object="true" data-object-type="shape" style="position: absolute; top: 275px; left: 60px; width: 1160px; height: 2px; background-color: #0A0A0A; z-index: 1;"></div>
<!-- 时间线节点容器 -->
<div data-object="true" data-object-type="textbox" style="position: absolute; top: 225px; left: 60px; width: 1160px; height: 400px; display: flex; gap: 8px; z-index: 2;">
{timeline_items_html}
</div>
</div>
</body>
</html>"""

_TIMELINE_ITEM_TEMPLATE = """\
<!-- {day_label} -->
<div style="flex: 1; text-align: center; position: relative;">
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 700; font-size: 12px; letter-spacing: 2px; color: #A3A3A3;">{day_label}</p>
<div style="width: 40px; height: 40px; border-radius: 50%; background-color: {circle_bg}; border: 2px solid {circle_border}; display: flex; align-items: center; justify-content: center; margin: 8px auto 0 auto; box-sizing: border-box; z-index: 5; position: relative;">
<span style="font-family: 'Noto Serif SC', serif; font-weight: 900; font-size: 18px; color: {circle_text};">{circle_number}</span>
</div>
<div style="margin-top: 18px; border: 1px solid #E5E7EB; padding: 14px 10px; height: 260px; box-sizing: border-box; display: flex; flex-direction: column; background-color: {card_bg};">
<i class="{icon_class}" style="font-size: 20px; color: {icon_color}; margin: 0 auto;"></i>
<p style="font-family: 'Noto Serif SC', serif; font-weight: 700; font-size: 13px; color: {item_title_color}; margin-top: 10px;">{item_title}</p>
<p style="font-family: 'Noto Sans SC', sans-serif; font-weight: 400; font-size: 11px; color: #333333; line-height: 1.4; margin-top: 8px;">{item_desc}</p>
</div>
</div>"""


def generate_doc_html(
    file_path: str,
    title: str,
    subtitle: str = "",
    section_label: str = "",
    timeline_items: list[dict[str, Any]] | None = None,
) -> dict:
    """Generate a timeline-style document HTML file.

    Each page is a 1280×720 px container with a horizontal timeline.

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
        List of timeline entries.  Each dict may contain:
          - day_label (str): e.g. "DAY 01", "Phase 1"
          - number (int/str): Number in the circle
          - icon (str): FontAwesome icon class, e.g. "fa-solid fa-crosshairs"
          - item_title (str): Bold title under the icon
          - description (str): Description text
          - highlight (bool): If True, use dark background for this card

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

                if highlight:
                    circle_bg = "#0A0A0A"
                    circle_border = "#0A0A0A"
                    circle_text = "#FFFFFF"
                    card_bg = "#0A0A0A"
                    icon_color = "#FFFFFF"
                    item_title_color = "#FFFFFF"
                else:
                    circle_bg = "#FFFFFF"
                    circle_border = "#0A0A0A"
                    circle_text = "#0A0A0A"
                    card_bg = "#FFFFFF"
                    icon_color = "#0A0A0A"
                    item_title_color = "#0A0A0A"

                item_html = _TIMELINE_ITEM_TEMPLATE.format(
                    day_label=day_label,
                    circle_bg=circle_bg,
                    circle_border=circle_border,
                    circle_text=circle_text,
                    circle_number=html_mod.escape(str(number)),
                    card_bg=card_bg,
                    icon_class=icon_class,
                    icon_color=icon_color,
                    item_title=item_title,
                    item_title_color=item_title_color,
                    item_desc=item_desc,
                )
                items_html_parts.append(item_html)

        timeline_items_html = "\n".join(items_html_parts)

        doc_html = _DOC_TEMPLATE.format(
            doc_title=html_mod.escape(title),
            section_label=html_mod.escape(section_label),
            title=html_mod.escape(title),
            subtitle=html_mod.escape(subtitle),
            timeline_items_html=timeline_items_html,
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
    size: {width_mm}mm {height_mm}mm;
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
    overflow: hidden;
    position: relative;
    box-sizing: border-box;
}}
.slide-page:last-child {{
    page-break-after: auto;
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
        width_mm=_PDF_PAGE_WIDTH_MM,
        height_mm=_PDF_PAGE_HEIGHT_MM,
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
        f"@page {{ size: {_PDF_PAGE_WIDTH_MM}mm {_PDF_PAGE_HEIGHT_MM}mm; margin: 0; }}\n"
        "html, body { "
        "  -webkit-print-color-adjust: exact; "
        "  print-color-adjust: exact; "
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
                width=f"{_PDF_PAGE_WIDTH_MM}mm",
                height=f"{_PDF_PAGE_HEIGHT_MM}mm",
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
