"""多阶段评估管线(对应 FactorMiner 论文中的 Validation Pipeline)。

Stage 1: 语法/复杂度门控(本地零成本)
Stage 2: Brain 真实模拟(IS 回测) — 调用 client.simulate
Stage 3: Brain 内置 checks 验证(LOW_SHARPE / HIGH_TURNOVER / SELF_CORR 等)
Stage 4: 与本地 alpha_library 模板相似度去重

最终输出统一为 EvaluationVerdict,便于上层做 admit/reject 决策。
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from .client import SimulationSettings, WQAPIError, WQBrainClient
from .memory import AlphaRecord, ExperienceMemory, ForbiddenRegion


# ──────────────────────────────────────────────────────────────────────
# 默认门控阈值(可通过 set_thresholds 覆盖)
# ──────────────────────────────────────────────────────────────────────
@dataclass(slots=True)
class Thresholds:
    min_sharpe: float = 1.25       # Brain PASS 阈值
    min_fitness: float = 1.0
    max_turnover: float = 0.7
    max_drawdown: float = 0.10
    min_returns: float = 0.05
    max_self_correlation: float = 0.7
    max_expr_length: int = 250
    max_operator_depth: int = 8


@dataclass(slots=True)
class EvaluationVerdict:
    expression: str
    passed: bool
    stage_failed: str | None = None
    reason: str = ""
    metrics: dict[str, Any] = field(default_factory=dict)
    alpha_id: str | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)
    raw: dict[str, Any] = field(default_factory=dict)


# ──────────────────────────────────────────────────────────────────────
# Stage 1: 本地语法+复杂度门控
# ──────────────────────────────────────────────────────────────────────
PAREN_PATTERN = re.compile(r"\w+\s*\(")


def stage1_local_check(expression: str, thresholds: Thresholds) -> tuple[bool, str]:
    expr = expression.strip()
    if not expr:
        return False, "empty expression"
    if len(expr) > thresholds.max_expr_length:
        return False, f"expression too long: {len(expr)} > {thresholds.max_expr_length}"
    # 简单的算子嵌套深度估算:用括号深度
    depth = 0
    max_depth = 0
    for ch in expr:
        if ch == "(":
            depth += 1
            max_depth = max(max_depth, depth)
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False, "unbalanced parentheses"
    if depth != 0:
        return False, "unbalanced parentheses"
    if max_depth > thresholds.max_operator_depth:
        return False, f"operator nesting too deep: {max_depth} > {thresholds.max_operator_depth}"
    # 检查是否调用了至少一个函数(防止裸字段 'close')
    if not PAREN_PATTERN.search(expr):
        return False, "expression must invoke at least one operator"
    return True, "ok"


# ──────────────────────────────────────────────────────────────────────
# Stage 3: 解析 Brain checks
# ──────────────────────────────────────────────────────────────────────
def parse_brain_checks(is_payload: dict[str, Any]) -> tuple[bool, str, list[dict[str, Any]]]:
    """读取 Brain 返回的 is.checks 数组,提取关键失败项。"""
    checks = is_payload.get("checks", []) or []
    failures: list[str] = []
    for check in checks:
        if not isinstance(check, dict):
            continue
        result = check.get("result", "").upper()
        name = check.get("name", "")
        if result in ("FAIL", "ERROR"):
            value = check.get("value", "")
            limit = check.get("limit", "")
            failures.append(f"{name}={value} (limit={limit})")
    if failures:
        return False, "; ".join(failures), checks
    return True, "all checks passed", checks


# ──────────────────────────────────────────────────────────────────────
# Stage 4: 本地模板去重(廉价启发式)
# ──────────────────────────────────────────────────────────────────────
TEMPLATE_NORMALIZE_RE = re.compile(r"\b\d+(?:\.\d+)?\b")


def normalize_template(expression: str) -> str:
    """将 ts_rank(close, 5) 与 ts_rank(close, 20) 视为同一模板。"""
    norm = TEMPLATE_NORMALIZE_RE.sub("N", expression)
    return re.sub(r"\s+", "", norm)


def stage4_template_dedup(expression: str, memory: ExperienceMemory) -> tuple[bool, str]:
    target_template = normalize_template(expression)
    # 库内已有完全相同表达式 -> 直接拒
    if memory.has_expression(expression):
        return False, "expression already exists in library"
    # 库内已有同模板 -> 标记(后续可能替换,这里先警告但仍放行到 Brain 评估)
    for record in memory.list_alphas(limit=200):
        if normalize_template(record.get("expression", "")) == target_template:
            return False, f"template collision with existing alpha {record.get('alpha_id','')}"
    return True, "no template collision"


# ──────────────────────────────────────────────────────────────────────
# 顶层评估流水线
# ──────────────────────────────────────────────────────────────────────
def evaluate_expression(
    *,
    expression: str,
    client: WQBrainClient,
    memory: ExperienceMemory,
    settings: SimulationSettings | None = None,
    thresholds: Thresholds | None = None,
    direction_tag: str = "",
    wait: bool = True,
) -> EvaluationVerdict:
    thresholds = thresholds or Thresholds()
    settings = settings or SimulationSettings()

    # Stage 1
    ok, reason = stage1_local_check(expression, thresholds)
    if not ok:
        return EvaluationVerdict(expression=expression, passed=False, stage_failed="stage1_local", reason=reason)

    # Stage 4 提前(廉价):本地模板去重
    ok, reason = stage4_template_dedup(expression, memory)
    if not ok:
        return EvaluationVerdict(expression=expression, passed=False, stage_failed="stage4_dedup", reason=reason)

    # Stage 2: Brain 真实模拟
    try:
        sim_result = client.simulate(expression=expression, settings=settings, wait=wait)
    except WQAPIError as exc:
        return EvaluationVerdict(expression=expression, passed=False, stage_failed="stage2_simulate", reason=str(exc))

    if not sim_result.get("ok"):
        return EvaluationVerdict(
            expression=expression,
            passed=False,
            stage_failed="stage2_simulate",
            reason=sim_result.get("message", "simulation failed"),
            raw=sim_result,
        )

    alpha_id = sim_result.get("alpha_id", "")
    is_payload = sim_result.get("is", {}) or {}
    metrics = {
        "sharpe": is_payload.get("sharpe"),
        "fitness": is_payload.get("fitness"),
        "returns": is_payload.get("returns"),
        "turnover": is_payload.get("turnover"),
        "drawdown": is_payload.get("drawdown"),
        "margin": is_payload.get("margin"),
        "longCount": is_payload.get("longCount"),
        "shortCount": is_payload.get("shortCount"),
    }

    # Stage 3: Brain checks
    passed, check_reason, checks = parse_brain_checks(is_payload)
    if not passed:
        # 自相关性高 -> 收录到 forbidden regions
        if "SELF_CORR" in check_reason.upper() or "CORR" in check_reason.upper():
            memory.add_forbidden_region(
                ForbiddenRegion(
                    template=normalize_template(expression),
                    reason=check_reason,
                    representative_expressions=[expression],
                    correlated_with=[alpha_id] if alpha_id else [],
                    hit_count=1,
                    tags=[direction_tag] if direction_tag else [],
                )
            )
        return EvaluationVerdict(
            expression=expression,
            passed=False,
            stage_failed="stage3_brain_checks",
            reason=check_reason,
            metrics=metrics,
            alpha_id=alpha_id,
            checks=checks,
            raw=sim_result,
        )

    # 综合本地阈值二次校验
    sharpe = (metrics["sharpe"] or 0.0)
    fitness = (metrics["fitness"] or 0.0)
    turnover = (metrics["turnover"] or 1.0)
    if sharpe < thresholds.min_sharpe:
        return EvaluationVerdict(
            expression=expression,
            passed=False,
            stage_failed="stage3_threshold",
            reason=f"sharpe={sharpe:.3f} < {thresholds.min_sharpe}",
            metrics=metrics,
            alpha_id=alpha_id,
            checks=checks,
        )
    if fitness < thresholds.min_fitness:
        return EvaluationVerdict(
            expression=expression,
            passed=False,
            stage_failed="stage3_threshold",
            reason=f"fitness={fitness:.3f} < {thresholds.min_fitness}",
            metrics=metrics,
            alpha_id=alpha_id,
            checks=checks,
        )
    if turnover > thresholds.max_turnover:
        return EvaluationVerdict(
            expression=expression,
            passed=False,
            stage_failed="stage3_threshold",
            reason=f"turnover={turnover:.3f} > {thresholds.max_turnover}",
            metrics=metrics,
            alpha_id=alpha_id,
            checks=checks,
        )

    return EvaluationVerdict(
        expression=expression,
        passed=True,
        reason="passed all stages",
        metrics=metrics,
        alpha_id=alpha_id,
        checks=checks,
        raw=sim_result,
    )


# ──────────────────────────────────────────────────────────────────────
# 将通过 Verdict 转化为 AlphaRecord
# ──────────────────────────────────────────────────────────────────────
def verdict_to_alpha_record(
    verdict: EvaluationVerdict,
    *,
    direction: str = "",
    region: str = "USA",
    universe: str = "TOP3000",
    notes: str = "",
) -> AlphaRecord:
    metrics = verdict.metrics or {}
    return AlphaRecord(
        alpha_id=verdict.alpha_id or "",
        expression=verdict.expression,
        direction=direction,
        sharpe=metrics.get("sharpe"),
        fitness=metrics.get("fitness"),
        turnover=metrics.get("turnover"),
        returns=metrics.get("returns"),
        drawdown=metrics.get("drawdown"),
        region=region,
        universe=universe,
        notes=notes,
    )
