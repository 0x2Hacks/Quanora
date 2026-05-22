"""Experience Memory(经验记忆模块)。

实现 FactorMiner 论文的 Memory M_t = (S, P, I):
- S: Mining State (因子库规模、近期准入日志)
- P: Structural Experience
    - P_succ: 推荐方向(Successful Patterns)
    - P_fail: 禁区(Forbidden Regions / 红海)
- I: Strategic Insights (高层教训,如算子稳定性警告)

存储方式:JSONL append-only 事件流(对齐 Quanora 整体的事件溯源风格)。
读写策略:
- 写: 每轮挖掘结束追加 distillation 记录
- 读: 检索时根据 tag/keyword 召回 top-K,注入 prompt
- 进化: 通过 _compact() 合并冗余条目(在条目数超过阈值时触发)
"""

from __future__ import annotations

import json
import os
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _new_id() -> str:
    return uuid.uuid4().hex[:12]


@dataclass(slots=True)
class AlphaRecord:
    """因子库中的一条 alpha(全局视角)。"""

    alpha_id: str = ""
    expression: str = ""
    direction: str = ""           # 所属研究方向
    sharpe: float | None = None
    fitness: float | None = None
    turnover: float | None = None
    returns: float | None = None
    drawdown: float | None = None
    ic: float | None = None
    icir: float | None = None
    correlation: float | None = None  # 与库内最大相关性
    region: str = "USA"
    universe: str = "TOP3000"
    status: str = "UNSUBMITTED"   # UNSUBMITTED / SUBMITTED / REJECTED
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)
    notes: str = ""


@dataclass(slots=True)
class SuccessfulPattern:
    """P_succ:成功的因子模板。"""

    pattern_id: str = field(default_factory=_new_id)
    template: str = ""       # 形如 "ts_rank(skew(returns, T), W)"
    rationale: str = ""      # 经济学/统计学解释
    example_expressions: list[str] = field(default_factory=list)
    avg_sharpe: float = 0.0
    hit_count: int = 0
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)


@dataclass(slots=True)
class ForbiddenRegion:
    """P_fail:禁区(红海)。"""

    region_id: str = field(default_factory=_new_id)
    template: str = ""
    reason: str = ""             # 如 "max corr with 库内: 0.74"
    representative_expressions: list[str] = field(default_factory=list)
    correlated_with: list[str] = field(default_factory=list)  # 触发禁区的 alpha_id
    hit_count: int = 0
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)


@dataclass(slots=True)
class StrategicInsight:
    """I:策略级洞察。"""

    insight_id: str = field(default_factory=_new_id)
    insight: str = ""           # 如 "ts_rank 窗口 > 60 时数值不稳定,易出现 NaN"
    category: str = "general"    # operator | data_field | regime | general
    severity: str = "info"       # info | warning | critical
    tags: list[str] = field(default_factory=list)
    created_at: str = field(default_factory=_now_iso)


class ExperienceMemory:
    """文件后端的 Experience Memory。

    目录布局::

        <root>/
        ├── alpha_library.jsonl       # 因子库(全局)
        ├── successful_patterns.jsonl # P_succ
        ├── forbidden_regions.jsonl   # P_fail
        ├── strategic_insights.jsonl  # I
        └── mining_state.json         # S (单文件覆盖写)
    """

    PATTERN_CAPACITY = 200       # 超过则触发合并
    FORBIDDEN_CAPACITY = 200
    INSIGHT_CAPACITY = 100

    def __init__(self, root: str | None = None) -> None:
        env_root = os.getenv("WQ_MEMORY_ROOT", "").strip()
        chosen = root or env_root or "./wq_memory"
        self.root = Path(chosen).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.alpha_path = self.root / "alpha_library.jsonl"
        self.succ_path = self.root / "successful_patterns.jsonl"
        self.fail_path = self.root / "forbidden_regions.jsonl"
        self.insight_path = self.root / "strategic_insights.jsonl"
        self.state_path = self.root / "mining_state.json"
        for f in (self.alpha_path, self.succ_path, self.fail_path, self.insight_path):
            if not f.exists():
                f.touch()
        if not self.state_path.exists():
            self.state_path.write_text(json.dumps({"library_size": 0, "recent_admits": []}, indent=2), encoding="utf-8")

    # ──────────────────────────────────────────────────────────
    # 低层 IO
    # ──────────────────────────────────────────────────────────
    def _append_jsonl(self, path: Path, record: dict[str, Any]) -> None:
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")

    def _read_jsonl(self, path: Path) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except Exception:
                continue
        return records

    def _rewrite_jsonl(self, path: Path, records: list[dict[str, Any]]) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            for record in records:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        tmp.replace(path)

    # ──────────────────────────────────────────────────────────
    # 因子库(Alpha Library)
    # ──────────────────────────────────────────────────────────
    def add_alpha(self, alpha: AlphaRecord) -> None:
        self._append_jsonl(self.alpha_path, asdict(alpha))
        state = json.loads(self.state_path.read_text(encoding="utf-8"))
        state["library_size"] = state.get("library_size", 0) + 1
        admits = state.get("recent_admits", [])
        admits.append({"alpha_id": alpha.alpha_id, "expression": alpha.expression[:120], "sharpe": alpha.sharpe})
        state["recent_admits"] = admits[-20:]
        self.state_path.write_text(json.dumps(state, indent=2), encoding="utf-8")

    def list_alphas(self, limit: int | None = None, min_sharpe: float | None = None) -> list[dict[str, Any]]:
        records = self._read_jsonl(self.alpha_path)
        if min_sharpe is not None:
            records = [r for r in records if (r.get("sharpe") or 0) >= min_sharpe]
        records.sort(key=lambda r: (r.get("sharpe") or 0), reverse=True)
        return records[:limit] if limit else records

    def has_expression(self, expression: str) -> bool:
        target = expression.strip()
        for record in self._read_jsonl(self.alpha_path):
            if record.get("expression", "").strip() == target:
                return True
        return False

    # ──────────────────────────────────────────────────────────
    # Successful Patterns (P_succ)
    # ──────────────────────────────────────────────────────────
    def add_successful_pattern(self, pattern: SuccessfulPattern) -> None:
        records = self._read_jsonl(self.succ_path)
        # 同模板已有则累加 hit_count + 更新平均 sharpe
        for record in records:
            if record.get("template") == pattern.template:
                old_count = record.get("hit_count", 0)
                old_avg = record.get("avg_sharpe", 0.0)
                new_count = old_count + max(pattern.hit_count, 1)
                record["hit_count"] = new_count
                record["avg_sharpe"] = (old_avg * old_count + pattern.avg_sharpe * max(pattern.hit_count, 1)) / new_count
                examples = list(record.get("example_expressions", [])) + list(pattern.example_expressions)
                record["example_expressions"] = list(dict.fromkeys(examples))[:5]
                self._rewrite_jsonl(self.succ_path, records)
                return
        self._append_jsonl(self.succ_path, asdict(pattern))
        if len(records) + 1 > self.PATTERN_CAPACITY:
            self._compact_patterns()

    def top_successful_patterns(self, k: int = 5, tags: list[str] | None = None) -> list[dict[str, Any]]:
        records = self._read_jsonl(self.succ_path)
        if tags:
            tag_set = set(tags)
            records = [r for r in records if tag_set.intersection(set(r.get("tags") or []))]
        records.sort(key=lambda r: (r.get("avg_sharpe", 0.0), r.get("hit_count", 0)), reverse=True)
        return records[:k]

    def _compact_patterns(self) -> None:
        # 删除 avg_sharpe < 0.3 且 hit_count == 1 的稀疏样本
        records = self._read_jsonl(self.succ_path)
        cleaned = [r for r in records if not (r.get("avg_sharpe", 0.0) < 0.3 and r.get("hit_count", 0) <= 1)]
        self._rewrite_jsonl(self.succ_path, cleaned)

    # ──────────────────────────────────────────────────────────
    # Forbidden Regions (P_fail)
    # ──────────────────────────────────────────────────────────
    def add_forbidden_region(self, region: ForbiddenRegion) -> None:
        records = self._read_jsonl(self.fail_path)
        for record in records:
            if record.get("template") == region.template:
                record["hit_count"] = record.get("hit_count", 0) + max(region.hit_count, 1)
                merged_corr = list(set(record.get("correlated_with", []) + list(region.correlated_with)))
                record["correlated_with"] = merged_corr[:10]
                self._rewrite_jsonl(self.fail_path, records)
                return
        self._append_jsonl(self.fail_path, asdict(region))
        if len(records) + 1 > self.FORBIDDEN_CAPACITY:
            self._compact_forbidden()

    def top_forbidden_regions(self, k: int = 5, tags: list[str] | None = None) -> list[dict[str, Any]]:
        records = self._read_jsonl(self.fail_path)
        if tags:
            tag_set = set(tags)
            records = [r for r in records if tag_set.intersection(set(r.get("tags") or []))]
        records.sort(key=lambda r: r.get("hit_count", 0), reverse=True)
        return records[:k]

    def _compact_forbidden(self) -> None:
        records = self._read_jsonl(self.fail_path)
        # 保留 hit_count >= 2 的禁区,稀疏的丢弃
        cleaned = [r for r in records if r.get("hit_count", 0) >= 2]
        self._rewrite_jsonl(self.fail_path, cleaned)

    # ──────────────────────────────────────────────────────────
    # Strategic Insights (I)
    # ──────────────────────────────────────────────────────────
    def add_insight(self, insight: StrategicInsight) -> None:
        records = self._read_jsonl(self.insight_path)
        for record in records:
            if record.get("insight") == insight.insight:
                return  # 去重
        self._append_jsonl(self.insight_path, asdict(insight))
        if len(records) + 1 > self.INSIGHT_CAPACITY:
            self._compact_insights()

    def top_insights(self, k: int = 5, severity_min: str = "info") -> list[dict[str, Any]]:
        order = {"info": 0, "warning": 1, "critical": 2}
        threshold = order.get(severity_min, 0)
        records = [r for r in self._read_jsonl(self.insight_path) if order.get(r.get("severity", "info"), 0) >= threshold]
        records.sort(key=lambda r: order.get(r.get("severity", "info"), 0), reverse=True)
        return records[:k]

    def _compact_insights(self) -> None:
        records = self._read_jsonl(self.insight_path)
        records = records[-self.INSIGHT_CAPACITY :]
        self._rewrite_jsonl(self.insight_path, records)

    # ──────────────────────────────────────────────────────────
    # Mining State (S)
    # ──────────────────────────────────────────────────────────
    def get_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            return {"library_size": 0, "recent_admits": []}
        return json.loads(self.state_path.read_text(encoding="utf-8"))

    # ──────────────────────────────────────────────────────────
    # 检索:为 LLM prompt 构造一份"记忆快照"
    # ──────────────────────────────────────────────────────────
    def retrieve_for_prompt(
        self,
        tags: list[str] | None = None,
        succ_k: int = 5,
        fail_k: int = 5,
        insight_k: int = 3,
    ) -> dict[str, Any]:
        """检索本轮挖掘需要注入到 prompt 的记忆快照。"""
        return {
            "mining_state": self.get_state(),
            "successful_patterns": self.top_successful_patterns(k=succ_k, tags=tags),
            "forbidden_regions": self.top_forbidden_regions(k=fail_k, tags=tags),
            "strategic_insights": self.top_insights(k=insight_k),
            "library_top": self.list_alphas(limit=10, min_sharpe=1.0),
        }
