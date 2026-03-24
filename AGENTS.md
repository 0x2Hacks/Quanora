# Repository Guidelines

## Project Structure & Module Organization
- Entry point: `main.py` (CLI startup, session options, debug mode).
- Core agent logic: `agent/` (`basic_agent.py`, `prompts.py`).
- Tooling layer: `tools/` (`file_ops.py`, `bash.py`, `web.py`, `schemas.py`, `base.py`).
- Configuration: `config/settings.py` (OpenAI client and env-driven settings).
- Session persistence: `session/` (manager) and `sessions/` (runtime data, JSON/JSONL).
- Tests: `test/` (current scripted tool tests) plus top-level `test_web.py`.
- Utility assets: `utils/` (`logo.py`, `logo.txt`).
- Planning/design notes: `plan/`.

## Build, Test, and Development Commands
- `python main.py`  
  Run the interactive agent CLI.
- `python main.py --debug`  
  Run in non-streaming debug mode with verbose tool output.
- `python main.py -c`  
  Resume the latest persisted session.
- `python test/test_bash_tool.py`  
  Execute bash tool regression checks.
- `python -m compileall -q .`  
  Quick syntax validation across the repository.

## Coding Style & Naming Conventions
- Language: Python 3.12+ style with 4-space indentation and UTF-8 files.
- Use `snake_case` for functions/variables, `PascalCase` for classes, `UPPER_SNAKE_CASE` for constants.
- Keep tool outputs structured via `tool_ok` / `tool_error` patterns.
- Prefer small, focused functions; keep side effects explicit (especially in `tools/` and `session/`).
- Code design must prioritize **high cohesion, low coupling, clear structure, and readability**.
- Keep single Python files compact: target **<= 400 lines**; hard limit **<= 800 lines**. If a file grows, split by responsibility.

## Testing Guidelines
- Add tests under `test/` using `test_*.py` naming.
- Mirror module names where possible (example: `tools/bash.py` -> `test/test_bash_tool.py`).
- For new tools/features, include:
  - success path,
  - failure path,
  - one edge case (timeouts, invalid args, large input, etc.).

## Commit & Pull Request Guidelines
- Follow observed commit style: `feat:`, `fix:`, `refactor:`, optionally scoped (`feat(session): ...`).
- Write imperative, concise subjects (<=72 chars preferred).
- PRs should include:
  - clear summary of behavior change,
  - affected paths/modules,
  - test evidence (commands + results),
  - notes on config/env changes (if any).

## Security & Configuration Tips
- Keep secrets in `.env`; never commit real keys.
- Required env: `OPENAI_API_KEY`; optional: `OPENAI_API_BASE`, model/tuning settings.
- Treat `sessions/` as runtime artifacts; review before sharing logs/tool outputs externally.

## Agent Prompt Suggestions
- Refactor prompt:  
  `Refactor <path> with high cohesion and low coupling. Propose a module split plan first, then implement it; keep each file <=400 lines where possible.`
- Feature prompt:  
  `Add <feature> to <module> without breaking existing interfaces, and include tests for failure paths and boundary cases.`
- Reliability prompt:  
  `Review exception handling and timeout behavior in <module>, list risks, and directly fix all P0 issues.`
- Architecture prompt:  
  `Based on the current directory layout, propose a three-layer architecture optimization (CLI/Agent/Tools) and provide minimal, practical code changes.`
- Review prompt:  
  `Perform a severity-based code review: list defects and regression risks first, then provide patches and verification commands.`
