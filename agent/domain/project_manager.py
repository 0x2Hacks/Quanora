"""项目级 Workspace 分区管理器。

负责：
1. 从用户任务描述 / MD 文件 / 项目名提取项目标识
2. 在 workspace_root 下按项目建子目录
3. 新任务启动时自动模糊匹配已有项目目录（keyword + levenshtein）
   找到则复用该目录而非新建

设计原则：
- 每个项目在 workspace_root 下有一个独立子目录
- 目录名 = project_slug（slugified from project name / md title）
- 支持模糊回溯已有项目（keyword match > levenshtein proximity）
- 项目类型自动识别：根据任务描述中的关键词检测项目类型，加入类型前缀
  (如 wq_xxx, quant_xxx, web_xxx)，使同类项目更容易匹配
"""

import re
import unicodedata
from pathlib import Path


# ────────────────────────────────────────────
# 项目类型识别
# ────────────────────────────────────────────

# 项目类型 → (前缀, 关键词列表)
# 关键词按优先级排序，匹配到高优先级关键词即确定类型
PROJECT_TYPE_RULES: list[tuple[str, str, list[str]]] = [
    # (type_id, slug_prefix, keywords)
    ("wq_alpha", "wq", [
        "worldquant", "brain", "wq", "alpha mining",
        "alpha 挖掘", "alpha表达式", "ralph loop",
    ]),
    ("quant_research", "quant", [
        "量化", "quant", "backtest", "回测", "策略研究",
        "factor", "因子", "sharpe", "momentum", "mean_reversion",
    ]),
    ("data_pipeline", "data", [
        "etl", "pipeline", "数据管道", "data pipeline",
        "数据清洗", "data cleaning", "ingest",
    ]),
    ("web_app", "web", [
        "webapp", "web app", "frontend", "backend",
        "api server", "网站", "dashboard",
    ]),
]


def _detect_project_type(task_description: str) -> tuple[str, str]:
    """检测项目类型，返回 (type_id, slug_prefix)。

    >>> _detect_project_type("WorldQuant Brain alpha mining")
    ('wq_alpha', 'wq')
    >>> _detect_project_type("量化策略回测")
    ('quant_research', 'quant')
    >>> _detect_project_type("随便写个东西")
    ('general', 'proj')
    """
    text_lower = task_description.lower()
    for type_id, slug_prefix, keywords in PROJECT_TYPE_RULES:
        for kw in keywords:
            if kw in text_lower:
                return type_id, slug_prefix
    return "general", "proj"


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


def _slugify(text: str) -> str:
    """将自然语言文本转为 URL-safe slug（用于目录名）。

    >>> _slugify("我的量化策略项目")
    'wo-de-liang-hua-ce-lve-xiang-mu'
    >>> _slugify("ChainPeer - Decentralized Consensus")
    'chainpeer-decentralized-consensus'
    """
    # Normalize unicode → ASCII equivalents where possible
    text = unicodedata.normalize("NFKD", text)
    # Remove non-ASCII (pinyin transliteration is lossy; keep only ASCII)
    text = text.encode("ascii", "ignore").decode("ascii")
    # Lowercase
    text = text.lower()
    # Replace non-alphanumeric with hyphen
    text = re.sub(r"[^a-z0-9]+", "-", text)
    # Collapse consecutive hyphens
    text = re.sub(r"-{2,}", "-", text)
    # Strip leading/trailing hyphens
    text = text.strip("-")
    return text or "untitled"


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
    """在 workspace_root 下查找或创建项目子目录。

    流程：
    1. 检测项目类型 → 确定前缀
    2. 从 task_description 提取项目名 → slugify → project_slug
    3. 若有类型前缀，将 project_slug 改为 {prefix}-{slug}
    4. 检查 workspace_root/project_slug 是否存在 → 直接返回
    5. 模糊匹配已有项目目录（threshold ≥ 0.6 视为匹配）
       - 优先匹配同类型前缀的目录
    6. 无匹配则创建新目录 workspace_root/project_slug

    :param workspace_root: 工作区根目录（如 ~/quanora-projects）
    :param task_description: 用户任务描述
    :param threshold: 模糊匹配阈值（0~1），默认 0.6
    :return: 项目子目录的绝对路径
    """
    # 检测项目类型
    type_id, slug_prefix = _detect_project_type(task_description)

    # 提取项目名并 slugify
    project_name = extract_project_name(task_description)
    base_slug = _slugify(project_name)

    # 加入类型前缀（避免前缀重复，如 "wq-wq-alpha" → "wq-alpha"）
    if slug_prefix and not base_slug.startswith(slug_prefix + "-") and base_slug != slug_prefix:
        project_slug = f"{slug_prefix}-{base_slug}"
    else:
        project_slug = base_slug

    # 确保 workspace_root 存在
    workspace_root.mkdir(parents=True, exist_ok=True)

    # 1. 精确匹配
    exact_dir = workspace_root / project_slug
    if exact_dir.is_dir():
        return exact_dir.resolve()

    # 2. 模糊匹配已有项目目录
    #    对同类型前缀的目录给予加分
    best_match: Path | None = None
    best_score: float = 0.0

    for child in workspace_root.iterdir():
        if not child.is_dir():
            continue
        # 跳过隐藏目录
        if child.name.startswith("."):
            continue
        score = _fuzzy_match_score(project_slug, child.name)

        # 同类型前缀加分：如果两个目录都有相同类型前缀，分数 +0.1
        if slug_prefix and child.name.startswith(slug_prefix + "-"):
            score = min(score + 0.1, 1.0)

        if score > best_score:
            best_score = score
            best_match = child

    if best_match is not None and best_score >= threshold:
        return best_match.resolve()

    # 3. 无匹配 → 创建新项目目录
    exact_dir.mkdir(parents=True, exist_ok=True)
    return exact_dir.resolve()
