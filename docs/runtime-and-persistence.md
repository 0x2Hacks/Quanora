# Runtime And Persistence Streams

ChainPeer separates live progress transport from persisted session truth. New
features should choose the stream that matches the responsibility instead of
adding overlapping side logs.

## Live Runtime Events

`RuntimeEvent` objects are emitted during an active turn by the runtime and tool
pipeline. They drive CLI status rendering and API server-sent events. They are
serializable for transport, but they are not persisted as a replayable event log
and should not be treated as long-term session truth.

## Append-Only Session Records

`AsyncJsonlSessionStore` persists model reconstruction state:

- `messages.jsonl` for user, assistant, system, tool, and compact-boundary
  messages.
- `tool_calls.jsonl` for tool execution records and model-facing tool content.
- `compactions.jsonl` for compact handoff records created by
  `CompactionService`.
- `meta.json` for session metadata, counts, model selection, and compact-window
  bookkeeping.

Resume and context projection should use these records, not live
`RuntimeEvent` history.

## Plan Events

`plan_events.jsonl` records plan control-state changes only. It exists to audit
plan mutations and rebuild plan control state, not to store model-written
observations, summaries, or factual conclusions as long-term truth.
