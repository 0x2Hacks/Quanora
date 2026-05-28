---
name: workspace_discipline
description: >
  Project workspace boundary & directory convention discipline. Activates when
  the user asks you to scaffold, create, organize, or refactor project files,
  or whenever you need to decide whether/how to create a workspace directory.
  Governs: (1) when to create workspace dirs, (2) project naming, (3) unified
  sub-directory layout for quant/tool/doc projects, (4) output timestamping.
triggers:
  - "$workspace"
  - "$workspace_discipline"
  - "$project_layout"
  - "项目结构"
  - "项目目录"
  - "工作区"
  - "新建项目"
  - "创建项目"
  - "scaffold"
  - "create project"
  - "new project"
---

# Workspace Directory Convention

You MUST follow these rules every time you consider creating or organizing
files under the `workspace/` directory. Violations produce fragmented,
inconsistent directory trees that degrade over sessions.

---

## 1. Decision Gate: Do I Need a Workspace Directory?

Before creating ANY directory under `workspace/`, run this decision gate:

```
Does the task involve:
  ├─ Reading/querying data only (no code to write)?        → ❌ NO directory needed
  ├─ A quick bug-fix or param tweak (single file)?          → ❌ NO directory needed
  ├─ Pure conversation / Q&A / explanation?                 → ❌ NO directory needed
  └─ Any of the following?                                  → ✅ YES, create directory
       ├─ Driven by a docs/*.md document (the md name = project name)
       ├─ Writing strategy/signal/backtest code
       ├─ Quantitative research or backtesting
       ├─ Multi-file tool or script development
       └─ Output artifacts (charts, reports, CSVs) to persist
```

**If NO → do NOT create a workspace directory.** Work in-memory or use
temporary output. Mention results directly in the conversation.

**If YES → proceed to naming rules below.**

---

## 2. Project Directory Naming

Format: `<type>-<name>`

### 2.1 Type Prefix

| Type    | When to Use                                    | Examples                      |
|---------|------------------------------------------------|-------------------------------|
| `quant` | Quantitative strategies, backtests, research    | `quant-xauusd-macd`, `quant-sp500-momentum` |
| `tool`  | Utility scripts, data pipelines, infrastructure | `tool-data-downloader`, `tool-risk-monitor` |
| `doc`   | Documentation-driven tasks (from docs/*.md)     | `doc-fx-trading-guide`, `doc-api-spec`      |

### 2.2 Name Rules

- **kebab-case** only: lowercase letters, digits, hyphens as separators.
- **Concise & semantic**: max 4 hyphen-separated segments.
- **docs/*.md driven tasks**: `name` = md filename without `.md` extension.
  - Example: `docs/fx-trading-guide.md` → `workspace/doc-fx-trading-guide/`
- **No session IDs, no counters, no "1-agent" style names.**
- **No duplicate directories**: before creating, check if an existing
  directory already covers the same scope. Reuse it.

### 2.3 Examples

| Task | Directory |
|------|-----------|
| XAUUSD MACD strategy backtest | `workspace/quant-xauusd-macd/` |
| Data download utility | `workspace/tool-data-downloader/` |
| Task from `docs/fx-trading-guide.md` | `workspace/doc-fx-trading-guide/` |

---

## 3. Unified Sub-Directory Layout

### 3.1 Quant Projects (`quant-*`)

```
workspace/
└── quant-<name>/
    ├── src/                    # Strategy / signal / indicator source code
    │   ├── strategy.py         #   Core strategy logic
    │   ├── signal.py           #   Signal generation
    │   └── indicators.py       #   Technical indicators
    ├── scripts/                # Executable entry-points
    │   ├── backtest.py         #   Backtest runner
    │   └── download_data.py    #   Data acquisition
    ├── output/                 # ALL generated outputs (backtest results, charts)
    │   ├── 20260528_153000/    #   Timestamped backtest run
    │   │   ├── results.json    #     Metrics & summary
    │   │   ├── equity_curve.png
    │   │   ├── trades.csv
    │   │   └── log.txt
    │   └── 20260529_090000/    #   Another run
    │       └── ...
    ├── data/                   # Local data files (if project-specific)
    │   └── raw/                #   Raw downloaded data
    ├── config/                 # Configuration & parameters
    │   └── params.yaml
    ├── notebooks/              # Jupyter notebooks (optional)
    └── README.md               # Project description & usage
```

**Key rules for quant projects:**

1. **`output/` is the ONLY place for backtest results.** Never put results
   in `src/`, `scripts/`, or the project root.
2. **Every backtest run creates a `YYYYMMDD_HHMMSS/` subdirectory.**
   - Timestamp = the moment the backtest was *launched*, not completed.
   - Format: zero-padded, 24h clock. Example: `20260528_153000`.
3. **At minimum, each run directory contains `results.json`** with key
   metrics (sharpe, return, drawdown, etc.) for easy programmatic comparison.
4. **`src/` is for importable modules** (strategy, signal, indicators).
   **`scripts/` is for CLI entry-points** that import from `src/`.

### 3.2 Tool Projects (`tool-*`)

```
workspace/
└── tool-<name>/
    ├── src/                    # Core library code
    ├── scripts/                # Executable scripts
    ├── output/                 # Generated outputs (timestamped if applicable)
    ├── config/                 # Configuration
    └── README.md
```

### 3.3 Doc Projects (`doc-*`)

```
workspace/
└── doc-<name>/
    ├── src/                    # Document source / processing code
    ├── output/                 # Generated artifacts
    └── README.md
```

### 3.4 Minimal Project (any type)

For very small tasks, you MAY omit optional directories. The **minimum
viable structure** is:

```
workspace/
└── <type>-<name>/
    ├── src/                    # (or scripts/ — at least one must exist)
    └── README.md
```

Never create a project directory with zero files. If you only need one
script, put it under `scripts/` and add a brief `README.md`.

---

## 4. Output Timestamp Convention

Applies to **all project types** whenever artifacts are generated:

| Convention | Value |
|---|---|
| Directory name | `YYYYMMDD_HHMMSS` |
| Timezone | UTC (use `date -u +%Y%m%d_%H%M%S`) |
| Contents | At least one file; never empty directories |
| Metadata | Include `results.json` (quant) or `manifest.json` (other) for traceability |

**Example `results.json` for quant:**
```json
{
  "run_id": "20260528_153000",
  "strategy": "macd_crossover",
  "instrument": "XAUUSD",
  "timeframe": "H1",
  "period": {"start": "2024-01-01", "end": "2025-12-31"},
  "metrics": {
    "sharpe": 1.45,
    "total_return": 0.23,
    "max_drawdown": 0.08,
    "win_rate": 0.56,
    "total_trades": 342
  },
  "parameters": {
    "fast_period": 12,
    "slow_period": 26,
    "signal_period": 9
  }
}
```

---

## 5. Anti-Patterns (MUST Avoid)

| Anti-Pattern | Why It's Bad | Correct Approach |
|---|---|---|
| `workspace/1-agent/` | Opaque, no semantic meaning | Use `<type>-<name>` prefix |
| `workspace/backtest/bt_1/` | Nested project-type directories | `workspace/quant-<name>/` |
| `workspace/projects/proj_1_.../` | Counter-based naming | Use semantic kebab-case |
| `workspace/quant-1-self-doc-...-2/` | Session counter suffix | Clean name, reuse existing |
| Results in project root | Scattered, hard to compare | Always in `output/<timestamp>/` |
| `workspace/docs/` | Conflicts with root `docs/` | Doc projects → `workspace/doc-<name>/` |
| Empty directories | Clutter | Only create dirs when writing files |
| Multiple dirs for same task | Fragmentation | Reuse existing project directory |

---

## 6. Pre-Flight Checklist

Before creating any workspace directory, mentally (or explicitly) confirm:

- [ ] Task passes the **Decision Gate** (Section 1) → YES
- [ ] No existing directory already covers this scope → check `ls workspace/`
- [ ] Name follows `<type>-<name>` convention (Section 2)
- [ ] Sub-directories follow the unified layout (Section 3)
- [ ] Any output will go into `output/YYYYMMDD_HHMMSS/` (Section 4)
- [ ] No anti-patterns from Section 5

---

## 7. Migration Notes (Existing Messy Directories)

When you encounter existing directories that violate this convention:

1. **Do NOT auto-delete or auto-move them** without user confirmation.
2. When working IN a messy directory, follow the new convention for any NEW
   files you create (e.g., put new backtest results in `output/<timestamp>/`).
3. If the user asks to clean up, propose a migration plan:
   - Map old dir → new dir name
   - List files to move
   - Get explicit approval before executing

---

This skill is active whenever you consider creating, naming, or organizing
files under `workspace/`. When in doubt, re-read Section 1 (Decision Gate).
