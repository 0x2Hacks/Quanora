---
name: "research_experience"
description: "量化研究经验跨会话持久化：研究前查阅、研究后总结，避免重复探索"
triggers:
  - "研究经验"
  - "研究总结"
  - "策略经验"
  - "经验记录"
  - "研究前查阅"
  - "research experience"
---

# Research Experience Skill

## 目的
让量化策略研究经验跨会话复用。每次研究完成后自动总结经验，每次新研究开始前查阅历史经验，避免重复探索已知死路。

## 工作流程

### 阶段1: 研究前 — 查阅经验
在新研究开始时，**必须**：
1. 调用 `query_research_experience` 查询相关历史经验
   - 至少按 `instrument` 或 `strategy_category` 过滤
   - 重点关注 `outcome=failure` 的记录，避免重复
2. 调用 `get_research_summary` 了解项目整体研究进展
3. 将查询到的经验纳入研究计划，明确哪些方向已有结论

示例：
```
query_research_experience(instrument="XAUUSD", strategy_category="mean_reversion")
```

### 阶段2: 研究中 — 积累经验
在研究过程中发现重要模式时：
- 发现某个参数组合无效 → 准备记录 failure
- 发现某个策略有前景但需优化 → 准备记录 partial
- 获得非策略类洞察（如数据特征、市场微观结构）→ 准备记录 insight

### 阶段3: 研究后 — 总结经验
**每个显著的研究结果都必须记录**，无论成功或失败。使用 `record_research_experience`：

```
record_research_experience(
    strategy_name="dual_ma_crossover",
    strategy_category="trend_following",
    instrument="XAUUSD",
    timeframe="M5",
    outcome="failure",
    key_insight="双均线交叉在XAUUSD M5上频繁假突破，止损成本超过收益",
    what_worked="长期窗口(200/50)趋势方向判断有一定准确率",
    what_failed="短期交叉信号在震荡市反复触发，胜率仅35%",
    pitfalls='["M5级别滑点影响显著","XAUUSD在亚盘时段波动不足"]',
    performance='{"sharpe":-0.3,"win_rate":0.35,"max_drawdown":0.18}',
    tags='["xauusd","trend_following","dual_ma"]',
    next_steps='["尝试加入ADX过滤器","转向更高时间框架H1"]'
)
```

### 强制规则

1. **失败也要记录**：失败的策略经验比成功的更有价值，防止未来重复踩坑
2. **核心洞察必填**：`key_insight` 是最重要的字段，必须一句话说清楚最重要的发现
3. **量化指标优先**：`performance` 字段尽量填入数值指标（Sharpe、胜率等），不要只写文字描述
4. **标签规范**：tags 至少包含标的和策略分类，方便后续过滤
5. **不要重复记录**：如果已有相同策略的记录，更新而非新建（先query检查）

## 经验质量标准

一条好的研究经验应包含：
- ✅ 清晰的策略名称和分类
- ✅ 明确的研究结果（success/partial/failure/insight）
- ✅ 一句话核心洞察
- ✅ 量化性能指标（如有）
- ✅ 失败原因的具体描述（对failure记录尤其重要）
- ✅ 可操作的后续步骤建议

一条差的经验：
- ❌ "策略不行" — 太模糊
- ❌ 只有结论没有原因 — 无法指导后续决策
- ❌ 缺少标的/时间框架信息 — 无法判断适用范围
