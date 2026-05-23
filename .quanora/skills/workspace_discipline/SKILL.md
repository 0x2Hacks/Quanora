---
name: workspace_discipline
description: >
  Project workspace boundary discipline. Activates when the user asks you to
  scaffold, create, organize, or refactor project files. Reminds you that
  every file you write must land inside the workspace, NEVER in Quanora's own
  source tree or arbitrary system paths.
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

1. **All writes land inside the workspace.** The runtime resolves relative
   paths under `QUANORA_WORKSPACE` (default `<install>/workspace/`). Prefer
   relative paths.
2. **Quanora's own code is PROTECTED** (`agent/`, `test/`, `.quanora/`,
   `scripts/`, `main.py`, `requirements.txt`, `.env*`). The runtime will hard
   reject any write that targets those paths.
3. **A project should be self-contained.** It should be possible to `cp -r
   <workspace>` to a USB drive and have a complete, working project. Nothing
   in `/tmp`, nothing in `$HOME` siblings, nothing in the Quanora repo.

---

## Playbook A — User asks "create a new project for X"

1. Determine the project root. By default: `<workspace>/<project_name>/`.
   Confirm with the user if the workspace already has unrelated content.
2. Establish a conventional layout BEFORE writing code:
   - **Python**: `<project>/<package>/__init__.py`, `<project>/tests/`,
     `<project>/pyproject.toml` (or `requirements.txt`), `<project>/README.md`.
   - **JS/TS**: `<project>/src/`, `<project>/tests/`, `<project>/package.json`,
     `<project>/README.md`, optional `<project>/tsconfig.json`.
   - **Quant strategy**: `<project>/strategy/`, `<project>/data/`,
     `<project>/notebooks/`, `<project>/results/`, `<project>/README.md`.
3. Use `list_files` on the workspace first to see what already exists.
4. Create directories implicitly via `write_file` — `write_file` makes parent
   dirs automatically.
5. Initialise version control (`bash: cd <project> && git init`) only after
   the user confirms — not as a default.

## Playbook B — User asks "add a feature to existing project"

1. `list_files` the workspace to identify the existing project structure.
2. Follow the existing convention (don't introduce a new layout). If the
   project uses `src/`, your new file goes in `src/`. If it uses flat
   modules, follow flat.
3. Put tests next to the project's existing test dir.
4. Never create sibling helper files at the workspace root unless the user
   explicitly asks for "a quick script".

## Playbook C — You hit ⛔ WORKSPACE BOUNDARY VIOLATION

Stop. Read the error's `suggested_fix` meta. Two cases:

- **`status: outside`** — your path escaped the workspace. Rewrite the path
  as relative (or absolute under the workspace root).
- **`status: protected`** — you tried to write into Quanora's own code.
  Stop and tell the user exactly what you tried; ask whether they want to
  modify Quanora itself (which they should do manually) or whether you
  misunderstood and the target should be a project file under the workspace.

DO NOT retry the same path. DO NOT try `bash echo > <protected_path>` as a
workaround — the violation banner is visible to the user.

## Quick decision table

| User says | Where does the file go? |
|---|---|
| "create a quant strategy called momentum_50" | `<workspace>/momentum_50/strategy/...` |
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
