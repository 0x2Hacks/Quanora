# 美股代币化合约/永续资金费率套利回测规范文档

> 本文档供 Agent 框架参考，定义**美股相关代币化标的的资金费率套利回测**标准流程。这里的“套利”不是主观择时，也不是单腿方向性策略，而是回答：
> **当某个美股相关代币化合约/永续存在可持续的 funding 偏移时，采用“现货（或现金等价暴露）+ 反向合约”对冲后，扣除交易成本、点差、滑点、融资/借券与制度约束后，是否存在可实现的净 carry。**
>
> 本文档不是执行报告，而是**研究规范 + 回测方案**。
> 重点不在“信号有没有预测未来涨跌能力”，而在：
> 1. 标的是否真实可交易；
> 2. funding 是否可稳定收取；
> 3. 基差/贴水/溢价风险是否会吞噬 carry；
> 4. 现货腿成本与合约腿成本是否使套利在净值口径下仍成立。
>
> **现货腿价格来源：Futu / moomoo 历史行情**；
> **合约腿价格与历史 funding 来源：Binance / OKX 官方历史数据或官方 API**；
> **交易成本：按 Futu 美股交易费用 + 交易所 taker/maker 费率 + bid/ask 点差 + 滑点 + 资金占用/借券成本合理估算。**

---

# 0. 项目边界与可行性前置判断（Agent 必须先完成）

> **⚠ 本项目第一步不是直接下载数据，而是先做“可交易性核验”。**
> 因为“美股代币化标的”在不同平台上的产品形态并不一致：
> - [Binance](https://www.binance.com/en/support/announcement/detail/3a0304f3ee1c43668959c1b01f610d59) 曾在 2021 年停止 stock tokens 支持，路透也报道了其停止销售并在后续终止支持的事实 [Reuters](https://www.reuters.com/world/china/binance-stops-selling-stock-tokens-after-regulatory-scrutiny-2021-07-16/)。
> - [OKX](https://www.okx.com/en-us/help/tokenized-stocks-faq) 当前公开说明的 tokenized stocks 属于**第三方发行的链上代币化股票/ETF 价格暴露工具**，并不天然等同于“中心化交易所永续合约”；其 FAQ 还明确说明这类资产通常**不代表底层股票所有权，也通常不附带股东权利**，且交易时段由发行方定义 [OKX](https://www.okx.com/en-us/help/tokenized-stocks-faq)。
>
> 因此：
> **若回测期内不存在可持续交易、且能获取历史 funding 的美股相关永续/合约产品，则不得伪造 funding 套利回测。**
> 此时只能输出“不可回测/样本为空”的研究结论，或降级为“代币化股票价格偏离/溢价折价研究”，不能冒充为 funding arbitrage。

## 0.1 研究对象定义

本项目研究对象为以下两类之一：

1. **中心化交易所永续/合约产品**
   - 有明确合约代码；
   - 有历史 funding rate；
   - 有 mark/index/成交或 K 线；
   - 可做多/做空；
   - funding 在固定周期结算。

2. **代币化股票现货 + 可融资/可杠杆腿**
   - 若平台提供的并非永续，而只是 tokenized stock spot，则其本身**不构成 funding arbitrage 样本**；
   - 只能作为“被对冲资产”或“价格映射对象”；
   - 必须另找具有 funding 结算机制的对冲腿。

## 0.2 平台现实约束（必须写入报告首页）

| 平台 | 研究角色 | 必须先核验的事实 | 不可省略的结论 |
|------|----------|------------------|----------------|
| Binance | 合约腿候选 / 历史样本候选 | 回测期内是否存在美股相关 tokenized equity perp / futures；是否有 funding history API 可取 | 若无合约或无 funding 历史，则 Binance 样本记为不可用 |
| OKX | 合约腿候选 / tokenized stock 现货映射候选 | 当前 tokenized stocks 是否只是 provider-issued token；是否存在可配对的 funding 合约 | 若只有 tokenized spot 而无 perp funding，则不能做 funding 套利回测 |
| Futu | 现货腿基准价来源 | 是否可通过 OpenAPI 获取美股分钟/日线历史价格；是否包含盘前盘后 | 若只拿 regular session，要在报告中声明与 24/7/扩展时段腿的错配 |

## 0.3 官方资料（本项目优先级）

| 用途 | 官方来源 |
|------|---------|
| 美股现货历史价格 | [Futu OpenAPI](https://openapi.futunn.com/futu-api-doc/en/) |
| Futu 历史 K 线接口 | [request_history_kline](https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html) |
| Futu 实时/近期 K 线接口 | [get_cur_kline](https://openapi.futunn.com/futu-api-doc/en/quote/get-kl.html) |
| Binance funding 历史 API | [Binance Get Funding Rate History](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) |
| Binance funding 历史网页 | [Binance Futures Funding History](https://www.binance.com/en/futures/funding-history/perpetual/funding-fee-history) |
| OKX funding 机制说明 | [OKX perpetual funding fee mechanism](https://www.okx.com/en-us/help/perps-funding-fee-mechanism) |
| OKX tokenized stocks FAQ | [OKX tokenized stocks FAQ](https://www.okx.com/en-us/help/tokenized-stocks-faq) |
| Binance 停止 stock tokens 说明 | [Binance announcement](https://www.binance.com/en/support/announcement/detail/3a0304f3ee1c43668959c1b01f610d59) / [Reuters](https://www.reuters.com/world/china/binance-stops-selling-stock-tokens-after-regulatory-scrutiny-2021-07-16/) |

## 0.4 回测期建议

> 推荐先做两层时间范围：
>
> - **可交易性核验期**：回测期前后各加 30 天，确认产品是否存在、是否停牌/下架/改规则；
> - **正式回测期**：以 funding 历史可获得区间为准。
>
> Binance 官方 funding history API 允许查询 funding 历史记录；OKX 也提供 funding rate 相关能力与历史市场数据下载页面 [Binance Developers](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) [OKX](https://www.okx.com/en-us/historical-data)。

## 0.5 若产品不存在，必须这样写

```text
结论：截至所选回测区间，未能确认 Binance/OKX 存在“可持续交易 + 可回溯历史 funding + 可与 Futu 美股现货配对”的美股相关永续合约，因此严格意义上的 funding arbitrage 回测不成立。后续仅可转做：
1）tokenized stock 与美股现货的溢价/折价研究；
2）若未来上线相应 perp，再复用本文档框架开展正式 funding 回测。
```

---

# 1. 数据获取（Agent 必须先完成）

## 1.1 现货腿：Futu 历史行情

> **现货腿统一使用 Futu / moomoo 作为“美股基准价格源”。**
>
> Futu OpenAPI 支持美股行情；其中：
> - `request_history_kline(...)` 用于拉取历史 K 线，可指定 `start/end/ktype/max_count/page_req_key`，并支持 `extended_time=True` 获取美股盘前盘后数据 [Futu OpenAPI](https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html)；
> - `get_cur_kline(...)` 用于获取订阅后实时/近期 K 线 [Futu OpenAPI](https://openapi.futunn.com/futu-api-doc/en/quote/get-kl.html)。

**建议字段：**

| 字段 | 说明 |
|------|------|
| `code` | 美股代码，如 `US.AAPL` |
| `time_key` | bar 时间 |
| `open/high/low/close` | OHLC |
| `volume` | 成交量 |
| `turnover` | 成交额 |
| `last_close` | 前收 |
| `change_rate` | 涨跌幅 |

**建议频率：**

| 目的 | 推荐频率 |
|------|---------|
| funding 套利主回测 | 1m / 5m |
| 稳健性复核 | 15m / 1h |
| 长期可行性概览 | 1d |

**关键要求：**

1. 美股若要和加密平台的延长/夜盘或 provider-defined trading session 对齐，必须使用 `extended_time=True` 单独落库；
2. regular-only 与 extended-time 不能混用；
3. 若 Futu 数据只覆盖交易时段，而合约腿 24/7，则非美股交易时段不得伪造现货可交易性；
4. corporate action（拆股、分红、并股）必须保留原始字段并明确复权口径。

## 1.2 合约腿：Binance / OKX 价格与 funding

### 1.2.1 Binance

[Binance funding history API](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) 返回示例字段包括：
- `symbol`
- `fundingRate`
- `fundingTime`
- `markPrice`

因此，若存在目标美股相关 perp，Binance 可作为 funding 历史的官方主源之一 [Binance Developers](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History)。

但必须强调：
- funding history API 的存在 **不代表任意资产类别都存在对应合约**；
- 必须先确认目标 ticker 在回测期内真实上市并可交易；
- Binance 曾停止 stock tokens 支持，这一历史事实必须在可行性章节中写明 [Reuters](https://www.reuters.com/world/china/binance-stops-selling-stock-tokens-after-regulatory-scrutiny-2021-07-16/)。

### 1.2.2 OKX

[OKX perpetual funding fee mechanism](https://www.okx.com/en-us/help/perps-funding-fee-mechanism) 说明：
- 资金费率正时，多头支付给空头；
- 资金费率负时，空头支付给多头；
- 默认每 8 小时结算一次（00:00 / 08:00 / 16:00 UTC），但可根据市场情况调整为 1/2/4 小时等更短间隔；
- fee 以持仓在结算瞬间的头寸价值计算 [OKX](https://www.okx.com/en-us/help/perps-funding-fee-mechanism)。

因此，在 OKX 回测时必须保留：
- funding 结算时间戳；
- 实际结算频率；
- 结算对应 mark/index；
- 合约 multiplier / face value。

### 1.2.3 OKX tokenized stocks 的边界

[OKX tokenized stocks FAQ](https://www.okx.com/en-us/help/tokenized-stocks-faq) 明确说明：
- tokenized stocks 为第三方发行；
- 通常仅提供价格暴露，不代表底层股票所有权；
- 一般不含投票权/分红权（除非 provider 另有说明）；
- 交易时段由 provider 定义，而不是简单等同美股常规盘 [OKX](https://www.okx.com/en-us/help/tokenized-stocks-faq)。

因此：
**OKX tokenized stock 本身不能自动视为 perpetual 合约。**
若没有 funding 字段或 funding 结算机制，该产品只能作为现货类映射资产，而不是 funding 套利腿。

## 1.3 时间统一与时区

| 数据源 | 原始时区 | 统一时区 |
|--------|---------|---------|
| Futu US stock | 需按接口返回时间解释 | 统一转 UTC |
| Binance funding | 毫秒时间戳 | UTC |
| OKX funding | 官方接口时间戳 | UTC |
| Binance/OKX K 线或 mark | 交易所时间戳 | UTC |

**强制要求：**
1. 全部入库后统一为 UTC；
2. 不得在本地时区下计算 funding 窗口；
3. 美股交易日历与 crypto/链上产品交易时段要分离建模。

## 1.4 建议数据表结构

**`spot_futu.parquet`**

| 列名 | 类型 | 说明 |
|------|------|------|
| `timestamp` | datetime64[ns, UTC] | bar 开始时间 |
| `symbol` | string | `US.AAPL` 等 |
| `open/high/low/close` | float64 | 现货 OHLC |
| `volume` | float64 | 成交量 |
| `turnover` | float64 | 成交额 |
| `session_type` | string | regular / extended |
| `autype` | string | qfq / hfq / none |

**`perp_funding.parquet`**

| 列名 | 类型 | 说明 |
|------|------|------|
| `timestamp` | datetime64[ns, UTC] | funding 结算时间 |
| `venue` | string | Binance / OKX |
| `symbol` | string | 合约代码 |
| `funding_rate` | float64 | 本期 funding |
| `mark_price` | float64 | funding 对应 mark |
| `funding_interval_hours` | float64 | 本期结算间隔 |
| `index_price` | float64 | 若可得则保留 |

**`perp_bars.parquet`**

| 列名 | 类型 | 说明 |
|------|------|------|
| `timestamp` | datetime64[ns, UTC] | bar 时间 |
| `venue` | string | Binance / OKX |
| `symbol` | string | 合约代码 |
| `open/high/low/close` | float64 | 合约价格 |
| `mark_price` | float64 | 标记价格 |
| `bid/ask` | float64 | 若可得 |
| `volume` | float64 | 成交量 |

## 1.5 数据完整性检查清单

| 检查项 | 通过标准 |
|--------|---------|
| Futu 时间覆盖 | 覆盖回测期全部美股交易日 |
| Extended 时段标识 | 明确区分 regular / pre / post / overnight |
| Funding 时间戳 | 与官方结算点一致 |
| Funding 间隔 | Binance/OKX 每次结算间隔有记录，变频时不丢失 |
| 合约状态 | 下架/停盘/交易暂停时段可识别 |
| 重复记录 | `timestamp + venue + symbol` 唯一 |
| 缺口处理 | 缺失 funding 不得前填，不得补零 |
| Corporate action | 拆股/分红前后价格口径一致 |
| 币股映射关系 | `AAPL ↔ tokenized AAPL-related contract` 映射有元数据记录 |

---

# 2. 套利定义与回测目标

## 2.1 资金费率套利的标准定义

资金费率套利的最小原子单元是：

- **正 funding 场景**：
  - 做空永续/合约；
  - 做多对应现货或现金等价暴露；
  - 目标：赚 funding，同时承受基差与现货腿成本。

- **负 funding 场景**：
  - 做多永续/合约；
  - 做空现货或使用可替代反向暴露；
  - 目标：赚 funding，同时承受借券/融券/做空约束。

> 在美股场景中，**负 funding 套利通常比正 funding 更难落地**，因为现货腿做空可能涉及借券、融券利息、可借性、强平与 locate 失败等现实约束。因此本规范默认先研究“正 funding：long stock + short perp”的可行性。

## 2.2 回测要回答的核心问题

1. funding 收益在毛收益口径下是否显著为正；
2. 扣除交易成本后净收益是否仍为正；
3. 收益是否主要来自少数极端区间；
4. 基差回归速度是否足够快，还是会长期偏离；
5. 在美股闭市、盘前盘后、周末、财报日、拆股日前后，策略是否失效；
6. 平台规则变化（下架、结算频率变化、标的迁移）是否导致样本断裂。

## 2.3 不属于本项目的内容

以下内容不属于本规范的核心：
- 主观择时买卖股票；
- 多标的横截面排序；
- 高频盘口 alpha；
- 复杂做市策略；
- 期权合成替代；
- 不可验证的“隐含现货腿”。

---

# 3. 回测基本单位与持仓规则

## 3.1 时间粒度

建议至少同时准备三层粒度：

| 粒度 | 用途 |
|------|------|
| Funding-level | 以每次 funding 结算为一个 cashflow 事件 |
| 1m / 5m bars | 计算持仓期间基差变化、建仓/平仓成本 |
| 1d | 输出长期净值、回撤与 regime 统计 |

## 3.2 头寸匹配原则

头寸价值采用名义金额匹配：

```text
spot_notional_t = shares_t × spot_price_t
perp_notional_t = contracts_t × contract_size × multiplier × mark_price_t
hedge_ratio_t = perp_notional_t / spot_notional_t
```

**默认要求：**
- 初始建仓时 `|hedge_ratio - 1| <= 2%`；
- 若合约 multiplier 导致不能精确对齐，剩余敞口必须计入未对冲风险；
- 不得用事后最优 hedge ratio 回填历史。

## 3.3 Funding 归属规则

以 OKX 官方说明为例，持仓在结算点时才会支付/收取 funding，且若在结算前平仓则本次 funding 不发生 [OKX](https://www.okx.com/en-us/help/perps-funding-fee-mechanism)。

因此回测中：

```text
若 t_funding 时刻前一瞬间持有合约空头，则在 funding_rate > 0 时收取：
funding_cashflow_t = + |perp_notional_t| × funding_rate_t

若持有合约多头，则在 funding_rate > 0 时支付：
funding_cashflow_t = - |perp_notional_t| × funding_rate_t
```

并要求：
1. funding 使用结算时刻对应 mark；
2. 若平台实际给出 funding fee 历史而非 funding rate，则优先用 fee 原值；
3. funding 结算周期变化时，不能简单年化后混在一起比较，必须保留原周期信息。

## 3.4 建仓/平仓时点

推荐三种标准化建仓规则，回测必须全都跑：

1. **close-before-funding**：在 funding 前 `X` 分钟建仓，结算后 `Y` 分钟平仓；
2. **rolling-carry**：只要 funding 年化高于阈值则持续持有，并按阈值/风险约束再平衡；
3. **session-filtered carry**：仅在美股 regular session 或 liquidity 较高时段允许换仓。

---

# 4. 信号与入场逻辑

> 本项目的“信号”不是传统 alpha，而是**净 carry 预期**。

## 4.1 原始信号定义

```text
gross_carry_t = expected_funding_t - expected_basis_drift_t
net_carry_t   = gross_carry_t - expected_trading_cost_t - expected_financing_cost_t
```

其中：
- `expected_funding_t`：最近一期已公布 funding 或下一期预估 funding；
- `expected_basis_drift_t`：合约相对现货的溢价/贴水在持有期内的变化预期；
- `expected_trading_cost_t`：双腿进出场交易成本；
- `expected_financing_cost_t`：现金占用、借券、融券、资金利息等。

## 4.2 基差定义

```text
basis_abs_t = perp_mark_t - spot_mid_t
basis_pct_t = perp_mark_t / spot_mid_t - 1
annualized_basis_t = basis_pct_t × 365 × 24 / hours_to_close
```

> 若标的是无到期永续，则不使用传统期现到期年化基差，而改用**持有窗内基差漂移**统计。

## 4.3 入场条件建议

### 4.3.1 方案 A：纯 funding 过滤

```text
if funding_rate_t >= q80_of_history and basis_pct_t not too extreme:
    long spot / short perp
```

### 4.3.2 方案 B：净 carry 过滤

```text
if expected_net_carry_t > 0 and liquidity_ok and basis_zscore_t < z_max:
    open hedge
```

### 4.3.3 方案 C：多重安全阈值

同时满足：
- funding 年化 > 成本缓冲；
- basis 未超过历史 95% 分位；
- 现货与合约的可成交量均达标；
- 不在财报/拆股/重大 corporate action 冻结窗口。

## 4.4 退出条件建议

| 类型 | 规则 |
|------|------|
| Funding 兑现退出 | 收完 1 次或 N 次 funding 即平仓 |
| Carry 失效退出 | 预估净 carry ≤ 0 |
| Basis 风险退出 | `|basis_zscore|` 超过阈值 |
| 流动性退出 | 点差/冲击成本暴涨 |
| 事件退出 | 财报、拆股、停牌、下架、规则变更前强制平仓 |

---

# 5. 交易成本模型（必须显式建模）

> **⚠ 不允许只算 funding、不算成本。**
> 资金费率套利的主要误判通常都来自低估成本。

## 5.1 现货腿成本（Futu）

Futu / moomoo 官方材料显示其美股交易存在佣金、平台费以及监管/第三方收费等项目；公开帮助页中可见典型股票费用口径包括**按股数计费并设置单笔最低收费**的 commission 与 platform fee 结构 [FUTU HK Help Center](https://www.futuhk.com/en/support/topic2_283)。

因此在回测中，现货腿成本必须拆成：

```text
spot_cost = commission + platform_fee + regulatory_fees + spread_cost + slippage_cost + fx_cost
```

建议建模：

| 成本项 | 建议处理方式 |
|--------|-------------|
| commission | 按官方费率表参数化，不写死 |
| platform fee | 按官方费率表参数化 |
| SEC/TAF/交收费 | 设为方向相关的线性/分段费率 |
| spread cost | 以 half-spread 估算一次成交冲击 |
| slippage | 设为 `max(固定bp, participation_rate × intrabar_range)` |
| FX cost | 若账户非 USD，单独估算换汇成本 |

> **合规写法：** 费率必须写成“以实际账户等级/地区费表为准，本回测使用保守估计值”。不要伪称自己掌握用户真实费率。

## 5.2 合约腿成本（Binance / OKX）

```text
perp_cost = trading_fee + bid_ask_cost + slippage_cost + borrow_or_margin_cost + liquidation_buffer_cost
```

其中：
- `trading_fee`：maker/taker 费率；
- `bid_ask_cost`：按 half-spread 或盘口冲击估算；
- `slippage_cost`：与成交量、盘口深度有关；
- `borrow_or_margin_cost`：若使用保证金或融资；
- `liquidation_buffer_cost`：为防止短时爆仓而保留的额外资本占用。

## 5.3 Funding 本身不是“免费 alpha”

即使 funding 为正、空头能收钱，也要同时面对：
1. perp 相对现货可能长期溢价；
2. 结算前瞬间 basis 可能恶化；
3. 美股闭市时无法同步调整现货腿；
4. 极端行情下基差跳变远大于单次 funding。

## 5.4 推荐成本参数层级

回测至少输出三套净值：

| 情景 | 说明 |
|------|------|
| Ideal | 只扣官方 fee，不扣滑点 |
| Base | 官方 fee + 合理 half-spread + 保守滑点 |
| Stress | 宽点差 + 高滑点 + 财报/盘前盘后流动性折价 |

---

# 6. 收益分解与回测口径

## 6.1 单期收益分解

对于 `long spot + short perp`：

```text
pnl_t = funding_pnl_t
      + spot_price_pnl_t
      + perp_price_pnl_t
      - spot_cost_t
      - perp_cost_t
      - financing_cost_t
      - borrow_cost_t
      - fx_cost_t
```

若对冲完美，则价格项应大体互相抵消，剩余主要来自：
- funding 现金流；
- basis 收敛/发散；
- 成本。

## 6.2 推荐收益拆分报表

| 模块 | 指标 |
|------|------|
| Funding 收益 | 总 funding、每期 funding、中位 funding、年化 funding |
| Basis 收益 | 基差收敛收益、基差发散亏损、极端尾部损失 |
| 成本损耗 | 现货成本、合约成本、融资/借券、FX |
| 净结果 | 净收益、净 Sharpe、净 Calmar、净 carry capture |

## 6.3 资金占用口径

至少计算三种收益率：

1. **Gross notional return**：以双腿名义金额为分母；
2. **Capital at risk return**：以初始保证金 + 现货资金占用为分母；
3. **Equity return**：以实际占用自有资金为分母。

> 不同口径下 Sharpe / 年化不可混写，必须并列展示。

---

# 7. 核心输出指标

## 7.1 可行性指标

| 指标 | 含义 |
|------|------|
| Eligible sample ratio | 满足可交易/可配对/有 funding 的时间占比 |
| Session overlap ratio | 现货腿可交易时段与合约腿可调仓时段的重叠比例 |
| Funding coverage ratio | 拿到真实 funding 记录的覆盖率 |
| Product survival ratio | 回测期内未下架/未停用的比例 |

## 7.2 Carry 类指标

| 指标 | 含义 |
|------|------|
| Gross funding APR | 未扣成本 funding 年化 |
| Net carry APR | 扣成本后年化 |
| Funding capture ratio | 实际拿到 funding / 理论 funding |
| Positive-funding hit rate | 正 funding 期间最终净收益为正的比例 |
| Breakeven funding | 覆盖总成本所需最小 funding |

## 7.3 风险类指标

| 指标 | 含义 |
|------|------|
| Basis VaR / ES | 基差尾部风险 |
| Max adverse basis move | 持仓窗内最大不利基差波动 |
| Liquidity stress loss | 宽点差/滑点条件下损失 |
| Session gap loss | 美股闭市期间无法调仓造成的损失 |
| Corporate-action loss | 财报、拆股、停牌事件窗口损失 |

## 7.4 绩效类指标

| 指标 | 含义 |
|------|------|
| 年化收益 | Annualized return |
| Sharpe / Sortino / Calmar | 风险调整收益 |
| 最大回撤 | MDD |
| 收益偏度 / 峰度 | 尾部特征 |
| 周转率 | Turnover |
| 持仓周期分布 | Holding period |
| 单笔盈亏分布 | Trade PnL distribution |

---

# 8. 分层分析（必须做）

## 8.1 按时段分层

至少分为：
- 美股 regular session；
- 盘前盘后；
- overnight / 非股票主盘时段；
- 周末（若代币/合约可交易而现货不可交易，则单独统计）。

OKX tokenized stocks FAQ 已明确其 trading session 由 provider 定义，并非简单等同美股常规盘，因此时段错配分析是必做项 [OKX](https://www.okx.com/en-us/help/tokenized-stocks-faq)。

## 8.2 按事件分层

必须分别报告：
- 财报日前后；
- 拆股/并股前后；
- 指数纳入/剔除；
- 重大监管新闻；
- 平台公告（下架、迁移、费率机制变更）前后。

## 8.3 按 funding regime 分层

| Regime | 定义 |
|--------|------|
| Mild positive | funding 小幅为正 |
| Extreme positive | funding 位于历史 90% / 95% 分位以上 |
| Negative | funding 为负 |
| Frequency-changed | funding 结算周期变化阶段 |

## 8.4 按流动性分层

以以下代理变量分层：
- spot volume；
- perp volume；
- bid/ask spread；
- intrabar range；
- 盘口深度（若可得）。

---

# 9. 图表要求

## 9.1 必须输出的图表

1. **标的与基差三联图**
   - spot 价格
   - perp/mark 价格
   - basis_pct

2. **Funding 时间序列图**
   - funding rate
   - rolling annualized funding
   - funding interval changes 标记

3. **累计 PnL 图（毛 / 净 / Stress）**
   - gross pnl
   - net pnl
   - stress pnl

4. **收益分解堆叠图**
   - funding
   - basis
   - spot cost
   - perp cost
   - financing / borrow / FX

5. **按 session 的收益箱线图**
   - regular
   - pre/post
   - overnight
   - weekend/closed mismatch

6. **事件研究图**
   - 围绕 funding 结算点的平均 basis 演化
   - 围绕财报日/拆股日的净值变化

7. **回撤水下图**
   - 净策略净值的 underwater curve

8. **Breakeven funding 分布图**
   - 每次交易需要多少 funding 才能覆盖全部成本

## 9.2 推荐输出图表

- Funding vs realized net carry 散点图；
- basis z-score vs future carry 散点图；
- turnover vs net pnl 散点图；
- rolling Sharpe；
- product availability timeline（上线/下架/停牌时间轴）。

---

# 10. 常见隐患与陷阱（资金费率套利专属）

## 10.1 把“tokenized stock spot”误当成“perp funding 产品”

这是最严重的错误。若资产没有 funding 结算机制，就不是 funding arbitrage 标的。

## 10.2 假设 Binance 必然有美股相关合约

错误。Binance funding API 是通用接口，但是否存在对应资产，需要逐个 ticker 核验；同时 Binance 曾停止 stock tokens 支持，这一历史事实不能省略 [Reuters](https://www.reuters.com/world/china/binance-stops-selling-stock-tokens-after-regulatory-scrutiny-2021-07-16/)。

## 10.3 用股票收盘价去对齐 24/7 合约

错误。若 crypto/链上腿在股票闭市后继续波动，而你仍拿当天股票收盘价充当可交易现货价，会严重低估基差风险。

## 10.4 把单次 funding 直接年化后当作稳定收益

错误。资金费率可正可负，也可能改变结算间隔。OKX 官方就说明结算周期可能由默认 8 小时调整为 1/2/4 小时等 [OKX](https://www.okx.com/en-us/help/perps-funding-fee-mechanism)。

## 10.5 忽略 corporate action

拆股、并股、分红、财报都可能使 spot 与 tokenized/perp 的映射短时失真。若不做事件剔除，回测结果会被伪 alpha 污染。

## 10.6 忽略做空现货约束

负 funding 套利通常需要 short spot，但美股 short 现实中可能受限于：
- 可借券不足；
- 借券利率高；
- locate 失败；
- 强平与回补风险。

若拿不到真实 borrow 数据，必须把负 funding 套利标为“理论可行，实际待验证”。

## 10.7 忽略 FX 与跨账户资金占用

若股票腿在券商、合约腿在交易所/链上，实际存在：
- 现金划转时间差；
- 不同保证金币种；
- 稳定币/美元转换成本；
- 跨平台信用与托管风险。

这些都属于净 carry 的一部分，而非可忽略项。

---

# 11. 标准回测流程

## 11.1 流程图

```text
产品可行性核验
    ↓
确定标的映射（股票 ↔ token/perp）
    ↓
抓取 Futu 现货历史价格
    ↓
抓取 Binance/OKX 合约价格 + funding 历史
    ↓
统一 UTC / 统一 schema / 标注 session
    ↓
构建 basis / carry / cost 模型
    ↓
运行 3 套持仓规则（single funding / rolling / session filtered）
    ↓
输出 gross / net / stress 三套净值
    ↓
做 session / event / regime 分层分析
    ↓
输出报告与“是否可落地”结论
```

## 11.2 最低可复现实验

建议先用**单一标的 + 单一平台 + 30~90 天样本**做 smoke test：

1. 选一个回测期内明确存在的标的；
2. 抓取 Futu 1m 或 5m 扩展时段数据；
3. 抓取 Binance/OKX funding history；
4. 用 `long stock + short perp` 跑单次 funding 策略；
5. 检查净收益是否主要被成本吞噬；
6. 再扩展到多月/多标的。

---

# 12. 报告模板（最终交付必须遵循）

## 12.1 执行摘要

- 本次研究覆盖的平台与标的；
- 是否存在可交易 funding 样本；
- 主要收益来源；
- 主要风险来源；
- 结论：可落地 / 仅理论可行 / 当前不可行。

## 12.2 数据说明

- Futu 数据频率、session、复权口径；
- Binance / OKX funding 与 price 数据来源；
- 时间范围；
- 缺失处理。

## 12.3 成本说明

- 现货腿费率假设；
- 合约腿费率假设；
- 滑点与点差模型；
- 借券/融资/FX 假设。

## 12.4 策略定义

- 入场；
- 退出；
- 头寸匹配；
- 再平衡；
- 风险约束。

## 12.5 结果

- gross / net / stress 净值；
- 关键指标表；
- 图表；
- 分层分析。

## 12.6 结论

必须二选一：

**A. 可做**
```text
在保守成本假设下，正 funding 套利在多数样本窗内仍为正，且收益并非完全依赖极端单次 funding，具备进一步实盘验证价值。
```

**B. 不可做 / 暂不可做**
```text
虽然表面 funding 为正，但在纳入现货交易成本、基差波动、session mismatch 与制度约束后，净 carry 不稳定或样本不足，因此当前不支持实盘执行。
```

---

# 13. Agent 执行检查清单

| 检查项 | 必须通过 |
|--------|---------|
| 已核验目标平台回测期内确有可交易产品 | 是 |
| 已确认该产品确有 funding 机制 | 是 |
| 已抓取 Futu 历史现货价格 | 是 |
| 已区分 regular / extended sessions | 是 |
| 已抓取 funding 历史并保留原始结算时间 | 是 |
| 已统一时区为 UTC | 是 |
| 已显式建模现货腿成本 | 是 |
| 已显式建模合约腿成本 | 是 |
| 已显式建模 session mismatch 风险 | 是 |
| 已显式建模 corporate action 风险 | 是 |
| 已输出 gross / net / stress 三套结果 | 是 |
| 已给出“当前可交易性”结论，而非只给回测收益 | 是 |

---

# 14. 推荐实现备注

## 14.1 Futu 拉数建议

[Futu `request_history_kline`](https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html) 支持：
- `start/end`
- `ktype`
- `max_count`
- `page_req_key`
- `extended_time`

因此建议：
1. 用分页方式拉完整历史；
2. regular 与 extended 分开保存；
3. 不同复权口径分开保存；
4. 对 corporate action 前后做单独校验。

## 14.2 Binance / OKX 拉数建议

- Binance funding history 使用官方 API 拉全量历史，并与网页展示结果抽样核对 [Binance Developers](https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History) [Binance](https://www.binance.com/en/futures/funding-history/perpetual/funding-fee-history)；
- OKX funding 历史优先用官方 API / 官方历史数据下载源；
- funding rate、mark price、funding interval 必须同步保存；
- 若合约代码/产品规则曾变更，必须做 versioned symbol mapping。

## 14.3 数据目录建议

```text
data/
├── raw/
│   ├── futu/
│   ├── binance/
│   └── okx/
├── processed/
│   ├── spot_futu.parquet
│   ├── perp_bars.parquet
│   ├── perp_funding.parquet
│   └── symbol_mapping.parquet
└── artifacts/
    ├── figures/
    ├── tables/
    └── final_report.md
```

---

# 15. 研究结论的合规写法

## 15.1 可以写

- “在已确认存在 funding 记录的样本窗内，正 funding carry 在毛收益层面为正，但净收益依赖成本假设。”
- “OKX tokenized stocks 属于 provider-issued tokenized assets，不应直接等同于 perpetual futures。”
- “Binance 曾终止 stock tokens 支持，因此必须逐期核验相关产品是否真实存在。”

## 15.2 不可以写

- “Binance/OKX 一直都有美股永续合约。”
- “只要 funding 为正就能稳定套利。”
- “股票现货腿可以随时按收盘价成交。”
- “不考虑交易成本也能说明策略有效。”

---

# 16. 参考资料

1. Futu OpenAPI 总览：<https://openapi.futunn.com/futu-api-doc/en/>
2. Futu 历史 K 线：<https://openapi.futunn.com/futu-api-doc/en/quote/request-history-kline.html>
3. Futu 实时 K 线：<https://openapi.futunn.com/futu-api-doc/en/quote/get-kl.html>
4. Binance Funding History API：<https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api/Get-Funding-Rate-History>
5. Binance Funding History 页面：<https://www.binance.com/en/futures/funding-history/perpetual/funding-fee-history>
6. Binance 停止 stock tokens 相关新闻：<https://www.reuters.com/world/china/binance-stops-selling-stock-tokens-after-regulatory-scrutiny-2021-07-16/>
7. Binance 停止 stock tokens 公告：<https://www.binance.com/en/support/announcement/detail/3a0304f3ee1c43668959c1b01f610d59>
8. OKX perpetual funding fee mechanism：<https://www.okx.com/en-us/help/perps-funding-fee-mechanism>
9. OKX tokenized stocks FAQ：<https://www.okx.com/en-us/help/tokenized-stocks-faq>
10. OKX historical data：<https://www.okx.com/en-us/historical-data>
11. Futu 美股费用帮助页：<https://www.futuhk.com/en/support/topic2_283>
