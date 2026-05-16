"""WorldQuant Brain 表达式语言(FASTEXPR)的精简知识库 + Prompt 拼装。

为什么内置?
- 算子/数据字段在线接口可能受限或慢,先内置常用集合做"零网络冷启动"
- LLM 生成因子时强约束类型签名,显著降低无效表达式
"""

from __future__ import annotations

import json
from typing import Any

# ──────────────────────────────────────────────────────────────────────
# 内置算子集(覆盖 FactorMiner 论文中提到的 60+ 算子的子集 + Brain 平台命名)
# 命名以 Brain 的 FASTEXPR 为准。
# ──────────────────────────────────────────────────────────────────────
BUILTIN_OPERATORS: dict[str, dict[str, str]] = {
    # 算术
    "add": {"category": "arith", "sig": "(x,y) -> num", "desc": "x + y"},
    "subtract": {"category": "arith", "sig": "(x,y) -> num", "desc": "x - y"},
    "multiply": {"category": "arith", "sig": "(x,y) -> num", "desc": "x * y"},
    "divide": {"category": "arith", "sig": "(x,y) -> num", "desc": "x / y (NaN if y==0)"},
    "abs": {"category": "arith", "sig": "(x) -> num", "desc": "|x|"},
    "log": {"category": "arith", "sig": "(x) -> num", "desc": "log(x) (x>0)"},
    "signed_power": {"category": "arith", "sig": "(x,n) -> num", "desc": "sign(x) * |x|^n"},
    "sign": {"category": "arith", "sig": "(x) -> {-1,0,1}", "desc": ""},
    # 截面
    "rank": {"category": "cross", "sig": "(x) -> [0,1]", "desc": "横截面 rank"},
    "scale": {"category": "cross", "sig": "(x,a=1) -> num", "desc": "归一化到 L1=a"},
    "zscore": {"category": "cross", "sig": "(x) -> num", "desc": "横截面 z-score"},
    "winsorize": {"category": "cross", "sig": "(x,std=4) -> num", "desc": "去极值"},
    # 时间序列
    "ts_rank": {"category": "ts", "sig": "(x,d) -> [0,1]", "desc": "过去 d 天 rank"},
    "ts_mean": {"category": "ts", "sig": "(x,d) -> num", "desc": "过去 d 天均值"},
    "ts_std_dev": {"category": "ts", "sig": "(x,d) -> num", "desc": "过去 d 天标准差"},
    "ts_max": {"category": "ts", "sig": "(x,d) -> num", "desc": ""},
    "ts_min": {"category": "ts", "sig": "(x,d) -> num", "desc": ""},
    "ts_arg_max": {"category": "ts", "sig": "(x,d) -> int", "desc": "max 出现位置(距今)"},
    "ts_arg_min": {"category": "ts", "sig": "(x,d) -> int", "desc": ""},
    "ts_delta": {"category": "ts", "sig": "(x,d) -> num", "desc": "x - delay(x,d)"},
    "ts_decay_linear": {"category": "ts", "sig": "(x,d) -> num", "desc": "线性衰减 SMA"},
    "ts_corr": {"category": "ts", "sig": "(x,y,d) -> [-1,1]", "desc": ""},
    "ts_covariance": {"category": "ts", "sig": "(x,y,d) -> num", "desc": ""},
    "ts_skewness": {"category": "ts", "sig": "(x,d) -> num", "desc": ""},
    "ts_kurtosis": {"category": "ts", "sig": "(x,d) -> num", "desc": ""},
    "ts_regression": {"category": "ts", "sig": "(y,x,d) -> num", "desc": "回归斜率"},
    "ts_sum": {"category": "ts", "sig": "(x,d) -> num", "desc": ""},
    "ts_product": {"category": "ts", "sig": "(x,d) -> num", "desc": ""},
    "ts_zscore": {"category": "ts", "sig": "(x,d) -> num", "desc": ""},
    # 逻辑
    "if_else": {"category": "logic", "sig": "(cond,a,b) -> num", "desc": ""},
    "greater": {"category": "logic", "sig": "(x,y) -> bool", "desc": ""},
    "less": {"category": "logic", "sig": "(x,y) -> bool", "desc": ""},
    "and_op": {"category": "logic", "sig": "(x,y) -> bool", "desc": ""},
    "or_op": {"category": "logic", "sig": "(x,y) -> bool", "desc": ""},
    # 分组(行业/类别)
    "group_neutralize": {"category": "group", "sig": "(x,g) -> num", "desc": "组内中性化"},
    "group_rank": {"category": "group", "sig": "(x,g) -> [0,1]", "desc": ""},
    "group_mean": {"category": "group", "sig": "(x,g) -> num", "desc": ""},
    "group_zscore": {"category": "group", "sig": "(x,g) -> num", "desc": ""},
}

# 常用数据字段(Brain USA TOP3000 / Delay 1 默认可用)
BUILTIN_FIELDS: dict[str, str] = {
    "open": "开盘价",
    "high": "最高价",
    "low": "最低价",
    "close": "收盘价",
    "volume": "成交量",
    "vwap": "成交量加权均价",
    "returns": "日收益率",
    "cap": "市值",
    "adv20": "20日平均成交量",
    "adv60": "60日平均成交量",
    "industry": "行业分组",
    "sector": "板块分组",
    "subindustry": "子行业分组",
}

# ──────────────────────────────────────────────────────────────────────
# Direction Library:常见研究方向(对应 QuantaAlpha 的 Planning Diversification)
# ──────────────────────────────────────────────────────────────────────
DIRECTION_LIBRARY: dict[str, dict[str, Any]] = {
    "reversal_short_term": {
        "name": "短期反转",
        "description": "捕捉 1-10 日尺度的均值回归",
        "key_fields": ["close", "returns", "volume"],
        "key_operators": ["ts_rank", "ts_delta", "rank"],
        "tags": ["reversal", "short_term"],
    },
    "momentum_mid_term": {
        "name": "中期动量",
        "description": "捕捉 20-120 日尺度的趋势延续",
        "key_fields": ["close", "returns", "high", "low"],
        "key_operators": ["ts_mean", "ts_delta", "ts_regression"],
        "tags": ["momentum", "mid_term"],
    },
    "volatility_regime": {
        "name": "波动率因子",
        "description": "基于波动率结构变化的择股信号",
        "key_fields": ["returns", "high", "low", "close"],
        "key_operators": ["ts_std_dev", "ts_kurtosis", "ts_skewness"],
        "tags": ["volatility", "risk"],
    },
    "volume_price_divergence": {
        "name": "量价背离",
        "description": "成交量与价格的非线性关系",
        "key_fields": ["volume", "close", "vwap", "adv20"],
        "key_operators": ["ts_corr", "rank", "divide"],
        "tags": ["volume", "microstructure"],
    },
    "high_order_moments": {
        "name": "高阶矩",
        "description": "偏度/峰度等高阶统计量的截面排序",
        "key_fields": ["returns", "close"],
        "key_operators": ["ts_skewness", "ts_kurtosis", "rank", "if_else"],
        "tags": ["high_order", "skew"],
    },
    "intraday_microstructure": {
        "name": "日内微结构",
        "description": "开-高-低-收 + VWAP 之间的关系",
        "key_fields": ["open", "high", "low", "close", "vwap"],
        "key_operators": ["subtract", "divide", "ts_mean"],
        "tags": ["microstructure", "intraday"],
    },
}


# ──────────────────────────────────────────────────────────────────────
# Prompt 拼装
# ──────────────────────────────────────────────────────────────────────
GENERATION_PROMPT_TEMPLATE = """你是 WorldQuant Brain 平台的 alpha 因子研究员。请基于以下信息生成 {n} 个**新颖、低相关、可直接在 Brain 平台执行**的 alpha 表达式。

## 研究方向
{direction_block}

## 假设(Hypothesis)
{hypothesis}

## 可用算子(节选)
{operator_block}

## 可用数据字段(节选)
{field_block}

## 经验记忆 — 推荐方向 (P_succ)
{succ_block}

## 经验记忆 — 禁区 / 红海 (P_fail) - 必须避开
{fail_block}

## 策略级洞察 (I)
{insight_block}

## 因子库当前状态
{state_block}

## 表达式规范
1. 使用 FASTEXPR 语法,函数调用风格,例如:`rank(ts_delta(close, 5))`
2. 字段不带 $ 前缀,直接写 `close`/`volume`/`vwap` 等
3. 表达式必须以截面排序或 z-score 收尾(返回截面打分),如 `rank(...)` 或 `zscore(...)`
4. 表达式总长度不要超过 250 字符
5. **必须避开 P_fail 中列出的所有模板**

## 输出格式
严格输出一个 JSON 数组,每个元素是:
```json
{{
  "expression": "rank(ts_corr(volume, close, 10))",
  "hypothesis": "成交量-价格短期相关度反映流动性变化",
  "template": "rank(ts_corr(volume, close, T))",
  "tags": ["volume_price_divergence"]
}}
```
不要任何额外解释,只输出 JSON 数组。
"""


def render_operator_block(operators: dict[str, dict[str, str]] | None = None, max_n: int = 30) -> str:
    operators = operators or BUILTIN_OPERATORS
    lines = []
    for name, meta in list(operators.items())[:max_n]:
        lines.append(f"- `{name}{meta.get('sig','')}` [{meta.get('category','')}] {meta.get('desc','')}")
    return "\n".join(lines)


def render_field_block(fields: dict[str, str] | None = None) -> str:
    fields = fields or BUILTIN_FIELDS
    return "\n".join(f"- `{name}`: {desc}" for name, desc in fields.items())


def render_succ_block(patterns: list[dict[str, Any]]) -> str:
    if not patterns:
        return "- (空,本次会冷启动)"
    return "\n".join(
        f"- 模板 `{p.get('template','')}` | avg_sharpe={p.get('avg_sharpe',0):.2f} | hits={p.get('hit_count',0)} | rationale: {p.get('rationale','')}"
        for p in patterns
    )


def render_fail_block(regions: list[dict[str, Any]]) -> str:
    if not regions:
        return "- (空)"
    return "\n".join(
        f"- 禁区 `{r.get('template','')}` | hits={r.get('hit_count',0)} | reason: {r.get('reason','')}"
        for r in regions
    )


def render_insight_block(insights: list[dict[str, Any]]) -> str:
    if not insights:
        return "- (空)"
    return "\n".join(f"- [{i.get('severity','info').upper()}] {i.get('insight','')}" for i in insights)


def render_state_block(state: dict[str, Any]) -> str:
    return f"- 因子库规模: {state.get('library_size',0)}\n- 近期准入(节选): {len(state.get('recent_admits',[]))} 条"


def render_direction_block(direction: dict[str, Any] | str) -> str:
    if isinstance(direction, str):
        return f"- {direction}"
    return (
        f"- 名称: {direction.get('name','')}\n"
        f"- 描述: {direction.get('description','')}\n"
        f"- 关键字段: {', '.join(direction.get('key_fields',[]))}\n"
        f"- 关键算子: {', '.join(direction.get('key_operators',[]))}\n"
        f"- 标签: {', '.join(direction.get('tags',[]))}"
    )


def build_generation_prompt(
    *,
    n: int,
    direction: dict[str, Any] | str,
    hypothesis: str,
    memory_snapshot: dict[str, Any],
    operators: dict[str, dict[str, str]] | None = None,
    fields: dict[str, str] | None = None,
) -> str:
    return GENERATION_PROMPT_TEMPLATE.format(
        n=n,
        direction_block=render_direction_block(direction),
        hypothesis=hypothesis or "(由 LLM 自行选择一个待验证假设)",
        operator_block=render_operator_block(operators),
        field_block=render_field_block(fields),
        succ_block=render_succ_block(memory_snapshot.get("successful_patterns", [])),
        fail_block=render_fail_block(memory_snapshot.get("forbidden_regions", [])),
        insight_block=render_insight_block(memory_snapshot.get("strategic_insights", [])),
        state_block=render_state_block(memory_snapshot.get("mining_state", {})),
    )
