---
name: workspace_discipline
description: >
  Project workspace boundary & directory convention discipline. Activates when
  the user asks you to scaffold, create, organize, or refactor project files,
  or whenever you need to decide whether/how to create a workspace directory.
  Governs: (1) when to create workspace dirs, (2) project naming, (3) unified
  sub-directory layout for quant/tool/doc projects, (4) output timestamping,
  (5) strict output/ directory enforcement.
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

Format: `<descriptive-name>` (kebab-case)

### 2.1 Naming Principles

- **No type prefix**: The project type is detected internally and does NOT
  appear in the directory name. Types like `quant_`, `bt_`, `wq_` are
  forbidden as directory name prefixes.
- **Flat structure**: All project directories live directly under
  `workspace/`, with no intermediate category directories (no `backtest/`,
  `alpha/`, `docs/` sub-trees).
- **Content-derived**: The name comes from the task description / MD filename,
  not from an artificial classification.

### 2.2 Name Rules

- **kebab-case** only: lowercase letters, digits, hyphens as separators.
- **No underscores**: Use hyphens, not underscores, for readability and
  consistency with URL/CLI conventions.
- **Concise & semantic**: max 4 hyphen-separated segments, max 60 chars.
- **docs/*.md driven tasks**: `name` = md filename without `.md` extension.
  - Example: `docs/tokenized_stock_funding.md` → `workspace/tokenized-stock-funding/`
- **No session IDs, no counters, no "1-agent" style names.**
- **No type prefixes**: `bt_`, `wq_`, `spec_`, `sig_` etc. are FORBIDDEN.
- **No duplicate directories**: before creating, check if an existing
  directory already covers the same scope. Reuse it.

### 2.3 Examples

| Task | Directory |
|------|-----------|
| XAUUSD MACD strategy backtest | `workspace/xauusd-macd-backtest/` |
| Data download utility | `workspace/data-downloader/` |
| Task from `docs/tokenized_stock_funding.md` | `workspace/tokenized-stock-funding/` |
| WorldQuant alpha mining | `workspace/worldquant-alpha-mining/` |

---

## 3. Unified Sub-Directory Layout

The project manager (`agent/domain/project_manager.py`) distinguishes two
categories: **Doc-Only** and **Code** types. Doc-only types skip skeleton
creation entirely; code types get auto-created sub-directories.

### 3.1 Doc-Only Types (no skeleton sub-directories)

These types produce **Markdown / documentation only**. When creating a
doc-only project, create the root directory but do NOT create `data/`,
`output/`, `src/` or any other sub-directory. The user will add files as
needed.

**Doc-only types** (defined in `_DOC_ONLY_TYPES` in project_manager.py):

| type_id | Description |
|---|---|
| `quant_md_futures` | Futures market research notes |
| `quant_md_fx` | FX market research notes |
| `quant_md_crypto` | Crypto market research notes |
| `quant_research` | General quant research notes |

Layout:
```
workspace/
└── <type>-<name>/
    ├── research_notes.md       # Added by user on demand
    └── ...                     # No auto-created sub-dirs
```

### 3.2 Code Types (standard skeleton)

These types require code, data, and output directories. The project
manager auto-creates a standard skeleton on first use.

| type_id | Skeleton sub-directories |
|---|---|
| `wq_alpha` | `data/`, `output/report/`, `output/logs/`, `docs/` |
| `quant_signal` | `data/`, `src/`, `output/report/`, `output/logs/`, `docs/` |
| `quant_backtest` | `data/`, `src/`, `output/report/`, `output/logs/`, `output/artifacts/`, `docs/` |
| `data_pipeline` | `data/raw/`, `data/processed/`, `src/`, `output/logs/`, `output/artifacts/`, `docs/` |
| `web_app` | `src/`, `static/`, `templates/`, `output/logs/`, `docs/` |
| `general` | `data/`, `src/`, `output/`, `docs/` |

Example (`quant_backtest`):
```
workspace/
└── macd-strategy-backtest/
    ├── src/                     # Strategy / signal / indicator source code
    │   ├── strategy.py         #   Core strategy logic
    │   ├── signal.py           #   Signal generation
    │   └── indicators.py       #   Technical indicators
    ├── scripts/                # Executable entry-points
    │   ├── backtest.py         #   Backtest runner
    │   └── download_data.py    #   Data acquisition
    ├── output/                 # ALL generated outputs
    │   ├── 20260528_153000/    #   Timestamped backtest run
    │   │   ├── results.json    #     Metrics & summary
    │   │   ├── equity_curve.png
    │   │   ├── trades.csv
    │   │   └── log.txt
    │   └── 20260529_090000/    #   Another run
    │       └── ...
    ├── data/                   # Local data files
    │   └── raw/                #   Raw downloaded data
    ├── docs/
    └── README.md
```

### 3.3 Minimal Project (code types only)

For very small tasks, you MAY omit optional directories. The **minimum
viable structure** for a code-type project is:

```
workspace/
└── <type>-<name>/
    ├── src/                     # At least one source file
    └── README.md
```

Never create a project directory with zero files. If you only need one
script, put it under `src/` and add a brief `README.md`.

**Key rules for code-type projects:**

1. **`output/` is the ONLY place for backtest results.** Never put results
   in `src/`, `scripts/`, or the project root.
2. **Every backtest run creates a `YYYYMMDD_HHMMSS/` subdirectory.**
   - Timestamp = the moment the backtest was *launched*, not completed.
   - Format: zero-padded, 24h clock. Example: `20260528_153000`.
3. **At minimum, each run directory contains `results.json`** with key
   metrics (sharpe, return, drawdown, etc.) for easy programmatic comparison.
4. **`src/` is for importable modules** (strategy, signal, indicators).
   **`scripts/` is for CLI entry-points** that import from `src/`.

---

## 4b. Output Directory Enforcement (CRITICAL)

**`output/` is the SOLE location for ALL generated results, artifacts, and
backtest outputs.** This rule is absolute and has zero exceptions.

### What MUST go in `output/`:
- Backtest results (equity curves, trade logs, performance metrics)
- Generated reports, charts, and plots
- Model artifacts (trained models, parameter snapshots)
- Any file produced by a script/run (not hand-edited)

### What MUST NOT go in `output/`:
- Source code → `src/`
- Raw or downloaded data → `data/`
- Manual documentation → `docs/`
- CLI entry-points → `scripts/`

### Specifically FORBIDDEN locations for results:
| ❌ Forbidden Location | ✅ Correct Location |
|---|---|
| `data/results/` | `output/<timestamp>/` |
| `data/output/` | `output/<timestamp>/` |
| `src/results/` | `output/<timestamp>/` |
| Project root | `output/<timestamp>/` |
| `scripts/results/` | `output/<timestamp>/` |

### Why this matters:
1. **Data integrity**: `data/` is for INPUT data only. Mixing results
   with raw data creates confusion about what is source vs. derived.
2. **Reproducibility**: Timestamped `output/` subdirectories enable
   comparing runs across time.
3. **Cleanup**: `output/` can be safely deleted without losing source
   code or raw data.

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
| Results in `data/results/` | `data/` is for INPUT data only | Always in `output/<timestamp>/` |
| `workspace/docs/` | Conflicts with root `docs/` | Doc projects → `workspace/doc-<name>/` |
| Empty directories | Clutter | Only create dirs when writing files |
| Multiple dirs for same task | Fragmentation | Reuse existing project directory |
| Skeleton dirs for doc-only types | Unnecessary clutter (data/, output/ for markdown) | Doc-only types: only root dir, no sub-dirs |

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

---

## 8. Auto-Cleanup: Removing Unused Directories

The project manager provides `list_unused_dirs(base)` to scan a directory
tree and identify **skeleton-only** or **empty** project directories that
can be safely deleted.

### What counts as "unused"

A directory is considered unused (safe to delete) if:
- It is **empty** (no visible files)
- It contains only **`.gitkeep`** and/or **`README.md`** (skeleton files)

### When to run cleanup

- **Session start**: Before creating new projects, scan for stale ones.
- **After project completion**: If a project produced no meaningful output,
  consider it a candidate for cleanup.
- **Periodic housekeeping**: When the user asks to tidy up, or when you
  notice many empty directories in `workspace/`.

### How to clean up

1. Call `list_unused_dirs(workspace_root / "workspace")` to get candidates.
2. Present the list to the user for confirmation.
3. Delete confirmed directories using `find <dir> -type f -delete` then
   `find <dir> -type d -empty -delete`.

### Prevention

- **Doc-only types** (`quant_md_*`, `quant_research`) no longer create
  skeleton sub-directories — this prevents the most common source of empty
  directory litter.
- The project manager logs a warning when creating a doc-only project:
  `"doc-only project, skipping skeleton"`.
