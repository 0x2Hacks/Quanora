"""WorldQuant Brain 工具集的单元测试(不依赖真实 Brain 网络)。

覆盖:
- ExperienceMemory 的读写、合并、去重
- knowledge 的 prompt 拼装
- evaluator 的本地 stage1 / stage4 门控
- 工具暴露层的 schema 注册
- mutate / crossover 的语法正确性
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# 让 import 找到项目根
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ──────────────────────────────────────────────────────────────────────
# ExperienceMemory
# ──────────────────────────────────────────────────────────────────────
def test_experience_memory_roundtrip(tmp_path):
    from agent.infrastructure.tools.impl.tools.worldquant.memory import (
        AlphaRecord,
        ExperienceMemory,
        ForbiddenRegion,
        StrategicInsight,
        SuccessfulPattern,
    )

    mem = ExperienceMemory(root=str(tmp_path))
    mem.add_alpha(AlphaRecord(alpha_id="a1", expression="rank(close)", sharpe=1.8, direction="dir1"))
    mem.add_alpha(AlphaRecord(alpha_id="a2", expression="rank(volume)", sharpe=1.5, direction="dir1"))
    listed = mem.list_alphas()
    assert len(listed) == 2
    assert listed[0]["alpha_id"] == "a1"  # 按 sharpe 排序
    assert mem.has_expression("rank(close)") is True
    assert mem.has_expression("rank(open)") is False

    state = mem.get_state()
    assert state["library_size"] == 2

    mem.add_successful_pattern(
        SuccessfulPattern(template="rank(ts_delta(close, N))", avg_sharpe=1.6, hit_count=1, tags=["reversal"])
    )
    mem.add_successful_pattern(
        SuccessfulPattern(template="rank(ts_delta(close, N))", avg_sharpe=2.0, hit_count=1, tags=["reversal"])
    )
    top_succ = mem.top_successful_patterns()
    assert len(top_succ) == 1
    assert top_succ[0]["hit_count"] == 2
    assert abs(top_succ[0]["avg_sharpe"] - 1.8) < 1e-6  # (1.6+2.0)/2

    mem.add_forbidden_region(
        ForbiddenRegion(template="rank(divide(close, vwap))", reason="corr=0.81", hit_count=1)
    )
    mem.add_forbidden_region(
        ForbiddenRegion(template="rank(divide(close, vwap))", reason="corr=0.74", hit_count=1, correlated_with=["x"])
    )
    top_fail = mem.top_forbidden_regions()
    assert top_fail[0]["hit_count"] == 2

    mem.add_insight(StrategicInsight(insight="ts_rank 窗口过大易 NaN", severity="warning"))
    mem.add_insight(StrategicInsight(insight="ts_rank 窗口过大易 NaN", severity="warning"))  # 去重
    assert len(mem.top_insights()) == 1

    snapshot = mem.retrieve_for_prompt()
    assert "mining_state" in snapshot
    assert "successful_patterns" in snapshot


def test_experience_memory_uses_env_root(tmp_path, monkeypatch):
    from agent.infrastructure.tools.impl.tools.worldquant.memory import ExperienceMemory

    monkeypatch.setenv("WQ_MEMORY_ROOT", str(tmp_path / "via_env"))
    mem = ExperienceMemory()
    assert Path(mem.root).resolve() == (tmp_path / "via_env").resolve()


# ──────────────────────────────────────────────────────────────────────
# Knowledge / Prompt
# ──────────────────────────────────────────────────────────────────────
def test_build_generation_prompt_contains_blocks():
    from agent.infrastructure.tools.impl.tools.worldquant.knowledge import (
        DIRECTION_LIBRARY,
        build_generation_prompt,
    )

    snapshot = {
        "mining_state": {"library_size": 5, "recent_admits": []},
        "successful_patterns": [
            {"template": "rank(ts_delta(close, N))", "avg_sharpe": 1.8, "hit_count": 3, "rationale": "..."}
        ],
        "forbidden_regions": [
            {"template": "rank(divide(close, vwap))", "hit_count": 4, "reason": "high self-corr"}
        ],
        "strategic_insights": [{"insight": "deep nesting overfits", "severity": "warning"}],
    }
    prompt = build_generation_prompt(
        n=3,
        direction=DIRECTION_LIBRARY["reversal_short_term"],
        hypothesis="短期价格反转",
        memory_snapshot=snapshot,
    )
    assert "短期反转" in prompt
    assert "rank(ts_delta(close, N))" in prompt
    assert "rank(divide(close, vwap))" in prompt
    assert "JSON" in prompt


# ──────────────────────────────────────────────────────────────────────
# Evaluator local gates
# ──────────────────────────────────────────────────────────────────────
def test_stage1_local_check():
    from agent.infrastructure.tools.impl.tools.worldquant.evaluator import (
        Thresholds,
        stage1_local_check,
    )

    th = Thresholds()
    ok, _ = stage1_local_check("rank(ts_delta(close, 5))", th)
    assert ok is True

    ok, reason = stage1_local_check("close", th)
    assert ok is False and "operator" in reason

    ok, reason = stage1_local_check("rank((close, 5)", th)
    assert ok is False and "parentheses" in reason

    deep_expr = "rank(" * 12 + "close" + ")" * 12
    ok, reason = stage1_local_check(deep_expr, th)
    assert ok is False and "nesting" in reason


def test_stage4_template_dedup(tmp_path):
    from agent.infrastructure.tools.impl.tools.worldquant.evaluator import stage4_template_dedup
    from agent.infrastructure.tools.impl.tools.worldquant.memory import (
        AlphaRecord,
        ExperienceMemory,
    )

    mem = ExperienceMemory(root=str(tmp_path))
    mem.add_alpha(AlphaRecord(alpha_id="x1", expression="rank(ts_delta(close, 5))"))
    # 完全相同 -> 拒
    ok, reason = stage4_template_dedup("rank(ts_delta(close, 5))", mem)
    assert ok is False
    # 模板相同(只是窗口变了) -> 拒
    ok, reason = stage4_template_dedup("rank(ts_delta(close, 20))", mem)
    assert ok is False and "template" in reason
    # 完全不同模板 -> 通过
    ok, _ = stage4_template_dedup("rank(volume)", mem)
    assert ok is True


def test_normalize_template():
    from agent.infrastructure.tools.impl.tools.worldquant.evaluator import normalize_template

    a = normalize_template("rank(ts_delta(close, 5))")
    b = normalize_template("rank(ts_delta(close, 20))")
    c = normalize_template("rank(ts_delta(close,  30) )")
    assert a == b == c


def test_parse_brain_checks_pass():
    from agent.infrastructure.tools.impl.tools.worldquant.evaluator import parse_brain_checks

    is_payload = {"checks": [{"name": "LOW_SHARPE", "result": "PASS", "value": 1.5, "limit": 1.25}]}
    ok, reason, checks = parse_brain_checks(is_payload)
    assert ok is True
    assert len(checks) == 1


def test_parse_brain_checks_fail():
    from agent.infrastructure.tools.impl.tools.worldquant.evaluator import parse_brain_checks

    is_payload = {
        "checks": [
            {"name": "LOW_SHARPE", "result": "PASS", "value": 1.5},
            {"name": "SELF_CORR", "result": "FAIL", "value": 0.81, "limit": 0.7},
        ]
    }
    ok, reason, _ = parse_brain_checks(is_payload)
    assert ok is False
    assert "SELF_CORR" in reason


# ──────────────────────────────────────────────────────────────────────
# Tool 暴露层 — 不需要登录的工具应当可独立工作
# ──────────────────────────────────────────────────────────────────────
def test_tool_registry_includes_wq_tools():
    from agent.infrastructure.tools.impl import TOOLS, TOOL_SCHEMAS

    for name in (
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
    ):
        assert name in TOOLS, f"tool {name} missing"
    names_in_schemas = {item["function"]["name"] for item in TOOL_SCHEMAS}
    assert {"wq_login", "wq_evaluate_alpha", "wq_mutate_alpha"}.issubset(names_in_schemas)


def test_wq_list_operators_cache_no_network():
    from agent.infrastructure.tools.impl.tools.worldquant import wq_list_operators

    raw = wq_list_operators(use_cache=True)
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert "operators" in payload["data"]
    assert "ts_rank" in payload["data"]["operators"]


def test_wq_list_directions():
    from agent.infrastructure.tools.impl.tools.worldquant import wq_list_directions

    raw = wq_list_directions()
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert "reversal_short_term" in payload["data"]["directions"]


def test_wq_memory_snapshot_empty_root(tmp_path, monkeypatch):
    monkeypatch.setenv("WQ_MEMORY_ROOT", str(tmp_path / "mem"))
    import importlib

    import agent.infrastructure.tools.impl.tools.worldquant as wq

    importlib.reload(wq)
    raw = wq.wq_memory_snapshot()
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["data"]["mining_state"]["library_size"] == 0


def test_wq_build_generation_prompt(tmp_path, monkeypatch):
    monkeypatch.setenv("WQ_MEMORY_ROOT", str(tmp_path))
    import importlib

    import agent.infrastructure.tools.impl.tools.worldquant as wq

    importlib.reload(wq)
    raw = wq.wq_build_generation_prompt(direction_key="momentum_mid_term", hypothesis="中期动量", n=4)
    payload = json.loads(raw)
    assert payload["ok"] is True
    prompt = payload["data"]["prompt"]
    assert "中期动量" in prompt
    assert "JSON" in prompt
    assert "P_succ" in prompt or "推荐方向" in prompt


def test_wq_mutate_alpha():
    from agent.infrastructure.tools.impl.tools.worldquant import wq_mutate_alpha

    raw = wq_mutate_alpha("rank(ts_delta(close, 5))", window_candidates=[10, 20, 60])
    payload = json.loads(raw)
    assert payload["ok"] is True
    variants = payload["data"]["variants"]
    assert "rank(ts_delta(close, 10))" in variants
    assert "rank(ts_delta(close, 20))" in variants


def test_wq_mutate_alpha_no_param():
    from agent.infrastructure.tools.impl.tools.worldquant import wq_mutate_alpha

    raw = wq_mutate_alpha("rank(close)")
    payload = json.loads(raw)
    assert payload["ok"] is False


def test_wq_crossover_alpha_wrap_strategy():
    from agent.infrastructure.tools.impl.tools.worldquant import wq_crossover_alpha

    raw = wq_crossover_alpha("rank(ts_delta(close, 5))", "ts_rank(volume, 10)", strategy="wrap_b_in_a")
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert "ts_rank(volume, 10)" in payload["data"]["result"]
    assert payload["data"]["result"].startswith("rank(")


def test_wq_crossover_alpha_rank_pair():
    from agent.infrastructure.tools.impl.tools.worldquant import wq_crossover_alpha

    raw = wq_crossover_alpha("close", "volume", strategy="rank_pair")
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["data"]["result"] == "subtract(rank(close), rank(volume))"


def test_wq_distill_insight(tmp_path, monkeypatch):
    monkeypatch.setenv("WQ_MEMORY_ROOT", str(tmp_path))
    import importlib

    import agent.infrastructure.tools.impl.tools.worldquant as wq

    importlib.reload(wq)
    raw = wq.wq_distill_insight("使用过大的 ts_rank 窗口易出现 NaN", severity="warning", tags=["volatility"])
    payload = json.loads(raw)
    assert payload["ok"] is True
    snap_raw = wq.wq_memory_snapshot()
    snap = json.loads(snap_raw)
    insights = snap["data"]["strategic_insights"]
    assert any("ts_rank" in i.get("insight", "") for i in insights)


# ──────────────────────────────────────────────────────────────────────
# 凭证解析
# ──────────────────────────────────────────────────────────────────────
def test_credentials_from_env(monkeypatch):
    from agent.infrastructure.tools.impl.tools.worldquant.client import WQCredentials

    monkeypatch.setenv("WQ_BRAIN_EMAIL", "user@example.com")
    monkeypatch.setenv("WQ_BRAIN_PASSWORD", "secret")
    creds = WQCredentials.resolve()
    assert creds.email == "user@example.com"
    assert creds.password == "secret"


def test_credentials_missing_raises(monkeypatch):
    from agent.infrastructure.tools.impl.tools.worldquant.client import WQAuthError, WQCredentials

    monkeypatch.delenv("WQ_BRAIN_EMAIL", raising=False)
    monkeypatch.delenv("WQ_BRAIN_PASSWORD", raising=False)
    monkeypatch.chdir(Path(tempfile.mkdtemp()))  # 切到空目录避免 credential.txt 干扰
    with pytest.raises(WQAuthError):
        WQCredentials.resolve()
