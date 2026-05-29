"""项目级 Workspace 分区管理器。

负责：
1. 从用户任务描述 / MD 文件 / 项目名提取项目标识
2. 在 workspace_root 下按项目建子目录（扁平结构）
3. 新任务启动时自动模糊匹配已有项目目录（keyword + levenshtein）
   找到则复用该目录而非新建

设计原则：
- 每个项目在 workspace_root 下有一个独立子目录
- 目录采用扁平结构：workspace_root/slug（无中间类型层级）
  （如 tokenized-stock-funding, xauusd-timeseries-signal-backtest）
- slug 使用连字符风格（kebab-case），简洁直观
- 支持模糊回溯已有项目（keyword match > levenshtein proximity）
- 项目类型仅用于决定骨架子目录结构，不参与目录层级
"""

import logging
import re
import unicodedata

logger = logging.getLogger(__name__)
from pathlib import Path


# ────────────────────────────────────────────
# 项目类型识别 — 骨架目录规范
# ────────────────────────────────────────────

# 项目类型 → (type_id, skeleton_dirs, keywords)
# type_id: 项目类型标识，决定创建哪些骨架子目录
# skeleton_dirs: 该类型项目需要的子目录列表（相对于项目根目录）
# 关键词按优先级排序，匹配到高优先级关键词即确定类型
PROJECT_TYPE_RULES: list[tuple[str, list[str], list[str]]] = [
    # (type_id, skeleton_dirs, keywords)
    ("wq_alpha", ["src", "output", "data", "scripts", "docs"], [
        "worldquant", "brain", "wq", "alpha mining",
        "alpha 挖掘", "alpha表达式", "ralph loop",
    ]),
    ("quant_md_futures", ["src", "output", "data", "docs"], [
        "期货", "合约", "futures", "binance", "okx", "bybit",
        "永续", "perp", "perpetual", "交割",
    ]),
    ("quant_md_fx", ["src", "output", "data", "docs"], [
        "外汇", "forex", "fx", "currency", "货币",
        "xauusd", "eurusd", "gbpusd", "usdjpy",
    ]),
    ("quant_md_crypto", ["src", "output", "data", "docs"], [
        "加密", "crypto", "bitcoin", "btc", "eth",
        "defi", "链上", "on-chain",
    ]),
    ("quant_signal", ["src", "output", "data", "scripts", "docs"], [
        "信号", "signal", "indicator", "指标",
        "因子", "factor", "特征", "feature",
    ]),
    ("quant_backtest", ["src", "output", "data", "scripts", "docs"], [
        "量化", "quant", "backtest", "回测", "策略研究",
        "factor", "因子", "sharpe", "momentum", "mean_reversion",
    ]),
    ("quant_research", ["src", "output", "data", "docs"], [
        "研究", "research", "分析", "analysis",
        "调研", "investigation", "报告", "report",
    ]),
    ("data_pipeline", ["src", "output", "data", "scripts"], [
        "etl", "pipeline", "数据管道", "data pipeline",
        "数据清洗", "data cleaning", "ingest",
    ]),
    ("web_app", ["src", "static", "templates", "tests"], [
        "webapp", "web app", "frontend", "backend",
        "api server", "网站", "dashboard",
    ]),
]


def _detect_project_type(task_description: str) -> tuple[str, list[str]]:
    """检测项目类型，返回 (type_id, skeleton_dirs)。

    type_id 用于日志和元数据记录；skeleton_dirs 决定创建哪些子目录。
    项目类型不再参与目录层级或 slug 前缀。

    >>> _detect_project_type("WorldQuant Brain alpha mining")
    ('wq_alpha', ['src', 'output', 'data', 'scripts', 'docs'])
    >>> _detect_project_type("量化策略回测")
    ('quant_backtest', ['src', 'output', 'data', 'scripts', 'docs'])
    >>> _detect_project_type("随便写个东西")
    ('general', ['src', 'output', 'data', 'docs'])
    """
    text_lower = task_description.lower()
    for type_id, skeleton_dirs, keywords in PROJECT_TYPE_RULES:
        for kw in keywords:
            if kw in text_lower:
                return type_id, skeleton_dirs
    return "general", ["src", "output", "data", "docs"]


# ────────────────────────────────────────────
# 语义规范化：同义词 / 缩写 → 标准形式
# ────────────────────────────────────────────

# 规范化映射：将常见变体映射到统一的规范形式
_SEMANTIC_NORMALIZE: dict[str, str] = {
    # WorldQuant 变体
    "worldquant": "worldquant",
    "wq": "worldquant",
    "brain": "worldquant",
    "worldquantbrain": "worldquant",
    "wqbrain": "worldquant",
    # Alpha 变体
    "alpha": "alpha",
    "alphamining": "alpha-mining",
    "alpha挖掘": "alpha-mining",
    # Quant 变体
    "quant": "quant",
    "quantitative": "quant",
    "量化": "quant",
    # Research 变体
    "research": "research",
    "研究": "research",
    "策略研究": "strategy-research",
    # Backtest 变体
    "backtest": "backtest",
    "回测": "backtest",
    "bt": "backtest",
}


def _normalize_semantic(text: str) -> str:
    """将文本中的语义等价词替换为规范形式，用于匹配。

    >>> _normalize_semantic("WQ alpha mining")
    'worldquant alpha-mining'
    """
    result = text.lower()
    # 按长度降序替换，避免短词误替换长词
    for variant in sorted(_SEMANTIC_NORMALIZE, key=len, reverse=True):
        if variant in result:
            result = result.replace(variant, _SEMANTIC_NORMALIZE[variant])
    return result


# Slug 最大长度（超过会被截断，保留最前面的完整单词）
_MAX_SLUG_LEN = 60


def _slugify(text: str) -> str:
    """将自然语言文本转为 kebab-case slug（用于目录名）。

    使用连字符风格，简洁直观，便于阅读和 shell 操作。

    >>> _slugify("我的量化策略项目")
    'wo-de-liang-hua-ce-lve-xiang-mu'
    >>> _slugify("ChainPeer - Decentralized Consensus")
    'chainpeer-decentralized-consensus'
    >>> _slugify("tokenized_stock_funding.md tokenized backtest")
    'tokenized-stock-funding-backtest'
    """
    # Normalize unicode → ASCII equivalents where possible
    text = unicodedata.normalize("NFKD", text)
    # Replace non-ASCII characters with hyphen (to avoid merging words like
    # "quant策略backtest" → "quantbacktest"; instead → "quant-backtest")
    text = re.sub(r"[^\x00-\x7f]+", "-", text)
    # Lowercase
    text = text.lower()
    # Remove common file extensions (.md, .txt, .py, .csv, .json, .yaml, .yml)
    text = re.sub(r"\.(md|txt|py|csv|json|yaml|yml)\b", "", text)
    # Replace non-alphanumeric with hyphen
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Collapse consecutive hyphens
    text = re.sub(r"-{2,}", "-", text)
    # Strip leading/trailing hyphens
    text = text.strip("-")
    # Remove duplicate words (e.g. "tokenized-stock-funding-tokenized-backtest"
    # → "tokenized-stock-funding-backtest")
    parts = text.split("-")
    seen: set[str] = set()
    deduped: list[str] = []
    for p in parts:
        if p not in seen:
            seen.add(p)
            deduped.append(p)
    text = "-".join(deduped)
    # Truncate to max length, keeping complete words
    if len(text) > _MAX_SLUG_LEN:
        text = text[:_MAX_SLUG_LEN].rsplit("-", 1)[0]
    # Fallback: if all characters were non-ASCII (e.g. pure Chinese),
    # use the project type as the slug base
    if not text:
        return "untitled"
    return text


# ────────────────────────────────────────────
# 项目名提取
# ────────────────────────────────────────────

# 用于从任务描述中提取项目名的模式
_PATTERNS: list[tuple[str, re.Pattern]] = [
    # (priority, compiled_pattern)
    # 1) 项目标识行：**project: name** / # Project: name
    ("project_line", re.compile(
        r"(?:^|\n)\s*(?:[#*_]*\s*)?(?:project|项目|proj)\s*[:：]\s*(.+?)(?:\n|$)",
        re.IGNORECASE,
    )),
    # 2) Markdown heading
    ("md_heading", re.compile(
        r"(?:^|\n)\s*#\s+(.+?)(?:\n|$)",
    )),
    # 3) Quoted project name
    ("quoted", re.compile(
        r'["\u201c\u201d\u300c\u300d]([^"]+?)["\u201c\u201d\u300c\u300d]',
    )),
]


def extract_project_name(task_description: str) -> str:
    """从任务描述中提取项目名。

    优先级：
    1. 明确的 project: name 标记
    2. Markdown 一级标题
    3. 引号中的内容
    4. 语义规范化后取前 80 字符
    5. 兜底：'untitled-project'

    >>> extract_project_name("project: My Alpha Strategy")
    'My Alpha Strategy'
    """
    for _, pat in _PATTERNS:
        m = pat.search(task_description)
        if m:
            name = m.group(1).strip()
            if name:
                return name

    # 没有明确标记 → 使用语义规范化后的文本
    normalized = _normalize_semantic(task_description)
    # 取前 80 字符，去掉尾部不完整词
    snippet = normalized[:80].rsplit(" ", 1)[0] if len(normalized) > 80 else normalized
    return snippet.strip() or "untitled-project"


# ────────────────────────────────────────────
# 目录匹配
# ────────────────────────────────────────────

def _levenshtein(a: str, b: str) -> int:
    """计算两字符串的 Levenshtein 距离。"""
    if len(a) < len(b):
        return _levenshtein(b, a)
    if not b:
        return len(a)
    prev_row = list(range(len(b) + 1))
    for i, ca in enumerate(a):
        curr_row = [i + 1]
        for j, cb in enumerate(b):
            cost = 0 if ca == cb else 1
            curr_row.append(min(
                prev_row[j + 1] + 1,  # deletion
                curr_row[j] + 1,      # insertion
                prev_row[j] + cost,   # substitution
            ))
        prev_row = curr_row
    return prev_row[-1]


# ────────────────────────────────────────────
# 项目骨架创建（Standard Project Layout）
# ────────────────────────────────────────────

# 标准 project layout 子目录
# 每种项目类型都有 data/ + output/ + docs/，但 src/ 只在代码类项目中创建
# 文档类项目类型 — 这些类型只产出 Markdown / 文档，
# 不需要 data/、output/、src/ 等子目录骨架。
# 只创建项目根目录，由用户按需自建子目录。
_DOC_ONLY_TYPES: set[str] = {
    "quant_md_futures",
    "quant_md_fx",
    "quant_md_crypto",
    "quant_research",   # 研究笔记，纯 Markdown
}

# 代码类项目类型的标准子目录骨架
# 注意：DOC_ONLY_TYPES 中的类型不在此表内，不会创建任何子目录
_SKELETON_DIRS_BY_TYPE: dict[str, list[str]] = {
    "wq_alpha": ["data", "output/report", "output/logs", "docs"],
    "quant_signal": ["data", "src", "output/report", "output/logs", "docs"],
    "quant_backtest": ["data", "src", "output/report", "output/logs", "output/artifacts", "docs"],
    "data_pipeline": ["data/raw", "data/processed", "src", "output/logs", "output/artifacts", "docs"],
    "web_app": ["src", "static", "templates", "output/logs", "docs"],
    "general": ["data", "src", "output", "docs"],
}

# README 模板
_README_TEMPLATE = """# {project_name}

> Auto-created by Quanora Project Manager
> Type: {type_id}

## Structure

{structure}

## Notes

<!-- Add project-specific notes here -->
"""


def _create_project_skeleton(
    project_dir: Path, type_id: str, skeleton_dirs: list[str] | None = None
) -> None:
    """创建项目目录骨架，包含标准子目录和 README。

    :param project_dir: 项目目录绝对路径
    :param type_id: 项目类型 ID（仅用于 README 记录）
    :param skeleton_dirs: 要创建的子目录列表；为 None 时从 _SKELETON_DIRS_BY_TYPE 获取
    """
    project_dir.mkdir(parents=True, exist_ok=True)

    # 创建标准子目录
    subdirs = skeleton_dirs or _SKELETON_DIRS_BY_TYPE.get(
        type_id, _SKELETON_DIRS_BY_TYPE["general"]
    )
    for subdir in subdirs:
        (project_dir / subdir).mkdir(parents=True, exist_ok=True)

    # 生成 README.md
    structure_lines = "\n".join(f"  - `{d}/`" for d in subdirs)
    readme_content = _README_TEMPLATE.format(
        project_name=project_dir.name,
        type_id=type_id,
        structure=structure_lines,
    )
    readme_path = project_dir / "README.md"
    if not readme_path.exists():
        readme_path.write_text(readme_content, encoding="utf-8")

    # 创建 .gitkeep 确保空目录被 git 追踪
    for subdir in subdirs:
        gitkeep = project_dir / subdir / ".gitkeep"
        if not gitkeep.exists() and not any((project_dir / subdir).iterdir()):
            gitkeep.write_text("", encoding="utf-8")


def _fuzzy_match_score(candidate: str, existing: str) -> float:
    """计算两个 slug 的模糊匹配分数（0~1）。

    综合考虑：
    1. Levenshtein 相似度（权重 0.4）
    2. 语义规范化后的 Levenshtein 相似度（权重 0.3）
    3. 关键词重叠度（权重 0.3）

    >>> round(_fuzzy_match_score("wq-alpha-mining", "wq-alpha-mining"), 1)
    1.0
    """
    # 1. 直接 Levenshtein 相似度
    max_len = max(len(candidate), len(existing), 1)
    lev_sim = 1 - _levenshtein(candidate, existing) / max_len

    # 2. 语义规范化后的 Levenshtein 相似度
    norm_candidate = _normalize_semantic(candidate)
    norm_existing = _normalize_semantic(existing)
    max_len_norm = max(len(norm_candidate), len(norm_existing), 1)
    norm_sim = 1 - _levenshtein(norm_candidate, norm_existing) / max_len_norm

    # 3. 关键词重叠度（词级 Jaccard）
    words_cand = set(candidate.replace("-", " ").split())
    words_exist = set(existing.replace("-", " ").split())
    if words_cand or words_exist:
        jaccard = len(words_cand & words_exist) / max(len(words_cand | words_exist), 1)
    else:
        jaccard = 0.0

    return 0.4 * lev_sim + 0.3 * norm_sim + 0.3 * jaccard


def find_or_create_project_dir(
    workspace_root: Path,
    task_description: str,
    threshold: float = 0.6,
) -> Path:
    """在 workspace_root 下查找或创建项目子目录（层级结构）。

    流程：
    1. 检测项目类型 → 确定 category_path 和 slug_prefix
    2. 从 task_description 提取项目名 → slugify → base_slug
    3. 若有 slug_prefix，将 base_slug 改为 {prefix}_{slug}（下划线风格）
    4. 项目目录 = workspace_root / category_path / project_slug
    5. 精确匹配 → 直接返回
    6. 模糊匹配 workspace_root 下的已有目录
    7. 无匹配 → 创建新目录（含标准子目录结构）

    目录结构示例（扁平，无中间层级）：
      workspace_root/
        tokenized-stock-funding/
        xauusd-timeseries-signal-backtest/
        wq-alpha-mean-reversion/
        my-random-project/

    :param workspace_root: 工作区根目录（如 ~/quanora-projects）
    :param task_description: 用户任务描述
    :param threshold: 模糊匹配阈值（0~1），默认 0.6
    :return: 项目子目录的绝对路径
    """
    # 检测项目类型（仅用于骨架目录和元数据，不参与目录层级）
    type_id, skeleton_dirs = _detect_project_type(task_description)

    # 提取项目名并 slugify（kebab-case 风格）
    project_name = extract_project_name(task_description)
    project_slug = _slugify(project_name)

    # Fallback: if slug is "untitled" (e.g. pure Chinese with no ASCII words),
    # use the type_id as the base slug, or extract any ASCII words from the
    # full task_description
    if project_slug == "untitled":
        full_slug = _slugify(task_description)
        if full_slug != "untitled":
            project_slug = full_slug
        elif type_id != "general":
            project_slug = type_id.replace("_", "-")

    # 扁平目录：workspace_root / project_slug
    workspace_root.mkdir(parents=True, exist_ok=True)

    # 1. 精确匹配
    exact_dir = workspace_root / project_slug
    if exact_dir.is_dir():
        return exact_dir.resolve()

    # 2. 模糊匹配 workspace_root 下的已有项目目录
    best_match: Path | None = None
    best_score: float = 0.0

    for child in workspace_root.iterdir():
        if not child.is_dir():
            continue
        # 跳过隐藏目录
        if child.name.startswith("."):
            continue
        score = _fuzzy_match_score(project_slug, child.name)

        if score > best_score:
            best_score = score
            best_match = child

    if best_match is not None and best_score >= threshold:
        return best_match.resolve()

    # 3. 无匹配 → 创建新项目目录
    # 文档类项目只创建根目录，不创建子目录骨架
    if type_id in _DOC_ONLY_TYPES:
        exact_dir.mkdir(parents=True, exist_ok=True)
        logger.info(
            "doc-only project, skipping skeleton: type=%s dir=%s",
            type_id, exact_dir,
        )
    else:
        _create_project_skeleton(exact_dir, type_id, skeleton_dirs)
    return exact_dir.resolve()


# ────────────────────────────────────────────
# Workspace 清理：扫描空目录 / 未使用的项目
# ────────────────────────────────────────────

def list_unused_dirs(base: str | Path) -> list[Path]:
    """扫描 base 下的空项目目录（只含 .gitkeep / README 的骨架目录）。

    返回所有可安全删除的子目录列表。判断标准：
    - 目录为空
    - 目录仅包含 .gitkeep 和/或 README.md

    Parameters
    ----------
    base : str | Path
        扫描根目录（如 workspace/ 或 projects/）

    Returns
    -------
    list[Path]
        可安全删除的目录路径
    """
    base = Path(base)
    if not base.is_dir():
        return []

    unused: list[Path] = []
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        # 跳过隐藏目录 (.quanora, .git 等)
        if child.name.startswith("."):
            continue
        # 递归检查子目录树
        files = [f for f in child.rglob("*") if f.is_file()]
        # 只保留非隐藏文件
        visible = [f for f in files if not f.name.startswith(".")]
        # 如果没有可见文件 → 空目录
        if not visible:
            unused.append(child)
            continue
        # 如果仅有 .gitkeep 和/或 README.md → 骨架目录
        non_skeleton = [
            f for f in visible
            if f.name not in {".gitkeep", "README.md"}
        ]
        if not non_skeleton:
            unused.append(child)

    return unused
