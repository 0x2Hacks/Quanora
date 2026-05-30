---
name: "presentation"
description: "通过HTML生成PPT演示文稿和PPT风格文档。提供 generate_ppt_html 和 generate_doc_html 两个工具。"
triggers:
  - "生成PPT"
  - "做PPT"
  - "制作幻灯片"
  - "生成演示文稿"
  - "生成文档"
  - "PPT文档"
  - "generate PPT"
  - "make slides"
  - "create presentation"
  - "PPT document"
  - "做演示"
---

# Presentation & Document Generation Skill

When the user asks to create a PPT, slides, presentation, or a PPT-style
document/report, activate this skill.  It provides two tools:

| Tool | Purpose | Output |
|------|---------|--------|
| `generate_ppt_html` | Multi-slide PPT-style HTML (1280×720 px per slide) | `.html` file in workspace |
| `generate_doc_html` | PPT-style document HTML (1280×720 px per page) | `.html` file in workspace |

Both tools write the result into the workspace as a self-contained HTML file
that can be opened in any browser or printed to PDF.

---

## ⚠ MANDATORY: Markdown Document Structure Rules

When you generate a Markdown document (`.md`) that will later be converted to
HTML, you **MUST** follow these structure rules. Violating any rule will cause
the HTML output to look wrong and the conversion to fail.

### Rule 1: Top-level sections MUST be numbered

Every `#` heading MUST have a number prefix in the format `N.` or `N、`:

```
✅ # 1. 摘要
✅ # 2. 研究背景
✅ # 3. 技术方案
❌ # 摘要          ← NO number
❌ # 一、摘要      ← Wrong format (use Arabic numerals)
❌ # Chapter 1     ← Wrong format (use N. not Chapter N)
```

### Rule 2: Sub-sections MUST use hierarchical numbering

Every `##` heading MUST use `N.N` format, every `###` MUST use `N.N.N` format:

```
✅ ## 1.1 核心概念
✅ ## 1.2 研究目标
✅ ### 1.2.1 主目标
✅ ### 1.2.2 子目标
❌ ## 核心概念      ← No number
❌ ## 1-1 核心概念  ← Wrong separator
❌ ### 1.1 核心概念 ← Level mismatch (should be ## 1.1)
```

### Rule 3: Numbering MUST be consecutive and consistent

- Section numbers must not skip: `1 → 2 → 3`, NOT `1 → 3 → 5`
- Sub-section numbers must be under the correct parent: `2.1, 2.2` under `2.`
- Do NOT mix numbered and unnumbered headings at the same level

### Rule 4: Maximum 3 levels of headings

Only use `#`, `##`, and `###`. Never use `####` or deeper.

### Rule 5: Reference template

Follow this template structure:

```markdown
# 1. 摘要
> Brief summary of the document

# 2. 研究背景
## 2.1 问题定义
## 2.2 相关工作

# 3. 技术方案
## 3.1 整体架构
### 3.1.1 数据层
### 3.1.2 逻辑层
## 3.2 核心算法

# 4. 实验结果
## 4.1 实验设置
## 4.2 结果分析

# 5. 总结与展望
```

---

## Step-by-step Playbook

### Step 1 — Clarify the request

Ask the user (or infer from context):

- **Type**: PPT (slides) or Document (multi-page)?
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
  - A multi-page PPT-style document (each page 1280×720 px)
  - Research reports, analysis documents, or structured overviews
  - Content organized in numbered sections with hierarchical structure

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
  - `day_label`: e.g. "DAY 01", "Phase 1", "01"
  - `number`: Optional numeric label
  - `icon`: Optional emoji or icon
  - `item_title`: Heading for this item
  - `description`: Body text
  - `highlight`: Optional highlight text

Example call:
```
generate_doc_html(
    file_path="output/attack_timeline.html",
    title="攻击链拆解",
    subtitle="供应链攻击全流程分析",
    section_label="03 / 攻击拆解",
    timeline_items=[
        {
            "day_label": "PHASE 1",
            "icon": "🎯",
            "item_title": "初始入侵",
            "description": "攻击者通过钓鱼邮件获取开发者凭证",
            "highlight": "0-click exploit",
        },
        {
            "day_label": "PHASE 2",
            "icon": "🔑",
            "item_title": "权限提升",
            "description": "利用CI/CD配置错误获取管理员权限",
        },
    ],
)
```

### Step 4 — Generate the HTML

Call the chosen tool with the prepared parameters. The tool writes the file
to `file_path` inside the workspace.

### Step 5 — Convert to PDF (optional)

If the user wants a PDF, use `convert_html_to_pdf`:

```
convert_html_to_pdf(
    file_path="output/pitch_deck.html",
    output_path="output/pitch_deck.pdf"
)
```

### Step 6 — Verify and deliver

1. Report the generated file path to the user
2. If they want changes, adjust the parameters and re-generate
3. Common adjustments:
   - Add/remove slides or timeline items
   - Change section labels or titles
   - Adjust content in `points` or `description`

---

## Tips

- **Keep it concise.** PPT slides and document pages work best with short,
  punchy content. Long paragraphs should be broken into bullet points.
- **Use section labels.** They help organize content visually (e.g. "02 / 市场").
- **Test in browser.** Open the generated HTML file in a browser to verify
  layout before converting to PDF.
- **Markdown structure.** When creating a Markdown document first, ALWAYS
  follow the structure rules above (numbered headings, hierarchical numbering,
  max 3 levels). This ensures clean conversion to HTML later.
