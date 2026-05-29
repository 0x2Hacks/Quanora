---
name: "presentation"
description: "通过HTML生成PPT演示文稿和时间线文档。提供 generate_ppt_html 和 generate_doc_html 两个工具。"
triggers:
  - "生成PPT"
  - "做PPT"
  - "制作幻灯片"
  - "生成演示文稿"
  - "生成文档"
  - "时间线文档"
  - "generate PPT"
  - "make slides"
  - "create presentation"
  - "timeline document"
  - "做演示"
---

# Presentation & Document Generation Skill

When the user asks to create a PPT, slides, presentation, or a timeline-style
document/report, activate this skill.  It provides two tools:

| Tool | Purpose | Output |
|------|---------|--------|
| `generate_ppt_html` | Multi-slide PPT-style HTML (1280×720 px per slide) | `.html` file in workspace |
| `generate_doc_html` | Timeline-style document HTML (1280×720 px) | `.html` file in workspace |

Both tools write the result into the workspace as a self-contained HTML file
that can be opened in any browser or printed to PDF.

---

## Step-by-step Playbook

### Step 1 — Clarify the request

Ask the user (or infer from context):

- **Type**: PPT (slides) or Document (timeline)?
- **Topic / Title**: What is the presentation about?
- **Audience**: Who is it for?
- **Key sections / slides**: What content should each slide cover?

If the user says something vague like "make a PPT about X", propose a structure
yourself and confirm before generating.

### Step 2 — Choose the right tool

- **`generate_ppt_html`** — when the user wants:
  - A slide deck with a title page, multiple content slides, and an ending page
  - Visual presentations for meetings, pitches, or reports

- **`generate_doc_html`** — when the user wants:
  - A single-page timeline or roadmap document
  - Phase-by-phase breakdown (e.g., attack chain, project phases, roadmap)
  - Any content that fits a horizontal timeline with 3-7 items

### Step 3 — Prepare the content

#### For `generate_ppt_html`

Gather:
- **title** (str): Main title of the presentation
- **subtitle** (str): Subtitle or tagline
- **author** (str): Author or team name
- **date** (str): Date string
- **target** (str): Target audience
- **version** (str): Version number
- **slides** (list of dicts): Each content slide with:
  - `section_label`: e.g. "02 / 概述"
  - `left_title`: Large text on the dark left panel
  - `left_subtitle`: Small descriptive text on the left
  - `right_title`: Category label above right content
  - `right_subtitle`: Bold heading on the right
  - `points`: List of bullet-point strings
- **end_text** (str): Text for the final slide (default: "THANK YOU")
- **end_subtitle** (str): Subtitle on the final slide

Example call:
```
generate_ppt_html(
    file_path="output/pitch_deck.html",
    title="产品发布计划",
    subtitle="2026年度战略",
    author="张三",
    date="2026-06-01",
    target="管理层",
    version="v2.0",
    slides=[
        {
            "section_label": "02 / 市场",
            "left_title": "市场分析",
            "left_subtitle": "行业趋势与机会",
            "right_title": "市场",
            "right_subtitle": "市场规模与增长",
            "points": ["全球市场规模达5000亿", "年增长率15%", "亚太地区增速最快"],
        },
        {
            "section_label": "03 / 产品",
            "left_title": "产品路线图",
            "left_subtitle": "核心功能迭代",
            "right_title": "路线图",
            "right_subtitle": "Q3-Q4 发布计划",
            "points": ["Q3: 核心引擎上线", "Q4: 国际化支持", "年底: AI集成"],
        },
    ],
    end_text="THANK YOU",
    end_subtitle="联系方式: zhangsan@example.com",
)
```

#### For `generate_doc_html`

Gather:
- **title** (str): Document title
- **subtitle** (str): Subtitle
- **section_label** (str): Section label (e.g. "03 / 攻击拆解")
- **timeline_items** (list of dicts): Each item with:
  - `day_label`: e.g. "DAY 01", "Phase 1"
  - `number`: Number displayed in the circle
  - `icon`: FontAwesome icon class (e.g. "fa-solid fa-crosshairs")
  - `item_title`: Bold title under the icon
  - `description`: Description text
  - `highlight` (bool): If True, use dark/highlighted card style

Example call:
```
generate_doc_html(
    file_path="output/attack_timeline.html",
    title="攻击链分析",
    subtitle="7天攻击事件全流程拆解",
    section_label="03 / 攻击拆解",
    timeline_items=[
        {"day_label": "DAY 01", "number": 1, "icon": "fa-solid fa-crosshairs", "item_title": "初始侦察", "description": "攻击者通过端口扫描识别目标开放服务", "highlight": True},
        {"day_label": "DAY 02", "number": 2, "icon": "fa-solid fa-key", "item_title": "凭证获取", "description": "通过钓鱼邮件获取初始访问凭证"},
        {"day_label": "DAY 03", "number": 3, "icon": "fa-solid fa-network-wired", "item_title": "横向移动", "description": "利用获取的凭证在内网中扩散"},
        {"day_label": "DAY 04", "number": 4, "icon": "fa-solid fa-server", "item_title": "权限提升", "description": "利用漏洞获取域管理员权限"},
    ],
)
```

### Step 4 — Generate and inform

1. Call the appropriate tool with all parameters.
2. After the file is generated, inform the user:
   - The file path
   - Number of slides (for PPT) or timeline items (for doc)
   - How to view it: "Open the HTML file in your browser, or print to PDF for sharing."

### Step 5 — Offer refinements

Common refinements the user may request:
- Add/remove slides or timeline items
- Change colors or highlight specific items
- Add more bullet points
- Change the title or section labels

Simply re-call the tool with updated parameters.

---

## Design Principles

The HTML templates use a **minimalist dark-and-white aesthetic**:

- **PPT slides**: Left dark panel (gradient `#0A0A0A → #2D2D2D`) with title, right white panel with content
- **Doc pages**: White background with a horizontal timeline, alternating white/dark cards for highlighted items
- **Fonts**: Noto Sans SC + Noto Serif SC (Chinese-optimized)
- **Icons**: FontAwesome 6 (for timeline items)

## Common FontAwesome Icons for Timeline Items

| Purpose | Icon Class |
|---------|-----------|
| Target/Recon | `fa-solid fa-crosshairs` |
| Key/Access | `fa-solid fa-key` |
| Network | `fa-solid fa-network-wired` |
| Server | `fa-solid fa-server` |
| Shield | `fa-solid fa-shield-halved` |
| Code | `fa-solid fa-code` |
| Bug | `fa-solid fa-bug` |
| Lock | `fa-solid fa-lock` |
| Warning | `fa-solid fa-triangle-exclamation` |
| Check | `fa-solid fa-circle-check` |
| Rocket | `fa-solid fa-rocket` |
| Chart | `fa-solid fa-chart-line` |
| Document | `fa-solid fa-file-lines` |
| User | `fa-solid fa-user` |
| Globe | `fa-solid fa-globe` |
