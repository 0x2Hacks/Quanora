# 🧬 WorldQuant Brain 自动挖因子使用指南

> ChainPeer Agent 集成的"自我进化挖因子"能力,融合了:
> - **FactorMiner**(论文 2602.14670v1):Ralph Loop + Skills/Experience Memory
> - **QuantaAlpha**(arXiv 2602.07085):Planning → Hypothesis → Code → Backtest → Evolution
> - **WorldQuant Brain** 平台:`api.worldquantbrain.com` 的真实回测后端

---

## 1. 整体设计

### 1.1 Ralph Loop 工作流

每一轮挖掘都按论文的 **Retrieve → Generate → Evaluate → Distill** 四阶段闭环:

```
┌──────────────────────────────────────────────────────────┐
│  Round t (按 plan_create 的 step 推进)                   │
├──────────────────────────────────────────────────────────┤
│  ① Retrieve  wq_memory_snapshot                         │
│       → P_succ (推荐模板) + P_fail (红海禁区)           │
│         + I (策略洞察) + 因子库 Top-10                  │
│                                                          │
│  ② Generate  wq_build_generation_prompt + LLM 推理      │
│       → 一批新的 FASTEXPR alpha 候选                    │
│                                                          │
│  ③ Evaluate  wq_evaluate_alpha (循环调用,每条一次)     │
│       Stage 1: 本地语法/复杂度门控                       │
│       Stage 2: Brain 真实模拟 (api.worldquantbrain.com)  │
│       Stage 3: Brain checks (SELF_CORR/LOW_SHARPE/...)   │
│       Stage 4: 本地模板去重 (normalize_template)         │
│       → 通过则 admit 入库 + 写 P_succ;失败则写 P_fail   │
│                                                          │
│  ④ Distill   wq_distill_insight                         │
│       → 把本轮教训沉淀到 I 区,影响下一轮 prompt         │
└──────────────────────────────────────────────────────────┘
                       ▼
              是否达到目标库规模? → 否,转下一轮
                       ▼ 是
                  wq_submit_alpha (按每日配额提交)
```

### 1.2 三类工具的角色

| 角色 | 工具 |
|---|---|
| **底层 Brain 通讯** | `wq_login` / `wq_simulate_alpha` / `wq_list_my_alphas` / `wq_submit_alpha` |
| **Skills(模块化技能)** | `wq_list_operators` / `wq_list_data_fields` / `wq_evaluate_alpha`(多阶段) / `wq_mutate_alpha` / `wq_crossover_alpha` |
| **Experience Memory** | `wq_memory_snapshot` / `wq_distill_insight` / `wq_list_library` / `wq_list_directions` / `wq_build_generation_prompt` |

### 1.3 存储布局

```
项目根/
├── wq_memory/                       # Experience Memory(默认目录)
│   ├── alpha_library.jsonl          # 因子库(全局视角)
│   ├── successful_patterns.jsonl    # P_succ:成功模板 + 平均 sharpe
│   ├── forbidden_regions.jsonl      # P_fail:红海禁区(高自相关被拒)
│   ├── strategic_insights.jsonl     # I:策略级教训
│   └── mining_state.json            # S:库规模、近期准入日志
├── credential.txt                   # (可选)Brain 凭证 ["email","password"]
└── ...
```

> 路径可通过环境变量 `WQ_MEMORY_ROOT` 改写。每个文件都是 append-only JSONL,完全对齐 ChainPeer 整体的事件溯源风格,支持任意时刻 `Ctrl+C` + 续跑。

---

## 2. 安装与配置

### 2.1 安装依赖

```bash
cd /home/user/webapp
pip install -r requirements.txt
# requests / urllib3 已经在原项目依赖里;不需要额外包
```

### 2.2 配置 Brain 凭证(三选一)

**方式 A:环境变量(推荐)**
```bash
export WQ_BRAIN_EMAIL="your_email@example.com"
export WQ_BRAIN_PASSWORD="your_password"
export WQ_MEMORY_ROOT="./wq_memory"   # 可选
```

**方式 B:`.env` 文件**
```env
# 在 .env 中追加
WQ_BRAIN_EMAIL=your_email@example.com
WQ_BRAIN_PASSWORD=your_password
WQ_MEMORY_ROOT=./wq_memory
```

**方式 C:`credential.txt`(兼容 worldquant-miner 格式)**
```json
["your_email@example.com", "your_password"]
```

### 2.3 启动 Agent

```bash
# 全新会话
python main.py

# 续跑上次中断的会话(关键!挖因子是长任务)
python main.py -c

# Debug 模式(可看到 token 估算、每次 tool 调用细节)
python main.py --debug
```

---

## 3. 实战示例

### 3.1 单条手工验证(熟悉 API)

进入 ChainPeer CLI 后,直接对它说:

```
请帮我用 wq_login 登录 Brain,然后用 wq_evaluate_alpha 评估
表达式 "rank(ts_delta(close, 5))",direction_tag 设为
"reversal_short_term"。把结果用表格展示。
```

Agent 会:
1. 调用 `wq_login`
2. 调用 `wq_evaluate_alpha(expression="rank(ts_delta(close, 5))", direction_tag="reversal_short_term")`
3. 解析返回的 `metrics` 给你看 sharpe / fitness / turnover / drawdown
4. 如通过,自动 `admit_to_library=True` 写入 `wq_memory/alpha_library.jsonl`

### 3.2 一键 Ralph Loop(标准用法)

```
请帮我执行一次完整的 WorldQuant 自动挖因子流程,
目标:在 USA / TOP3000 / Delay 1 上,挖出 5 个 sharpe ≥ 1.5 的因子,
研究方向选 "volume_price_divergence" 和 "high_order_moments"。

要求:
1. 用 plan_create 先把流程写成 DAG。
2. 每一轮先 wq_memory_snapshot,把禁区注入到你后续的思考里。
3. 用 wq_build_generation_prompt 拿到 prompt 后,
   直接在你的思考中输出 6 个 FASTEXPR 表达式。
4. 对每个表达式调 wq_evaluate_alpha,记录通过/失败。
5. 失败原因如果是 SELF_CORR,记录这个模板已自动写入禁区。
6. 用 wq_mutate_alpha 把表现最好的因子做 4 个变体,
   再各跑一遍评估。
7. 最后调 wq_distill_insight 写一句教训,然后 plan_close。
8. 用 wq_list_library 输出最终因子库列表。
```

Agent 会逐步推进,你可以中途 `Ctrl+C`,下次 `python main.py -c` 继续。

### 3.3 仅生成不提交(常用安全模式)

```
帮我挖 10 个 momentum 方向的因子,但**不要**调用 wq_submit_alpha,
我会人工审核因子库后再决定提交哪些。
```

### 3.4 进化已有因子

```
读 wq_memory/alpha_library.jsonl 里 sharpe 最高的前 3 个因子,
对每个用 wq_mutate_alpha 做参数扰动(窗口候选 [5,10,20,30,60,120]),
再两两 wq_crossover_alpha (策略 rank_pair),所有变体跑 wq_evaluate_alpha,
通过的写入库。
```

### 3.5 比赛投递(注意每日配额)

```
列出 wq_list_my_alphas 状态为 UNSUBMITTED 且 sharpe > 1.5 的 alpha,
按 sharpe 降序排,挑第 1 个 wq_submit_alpha 提交。
注意 Pre-Consultant 每日上限 1 条,所以**只提交 1 个**。
```

---

## 4. 工具完整目录

| 工具 | 调用频率 | 说明 |
|---|---|---|
| `wq_login` | 每次会话开始 1 次 | HTTP Basic 认证,设置 session cookie |
| `wq_list_directions` | 启动时 | 6 个内置研究方向(reversal / momentum / volatility / volume_price / high_order / microstructure) |
| `wq_list_operators` | 启动时 | 30+ 内置常用算子(use_cache=True 零网络) |
| `wq_list_data_fields` | 启动时 | 12 个内置常用字段;use_cache=False 在线查询完整池 |
| `wq_memory_snapshot` | **每轮 1 次** | 在生成因子前必须调用 |
| `wq_build_generation_prompt` | **每轮 1 次** | 拿到 prompt 后 LLM 自己写表达式数组 |
| `wq_evaluate_alpha` | 每个候选 1 次 | 4 阶段评估管线,通过自动入库 |
| `wq_simulate_alpha` | 单条调试用 | 不写本地库,只跑模拟 |
| `wq_mutate_alpha` | 进化阶段 | 参数扰动 |
| `wq_crossover_alpha` | 进化阶段 | 两两交叉 |
| `wq_distill_insight` | 每轮结束 | 沉淀教训 |
| `wq_list_library` | 阶段汇总 | 看本地因子库 |
| `wq_list_my_alphas` | 阶段汇总 | 查 Brain 账户上的 alpha |
| `wq_submit_alpha` | 提交时 | 注意每日配额 |

---

## 5. 关键设计决策(对应论文)

| 论文/项目概念 | ChainPeer 中的实现 |
|---|---|
| FactorMiner: **Skills Memory** | 一组 `wq_*` 工具函数,模块化技能,LLM 通过 tool_call 调用而非自己计算(避免幻觉) |
| FactorMiner: **Experience Memory** = (S, P, I) | `ExperienceMemory` 类,4 个 JSONL + 1 个 state.json |
| FactorMiner: **Ralph Loop** | `wq_memory_snapshot` → `wq_build_generation_prompt` → LLM → `wq_evaluate_alpha` → `wq_distill_insight` |
| FactorMiner: **Forbidden Regions** | `forbidden_regions.jsonl`,模板规范化用 `normalize_template`(把数字常量统一替换为 N) |
| FactorMiner: **多阶段验证** | `evaluator.py` 中 stage1_local / stage2_simulate / stage3_brain_checks / stage4_template_dedup |
| QuantaAlpha: **Diversified Planning** | `DIRECTION_LIBRARY` 6 个内置方向 + LLM 通过 `plan_create` 自由组合 |
| QuantaAlpha: **Mutation/Crossover** | `wq_mutate_alpha` / `wq_crossover_alpha`(4 种策略) |
| QuantaAlpha: **Quality Gate** | 阈值参数化:`min_sharpe` / `min_fitness` / `max_turnover` |
| ChainPeer: **DAG plan** | 复用 `plan_create` 等工具,挖因子流程被组织成 DAG |
| ChainPeer: **Event Sourcing** | `ExperienceMemory` 的 JSONL append-only 完全对齐整体风格 |

---

## 6. 故障排查

### 6.1 `WQAuthError`
- 检查 `WQ_BRAIN_EMAIL` / `WQ_BRAIN_PASSWORD` 是否正确
- Brain 平台账户是否激活了 API 访问权限(Pre-Consultant 通过 sign-up 即可)

### 6.2 `WQRateLimitError`
- Brain 平台对模拟请求有限速。降低并发,或在每次 `wq_evaluate_alpha` 之间 `time.sleep(2)`
- Pre-Consultant 每次最多 5 个并发模拟

### 6.3 Brain 返回 `SIMULATION_LIMIT_EXCEEDED`
- 当日模拟次数耗尽(Pre-Consultant 通常 100/day),明日继续

### 6.4 因子总是过不了 `SELF_CORR` check
- 这是正常的!说明你已经落入"红海"
- 看 `forbidden_regions.jsonl`,LLM 下一轮会自动避开
- 主动尝试更冷门的方向(`high_order_moments` / `intraday_microstructure`)

### 6.5 想强制重新登录
```python
from agent.infrastructure.tools.impl.tools.worldquant.client import reset_global_client
reset_global_client()
```
或直接重启 agent。

---

## 7. 进阶:扩展研究方向

编辑 `agent/infrastructure/tools/impl/tools/worldquant/knowledge.py` 的 `DIRECTION_LIBRARY`,加入新方向:

```python
DIRECTION_LIBRARY["alt_data_seasonality"] = {
    "name": "另类数据季节性",
    "description": "捕捉日历效应/月末再平衡",
    "key_fields": ["returns", "volume", "cap"],
    "key_operators": ["ts_mean", "ts_zscore", "group_rank"],
    "tags": ["alt_data", "seasonality"],
}
```

下次 `wq_list_directions` 就会包含它。

---

## 8. 与传统 worldquant-miner 项目的差异

| 维度 | worldquant-miner (zhutoutoutousan) | ChainPeer + WQ Skill |
|---|---|---|
| LLM | Ollama 本地 / Kimi API | 任意 OpenAI 兼容(GPT/DeepSeek/Claude/Qwen) |
| 架构 | 多脚本松耦合 (alpha_generator.py / alpha_miner.py 各自跑) | 单一 Agent + 统一 tool_call,DAG plan 调度 |
| 记忆机制 | 无(每次冷启动) | **Experience Memory**:成功/失败模板 + 策略洞察(论文核心创新) |
| 因子去重 | 简单字符串去重 | 模板正则化 (`normalize_template`) + Brain 平台 SELF_CORR + 库内相关性 |
| 进化算子 | 仅参数扰动 | Mutation + 4 种 Crossover 策略 |
| 断点续传 | 无 | 复用 ChainPeer JSONL event sourcing,`-c` 即可恢复 |
| 上下文管理 | 无 | 复用 ChainPeer 的 Hot/Warm/Cold 三温区预算 |

---

## 9. 后续可扩展方向

- [ ] 接 Brain Alphathon 比赛的实时排行榜 API,把"排名"加入 Strategic Insights
- [ ] 引入 `multiprocessing.Pool` 真并发跑 `wq_evaluate_alpha`(目前是串行,受限于 Pre-Consultant 5 并发)
- [ ] 加入"经济学先验"模板库(参考 Alpha101)
- [ ] 接入 Tushare/Qlib 做本地 IS 预筛选,Brain 只做最终验证(降低 API 消耗)
- [ ] WebSocket 实时进度推送到一个简单的 Web UI
