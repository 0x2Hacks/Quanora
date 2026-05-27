"""数据预审模块 — 在 Alpha 研究开始前检查数据可用性。

输出人类可读的数据综述（Data Review），供研究者确认后再进入 Ralph Loop。
核心逻辑：
1. 检查方向/假设所需的数据字段是否在 BUILTIN_FIELDS 中
2. 检查所需算子是否在 BUILTIN_OPERATORS 中
3. 在线查询 Brain API 获取 region/universe 的数据字段覆盖
4. 检查 Experience Memory 的禁区/洞察是否有相关风险
5. 输出结构化的 DataReviewReport
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from typing import Any

from .knowledge import (
    BUILTIN_FIELDS,
    BUILTIN_OPERATORS,
    DIRECTION_LIBRARY,
)


@dataclass
class FieldCheck:
    """单个数据字段的可用性检查结果。"""
    name: str
    available: bool  # 是否在 BUILTIN_FIELDS / Brain 平台中
    source: str      # "builtin" | "online" | "missing"
    description: str = ""


@dataclass
class OperatorCheck:
    """单个算子的可用性检查结果。"""
    name: str
    available: bool  # 是否在 BUILTIN_OPERATORS / Brain 平台中
    source: str      # "builtin" | "online" | "missing"
    signature: str = ""
    description: str = ""


@dataclass
class RiskFlag:
    """风险标记。"""
    severity: str    # "critical" | "warning" | "info"
    category: str    # "data_unavailable" | "operator_unavailable" | "forbidden_region" | "insight" | "coverage_gap"
    message: str


@dataclass
class DataReviewReport:
    """数据预审报告。"""
    # 研究方向信息
    direction_key: str
    direction_name: str
    region: str
    universe: str
    delay: int

    # 检查结果
    field_checks: list[FieldCheck] = field(default_factory=list)
    operator_checks: list[OperatorCheck] = field(default_factory=list)
    risk_flags: list[RiskFlag] = field(default_factory=list)

    # 摘要
    total_fields_required: int = 0
    fields_available: int = 0
    total_operators_required: int = 0
    operators_available: int = 0
    risk_count: int = 0
    recommendation: str = "proceed"  # "proceed" | "caution" | "abort"

    def to_markdown(self) -> str:
        """生成人类可读的 Markdown 报告。"""
        lines = [
            f"# 数据预审报告 (Data Review)",
            f"",
            f"**方向**: {self.direction_name} (`{self.direction_key}`)",
            f"**区域**: {self.region} | **股票池**: {self.universe} | **Delay**: {self.delay}",
            f"",
        ]

        # ── 字段可用性 ──
        lines.append("## 数据字段可用性")
        lines.append(f"可用: **{self.fields_available}/{self.total_fields_required}**")
        lines.append("")
        if self.field_checks:
            lines.append("| 字段 | 可用 | 来源 | 说明 |")
            lines.append("|---|---|---|---|")
            for fc in self.field_checks:
                mark = "✅" if fc.available else "❌"
                lines.append(f"| `{fc.name}` | {mark} | {fc.source} | {fc.description} |")
        lines.append("")

        # ── 算子可用性 ──
        lines.append("## 算子可用性")
        lines.append(f"可用: **{self.operators_available}/{self.total_operators_required}**")
        lines.append("")
        if self.operator_checks:
            lines.append("| 算子 | 可用 | 来源 | 签名 | 说明 |")
            lines.append("|---|---|---|---|---|")
            for oc in self.operator_checks:
                mark = "✅" if oc.available else "❌"
                lines.append(f"| `{oc.name}` | {mark} | {oc.source} | {oc.signature} | {oc.description} |")
        lines.append("")

        # ── 风险标记 ──
        lines.append("## 风险标记")
        lines.append(f"总计: **{self.risk_count}** 个")
        lines.append("")
        if self.risk_flags:
            for rf in self.risk_flags:
                icon = {"critical": "🔴", "warning": "🟡", "info": "🔵"}.get(rf.severity, "⚪")
                lines.append(f"- {icon} **[{rf.severity.upper()}]** [{rf.category}] {rf.message}")
        else:
            lines.append("- (无风险)")
        lines.append("")

        # ── 建议 ──
        rec_icon = {"proceed": "✅", "caution": "⚠️", "abort": "🛑"}.get(self.recommendation, "❓")
        lines.append(f"## 建议: {rec_icon} {self.recommendation.upper()}")
        if self.recommendation == "proceed":
            lines.append("数据条件满足，可进入 Ralph Loop 生成 Alpha。")
        elif self.recommendation == "caution":
            lines.append("部分字段/算子不可用或存在风险，建议调整后再继续。")
        elif self.recommendation == "abort":
            lines.append("关键数据缺失，建议更换研究方向或等待数据补充。")

        return "\n".join(lines)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def review_direction(
    direction_key: str,
    region: str = "USA",
    universe: str = "TOP3000",
    delay: int = 1,
    memory_snapshot: dict[str, Any] | None = None,
    online_fields: dict[str, str] | None = None,
    online_operators: dict[str, dict[str, str]] | None = None,
) -> DataReviewReport:
    """对指定研究方向执行数据预审。

    :param direction_key: DIRECTION_LIBRARY 中的方向 key
    :param region: 市场区域
    :param universe: 股票池
    :param delay: 数据延迟
    :param memory_snapshot: Experience Memory 快照 (from wq_memory_snapshot)
    :param online_fields: 在线查询到的数据字段 {name: description}
    :param online_operators: 在线查询到的算子 {name: {sig, category, desc}}
    :return: DataReviewReport
    """
    # 1. 查找方向
    direction = DIRECTION_LIBRARY.get(direction_key)
    if direction is None:
        # 未在库中找到 → 返回一个空报告 + critical 风险
        report = DataReviewReport(
            direction_key=direction_key,
            direction_name=f"(未知方向: {direction_key})",
            region=region,
            universe=universe,
            delay=delay,
            risk_flags=[RiskFlag(
                severity="critical",
                category="data_unavailable",
                message=f"方向 '{direction_key}' 不在 DIRECTION_LIBRARY 中，无法确定所需字段/算子。",
            )],
            risk_count=1,
            recommendation="abort",
        )
        return report

    key_fields = direction.get("key_fields", [])
    key_operators = direction.get("key_operators", [])
    direction_name = direction.get("name", direction_key)

    report = DataReviewReport(
        direction_key=direction_key,
        direction_name=direction_name,
        region=region,
        universe=universe,
        delay=delay,
    )

    # 2. 检查数据字段
    for fname in key_fields:
        # 先查 builtin
        if fname in BUILTIN_FIELDS:
            report.field_checks.append(FieldCheck(
                name=fname,
                available=True,
                source="builtin",
                description=BUILTIN_FIELDS[fname],
            ))
        # 再查 online
        elif online_fields and fname in online_fields:
            report.field_checks.append(FieldCheck(
                name=fname,
                available=True,
                source="online",
                description=online_fields[fname],
            ))
        else:
            report.field_checks.append(FieldCheck(
                name=fname,
                available=False,
                source="missing",
                description="",
            ))
            report.risk_flags.append(RiskFlag(
                severity="warning",
                category="data_unavailable",
                message=f"字段 '{fname}' 在缓存和在线查询中均不可用。",
            ))

    report.total_fields_required = len(key_fields)
    report.fields_available = sum(1 for fc in report.field_checks if fc.available)

    # 3. 检查算子
    for oname in key_operators:
        if oname in BUILTIN_OPERATORS:
            meta = BUILTIN_OPERATORS[oname]
            report.operator_checks.append(OperatorCheck(
                name=oname,
                available=True,
                source="builtin",
                signature=meta.get("sig", ""),
                description=meta.get("desc", ""),
            ))
        elif online_operators and oname in online_operators:
            meta = online_operators[oname]
            report.operator_checks.append(OperatorCheck(
                name=oname,
                available=True,
                source="online",
                signature=meta.get("sig", ""),
                description=meta.get("desc", ""),
            ))
        else:
            report.operator_checks.append(OperatorCheck(
                name=oname,
                available=False,
                source="missing",
            ))
            report.risk_flags.append(RiskFlag(
                severity="warning",
                category="operator_unavailable",
                message=f"算子 '{oname}' 在缓存和在线查询中均不可用。",
            ))

    report.total_operators_required = len(key_operators)
    report.operators_available = sum(1 for oc in report.operator_checks if oc.available)

    # 4. 检查 Experience Memory 禁区
    dir_tags = set(direction.get("tags", []))
    # 将 direction_key 本身也作为一个隐含 tag 用于匹配
    dir_tags_with_key = dir_tags | {direction_key}

    if memory_snapshot:
        # 禁区检查
        forbidden = memory_snapshot.get("forbidden_regions", [])
        for fr in forbidden:
            template = fr.get("template", "")
            # 如果禁区的标签与方向标签有交集（包含 direction_key）
            fr_tags = set(fr.get("tags", []))
            if fr_tags & dir_tags_with_key:
                report.risk_flags.append(RiskFlag(
                    severity="warning",
                    category="forbidden_region",
                    message=f"禁区 '{template}' 与当前方向标签重叠 (tags: {fr_tags & dir_tags})，命中率={fr.get('hit_count', 0)}。",
                ))

        # 洞察检查
        insights = memory_snapshot.get("strategic_insights", [])
        for ins in insights:
            ins_tags = set(ins.get("tags", []))
            if ins_tags & dir_tags_with_key:
                severity = ins.get("severity", "info")
                report.risk_flags.append(RiskFlag(
                    severity=severity,
                    category="insight",
                    message=f"相关洞察: {ins.get('insight', '')}",
                ))

    # 5. 计算建议
    report.risk_count = len(report.risk_flags)
    critical_count = sum(1 for rf in report.risk_flags if rf.severity == "critical")
    warning_count = sum(1 for rf in report.risk_flags if rf.severity == "warning")

    field_availability = report.fields_available / max(report.total_fields_required, 1)
    operator_availability = report.operators_available / max(report.total_operators_required, 1)

    if critical_count > 0 or field_availability < 0.5:
        report.recommendation = "abort"
    elif warning_count >= 2 or field_availability < 0.8 or operator_availability < 0.8:
        report.recommendation = "caution"
    else:
        report.recommendation = "proceed"

    return report
