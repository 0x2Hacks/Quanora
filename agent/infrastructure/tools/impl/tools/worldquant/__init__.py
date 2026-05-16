"""WorldQuant Brain 自动挖因子 — 暴露给 LLM 的工具函数。

每个函数都返回 ChainPeer 标准的 tool_ok / tool_error 字符串载荷。
这些函数会被 `agent/infrastructure/tools/impl/__init__.py` 注册到 TOOLS 字典。
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from typing import Any

from ...core.base import tool_error, tool_ok
from .client import (
    SimulationSettings,
    WQAPIError,
    WQAuthError,
    WQBrainClient,
    WQCredentials,
    WQRateLimitError,
    get_global_client,
    reset_global_client,
)
from .evaluator import (
    EvaluationVerdict,
    Thresholds,
    evaluate_expression,
    verdict_to_alpha_record,
)
from .knowledge import (
    BUILTIN_FIELDS,
    BUILTIN_OPERATORS,
    DIRECTION_LIBRARY,
    build_generation_prompt,
)
from .memory import (
    AlphaRecord,
    ExperienceMemory,
    ForbiddenRegion,
    StrategicInsight,
    SuccessfulPattern,
)

# ──────────────────────────────────────────────────────────────────────
# 共享的 memory 单例(每个进程一份,与全局 client 同生命周期)
# ──────────────────────────────────────────────────────────────────────
_GLOBAL_MEMORY: ExperienceMemory | None = None


def _memory() -> ExperienceMemory:
    global _GLOBAL_MEMORY
    if _GLOBAL_MEMORY is None:
        _GLOBAL_MEMORY = ExperienceMemory()
    return _GLOBAL_MEMORY


# ──────────────────────────────────────────────────────────────────────
# 工具 1: 登录
# ──────────────────────────────────────────────────────────────────────
def wq_login(email: str = "", password: str = "") -> str:
    """登录 WorldQuant Brain。

    凭证解析优先级:函数参数 > 环境变量 (WQ_BRAIN_EMAIL/WQ_BRAIN_PASSWORD) > ./credential.txt
    """
    try:
        creds = WQCredentials.resolve(email or None, password or None)
        client = WQBrainClient(credentials=creds)
        result = client.login()
        # 替换全局单例
        reset_global_client()
        import agent.infrastructure.tools.impl.tools.worldquant.client as _client_mod
        _client_mod._GLOBAL_CLIENT = client
        return tool_ok("wq_login", {"user": result.get("user"), "email": creds.email})
    except WQAuthError as exc:
        return tool_error("wq_login", str(exc), "WQAuthError")
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_login", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 2: 列出 Brain 算子
# ──────────────────────────────────────────────────────────────────────
def wq_list_operators(use_cache: bool = True) -> str:
    """列出 Brain 平台可用算子。

    use_cache=True 时直接返回内置精选算子(零网络),否则调用 Brain API 拉取真实清单。
    """
    if use_cache:
        return tool_ok("wq_list_operators", {"source": "builtin", "operators": BUILTIN_OPERATORS})
    try:
        client = get_global_client()
        ops = client.list_operators()
        return tool_ok("wq_list_operators", {"source": "brain_api", "operators": ops})
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_list_operators", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 3: 列出数据字段
# ──────────────────────────────────────────────────────────────────────
def wq_list_data_fields(
    region: str = "USA",
    universe: str = "TOP3000",
    delay: int = 1,
    search: str = "",
    use_cache: bool = True,
    limit: int = 50,
) -> str:
    """列出 Brain 数据字段。use_cache=True 走内置精选清单,否则在线查询。"""
    if use_cache:
        return tool_ok("wq_list_data_fields", {"source": "builtin", "fields": BUILTIN_FIELDS})
    try:
        client = get_global_client()
        data = client.list_data_fields(
            region=region,
            universe=universe,
            delay=delay,
            search=search or None,
            limit=limit,
        )
        return tool_ok("wq_list_data_fields", {"source": "brain_api", "data": data})
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_list_data_fields", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 4: 列出研究方向
# ──────────────────────────────────────────────────────────────────────
def wq_list_directions() -> str:
    """列出内置的研究方向库(diversified planning 候选池)。"""
    return tool_ok("wq_list_directions", {"directions": DIRECTION_LIBRARY})


# ──────────────────────────────────────────────────────────────────────
# 工具 5: 拿到一份"记忆快照",供 LLM 在生成因子时阅读
# ──────────────────────────────────────────────────────────────────────
def wq_memory_snapshot(
    tags: list[str] | None = None,
    succ_k: int = 5,
    fail_k: int = 5,
    insight_k: int = 3,
) -> str:
    """读取 Experience Memory 当前快照(P_succ/P_fail/I/state/库内 Top)。"""
    try:
        snapshot = _memory().retrieve_for_prompt(
            tags=tags or None,
            succ_k=succ_k,
            fail_k=fail_k,
            insight_k=insight_k,
        )
        return tool_ok("wq_memory_snapshot", snapshot)
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_memory_snapshot", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 6: 构造 alpha 生成 prompt(LLM 拿到后**自己**生成因子,不需要二次 LLM 调用)
# ──────────────────────────────────────────────────────────────────────
def wq_build_generation_prompt(
    direction_key: str = "reversal_short_term",
    hypothesis: str = "",
    n: int = 5,
    custom_direction: dict | None = None,
) -> str:
    """构造一份 alpha 生成 prompt。LLM 阅读后可直接产出 JSON 数组。

    LLM 调用方式:
    1. 先 `wq_build_generation_prompt(...)` 拿到 prompt 文本
    2. LLM 在自己的思考中按 prompt 输出 alpha 表达式数组
    3. 再用 `wq_evaluate_alpha` 批量评估
    """
    try:
        memory_snapshot = _memory().retrieve_for_prompt()
        direction: Any = custom_direction or DIRECTION_LIBRARY.get(direction_key)
        if not direction:
            return tool_error(
                "wq_build_generation_prompt",
                f"unknown direction_key={direction_key},可用: {list(DIRECTION_LIBRARY)}",
                "DirectionNotFound",
            )
        prompt = build_generation_prompt(
            n=n,
            direction=direction,
            hypothesis=hypothesis,
            memory_snapshot=memory_snapshot,
        )
        return tool_ok("wq_build_generation_prompt", {"prompt": prompt, "direction": direction})
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_build_generation_prompt", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 7: 在 Brain 平台模拟单条 alpha(底层 simulate 的包装)
# ──────────────────────────────────────────────────────────────────────
def wq_simulate_alpha(
    expression: str,
    region: str = "USA",
    universe: str = "TOP3000",
    delay: int = 1,
    decay: int = 0,
    neutralization: str = "INDUSTRY",
    truncation: float = 0.08,
    wait: bool = True,
    max_wait_seconds: int = 600,
) -> str:
    """提交单条 alpha 到 Brain 平台执行模拟,默认等待结果。"""
    try:
        client = get_global_client()
        settings = SimulationSettings(
            region=region,
            universe=universe,
            delay=delay,
            decay=decay,
            neutralization=neutralization,
            truncation=truncation,
        )
        result = client.simulate(expression=expression, settings=settings, wait=wait, max_wait_seconds=max_wait_seconds)
        return tool_ok("wq_simulate_alpha", result)
    except WQRateLimitError as exc:
        return tool_error("wq_simulate_alpha", str(exc), "WQRateLimitError")
    except WQAuthError as exc:
        return tool_error("wq_simulate_alpha", str(exc), "WQAuthError")
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_simulate_alpha", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 8: 完整多阶段评估(本地门控 + Brain + 自动写记忆)
# ──────────────────────────────────────────────────────────────────────
def wq_evaluate_alpha(
    expression: str,
    direction_tag: str = "",
    region: str = "USA",
    universe: str = "TOP3000",
    delay: int = 1,
    decay: int = 0,
    neutralization: str = "INDUSTRY",
    truncation: float = 0.08,
    min_sharpe: float = 1.25,
    min_fitness: float = 1.0,
    max_turnover: float = 0.7,
    admit_to_library: bool = True,
) -> str:
    """对单条 alpha 跑完整 Stage1-4 评估管线,通过则可选 admit 入库。

    返回:
        {
          "passed": bool,
          "stage_failed": "stage1_local"|"stage4_dedup"|"stage2_simulate"|"stage3_brain_checks"|"stage3_threshold"|None,
          "reason": str,
          "alpha_id": str,
          "metrics": {sharpe, fitness, turnover, returns, drawdown, ...},
          "checks": [Brain 的 check 列表],
          "admitted": bool
        }
    """
    try:
        client = get_global_client()
        mem = _memory()
        thresholds = Thresholds(min_sharpe=min_sharpe, min_fitness=min_fitness, max_turnover=max_turnover)
        settings = SimulationSettings(
            region=region,
            universe=universe,
            delay=delay,
            decay=decay,
            neutralization=neutralization,
            truncation=truncation,
        )
        verdict = evaluate_expression(
            expression=expression,
            client=client,
            memory=mem,
            settings=settings,
            thresholds=thresholds,
            direction_tag=direction_tag,
        )
        admitted = False
        if verdict.passed and admit_to_library:
            record = verdict_to_alpha_record(
                verdict,
                direction=direction_tag,
                region=region,
                universe=universe,
            )
            mem.add_alpha(record)
            admitted = True
            # 同步把成功模板写入 P_succ
            from .evaluator import normalize_template
            mem.add_successful_pattern(
                SuccessfulPattern(
                    template=normalize_template(expression),
                    rationale=f"sharpe={verdict.metrics.get('sharpe'):.2f} via direction={direction_tag or 'n/a'}",
                    example_expressions=[expression],
                    avg_sharpe=verdict.metrics.get("sharpe") or 0.0,
                    hit_count=1,
                    tags=[direction_tag] if direction_tag else [],
                )
            )
        return tool_ok(
            "wq_evaluate_alpha",
            {
                "passed": verdict.passed,
                "stage_failed": verdict.stage_failed,
                "reason": verdict.reason,
                "alpha_id": verdict.alpha_id,
                "metrics": verdict.metrics,
                "checks": verdict.checks,
                "admitted": admitted,
            },
        )
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_evaluate_alpha", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 9: 反思(Distill) — 把一个失败原因/教训写入 Insights
# ──────────────────────────────────────────────────────────────────────
def wq_distill_insight(insight: str, category: str = "general", severity: str = "info", tags: list[str] | None = None) -> str:
    """把本轮挖掘的策略级教训沉淀到 Experience Memory。

    Args:
        insight: 自然语言教训,如 "ts_rank 在窗口 > 60 时容易出现 NaN"
        category: operator|data_field|regime|general
        severity: info|warning|critical
        tags: 关联的方向标签
    """
    try:
        _memory().add_insight(
            StrategicInsight(insight=insight, category=category, severity=severity, tags=tags or [])
        )
        return tool_ok("wq_distill_insight", {"insight": insight, "category": category, "severity": severity})
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_distill_insight", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 10: 列出我的因子库
# ──────────────────────────────────────────────────────────────────────
def wq_list_library(min_sharpe: float = 0.0, limit: int = 50) -> str:
    """列出本地 alpha 库(包含 Brain 返回的 metrics)。"""
    try:
        records = _memory().list_alphas(limit=limit, min_sharpe=min_sharpe if min_sharpe > 0 else None)
        return tool_ok(
            "wq_list_library",
            {"count": len(records), "alphas": records, "state": _memory().get_state()},
        )
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_list_library", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 11: 列出 Brain 上我账户的 alpha
# ──────────────────────────────────────────────────────────────────────
def wq_list_my_alphas(status: str = "", limit: int = 50, offset: int = 0) -> str:
    """查询当前账户在 Brain 平台上的 alpha 列表。"""
    try:
        client = get_global_client()
        data = client.list_my_alphas(limit=limit, offset=offset, status=status or None)
        return tool_ok("wq_list_my_alphas", data)
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_list_my_alphas", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 12: 提交一个 alpha 到比赛
# ──────────────────────────────────────────────────────────────────────
def wq_submit_alpha(alpha_id: str) -> str:
    """提交某个已经通过质量检查的 alpha 到 Brain 比赛(注意每日配额)。"""
    try:
        client = get_global_client()
        result = client.submit_alpha(alpha_id)
        if result.get("ok"):
            return tool_ok("wq_submit_alpha", result)
        return tool_error("wq_submit_alpha", json.dumps(result, ensure_ascii=False), "SubmitRejected")
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_submit_alpha", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 13: 进化 — Mutation(扰动一个种子表达式)
# ──────────────────────────────────────────────────────────────────────
# 捕获":<sp>数字<sp>" 形式的常量,保留原有左右空格,只替换数字本身
_PARAM_PATTERN = re.compile(r"(?<=[,(])(\s*)(\d+(?:\.\d+)?)(\s*)(?=[,)])")


def wq_mutate_alpha(seed_expression: str, window_candidates: list | None = None, max_variants: int = 6) -> str:
    """对种子表达式做参数扰动,生成一批 mutation 候选(对应 QuantaAlpha 的 Mutation 算子)。

    实现:把表达式里**第一个**数值参数(通常是窗口期)替换成候选集中的每个值,保留原始空格。
    """
    try:
        candidates = window_candidates or [5, 10, 20, 30, 60, 120]
        if not _PARAM_PATTERN.search(seed_expression):
            return tool_error("wq_mutate_alpha", "种子表达式中未找到可变参数(数字常量)", "NoMutableParam")
        variants: list[str] = []
        for cand in candidates:
            variant = _PARAM_PATTERN.sub(
                lambda m, c=cand: f"{m.group(1)}{c}{m.group(3)}",
                seed_expression,
                count=1,
            )
            if variant != seed_expression and variant not in variants:
                variants.append(variant)
            if len(variants) >= max_variants:
                break
        return tool_ok("wq_mutate_alpha", {"seed": seed_expression, "variants": variants})
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_mutate_alpha", str(exc), exc.__class__.__name__)


# ──────────────────────────────────────────────────────────────────────
# 工具 14: 进化 — Crossover(把两个表达式的"内核"拼接)
# ──────────────────────────────────────────────────────────────────────
def wq_crossover_alpha(expression_a: str, expression_b: str, strategy: str = "wrap_b_in_a") -> str:
    """对两个表达式做交叉。

    strategy:
        - wrap_b_in_a: 用 a 作为外层算子,把 b 当成 a 的第一个参数
        - rank_pair:   rank(a) - rank(b),做截面相减
        - add_pair:    add(a, b)
        - corr_pair:   ts_corr(a, b, 20)
    """
    try:
        strategy = strategy.lower()
        if strategy == "wrap_b_in_a":
            # 找到 a 的第一个函数名,把它的第一个参数替换为 b
            m = re.match(r"^(\w+)\s*\((.*)\)$", expression_a.strip())
            if not m:
                return tool_error("wq_crossover_alpha", "expression_a 必须以函数调用形式开头", "BadFormat")
            head, body = m.group(1), m.group(2)
            # 拆分出第一个 top-level 参数
            depth = 0
            split_at = -1
            for i, ch in enumerate(body):
                if ch == "(":
                    depth += 1
                elif ch == ")":
                    depth -= 1
                elif ch == "," and depth == 0:
                    split_at = i
                    break
            if split_at < 0:
                new_body = expression_b
            else:
                new_body = f"{expression_b},{body[split_at+1:]}"
            crossed = f"{head}({new_body})"
        elif strategy == "rank_pair":
            crossed = f"subtract(rank({expression_a}), rank({expression_b}))"
        elif strategy == "add_pair":
            crossed = f"add({expression_a}, {expression_b})"
        elif strategy == "corr_pair":
            crossed = f"ts_corr({expression_a}, {expression_b}, 20)"
        else:
            return tool_error("wq_crossover_alpha", f"unknown strategy={strategy}", "UnknownStrategy")
        return tool_ok("wq_crossover_alpha", {"strategy": strategy, "result": crossed})
    except Exception as exc:  # noqa: BLE001
        return tool_error("wq_crossover_alpha", str(exc), exc.__class__.__name__)


__all__ = [
    "wq_login",
    "wq_list_operators",
    "wq_list_data_fields",
    "wq_list_directions",
    "wq_memory_snapshot",
    "wq_build_generation_prompt",
    "wq_simulate_alpha",
    "wq_evaluate_alpha",
    "wq_distill_insight",
    "wq_list_library",
    "wq_list_my_alphas",
    "wq_submit_alpha",
    "wq_mutate_alpha",
    "wq_crossover_alpha",
]
