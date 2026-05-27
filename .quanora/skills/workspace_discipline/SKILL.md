---
name: workspace_discipline
description: >
  Project workspace boundary discipline. Activates when the user asks you to
  scaffold, create, organize, or refactor project files. Reminds you that
  every file you write must land inside the workspace, NEVER in Quanora's own
  source tree or arbitrary system paths. Also governs project directory naming
  conventions to prevent duplicate/fragmented directories across sessions.
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
  - "organize files"
  - "重构目录"
---

# Workspace Discipline

You are working on a USER'S PROJECT. Quanora itself is a tool — it is NOT the
project. Three rules:

1. **All writes land inside the workspace.** The runtime resolves relative paths
   against the workspace root, not your CWD. If in doubt, use relative paths.

2. **Never modify Quanora's own code** (unless in self-dev mode and explicitly
   told to). The guard will reject writes to `agent/`, `main.py`, etc.

3. **Never scatter files** into `/tmp`, `$HOME`, or outside the workspace.

---

## Directory Naming Convention

When `find_or_create_project_dir` creates a project subdirectory under
`workspace_root`, it follows a **type-prefixed naming convention** to ensure
that similar projects from different sessions reuse the same directory:

| Project Type | Prefix | Example Directory Name |
|---|---|---|
| WorldQuant Brain alpha mining | `wq-` | `wq-alpha-momentum`, `wq-alpha-reversal` |
| Quantitative research | `quant-` | `quant-strategy-backtest`, `quant-factor-analysis` |
| Data pipeline | `data-` | `data-market-etl`, `data-cleaning` |
| Web application | `web-` | `web-dashboard`, `web-api-server` |
| General / other | `proj-` | `proj-my-experiment`, `proj-docs` |

### How it works

1. **Type detection**: The system scans the task description for keywords
   (e.g., "WorldQuant", "WQ", "alpha", "量化", "回测") and assigns a type.
2. **Slug generation**: The project name is slugified (lowercase, hyphens, ASCII).
3. **Prefix application**: The type prefix is prepended: `wq-alpha-mining`.
4. **Fuzzy matching**: Before creating a new directory, existing directories
   are checked using a composite score:
   - Levenshtein similarity (40% weight)
   - Semantic-normalized Levenshtein (30% — maps synonyms like "WQ" → "worldquant")
   - Keyword overlap / Jaccard (30%)
   - Same-type-prefix bonus (+0.1)
   - Threshold ≥ 0.6 → reuse existing directory

### What this means for you

- **Don't create ad-hoc directories.** Always use `find_or_create_project_dir`
  (called automatically by the session manager) to get the project directory.
- **If you see two directories like `alpha-research` and `wq-alpha-research`**
  in the same workspace, the latter is the canonical one (type-prefixed).
- **Chinese descriptions work**: "量化策略回测" → `quant-quant-ce-lve-hui-ce`
  (Chinese chars are stripped to ASCII; the prefix carries the meaning).
- **Sessions with similar tasks will reuse the same directory**, preventing
  directory sprawl.

---

## Standard project layout

Inside a project directory, follow this layout:

```
<workspace>/<project-slug>/
├── src/             # Source code
├── tests/           # Tests
├── scripts/         # Scripts (backtest, data download, etc.)
├── data/            # Generated / downloaded data (gitignored)
├── artifacts/       # Reports, figures, exports
├── docs/            # Documentation
├── results/         # Simulation results, logs
└── README.md        # Project overview
```

**Never** put files directly in the workspace root.

## Quick decision table

| User says | Where does the file go? |
|---|---|
| "create a quant strategy called momentum_50" | `<workspace>/quant-momentum-50/strategy/...` |
| "WQ alpha research on reversal" | `<workspace>/wq-alpha-reversal/...` |
| "add a backtest script" | `<workspace>/<existing-project>/scripts/backtest.py` |
| "show me the data fields" | NO write — just `read_file` / `wq_list_data_fields` |
| "fix the bug in agent/foo.py" | STOP — that's Quanora's own code, ask user |
| "save the simulation result" | `<workspace>/<project>/results/<timestamp>.json` |
| "make me a quick utility script" | `<workspace>/scripts/<name>.py` (NOT workspace root) |

## What "inside the workspace" means concretely

- `path = "foo/bar.py"` (relative) → `<workspace>/foo/bar.py` ✅
- `path = "<workspace>/foo/bar.py"` (absolute under workspace) → ✅
- `path = "/tmp/foo.py"` → ❌ outside
- `path = "/home/user/webapp/agent/foo.py"` → ❌ protected (Quanora code)
- `path = "../foo.py"` (escapes via `..`) → ❌ outside (resolved by guard)
