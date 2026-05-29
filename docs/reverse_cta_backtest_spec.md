# Binance 合约 Reverse CTA（动量衰竭反转做空）回测规范文档

> 本文档供 Agent 框架参考，定义 **Binance USDT 永续合约多标的、统一规则的 Reverse CTA 回测**标准流程、输出指标、图表要求、参数优化方法与常见隐患。
> 
> 本项目不是资金费率套利，也不是横截面选股/多因子排名；其核心问题是：
> **当某个合约在短时间内出现“强势拉升 + 过热 + 成交量放大 + 动量衰竭”组合时，做空反转是否具有稳定、可重复、扣成本后仍为正的交易 edge。**
> 
> 当前策略实现是 **单标的独立生成信号、统一参数批量跑全市场、最终聚合全部交易与净值** 的 CTA 框架；策略方向为 **只做空，不做多**。回测脚本来自 `binance_momentum_reversal_backtest.py`，离线多核参数优化来自 `optimize_parameters_offline.py`。[Source](https://www.genspark.ai/api/files/s/ePtbW1Um) [Source](https://www.genspark.ai/api/files/s/zZOaH3Yi)

---

## 〇、项目边界与数据获取（Agent 必须先完成）

> **⚠ 本项目数据源分为两种且必须口径一致：**
> 1. **在线回测**：Binance USDT-M Futures 官方 REST API；
> 2. **离线优化**：由同一 Binance 数据预先缓存得到的本地 CSV。
>
> 不允许把 yfinance、TradingView 导出、第三方 K 线网站、Kaggle 数据与 Binance 官方期货 K 线混用。
> 若离线 CSV 不是由 Binance 期货原始数据生成，必须在报告首页显式声明“数据口径不一致，结果仅供参考”。

### 0.1 研究对象定义

本项目研究对象为：

1. **交易所范围**：Binance USDT 计价永续合约；
2. **标的集合**：`exchangeInfo` 中 `contractType=PERPETUAL`、`quoteAsset=USDT`、`status=TRADING` 的全部交易对，或配置中人为截断后的子集；
3. **方向**：仅做空；
4. **频率**：默认 `5m`；
5. **回测方式**：逐标的运行同一策略规则，再将全部已平仓交易聚合为总交易表与总净值曲线。[Source](https://www.genspark.ai/api/files/s/ePtbW1Um)

### 0.2 数据源与运行模式

| 模式 | 数据来源 | 用途 | 必须满足 |
|------|---------|------|---------|
| 在线回测 | Binance Futures REST API | 获取交易对列表、下载 K 线、跑单次或批量回测 | 全部时间戳统一 UTC；缓存文件与在线数据同口径 |
| 离线优化 | `data_directory` 下本地 CSV | 多进程网格搜索、稳健性检验 | 文件命名必须为 `<symbol>_<interval>.csv` |
| 聚合输出 | 回测脚本本地产物 | 交易明细、净值、图表、最差交易样本 | 输出目录与文件命名固定且可追溯 |

### 0.3 默认配置概览（来自当前脚本）

| 属性 | 默认值 |
|------|------|
| 回测开始日期 | `2025-01-01` |
| 回测结束日期 | `None`（运行时当前 UTC） |
| K 线周期 | `5m` |
| 初始资金 | `100000` |
| 单笔仓位占比 | `0.1` |
| 手续费 | `0.0004` |
| 滑点 | `0.0002` |
| 固定止损 | `25%` |
| 固定止盈 | `15%` |
| 超时退出 | 4h/8h/12h 三档最低收益阈值 |
| 缓存目录 | `data_cache/` |
| 输出目录 | `backtest_outputs/` |

> **⚠ 重要口径提醒：** 虽然策略参数里存在 `stop_loss_atr` / `take_profit_atr`，但当前交易执行脚本实际使用的是 `BACKTEST_PARAMS` 中的固定百分比止损止盈（25% / 15%），不是 ATR 止损止盈。若报告把当前实现写成“ATR 出场”，属于口径错误。[Source](https://www.genspark.ai/api/files/s/ePtbW1Um)

### 0.4 在线数据结构与离线 CSV Schema

| 字段 | 类型 | 说明 |
|------|------|------|
| `open_time` | datetime / timestamp | bar 开始时间 |
| `open` | float | 开盘价 |
| `high` | float | 最高价 |
| `low` | float | 最低价 |
| `close` | float | 收盘价 |
| `volume` | float | 成交量 |
| `close_time` | datetime / timestamp | bar 结束时间（若本地无则可按周期推导） |

**离线优化脚本要求的最小列集：**

```text
open_time, open, high, low, close, volume
```

若存在 `close_time` 更佳；若不存在，优化脚本会按周期推导。文件名需遵循：

```text
BTCUSDT_5m.csv
ETHUSDT_5m.csv
...
```

[Source](https://www.genspark.ai/api/files/s/zZOaH3Yi)

### 0.5 缓存与截止时间机制

当前在线抓取实现包含三层防错逻辑：

1. **本地缓存**：同一交易对与周期缓存为 `data_cache/<symbol>_<interval>.csv`；
2. **增量下载**：优先复用已有缓存，只补缺失区间；
3. **不完整 bar 剔除**：按运行时统一截止时间剔除尚未收完的 K 线，避免不同交易对使用到不同“最后一根半成品 bar”。[Source](https://www.genspark.ai/api/files/s/ePtbW1Um)

### 0.6 数据完整性检查清单

| 检查项 | 通过标准 |
|--------|---------|
| 时间范围 | `start_date <= open_time <= end_date` |
| 时区统一 | 全部时间戳按 UTC 解释 |
| 无重复 K 线 | `open_time` 唯一 |
| OHLC 合法 | `low <= open, close <= high` |
| 量价完整 | `open/high/low/close/volume` 无关键缺失 |
| 周期一致 | 文件名中的 interval 与数据实际 bar 间隔一致 |
| 缓存完整性 | 最新 bar 不晚于统一 run cutoff |
| 样本长度 | 单标的数据点数不少于 `min_data_points`（默认 100） |

### 0.7 过滤与可交易性前置要求

| 项目 | 默认值 | 说明 |
|------|------|------|
| `min_volume` | `1,000,000` | 低流动性标的应标记风险或单独剔除 |
| `min_data_points` | `100` | 数据不足直接跳过 |
| `MAX_SYMBOLS` | `None` | 可用于 smoke test 或限量调试 |

> **建议要求：** 正式报告至少同时给出：
> - 全市场版本；
> - 剔除极低流动性小币版本；
> - 仅主流大市值合约版本。

---

## 一、策略定义（Reverse CTA 核心逻辑）

### 1.1 策略目标

本策略的目标不是追涨，而是捕捉 **短期拉升后的动量衰竭**。当价格在前期快速上涨、RSI 超买、成交量显著放大后，若后续出现“上涨动能减弱 + 高位回落确认”，则视为短线做空候选。脚本中的策略描述明确写为：

1. 左侧筛选：前期价格动量显著、RSI 超买、成交量放大；
2. 动量衰竭：动量开始连续走弱，短期价格仍在上冲；
3. 右侧确认（可选）：出现一定幅度回落、连续阴线或短期跌幅；
4. 高位约束：现价需处于过去 N 天价格高分位区间。[Source](https://www.genspark.ai/api/files/s/ePtbW1Um)

### 1.2 默认策略参数

| 参数 | 默认值 | 含义 |
|------|------|------|
| `momentum_period` | 12 | 动量回溯 bar 数 |
| `momentum_threshold` | 0.035 | 前期累计涨幅阈值 |
| `rsi_period` | 10 | RSI 周期 |
| `rsi_overbought` | 62 | RSI 超买阈值 |
| `volume_spike` | 2.0 | 成交量放大倍数 |
| `atr_period` | 10 | ATR 周期 |
| `stop_loss_atr` | 1.2 | 参数保留；当前执行未直接使用 |
| `take_profit_atr` | 2.0 | 参数保留；当前执行未直接使用 |
| `use_right_side_confirmation` | `True` | 是否启用右侧确认 |
| `confirmation_period` | 1 | 右侧确认窗口 bar 数 |
| `right_side_drop_pct` | 0.003 | 短期下跌幅度阈值 |
| `right_side_pullback_pct` | 0.0045 | 相对近期高点回撤阈值 |
| `right_side_bearish_count` | 1 | 窗口内最少阴线数量 |
| `price_quantile_lookback_days` | 15 | 高位分位回溯天数 |
| `price_quantile_level` | 0.82 | 价格高位分位阈值 |

### 1.3 指标计算定义

| 指标 | 定义 |
|------|------|
| `momentum` | `close.pct_change(momentum_period)` |
| `rsi` | 按滚动均值收益/损失计算 RSI |
| `volume_ma` | 20 根均量 |
| `volume_ratio` | `volume / volume_ma` |
| `atr` | 标准 True Range 滚动均值 |
| `price_change_5` | `close.pct_change(5)` |
| `momentum_declining` | 当前动量 < 前一根动量，且前一根 < 前两根 |
| `recent_high` | `confirmation_period + 1` 窗口最高价 |
| `pullback_pct` | `(close - recent_high) / recent_high` |
| `right_side_return` | `close.pct_change(confirmation_period)` |
| `bearish_count` | 确认窗口内阴线数量 |
| `price_quantile_threshold` | 过去 `price_quantile_lookback_days` 的滚动价格分位阈值 |

### 1.4 入场条件（做空信号）

当前实现的做空信号为：

```text
left_side_condition =
    momentum > momentum_threshold
    and rsi > rsi_overbought
    and volume_ratio > volume_spike
    and momentum_declining == True
    and price_change_5 > 0.02
    and close >= price_quantile_threshold

if use_right_side_confirmation:
    confirmation_condition =
        (right_side_return <= -right_side_drop_pct
         or pullback_pct <= -right_side_pullback_pct)
        and bearish_count >= right_side_bearish_count
else:
    confirmation_condition = True

signal = -1 if left_side_condition and confirmation_condition else 0
```

这意味着策略本质上是：
**先找“过热上涨”，再等“过热后的第一脚确认回落”，最后在高位开空。** [Source](https://www.genspark.ai/api/files/s/ePtbW1Um)

### 1.5 出场规则（当前实现）

| 类型 | 规则 | 当前脚本状态 |
|------|------|-------------|
| 固定止损 | `entry_price * (1 + stop_loss_pct)` | 已实现 |
| 固定止盈 | `entry_price * (1 - take_profit_pct)` | 已实现 |
| 超时退出 1 | 持仓 ≥ 4h 且收益 < 1% | 已实现 |
| 超时退出 2 | 持仓 ≥ 8h 且收益 < 2% | 已实现 |
| 超时退出 3 | 持仓 ≥ 12h 且收益 < 3% | 已实现 |
| 数据结束强平 | 到样本最后一根时平仓 | 已实现 |
| ATR 止损/止盈 | 依据 ATR 倍数动态平仓 | **参数存在，执行未接线** |

### 1.6 仓位与成交假设

| 项目 | 当前实现 |
|------|---------|
| 仓位模式 | 单标的同一时刻仅允许 1 个空头仓位 |
| 单笔名义仓位 | `capital * position_size` |
| 默认仓位比例 | 10% |
| 手续费扣减 | 开仓扣 commission，平仓再扣 commission + slippage |
| 开仓价格 | `close * (1 + slippage)` |
| 持仓数量 | `-(position_value / current_price)` |
| 资金模式 | 不复利到单笔层面；但资本随交易结果变动 |

> **⚠ 重要提醒：** 当前实现是在产生信号的同一根 bar 内，用该 bar 的 `close` 近似执行开仓。这对实盘是偏乐观的。正式报告建议至少附加一版 **next-bar open / next-bar VWAP** 成交复核，确认结论不依赖同 bar 成交假设。[Source](https://www.genspark.ai/api/files/s/ePtbW1Um)

---

## 二、回测目标与收益口径

### 2.1 回测要回答的核心问题

1. 该反转做空逻辑在多标的上是否具有稳定正期望；
2. 收益是否来自少数极端行情，还是多数交易都有效；
3. 扣除手续费与滑点后，净 Sharpe 是否仍为正；
4. 右侧确认是否真的提升胜率，还是只是降低频率；
5. 高位分位过滤是否能避免“过早摸顶”；
6. 样本外、跨标的、跨参数扰动后是否仍稳定。[Source](https://www.genspark.ai/api/files/s/ePtbW1Um) [Source](https://www.genspark.ai/api/files/s/zZOaH3Yi)

### 2.2 单笔收益定义

对于一笔空头交易：

```text
position < 0
pnl_gross = position × (exit_price - entry_price)
pnl_net   = pnl_gross - closing_fees - opening_fees
```

其中：
- 开仓时先扣一次 commission；
- 平仓时再扣 `commission + slippage`；
- 最终以美元记账。

### 2.3 聚合口径

本项目至少输出两层统计：

1. **单标的层**：每个合约各自的交易数、PnL、Sharpe、MDD；
2. **全组合层**：把全部已平仓交易按时间合并，生成总交易表、总净值曲线、总统计指标。

> **注意：** 当前脚本的综合表现是基于“全部交易聚合后的账户曲线”，不是简单对每个标的 Sharpe 求均值。优化脚本也复用这一组合层统计作为目标函数。[Source](https://www.genspark.ai/api/files/s/ePtbW1Um) [Source](https://www.genspark.ai/api/files/s/zZOaH3Yi)

### 2.4 不属于本项目的内容

以下内容不属于本规范核心：

- 资金费率套利；
- 现货对冲；
- 盘口级高频做市；
- 主观择时宏观判断；
- 多空配对统计套利；
- 横截面打分后只选 Top N 的排名系统。

---

## 三、核心输出指标

### 3.1 交易统计类

| 指标 | 定义 |
|------|------|
| `total_trades` | 总平仓交易数 |
| `winning_trades` / `losing_trades` | 盈利/亏损交易数 |
| `win_rate` | 胜率 |
| `avg_win` / `avg_loss` | 平均盈利 / 平均亏损 |
| `profit_factor` | 盈亏比 |
| `holding_minutes` | 单笔持仓时长（分钟） |
| `exit_reason` 分布 | `stop_loss / take_profit / timeout_4h / timeout_8h / timeout_12h / end_of_data` |

### 3.2 净值与风险类

| 指标 | 定义 |
|------|------|
| `total_pnl` | 总盈利 |
| `total_return_pct` | 总收益率 |
| `annualized_return_pct` | 区间年化收益 |
| `annualized_return_periodic_pct` | 按逐期均值推导的年化收益 |
| `annualized_volatility_pct` | 年化波动率 |
| `sharpe_ratio` | 夏普比率 |
| `max_drawdown_pct` | 最大回撤 |
| `no_new_high_ratio` | 净值长期未创新高占比 |
| `avg_drawdown_duration_hours` | 平均回撤持续时间 |
| `final_equity` | 期末权益 |

### 3.3 信号质量类（必须补充）

当前脚本已经内置了部分调试信息，正式报告必须显式输出：

| 指标 | 说明 |
|------|------|
| `signal_counts` | 每个标的生成了多少做空信号 |
| `first_signal_time` / `last_signal_time` | 首尾信号时间 |
| `sample_signals` | 代表性信号样本 |
| 信号转交易率 | 有信号后实际成交比例 |
| 触发密度 | 每日/每周信号次数 |
| 标的覆盖率 | 多少交易对真正产生了交易 |

### 3.4 组合覆盖类

| 指标 | 含义 |
|------|------|
| `symbols_evaluated` | 实际评估的交易对数量 |
| `symbols_with_trades` | 产生有效成交的交易对数量 |
| `symbols_covered` | 优化结果中有交易记录的交易对数量 |
| 小币依赖度 | 收益是否主要来自少数低流动性标的 |

---

## 四、参数优化与稳健性检验（必须做）

### 4.1 优化脚本定位

`optimize_parameters_offline.py` 是 **离线、多进程、批量网格搜索** 工具，不发起网络请求，只读取本地缓存数据。它复用主回测脚本的策略、交易聚合与综合统计逻辑，并可在 Linux 环境下利用最多 30 个 CPU 进程并行评估参数组合。[Source](https://www.genspark.ai/api/files/s/zZOaH3Yi)

### 4.2 输入要求

| 项目 | 要求 |
|------|------|
| 数据目录 | `OFFLINE_OPTIMIZATION_SETTINGS['data_directory']` |
| 交易对 | `symbols` 列表或 `ALL` |
| 周期 | `interval`，需与文件名一致 |
| 时间范围 | `start_date/end_date` 或 `lookback_days` |
| 参数空间 | `param_space` |
| 并发进程 | `max_workers` |
| 批次大小 | `batch_size` |

### 4.3 可优化参数（当前默认网格）

| 参数 | 默认候选范围特征 |
|------|----------------|
| `momentum_period` | 12 ~ 30 |
| `momentum_threshold` | 0.035 ~ 0.065 |
| `rsi_period` | 10 ~ 20 |
| `rsi_overbought` | 62 ~ 80 |
| `volume_spike` | 1.4 ~ 2.4 |
| `atr_period` | 10 ~ 20 |
| `stop_loss_atr` | 1.2 ~ 3.0 |
| `take_profit_atr` | 2.0 ~ 3.8 |
| `use_right_side_confirmation` | True / False |
| `confirmation_period` | 1 ~ 10 |
| `right_side_drop_pct` | 0.0030 ~ 0.0075 |
| `right_side_pullback_pct` | 0.0045 ~ 0.0090 |
| `right_side_bearish_count` | 1 ~ 10 |
| `price_quantile_lookback_days` | 15 ~ 45 |
| `price_quantile_level` | 0.82 ~ 0.98 |

> **⚠ 重要提醒：** `stop_loss_atr` / `take_profit_atr` 当前未参与实际出场执行，因此把它们纳入优化会产生“参数被优化但未实际生效”的假象。正式优化时应二选一：
> 1. 要么补齐 ATR 出场执行逻辑；
> 2. 要么把这两个参数移出优化空间。

### 4.4 目标函数建议

当前默认目标函数为 `avg_return_pct`，但正式研究至少应同时排序以下指标：

| 指标 | 用途 |
|------|------|
| `avg_annualized_return_pct` | 看收益规模 |
| `avg_sharpe_ratio` | 看风险调整后收益 |
| `avg_max_drawdown_pct` | 看回撤约束 |
| `profit_factor` | 看交易质量 |
| `win_rate` | 看稳定性 |
| `avg_no_new_high_ratio` | 看资金占用效率 |
| `symbols_covered` | 防止参数只在极少数标的有效 |

### 4.5 输出文件要求

离线优化至少输出：

| 文件 | 说明 |
|------|------|
| `optimization_metrics_offline.csv` | 实时追加的指标表 |
| `optimization_results.json` | 全量优化结果 JSON |
| `heatmap_<metric>.png` | 指定指标热力图 |
| baseline 行 | 默认参数基准表现 |

### 4.6 稳健性标准

| 检验 | 通过标准 |
|------|---------|
| 基准 vs 最优 | 最优结果不能只比基准略高但覆盖更差 |
| 参数高原 | 热力图应呈高原而非孤立尖峰 |
| 跨标的稳定性 | `symbols_covered` 不能过低 |
| 批量重跑一致性 | 断点续跑后结果一致 |
| 样本外复核 | 需在冻结区间复跑最优参数 |
| 成交密度 | 不得靠极少数交易支撑全部业绩 |

---

## 五、图表要求

### 5.1 必须输出的图表

1. **价格 + 信号标注图**
   - 显示代表性标的的 K 线；
   - 标出做空信号与入场点；
   - 至少展示 3 个成功案例与 3 个失败案例。

2. **累计净值曲线**
   - 展示组合权益曲线；
   - 标注总收益、夏普、最大回撤。

3. **回撤水下图**
   - 展示 `equity / peak_equity - 1`；
   - 用于识别最长回撤阶段。

4. **退出原因分布图**
   - `stop_loss / take_profit / timeout / end_of_data`；
   - 验证策略盈利是否主要依赖某一种退出机制。

5. **单笔 PnL 分布图**
   - 直方图 + 箱线图；
   - 检查是否由极端交易主导。

6. **最差交易样本图**
   - 当前脚本已支持导出 worst trades K 线图；
   - 正式报告必须附上 Top N 最差交易复盘截图。

7. **参数热力图**
   - 至少对目标函数与回撤各输出一张；
   - 默认轴建议 `momentum_period × momentum_threshold`。

### 5.2 推荐但非必需

| 图表 | 用途 |
|------|------|
| 标的收益贡献排行 | 看是否过度依赖少数币种 |
| 持仓时长分布 | 看超时规则是否合理 |
| 信号频率时间序列 | 看市场结构变化 |
| 右侧确认开/关对照图 | 衡量确认机制价值 |
| 高位分位阈值敏感性图 | 检查摸顶过早问题 |
| 滚动 Sharpe | 检查策略衰退 |

---

## 六、常见隐患与陷阱（Reverse CTA 专属）

### 6.1 同 bar 信号成交导致乐观偏差

当前实现是在生成信号的同一根 bar 用 `close` 近似开仓。若信号特征使用了该 bar 的 `close/high/low`，则存在现实上难以完全成交于该收盘附近的偏乐观问题。正式研究必须追加 next-bar 版本做鲁棒性复核。

### 6.2 ATR 参数与实际出场逻辑脱节

脚本计算了 ATR，也在参数区暴露了 `stop_loss_atr` / `take_profit_atr`，但交易执行实际采用固定百分比止损止盈。若不修正，这会造成“优化了不存在的自由度”。

### 6.3 小币流动性幻觉

全市场批量回测容易被低流动性永续合约扭曲：
- K 线涨跌剧烈但真实可成交性差；
- `volume` 高不等于盘口足够厚；
- 固定滑点假设对小币过于乐观。

### 6.4 只做空的市场偏置

USDT 永续长期存在大量上行趋势币。反转做空在熊市可能漂亮，在单边牛市可能持续受伤。必须按市场 regime 分层报告，不能只给全样本 Sharpe。

### 6.5 超时规则伪稳定

4h/8h/12h 的收益门槛实际上构成了“时间止损”。若大多数交易都被 timeout 退出，说明信号可能没有真正形成快速反转，只是被风控硬切。必须报告各退出原因占比。

### 6.6 收益被极少数暴跌行情主导

反转空头策略常见问题是：
- 大部分时间小亏或震荡；
- 少数大跌一次赚很多。

因此必须报告：
- 去掉前 1% 最佳交易后的 Sharpe；
- 去掉前 5 笔最佳交易后的总收益；
- 收益偏度与最大单笔盈利占比。

### 6.7 参数空间过大导致组合爆炸

默认网格中很多参数均为 10 档，若全量笛卡尔积展开，组合数会非常大。必须先做：
1. 小范围粗搜；
2. 锁定敏感参数；
3. 再做局部细搜。

### 6.8 仅用总收益排序导致风险失真

若只看 `avg_return_pct`，容易选出回撤极大、交易数极少、覆盖标的极低的“伪最优参数”。必须联合 Sharpe、MDD、symbols_covered 一起看。

---

## 七、标准回测流程

### 7.1 流程图

```text
获取 Binance 永续交易对列表
    ↓
按 UTC 统一时间范围拉取 / 读取 K 线
    ↓
清洗缓存、剔除未完成 bar、检查数据完整性
    ↓
计算技术指标（momentum / RSI / volume / ATR / quantile）
    ↓
生成做空信号（左侧过热 + 右侧确认 + 高位过滤）
    ↓
执行回测（开仓、止盈止损、超时退出、样本结束强平）
    ↓
汇总单标结果与组合层交易明细
    ↓
输出 summary / trades / equity / worst trades
    ↓
离线网格优化 + 热力图 + 样本外复核
    ↓
给出“可用 / 条件可用 / 不可用”结论
```

### 7.2 最低可复现实验

建议先做一个 smoke test：

1. `MAX_SYMBOLS = 20`；
2. 时间范围先取 30~90 天；
3. 周期固定 `5m`；
4. 先验证主脚本能正常导出 `summary/trades/equity`；
5. 再导出最差交易图；
6. 最后才进行离线多核优化。

---

## 八、报告模板（最终交付建议遵循）

```text
1. 策略概述
   - 策略名称：Reverse CTA / 动量衰竭反转做空
   - 交易对象：Binance USDT 永续合约
   - 核心逻辑：过热上涨后的高位反转做空
   - 策略边界：只做空；不是 funding 套利；不是横截面选币

2. 数据说明
   - 数据源：Binance Futures API / 本地缓存 CSV
   - 时间范围、K线周期、交易对数量
   - 数据清洗与截止时间控制
   - 低流动性过滤规则

3. 策略定义
   - 全部指标定义
   - 入场条件
   - 出场条件
   - 仓位和成本模型
   - 同 bar 成交与 next-bar 成交的口径说明

4. 回测结果
   - 总交易次数、胜率、盈亏比
   - 总收益、年化收益、Sharpe、MDD
   - 退出原因分布
   - 标的覆盖率

5. 稳健性分析
   - 参数热力图
   - 基准参数 vs 最优参数
   - 样本外结果
   - 去极端交易后的表现
   - 小币剔除后的表现

6. 风险与缺陷
   - 同 bar 成交偏乐观
   - ATR 参数未接线
   - 小币流动性问题
   - 牛市单边行情下的持续亏损风险

7. 结论
   - 策略是否有 edge
   - 哪些参数真正关键
   - 哪些市场环境适用/不适用
   - 下一步代码与研究改造建议
```

---

## 九、Agent 执行检查清单

```text
□ 数据源已确认：在线为 Binance Futures API，离线为同口径 CSV
□ 所有时间戳统一按 UTC 处理
□ 未完成 bar 已剔除，缓存增量逻辑正常
□ 低样本与低流动性标的已跳过或标记
□ 策略仅做空这一事实已写明
□ 入场条件与代码一致：动量/RSI/放量/衰竭/高位/右侧确认
□ 出场条件与代码一致：固定止损止盈 + timeout + end_of_data
□ ATR 参数未实际执行这一点已在报告中明确说明
□ 同 bar close 成交的偏乐观风险已提示
□ summary / trades / equity / worst trades 已全部导出
□ 退出原因分布已统计
□ 最差交易图已检查，确认无明显数据错位
□ 离线优化仅使用本地数据，无网络请求
□ param_space 未包含“未生效参数”，或已在报告中解释
□ baseline 与优化最优结果均已保留
□ 热力图已输出，且参数表现呈高原而非单点尖峰
□ 样本外复核已完成
□ 小币剔除版本与全市场版本已对比
□ 最终结论已明确：可用 / 条件可用 / 不可用
```

---

## 十、推荐实现备注（针对当前代码）

### 10.1 建议优先修复的实现问题

1. **把 ATR 参数接入真实出场逻辑**，否则优化空间失真；
2. **补一版 next-bar open 成交回测**，避免同 bar 成交高估；
3. **增加流动性过滤**，至少引入成交额、盘口或最小成交额代理；
4. **增加 regime 分层**，区分牛市、熊市、震荡市；
5. **增加按标的贡献拆解**，防止被单币带飞。

### 10.2 推荐目录结构

```text
Reverse_CTA/
├── binance_momentum_reversal_backtest.py
├── optimize_parameters_offline.py
├── data_cache/
│   ├── BTCUSDT_5m.csv
│   ├── ETHUSDT_5m.csv
│   └── ...
├── backtest_outputs/
│   ├── backtest_summary.json
│   ├── trades.csv
│   ├── equity_curve.csv
│   ├── equity_curve.png
│   ├── worst_trades.csv
│   └── worst_trades/
└── optimization_outputs/
    ├── optimization_metrics_offline.csv
    ├── optimization_results.json
    └── heatmap_*.png
```

---

## 参考来源

- [xauusd_timeseries_signal_backtest_spec.md](https://www.genspark.ai/api/files/s/8eAUfvBa)
- [tokenized_stock_funding.md](https://www.genspark.ai/api/files/s/Kn8bpv0T)
- [binance_momentum_reversal_backtest.py](https://www.genspark.ai/api/files/s/ePtbW1Um)
- [optimize_parameters_offline.py](https://www.genspark.ai/api/files/s/zZOaH3Yi)
