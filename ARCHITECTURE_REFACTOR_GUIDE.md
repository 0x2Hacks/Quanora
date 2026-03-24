# Architecture Refactor Guide

This document explains the completed architecture reorganization of the agent project.

## 1. Refactor Goal

The previous implementation concentrated CLI interaction, model calls, tool execution, and session persistence inside `agent/basic_agent.py`.  
That made iteration slower and increased coupling between user interface and business logic.

The refactor introduces a layered design to improve:

- high cohesion (each module has one clear responsibility),
- low coupling (layers depend in one direction),
- clearer extension paths (especially API/service integration),
- testability (runtime/tool logic can be tested without CLI).

## 2. New Layered Structure

The project now uses four logical layers under `agent/`:

```text
agent/
  basic_agent.py                  # Backward-compatible facade (entry composition)
  prompts.py                      # System prompt

  domain/
    tool_payload.py               # Tool-call parsing + payload recognition rules

  application/
    tool_executor.py              # Safe tool execution and standardized error handling
    runtime.py                    # Conversation orchestration loop (LLM + tools + session)

  infrastructure/
    llm/openai_chat_client.py     # OpenAI adapter
    tools/registry.py             # Tool registry adapter over tools.TOOLS / TOOL_SCHEMAS

  interfaces/
    cli/chat_cli.py               # Terminal interaction flow
    api/service.py                # Transport-agnostic API facade (ready for web framework)
```

## 3. Responsibility Boundaries

### Domain Layer

- `agent/domain/tool_payload.py`
- Provides core parsing/validation primitives:
  - `ParsedToolCall` (normalized tool call shape),
  - `parse_tool_args(...)` (JSON args parsing),
  - `looks_like_tool_payload(...)` (standard tool payload detection).
- No OpenAI, no CLI, no filesystem persistence logic.

### Application Layer

- `ToolExecutor` is the safe execution service:
  - checks tool existence,
  - wraps exceptions as structured `tool_error(...)`,
  - normalizes non-standard results via `tool_ok(...)`.
- `AgentRuntime` is the orchestration core:
  - runs chat completion loops (streaming and non-streaming),
  - consumes tool calls,
  - executes tools through `ToolExecutor`,
  - persists messages/tool records via session manager interface.

### Infrastructure Layer

- `OpenAIChatClient`: adapter for `chat.completions.create(...)`.
- `DefaultToolRegistry`: adapter for existing `tools.TOOLS` and `tools.TOOL_SCHEMAS`.
- Keeps third-party/external dependency details out of application logic.

### Interface Layer

- `ChatCLI`: only handles terminal UX and delegates behavior to `AgentRuntime`.
- `AgentAPIService`: API-facing service facade with `chat(query)`; web transport can be added without changing runtime logic.

## 4. BasicAgent After Refactor

`agent/basic_agent.py` is now a **thin composition root**:

1. Initializes `Config` dependencies.
2. Wires infrastructure adapters.
3. Wires application services.
4. Wires interface adapters (CLI + API facade).
5. Keeps legacy methods:
   - `run(query)` for one-shot request,
   - `chat()` for interactive CLI.

This keeps compatibility while removing the old god-class behavior.

## 5. Current Runtime Flow (CLI)

1. `main.py` creates `BasicAgent`.
2. `BasicAgent.chat()` delegates to `ChatCLI.start()`.
3. `ChatCLI` handles user input/output and session lifecycle bootstrap.
4. For each user turn, `ChatCLI` calls `AgentRuntime.process_user_turn(...)`.
5. `AgentRuntime` calls model adapter, parses tool calls, executes via `ToolExecutor`, persists results.
6. Control returns to CLI for next turn.

## 6. Compatibility and Validation

The following were verified after refactor:

- Python compilation success: `python -m compileall -q .`
- Core import path works: `from agent.basic_agent import BasicAgent`
- Root export import works after root package export fix.

## 7. Next Recommended Steps

Now that architecture is separated, the safest next work items are:

1. Add unit tests for `AgentRuntime` and `ToolExecutor` with mocked adapters.
2. Add real HTTP transport (FastAPI/Flask) on top of `AgentAPIService`.
3. Introduce structured logging and trace IDs in `application/runtime.py`.
4. Add token budget/context compaction strategy in application layer.

This sequence uses the new boundaries without re-coupling layers.
