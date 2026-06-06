# 1. 摘要

CryptoQuant 是一个面向加密货币市场的 **Alpha 研究引擎**，旨在帮助量化研究者快速定义、回测和评估加密货币因子策略。项目借鉴了 WorldQuant Brain 的表达式驱动研究范式，将其适配到高波动、7×24 小时交易的加密资产领域。

核心特性包括：

- **表达式引擎**：通过类 Brain 语法的 DSL 定义因子，支持时序（TS）、截面（CS）、分组（Group）和算术四大类算子，覆盖 30+ 内置操作
- **向量化回测**：基于 NumPy/Pandas 的全向量回测管线，无需循环即可完成信号→持仓→绩效计算
- **Walk-Forward 验证**：内建滚动窗口外样本验证，防止过拟合
- **Alpha 池管理**：SQLite 本地存储 + 去重 + 质量门控，支持跨会话策略复用
- **多分支迭代**：从 CLI 工具逐步演进到 FastAPI 后端 + MySQL 持久化的完整平台

> **源码仓库**：`https://github.com/0x2Hacks/cryptoquant`
>
> **许可证**：MIT

---

# 2. 项目概览

## 2.1 仓库信息

| 项目 | 详情 |
|------|------|
| 仓库 | `0x2Hacks/cryptoquant` |
| 语言 | Python 3.10+ |
| 包管理 | `pyproject.toml` (setuptools) |
| 核心依赖 | numpy, pandas, requests, gradio |
| 可选依赖 | mysql-connector-python (dev-v1/hyf-dev), fastapi + uvicorn (fastapi 分支) |

## 2.2 模块总览

```
cryptoquant/
├── __init__.py          # 版本与包元信息
├── cli.py               # Click 命令行入口
├── data/
│   ├── loader.py        # 数据加载器（CryptoCompare API）
│   ├── dataset.py       # 数据集构建与对齐
│   └── universes.py     # 币种 Universe 定义
├── engine/
│   ├── parser.py        # 表达式解析器（ANTLR 风格递归下降）
│   └── backtest.py      # 向量化回测引擎
├── operators/
│   ├── registry.py      # 算子注册表
│   ├── ts_ops.py        # 时序算子（ts_mean, ts_std, ts_rank …）
│   ├── cs_ops.py        # 截面算子（rank, zscore, scale …）
│   ├── group_ops.py     # 分组算子（group_rank, group_mean …）
│   └── arith_ops.py     # 算术运算（+, -, *, /, log, abs …）
├── evaluation/
│   ├── metrics.py       # 绩效指标计算
│   └── walkforward.py   # Walk-Forward 外样本验证
├── alpha_pool/
│   ├── pool.py          # Alpha 池（SQLite 持久化 + 去重）
│   ├── mysql_pool.py    # [dev-v1/hyf-dev] MySQL 持久化
│   └── mysql_bootstrap.py # [dev-v1] MySQL 表结构初始化
└── webui/
    └── app.py           # Gradio Web 界面
```

辅助目录：

```
tests/
└── test_smoke.py        # 冒烟测试
scripts/
└── run_cli.sh           # CLI 启动脚本
```

---

# 3. 核心架构

## 3.1 整体架构

CryptoQuant 采用经典的 **数据→引擎→评估→存储** 四层架构：

```
┌──────────────────────────────────────────────────────┐
│                    CLI / WebUI                        │  用户交互层
├──────────────────────────────────────────────────────┤
│  Alpha Pool (SQLite / MySQL)                         │  存储层
│  ┌──────────┐  ┌──────────┐  ┌──────────┐           │
│  │ 去重检查  │  │ 质量门控  │  │ 持久化    │           │
│  └──────────┘  └──────────┘  └──────────┘           │
├──────────────────────────────────────────────────────┤
│  Evaluation                                          │  评估层
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ Metrics      │  │ Walk-Forward │                  │
│  │ (Sharpe, DD) │  │ (滚动验证)   │                  │
│  └──────────────┘  └──────────────┘                  │
├──────────────────────────────────────────────────────┤
│  Engine                                              │  引擎层
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ Parser (DSL) │→ │ Backtest     │                  │
│  │ 表达式→AST   │  │ 向量化回测   │                  │
│  └──────────────┘  └──────────────┘                  │
├──────────────────────────────────────────────────────┤
│  Data                                                │  数据层
│  ┌──────────────┐  ┌──────────────┐                  │
│  │ Loader       │  │ Dataset      │                  │
│  │ CryptoCompare│  │ 多币种对齐   │                  │
│  └──────────────┘  └──────────────┘                  │
└──────────────────────────────────────────────────────┘
```

## 3.2 模块依赖关系

```
cli.py / webui/app.py
  ├── engine/backtest.py
  │   ├── engine/parser.py
  │   │   └── operators/registry.py
  │   │       ├── operators/ts_ops.py
  │   │       ├── operators/cs_ops.py
  │   │       ├── operators/group_ops.py
  │   │       └── operators/arith_ops.py
  │   └── data/dataset.py
  │       ├── data/loader.py
  │       └── data/universes.py
  ├── evaluation/metrics.py
  ├── evaluation/walkforward.py
  └── alpha_pool/pool.py
```

数据流方向：`用户输入表达式` → `Parser 解析为 AST` → `Backtest 引擎按 AST 逐节点计算因子值` → `生成信号与持仓` → `Metrics 计算绩效` → `WalkForward 外样本验证` → `Pool 存储与去重`

---

# 4. 数据层

## 4.1 数据源与加载

数据加载由 `cryptoquant/data/loader.py` 中的 `CryptoDataLoader` 类负责，核心数据源为 **CryptoCompare API**。

### 4.1.1 主要功能

| 功能 | 方法 | 说明 |
|------|------|------|
| 历史K线获取 | `fetch_ohlcv()` | 支持 daily/hourly 频率，返回 OHLCV + Volume |
| 多币种批量加载 | `load_universe()` | 按 Universe 定义批量拉取全部币种数据 |
| 缓存机制 | `fetch_ohlcv()` 内建 | 本地 Parquet 缓存，避免重复请求 |
| 增量更新 | `_incremental_update()` | 仅拉取最新缺失日期，节省 API 配额 |

### 4.1.2 API 参数

```python
# CryptoCompare API 调用参数示例
params = {
    "fsym": "BTC",        # 基础货币
    "tsym": "USD",        # 计价货币
    "limit": 2000,        # 最大返回条数
    "aggregate": 1,       # 聚合周期
    "e": "CCCAGG"         # 交易所聚合
}
```

### 4.1.3 数据格式

返回的 DataFrame 标准列：

| 列名 | 类型 | 说明 |
|------|------|------|
| `open` | float64 | 开盘价 |
| `high` | float64 | 最高价 |
| `low` | float64 | 最低价 |
| `close` | float64 | 收盘价 |
| `volumefrom` | float64 | 成交量（基础货币） |
| `volumeto` | float64 | 成交量（计价货币） |
| `timestamp` | int64 | Unix 时间戳 |

### 4.1.4 dev-v1 / hyf-dev 增强数据层

`dev-v1` 和 `hyf-dev` 分支对数据加载器进行了大幅增强：

- **CoinGecko 数据源**：新增 `CoinGeckoDataLoader` 作为备选数据源，支持更多市值排名数据
- **链上数据**：新增 `OnchainDataLoader`，支持加载链上指标（活跃地址数、交易笔数等）
- **数据源抽象**：引入 `BaseDataLoader` 抽象基类，统一不同数据源的接口
- **混合数据加载**：支持将价格数据和链上数据按时间戳对齐后合并为统一的 Dataset

```python
# dev-v1/hyf-dev 新增的抽象数据源
class BaseDataLoader(ABC):
    @abstractmethod
    def fetch_ohlcv(self, symbol, freq, start, end): ...

class CoinGeckoDataLoader(BaseDataLoader): ...
class OnchainDataLoader(BaseDataLoader): ...
```

## 4.2 数据集构建与 Universe

### 4.2.1 Dataset 类

`cryptoquant/data/dataset.py` 中的 `Dataset` 类负责将原始 OHLCV 数据构建为可供回测引擎使用的多维面板数据：

- **多币种对齐**：将不同币种的时间序列按日期索引对齐
- **缺失值填充**：前向填充缺失日期，保证面板完整性
- **特征字典**：将每列数据（open, high, low, close, volume）组织为 `{field_name: DataFrame}` 字典，其中 DataFrame 的行为日期、列为币种

### 4.2.2 Universe 定义

`cryptoquant/data/universes.py` 预定义了常用币种池：

| Universe 名称 | 币种数 | 说明 |
|---------------|--------|------|
| `TOP10` | 10 | 市值前 10 的主流币（BTC, ETH, BNB …） |
| `TOP20` | 20 | 市值前 20 |
| `TOP50` | 50 | 市值前 50 |
| `DEFI` | ~20 | DeFi 蓝筹（UNI, AAVE, MKR …） |

Universe 可通过 `get_universe(name)` 函数获取，返回币种符号列表。

---

# 5. 表达式引擎

## 5.1 解析器

`cryptoquant/engine/parser.py` 实现了一个 **递归下降表达式解析器**，将文本表达式解析为抽象语法树（AST），供回测引擎执行。

### 5.1.1 语法规则

表达式语法借鉴 WorldQuant Brain DSL，核心规则如下：

```
expression := term (('+' | '-') term)*
term       := factor (('*' | '/') factor)*
factor     := atom | '-' factor | '(' expression ')'
atom       := NUMBER | FIELD | FUNC_NAME '(' arg_list ')'
arg_list   := expression (',' expression)*
```

支持的原子类型：

| 类型 | 示例 | 说明 |
|------|------|------|
| 数值常量 | `0.5`, `20` | 直接作为常量因子 |
| 数据字段 | `close`, `volume`, `high/low` | 引用 Dataset 中的列 |
| 函数调用 | `ts_mean(close, 20)` | 算子调用 |
| 嵌套表达式 | `rank(ts_mean(close, 5))` | 算子组合 |

### 5.1.2 AST 节点类型

```python
class Node:                  # AST 基类
    pass

class NumberNode(Node):      # 数值常量
    value: float

class FieldNode(Node):       # 数据字段引用
    name: str

class BinaryOpNode(Node):    # 二元运算 (+, -, *, /)
    op: str
    left: Node
    right: Node

class UnaryOpNode(Node):     # 一元运算 (-, log, abs)
    op: str
    operand: Node

class FuncCallNode(Node):    # 函数调用
    func_name: str
    args: list[Node]
```

### 5.1.3 解析流程

```
"rank(ts_mean(close, 20))"
  ↓ tokenize
["rank", "(", "ts_mean", "(", "close", ",", "20", ")", ")"]
  ↓ recursive descent parse
FuncCallNode("rank", [FuncCallNode("ts_mean", [FieldNode("close"), NumberNode(20)])])
```

## 5.2 算子体系

算子是表达式引擎的核心。CryptoQuant 将算子分为四大类，全部通过 `operators/registry.py` 中的 `OperatorRegistry` 统一注册和调度。

### 5.2.1 时序算子（TS Operators）

时序算子沿时间轴滚动计算，是最常用的算子类别。定义在 `operators/ts_ops.py`。

| 算子 | 签名 | 说明 |
|------|------|------|
| `ts_mean(x, d)` | (DataFrame, int) → DataFrame | 滚动均值 |
| `ts_std(x, d)` | (DataFrame, int) → DataFrame | 滚动标准差 |
| `ts_sum(x, d)` | (DataFrame, int) → DataFrame | 滚动求和 |
| `ts_max(x, d)` | (DataFrame, int) → DataFrame | 滚动最大值 |
| `ts_min(x, d)` | (DataFrame, int) → DataFrame | 滚动最小值 |
| `ts_rank(x, d)` | (DataFrame, int) → DataFrame | 滚动百分位排名 |
| `ts_delta(x, d)` | (DataFrame, int) → DataFrame | 差分 x_t - x_{t-d} |
| `ts_returns(x, d)` | (DataFrame, int) → DataFrame | 收益率 x_t/x_{t-d} - 1 |
| `ts_corr(x, y, d)` | (DataFrame, DataFrame, int) → DataFrame | 滚动相关系数 |
| `ts_cov(x, y, d)` | (DataFrame, DataFrame, int) → DataFrame | 滚动协方差 |
| `ts_regression(y, x, d)` | (DataFrame, DataFrame, int) → DataFrame | 滚动回归残差 |
| `ts_argmax(x, d)` | (DataFrame, int) → DataFrame | 滚动窗口最大值位置 |
| `ts_argmin(x, d)` | (DataFrame, int) → DataFrame | 滚动窗口最小值位置 |
| `ts_decay_linear(x, d)` | (DataFrame, int) → DataFrame | 线性衰减加权均值 |

所有时序算子底层使用 Pandas 的 `rolling()` + 向量化操作实现，避免逐行循环。

### 5.2.2 截面算子（CS Operators）

截面算子在同一时间截面上对全部币种进行横截面操作。定义在 `operators/cs_ops.py`。

| 算子 | 签名 | 说明 |
|------|------|------|
| `rank(x)` | DataFrame → DataFrame | 横截面排名（归一化到 [0, 1]） |
| `zscore(x)` | DataFrame → DataFrame | 横截面 Z-Score 标准化 |
| `scale(x)` | DataFrame → DataFrame | 横截面缩放使绝对值之和为 1 |
| `demean(x)` | DataFrame → DataFrame | 横截面去均值 |
| `normalize(x)` | DataFrame → DataFrame | 横截面 Min-Max 归一化 |

### 5.2.3 分组算子（Group Operators）

分组算子按指定维度（如板块）分组后执行截面操作。定义在 `operators/group_ops.py`。

| 算子 | 签名 | 说明 |
|------|------|------|
| `group_rank(x, group)` | (DataFrame, Series) → DataFrame | 组内排名 |
| `group_mean(x, group)` | (DataFrame, Series) → DataFrame | 组内均值 |
| `group_zscore(x, group)` | (DataFrame, Series) → DataFrame | 组内 Z-Score |

分组信息通过 Universe 扩展属性提供，例如 DeFi/CEX/L1/L2 等板块标签。

### 5.2.4 算术运算（Arithmetic Operators）

基本算术运算不单独注册为算子，而是在 Parser 中直接处理。定义在 `operators/arith_ops.py`。

| 运算 | 示例 | 说明 |
|------|------|------|
| 加法 | `close + open` | 逐元素加 |
| 减法 | `close - open` | 逐元素减 |
| 乘法 | `close * volume` | 逐元素乘 |
| 除法 | `close / ts_mean(close, 20)` | 逐元素除（自动处理除零） |
| 对数 | `log(close)` | 自然对数 |
| 绝对值 | `abs(close - open)` | 绝对值 |
| 符号 | `sign(ts_delta(close, 1))` | 符号函数 |

## 5.3 算子注册机制

`OperatorRegistry` 提供统一的算子注册和查找接口：

```python
# 注册算子
registry = OperatorRegistry()
registry.register("ts_mean", ts_mean, category="ts", arity=2)
registry.register("rank", rank, category="cs", arity=1)

# 查找算子
op = registry.get("ts_mean")  # 返回 (函数, 元信息)
```

**扩展算子**只需三步：

1. 在对应模块中实现函数，签名遵循 `(DataFrame, ...) → DataFrame`
2. 调用 `registry.register()` 注册
3. 即可在表达式中使用

---

# 6. 回测引擎

## 6.1 向量化回测流程

`cryptoquant/engine/backtest.py` 实现了全向量化回测，核心流程：

```
表达式 → AST → 因子值矩阵 → 信号矩阵 → 持仓矩阵 → 绩效序列
```

### 6.1.1 核心类 BacktestEngine

```python
class BacktestEngine:
    def __init__(self, dataset: Dataset, parser: ExpressionParser):
        ...

    def run(self, expression: str, **kwargs) -> BacktestResult:
        """完整回测流程"""
        # 1. 解析表达式
        ast = self.parser.parse(expression)
        # 2. 递归求值 AST，生成因子值矩阵 (T × N)
        factor_matrix = self._evaluate(ast)
        # 3. 信号生成
        signals = self._generate_signals(factor_matrix)
        # 4. 构建持仓
        positions = self._build_positions(signals)
        # 5. 计算 PnL
        pnl = self._compute_pnl(positions)
        return BacktestResult(pnl, positions, factor_matrix, signals)
```

### 6.1.2 因子求值

`_evaluate(ast)` 方法递归遍历 AST 节点：

- `NumberNode` → 广播为全矩阵常量
- `FieldNode` → 从 Dataset 中取对应列的 DataFrame
- `BinaryOpNode` → 递归求值左右子树，执行算术运算
- `FuncCallNode` → 从 Registry 查找算子，递归求值参数后调用

### 6.1.3 信号与持仓

| 步骤 | 输入 | 输出 | 说明 |
|------|------|------|------|
| 信号生成 | 因子值矩阵 (T×N) | 信号矩阵 (T×N) | 横截面排名 → 多空分组 |
| 持仓构建 | 信号矩阵 | 持仓权重矩阵 (T×N) | 等权 / 信号加权 |
| PnL 计算 | 持仓 × 收益率 | 每日 PnL 序列 | ∑(w_i × r_i) |

## 6.2 信号生成策略

默认采用 **横截面排名多空** 策略：

1. 每个时间截面对因子值排名
2. 排名前 `long_pct`（默认 20%）的币种做多
3. 排名后 `short_pct`（默认 20%）的币种做空
4. 多空组合等权分配

支持自定义信号生成器，通过 `signal_fn` 参数注入。

---

# 7. 评估体系

## 7.1 核心指标

`cryptoquant/evaluation/metrics.py` 提供标准的量化绩效指标：

| 指标 | 函数 | 说明 |
|------|------|------|
| Sharpe Ratio | `sharpe_ratio(returns, rf=0)` | 年化 Sharpe，默认无风险利率 0 |
| Sortino Ratio | `sortino_ratio(returns, rf=0)` | 下行风险调整收益 |
| Max Drawdown | `max_drawdown(returns)` | 最大回撤（负值） |
| Calmar Ratio | `calmar_ratio(returns)` | 年化收益 / 最大回撤绝对值 |
| Turnover | `turnover(positions)` | 持仓换手率 |
| Win Rate | `win_rate(returns)` | 正收益日占比 |
| Annual Return | `annual_return(returns)` | 年化复合收益率 |
| Volatility | `annual_volatility(returns)` | 年化波动率 |

### 7.1.1 加密市场适配

针对加密市场 7×24 交易特性，指标计算做了以下适配：

- **年化因子**：使用 365 天（而非传统市场的 252 个交易日）
- **小时频支持**：`sharpe_ratio` 支持 `freq='hourly'` 参数，年化因子自动调整为 √(365×24)
- **零价格过滤**：自动过滤价格为零或 NaN 的币种-日期对

## 7.2 Walk-Forward 验证

`cryptoquant/evaluation/walkforward.py` 实现了滚动窗口外样本验证，防止过拟合。

### 7.2.1 工作原理

```
|── Train ──|── Test ──|                              Fold 1
   |── Train ──|── Test ──|                            Fold 2
      |── Train ──|── Test ──|                         Fold 3
         |── Train ──|── Test ──|                      Fold 4
```

### 7.2.2 WalkForwardValidator 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `train_window` | 180 | 训练窗口天数 |
| `test_window` | 30 | 测试窗口天数 |
| `step` | 30 | 滚动步长（天） |
| `min_trades` | 10 | 每折最少交易次数 |

### 7.2.3 输出

```python
@dataclass
class WalkForwardResult:
    fold_results: list[BacktestResult]   # 每折回测结果
    oos_sharpe: float                     # 外样本平均 Sharpe
    oos_max_drawdown: float               # 外样本最大回撤
    is_sharpe: float                      # 内样本平均 Sharpe
    is_oos_gap: float                     # IS-OOS Sharpe 差值（过拟合指标）
```

**过拟合判断规则**：若 `is_oos_gap > 0.5`（内样本 Sharpe 比外样本高 0.5 以上），标记为过拟合风险。

---

# 8. Alpha 池管理

## 8.1 本地存储（SQLite）

`cryptoquant/alpha_pool/pool.py` 实现基于 SQLite 的 Alpha 持久化存储。

### 8.1.1 AlphaRecord 数据结构

```python
@dataclass
class AlphaRecord:
    expression: str          # 因子表达式
    created_at: str          # 创建时间
    sharpe: float            # Sharpe Ratio
    max_drawdown: float      # 最大回撤
    turnover: float          # 换手率
    fitness: float           # 综合评分 = Sharpe × (1 - max(0, turnover - 0.5))
    status: str              # active / archived / rejected
```

### 8.1.2 AlphaPool API

| 方法 | 说明 |
|------|------|
| `add(record)` | 添加 Alpha 到池中 |
| `list(limit, min_sharpe)` | 列出 Alpha，支持 Sharpe 过滤 |
| `get(expression)` | 按表达式精确查找 |
| `remove(expression)` | 移除指定 Alpha |
| `is_duplicate(expression)` | 检查是否重复（表达式规范化后比对） |

### 8.1.3 去重机制

表达式去重通过 **规范化比较** 实现：

1. 去除空格
2. 统一算子名大小写
3. 比较规范化后的字符串

这可以捕获 `ts_mean(close,20)` 与 `ts_mean(close, 20)` 这类差异。

## 8.2 质量门控

Alpha 入池前需通过质量门控：

| 条件 | 默认阈值 | 说明 |
|------|----------|------|
| Sharpe Ratio | ≥ 1.0 | 最低 Sharpe 要求 |
| Max Drawdown | ≥ -0.5 | 最大回撤不超过 50% |
| Turnover | ≤ 0.7 | 换手率上限 |
| Fitness | ≥ 0.5 | 综合评分下限 |
| 非过拟合 | is_oos_gap < 0.5 | Walk-Forward 检查 |

---

# 9. CLI 与 WebUI

## 9.1 命令行工具

`cryptoquant/cli.py` 基于 Click 框架，提供以下子命令：

| 命令 | 说明 |
|------|------|
| `cryptoquant backtest "expr"` | 运行单因子回测 |
| `cryptoquant evaluate "expr"` | 完整评估（回测 + Walk-Forward + 门控） |
| `cryptoquant pool list` | 列出 Alpha 池 |
| `cryptoquant pool add "expr"` | 添加 Alpha 到池中 |
| `cryptoquant data fetch UNIVERSE` | 拉取指定 Universe 数据 |

### 9.1.1 常用示例

```bash
# 回测简单动量因子
cryptoquant backtest "rank(ts_returns(close, 20))"

# 完整评估，指定 Universe 和频率
cryptoquant evaluate "rank(ts_delta(close, 5))" \
    --universe TOP20 \
    --freq daily \
    --start 2023-01-01 \
    --end 2025-12-31

# 查看池中 Sharpe > 1.5 的 Alpha
cryptoquant pool list --min-sharpe 1.5

# 拉取 TOP50 数据
cryptoquant data fetch TOP50
```

## 9.2 Gradio Web 界面

`cryptoquant/webui/app.py` 提供基于 Gradio 的 Web 界面，支持：

| 功能 | 说明 |
|------|------|
| 表达式输入 | 文本框输入因子表达式 |
| 参数配置 | Universe、频率、时间范围选择 |
| 回测结果 | 净值曲线 + 关键指标展示 |
| Alpha 池浏览 | 表格展示池中所有 Alpha |
| 一键评估 | 回测 + Walk-Forward 一键运行 |

启动方式：

```bash
cryptoquant webui --port 7860
```

---

# 10. 分支迭代分析

项目共有 5 个分支，代表不同阶段的迭代方向：

## 10.1 main — 核心引擎

| 项目 | 详情 |
|------|------|
| Commit 数 | ~14 |
| 核心变更 | 完整的 CLI + 表达式引擎 + 回测 + 评估 + SQLite Alpha 池 |

main 分支是项目的**基线版本**，包含所有核心功能：

- 表达式解析器 + 四大类算子
- 向量化回测引擎
- Metrics + Walk-Forward 评估
- SQLite Alpha 池
- Click CLI + Gradio WebUI
- 冒烟测试

## 10.2 dev-v1 — MySQL + 增强数据层

| 项目 | 详情 |
|------|------|
| 相对 main 新增文件 | `mysql_pool.py`, `mysql_bootstrap.py`, `records.py` |
| 修改文件 | `loader.py`（大幅扩展）, `pool.py`, `cli.py` |

dev-v1 是最实质性的迭代分支，引入了三个关键改进：

### 10.2.1 MySQL 持久化

`mysql_pool.py` 将 Alpha 存储从 SQLite 升级为 MySQL：

```python
class MySQLAlphaPool(AlphaPoolBase):
    """MySQL 持久化 Alpha 池"""
    def __init__(self, host, port, user, password, database):
        self.conn = mysql.connector.connect(...)
        self._ensure_table()  # 自动建表

    def add(self, record: AlphaRecord): ...
    def list(self, limit, min_sharpe): ...
    def is_duplicate(self, expression): ...
```

`mysql_bootstrap.py` 负责表结构初始化：

```sql
CREATE TABLE IF NOT EXISTS alphas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    expression TEXT NOT NULL,
    created_at DATETIME,
    sharpe FLOAT,
    max_drawdown FLOAT,
    turnover FLOAT,
    fitness FLOAT,
    status VARCHAR(20),
    UNIQUE KEY uq_expression (expression(255))
);
```

### 10.2.2 增强数据加载器

`loader.py` 从 ~150 行扩展到 ~900 行，新增：

- **CoinGecko 数据源**：`CoinGeckoDataLoader` 类，支持市值排名、历史价格
- **链上数据**：`OnchainDataLoader` 类，支持活跃地址、交易数等
- **数据源抽象**：`BaseDataLoader` 基类统一接口
- **混合加载**：`HybridDataLoader` 支持多源数据合并

### 10.2.3 records 数据模型

`records.py` 引入了更完善的记录模型：

```python
@dataclass
class AlphaRecord:
    expression: str
    created_at: str
    sharpe: float
    max_drawdown: float
    turnover: float
    fitness: float
    status: str
    # 新增字段
    universe: str           # 回测使用的 Universe
    freq: str               # 数据频率
    start_date: str         # 回测起始日
    end_date: str           # 回测结束日
    oos_sharpe: float       # 外样本 Sharpe
    tags: list[str]         # 标签分类
```

## 10.3 hyf-dev — 数据层深度优化

| 项目 | 详情 |
|------|------|
| 相对 dev-v1 变更 | 删除 backend/、scripts/、tests/；精简 MySQL Pool |
| 核心聚焦 | 数据加载器进一步优化 |

hyf-dev 是 dev-v1 的精简分支，去除了与核心数据层无关的模块，专注数据加载优化：

- **数据清洗增强**：新增异常值检测与过滤（价格突变 > 50% 标记为异常）
- **API 限流处理**：增加请求速率控制和重试逻辑
- **并行加载**：使用 `concurrent.futures` 并行拉取多币种数据
- **精简 MySQL Pool**：移除不必要的复杂查询，保留核心 CRUD

## 10.4 20260526_add_fastapi_backend — FastAPI 后端

| 项目 | 详情 |
|------|------|
| 新增目录 | `backend/` (7 个文件) |
| 核心目的 | 为引擎添加 REST API 层 |

该分支引入了完整的 **FastAPI 后端服务**，使 CryptoQuant 可以作为服务被前端或其他系统调用。

### 10.4.1 后端架构

```
backend/
├── main.py                   # FastAPI 应用入口
├── api/
│   ├── auth.py               # JWT 认证
│   ├── factors.py            # 因子管理 API
│   └── backtest.py           # 回测执行 API
├── core/
│   ├── config.py             # 配置管理
│   └── security.py           # 安全工具（JWT 生成/验证）
├── db/
│   ├── session.py            # 数据库会话
│   └── models.py             # SQLAlchemy ORM 模型
├── models/
│   ├── schemas.py            # Pydantic 请求/响应模型
│   └── backtest.py           # 回测相关数据模型
└── services/
    └── backtest_service.py   # 回测业务逻辑
```

### 10.4.2 核心 API 端点

| 端点 | 方法 | 说明 |
|------|------|------|
| `/api/auth/login` | POST | 用户登录，返回 JWT |
| `/api/auth/register` | POST | 用户注册 |
| `/api/factors` | GET | 列出所有因子 |
| `/api/factors/{id}` | GET | 获取因子详情 |
| `/api/backtest/run` | POST | 执行回测 |
| `/api/backtest/results/{id}` | GET | 获取回测结果 |
| `/api/backtest/walkforward` | POST | 执行 Walk-Forward |

### 10.4.3 关键实现

**JWT 认证**（`core/security.py`）：

```python
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 30

def create_access_token(data: dict) -> str: ...
def verify_token(token: str) -> dict: ...
```

**数据库会话**（`db/session.py`）：

```python
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
```

**回测服务**（`services/backtest_service.py`）：

```python
class BacktestService:
    def run_backtest(self, expression: str, config: BacktestConfig) -> BacktestResult:
        """调用核心引擎执行回测"""
        engine = BacktestEngine(dataset, parser)
        result = engine.run(expression)
        return result
```

### 10.4.4 配置管理

```python
# backend/core/config.py
class Settings(BaseSettings):
    PROJECT_NAME: str = "CryptoQuant API"
    DATABASE_URL: str
    SECRET_KEY: str
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
```

## 10.5 genspark_ai_developer — AI 辅助开发

| 项目 | 详情 |
|------|------|
| 相对 main 差异 | 无代码差异 |
| 推测用途 | AI 辅助开发的实验分支 |

该分支与 main 分支代码完全一致，推测用于 Genspark AI 开发工具的集成实验，尚未产生实质性代码变更。

## 10.6 迭代路线图总结

```
main ─────────────────────────────────────────────────→ 基线版本
  │
  ├── dev-v1 ────────────────────────────────────────→ MySQL + 增强数据层
  │     │
  │     └── hyf-dev ─────────────────────────────────→ 数据层深度优化（精简）
  │
  ├── 20260526_add_fastapi_backend ──────────────────→ REST API 服务化
  │
  └── genspark_ai_developer ─────────────────────────→ AI 辅助开发（实验）
```

| 阶段 | 分支 | 核心目标 | 成熟度 |
|------|------|----------|--------|
| V0 | main | 核心引擎可用 | ✅ 稳定 |
| V1 | dev-v1 | 数据层扩展 + MySQL 持久化 | 🔧 开发中 |
| V1.1 | hyf-dev | 数据层精简优化 | 🔧 开发中 |
| V2 | 20260526_add_fastapi_backend | 服务化 + 用户系统 | 🔧 开发中 |
| V? | genspark_ai_developer | AI 集成探索 | 🧪 实验 |

---

# 11. 总结与展望

## 11.1 项目优势

1. **表达式驱动**：低门槛因子定义方式，无需编写 Python 代码即可研究新因子
2. **向量化高效**：全 Pandas/NumPy 向量化实现，回测速度远快于事件驱动框架
3. **Walk-Forward 内建**：原生支持外样本验证，降低过拟合风险
4. **加密市场适配**：365 天年化、7×24 小时处理、零价格过滤等细节
5. **多分支并行**：数据层、服务层、AI 层独立迭代，互不阻塞

## 11.2 潜在改进方向

| 方向 | 现状 | 建议 |
|------|------|------|
| 交易成本 | 未建模 | 添加滑点和手续费模型 |
| 风险模型 | 简单多空等权 | 引入因子中性化（行业/市值） |
| 数据频率 | 仅支持 daily | 扩展到 hourly / minute 级别 |
| 集成测试 | 仅有冒烟测试 | 添加端到端回测回归测试 |
| 分支合并 | 各分支独立 | 合并 dev-v1 的数据层增强到 main |
| 文档 | 仅 README | 补充 API 文档和算子参考手册 |
| CI/CD | 无 | 添加 GitHub Actions 自动测试 |

## 11.3 架构演进建议

基于当前分支分析，建议的合并路线：

1. **Phase 1**：将 hyf-dev 的数据层优化合入 dev-v1，统一数据层
2. **Phase 2**：将 dev-v1 的 MySQL 持久化合入 main，替换 SQLite
3. **Phase 3**：将 FastAPI 后端合入，形成 main + backend 双层架构
4. **Phase 4**：基于 FastAPI 前端对接，形成完整 SaaS 平台

---

> **文档生成时间**：2026-06-06
>
> **分析分支**：main, dev-v1, hyf-dev, 20260526_add_fastapi_backend, genspark_ai_developer
>
> **源码仓库**：`https://github.com/0x2Hacks/cryptoquant`
