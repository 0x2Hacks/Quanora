"""Research Experience tools — 供 agent 调用的工具函数.

提供工具让 agent 在量化研究中自动总结和查询项目级研究经验：

1. record_research_experience — 记录一条研究经验
2. query_research_experience — 查询项目历史研究经验
3. get_research_summary — 获取研究经验统计摘要
"""

from __future__ import annotations

import json as _json
from typing import Any

from agent.domain.tool_result import tool_error, tool_ok
from agent.domain.research_experience import (
    ResearchExperience,
    ResearchExperienceBook,
    StrategyCategory,
    Outcome,
    RegimeType,
)

_TOOL_NAME = "research_experience"


def _get_repo():
    """Lazy-load the ResearchExperienceRepository for the current project."""
    from agent.infrastructure.config import Config
    from agent.infrastructure.persistence.research_experience_repository import (
        ResearchExperienceRepository,
    )

    project_root = Config.WORKSPACE_ROOT
    if not project_root:
        return None
    return ResearchExperienceRepository(project_root)


def record_research_experience(
    strategy_name: str = "",
    strategy_category: str = "",
    expression: str = "",
    instrument: str = "",
    timeframe: str = "",
    outcome: str = "",
    key_insight: str = "",
    what_worked: str = "",
    what_failed: str = "",
    pitfalls: str = "",
    next_steps: str = "",
    tags: str = "",
    performance: str = "",
    market_regime: str = "",
    universe: str = "",
    region: str = "",
    date_range: str = "",
    parameters: str = "",
) -> str:
    """记录一条量化研究经验到项目级经验库。在完成策略研究后调用，总结经验教训供未来会话复用。

    Args:
        strategy_name: 策略名称，如 "dual_ma_crossover"
        strategy_category: 策略分类（momentum/mean_reversion/breakout/trend_following/volatility/seasonality/microstructure/statistical_arbitrage/machine_learning/other）
        expression: Alpha表达式或策略代码片段
        instrument: 标的，如 "XAUUSD"、"SPY"
        timeframe: 时间框架，如 "M5"、"H1"、"daily"
        outcome: 研究结果（success/partial/failure/inconclusive/insight）
        key_insight: 核心洞察（一句话总结最重要的发现）
        what_worked: 哪些方面有效
        what_failed: 哪些方面失败及原因
        pitfalls: 陷阱列表，JSON数组字符串，如 '["过拟合","滑点未计入"]'
        next_steps: 建议后续步骤，JSON数组字符串
        tags: 标签，JSON数组字符串，如 '["xauusd","mean_reversion"]'
        performance: 性能指标，JSON对象字符串，如 '{"sharpe":1.5,"max_drawdown":0.12}'
        market_regime: 市场环境（trending_up/trending_down/ranging/high_volatility/low_volatility/unknown）
        universe: 股票池/标的范围，如 "TOP3000"
        region: 市场区域，如 "USA"
        date_range: 回测日期范围，如 "2024-01-01~2025-12-31"
        parameters: 关键参数，JSON对象字符串，如 '{"window":20,"threshold":0.02}'
    """
    repo = _get_repo()
    if repo is None:
        return tool_error(_TOOL_NAME, "无法确定项目根目录，无法保存研究经验")

    # Parse JSON string parameters
    def _parse_json_list(s: str) -> list[str]:
        if not s:
            return []
        try:
            result = _json.loads(s)
            return result if isinstance(result, list) else [str(result)]
        except _json.JSONDecodeError:
            return [s]

    def _parse_json_dict(s: str) -> dict:
        if not s:
            return {}
        try:
            result = _json.loads(s)
            return result if isinstance(result, dict) else {}
        except _json.JSONDecodeError:
            return {}

    # Validate outcome
    valid_outcomes = {o.value for o in Outcome}
    if outcome and outcome not in valid_outcomes:
        return tool_error(
            _TOOL_NAME,
            f"无效outcome '{outcome}'，可选值: {', '.join(sorted(valid_outcomes))}",
        )

    # Validate strategy_category
    valid_categories = {c.value for c in StrategyCategory}
    if strategy_category and strategy_category not in valid_categories:
        return tool_error(
            _TOOL_NAME,
            f"无效strategy_category '{strategy_category}'，可选值: {', '.join(sorted(valid_categories))}",
        )

    record = ResearchExperience(
        strategy_name=strategy_name,
        strategy_category=strategy_category,
        expression=expression,
        instrument=instrument,
        timeframe=timeframe,
        outcome=outcome,
        key_insight=key_insight,
        what_worked=what_worked,
        what_failed=what_failed,
        pitfalls=_parse_json_list(pitfalls),
        next_steps=_parse_json_list(next_steps),
        tags=_parse_json_list(tags),
        performance=_parse_json_dict(performance),
        market_regime=market_regime,
        universe=universe,
        region=region,
        date_range=date_range,
        parameters=_parse_json_dict(parameters),
    )

    try:
        record_id = repo.add_record(record)
        book = repo.load()
        return tool_ok(
            _TOOL_NAME,
            f"研究经验已记录 (id={record_id})。项目经验库现有 {len(book)} 条记录。",
            {"record_id": record_id, "total_records": len(book)},
        )
    except Exception as exc:
        return tool_error(_TOOL_NAME, f"保存研究经验失败: {exc}")


def query_research_experience(
    strategy_category: str = "",
    instrument: str = "",
    outcome: str = "",
    tags: str = "",
    keyword: str = "",
    k: int = 10,
) -> str:
    """查询项目历史研究经验。在新研究开始前或研究过程中调用，查阅相关经验避免重复探索。

    Args:
        strategy_category: 按策略分类过滤（momentum/mean_reversion/...）
        instrument: 按标的过滤，如 "XAUUSD"
        outcome: 按结果过滤（success/partial/failure/inconclusive/insight）
        tags: 按标签过滤，JSON数组字符串，需全部匹配
        keyword: 关键词搜索（全文搜索）
        k: 最多返回条数（默认10）
    """
    repo = _get_repo()
    if repo is None:
        return tool_error(_TOOL_NAME, "无法确定项目根目录")

    book = repo.load()
    if len(book) == 0:
        return tool_ok(_TOOL_NAME, "项目经验库为空，尚无研究经验记录。", {"total": 0, "results": []})

    # Apply filters
    results = book.records

    if strategy_category:
        results = [r for r in results if r.strategy_category == strategy_category]

    if instrument:
        inst_lower = instrument.lower()
        results = [r for r in results if r.instrument.lower() == inst_lower]

    if outcome:
        results = [r for r in results if r.outcome == outcome]

    if tags:
        tag_list = _json.loads(tags) if tags.startswith("[") else [tags]
        tag_set = set(tag_list)
        results = [r for r in results if tag_set.issubset(set(r.tags))]

    if keyword:
        kw = keyword.lower()
        filtered = []
        for r in results:
            text = " ".join([
                r.strategy_name, r.expression, r.what_worked,
                r.what_failed, r.key_insight,
                " ".join(r.pitfalls), " ".join(r.next_steps),
            ]).lower()
            if kw in text:
                filtered.append(r)
        results = filtered

    # Sort by created_at desc, limit
    results.sort(key=lambda r: r.created_at, reverse=True)
    results = results[:k]

    # Format output
    lines = [f"找到 {len(results)} 条相关研究经验：", ""]
    for r in results:
        lines.append(f"### [{r.outcome.upper()}] {r.strategy_name or r.strategy_category}")
        if r.instrument:
            lines.append(f"- 标的: {r.instrument}")
        if r.key_insight:
            lines.append(f"- 核心洞察: {r.key_insight}")
        if r.what_worked:
            lines.append(f"- 有效: {r.what_worked}")
        if r.what_failed:
            lines.append(f"- 失败: {r.what_failed}")
        if r.performance:
            perf_parts = [f"{k}={v}" for k, v in r.performance.items() if v is not None]
            if perf_parts:
                lines.append(f"- 指标: {', '.join(perf_parts)}")
        if r.pitfalls:
            lines.append(f"- 陷阱: {', '.join(r.pitfalls)}")
        lines.append("")

    return tool_ok(
        _TOOL_NAME,
        "\n".join(lines),
        {"total": len(book), "filtered": len(results), "results": [r.to_dict() for r in results]},
    )


def get_research_summary() -> str:
    """获取项目研究经验统计摘要。了解项目整体研究进展和经验分布。

    Returns:
        统计摘要，包括各分类/结果/标的的经验数量分布。
    """
    repo = _get_repo()
    if repo is None:
        return tool_error(_TOOL_NAME, "无法确定项目根目录")

    book = repo.load()
    stats = book.get_summary_stats()

    if stats.get("total", 0) == 0:
        return tool_ok(_TOOL_NAME, "项目经验库为空。", stats)

    lines = [
        f"项目研究经验摘要 (共 {stats['total']} 条)",
        "",
        "### 按结果分布",
    ]
    for outcome, count in stats.get("by_outcome", {}).items():
        lines.append(f"- {outcome}: {count}")

    lines.append("")
    lines.append("### 按策略分类")
    for cat, count in stats.get("by_strategy_category", {}).items():
        lines.append(f"- {cat}: {count}")

    lines.append("")
    lines.append("### 按标的")
    for inst, count in stats.get("by_instrument", {}).items():
        lines.append(f"- {inst}: {count}")

    # Top insights
    insights = book.query_top_insights(k=5)
    if insights:
        lines.append("")
        lines.append("### 最近关键洞察")
        for r in insights:
            lines.append(f"- [{r.outcome.upper()}] {r.strategy_name}: {r.key_insight}")

    return tool_ok(_TOOL_NAME, "\n".join(lines), stats)
