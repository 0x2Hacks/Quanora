## Why

The Quanora Agent needed two core capabilities:
1. **Token/Time Consumption Analysis** — Users had no visibility into per-turn LLM token usage, tool execution time, or total cost. Without this, optimizing expensive API calls was impossible.
2. **Experience Knowledge Base Loop** — The agent was learning nothing from past turns. Each session started with zero context about what worked or failed for a given task type. This meant repetitive mistakes and no progressive improvement.

## What Changed

### Feature 1: Token/Time Consumption Analysis

- **`agent/domain/events.py`** — Added `LLMUsageRecord`, `ToolCallUsageRecord`, `TurnCostReport` dataclasses with accumulation methods and `summarize()` for flat dict output. `TurnCompletedEvent`, `TurnFailedEvent`, `TurnCancelledEvent` now carry a `TurnCostReport`.
- **`agent/application/runtime/message_stream_parser.py`** — `consume_async_stream` now returns a 3rd element: `LLMUsageRecord` extracted from the OpenAI stream's final chunk `usage` field.
- **`agent/application/runtime/async_turn_runner.py`** — Tracks `turn_start_time`, accumulates LLM and tool call costs into `TurnCostReport`, attaches it to all terminal events.
- **`agent/application/runtime/tool_telemetry.py`** — Added `render_cost_report_text()` pure function for formatted table output.
- **`agent/interfaces/cli/chat_cli.py`** — Renders cost report table at turn end; persists cost data to session store asynchronously.
- **`agent/infrastructure/persistence/turn_cost_repository.py`** — New JSONL-based repository for per-turn cost data.
- **`agent/infrastructure/persistence/async_jsonl_session_store.py`** — Added `persist_turn_cost()` method and `TurnCostRepository` integration.

### Feature 2: Experience Knowledge Base Loop

- **`agent/domain/knowledge_base.py`** — New domain model: `ExperienceRecord` (task type, lessons, pitfalls, suggestions, relevance score) + `ExperienceKnowledgeBase` (CRUD, query-by-task-type, top-k, relevance boosting).
- **`agent/infrastructure/persistence/knowledge_base_repository.py`** — JSON file repository for `ExperienceKnowledgeBase` (atomic write via temp+rename).
- **`agent/application/services/experience_distillation_service.py`** — Distills experience from completed turns into KB records. `distill_from_turn()` for manual use, `distill_auto()` for event-driven auto-distillation.
- **`agent/application/services/context_manager.py`** — Injects top-k KB experience records into LLM system prompt alongside skill instructions. Boosts relevance of used records.
- **`agent/interfaces/cli/chat_cli.py`** — Shows "💡 基于历史经验分析" hint at turn start and "📚 经验沉淀" summary at turn end.

## Tests

- `test/test_usage_model.py` — 25 tests: LLMUsageRecord, ToolCallUsageRecord, TurnCostReport accumulation, summarize, events with cost_report
- `test/test_kb_model.py` — 22 tests: ExperienceRecord CRUD, KB add/get/update/remove, query-by-task-type, top-k, boost, repo save/load roundtrip, corrupted file handling
- `test/test_cli_report.py` — 15 tests: Cost report rendering, distillation helpers, full inject→distill→query integration loop

Full suite: **229 passed, 28 skipped** (all existing tests still pass)

## Files

**Created:**
- `agent/domain/knowledge_base.py`
- `agent/infrastructure/persistence/knowledge_base_repository.py`
- `agent/infrastructure/persistence/turn_cost_repository.py`
- `agent/application/services/experience_distillation_service.py`
- `test/test_usage_model.py`
- `test/test_kb_model.py`
- `test/test_cli_report.py`

**Modified:**
- `agent/domain/events.py`
- `agent/application/runtime/message_stream_parser.py`
- `agent/application/runtime/async_turn_runner.py`
- `agent/application/runtime/tool_telemetry.py`
- `agent/application/services/context_manager.py`
- `agent/infrastructure/persistence/async_jsonl_session_store.py`
- `agent/interfaces/cli/chat_cli.py`