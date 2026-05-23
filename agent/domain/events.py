"""Runtime event definitions for conversation and tool execution."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from typing import Any, Literal


# ── Token / time usage tracking (Feature 1) ─────────────────────────────────

@dataclass(slots=True)
class LLMUsageRecord:
    """Token usage for a single LLM API call within a turn.

    Captured from the OpenAI stream's final chunk (usage field) or
    the non-streaming response's usage object.
    """
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    latency_seconds: float = 0.0          # wall time from request → last chunk
    model: str = ""


@dataclass(slots=True)
class ToolCallUsageRecord:
    """Time cost for a single tool call execution within a turn."""
    tool_name: str = ""
    call_id: str = ""
    wall_seconds: float = 0.0             # execution duration
    input_chars: int = 0                  # approximate input size
    output_chars: int = 0                 # approximate output size


@dataclass(slots=True)
class TurnCostReport:
    """Aggregated cost report attached to TurnCompletedEvent.

    Provides a detailed breakdown of all resource consumption within a
    single user turn, enabling per-turn analysis and cross-session stats.
    """
    llm_calls: list[LLMUsageRecord] = field(default_factory=list)
    tool_calls: list[ToolCallUsageRecord] = field(default_factory=list)
    total_prompt_tokens: int = 0
    total_completion_tokens: int = 0
    total_tokens: int = 0
    total_llm_latency_seconds: float = 0.0
    total_tool_wall_seconds: float = 0.0
    turn_wall_seconds: float = 0.0        # from turn_started → turn_completed
    num_llm_calls: int = 0
    num_tool_calls: int = 0

    def summarize(self) -> dict[str, Any]:
        """Return a flat summary dict suitable for CLI rendering."""
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_llm_latency_s": round(self.total_llm_latency_seconds, 2),
            "total_tool_wall_s": round(self.total_tool_wall_seconds, 2),
            "turn_wall_s": round(self.turn_wall_seconds, 2),
            "num_llm_calls": self.num_llm_calls,
            "num_tool_calls": self.num_tool_calls,
            "llm_details": [
                {
                    "model": r.model,
                    "prompt": r.prompt_tokens,
                    "completion": r.completion_tokens,
                    "total": r.total_tokens,
                    "latency_s": round(r.latency_seconds, 2),
                }
                for r in self.llm_calls
            ],
            "tool_details": [
                {
                    "tool": r.tool_name,
                    "wall_s": round(r.wall_seconds, 2),
                    "input_chars": r.input_chars,
                    "output_chars": r.output_chars,
                }
                for r in self.tool_calls
            ],
        }

    def accumulate_llm(self, record: LLMUsageRecord) -> None:
        """Add an LLM call record and update totals."""
        self.llm_calls.append(record)
        self.total_prompt_tokens += record.prompt_tokens
        self.total_completion_tokens += record.completion_tokens
        self.total_tokens += record.total_tokens
        self.total_llm_latency_seconds += record.latency_seconds
        self.num_llm_calls += 1

    def accumulate_tool(self, record: ToolCallUsageRecord) -> None:
        """Add a tool call record and update totals."""
        self.tool_calls.append(record)
        self.total_tool_wall_seconds += record.wall_seconds
        self.num_tool_calls += 1


@dataclass(slots=True)
class RuntimeEvent:
    """Base class for all runtime events."""
    type: str
    ts: str = field(default_factory=lambda: str(time.time()))

    def to_dict(self) -> dict[str, Any]:
        """Serialize event to a dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeEvent:
        """Deserialize a dictionary to a RuntimeEvent instance."""
        event_type = data.get("type")
        
        # We need to dispatch to the correct subclass
        for subclass in cls.__subclasses__():
            # Get the default value of 'type' field from the subclass
            if hasattr(subclass, "__dataclass_fields__") and "type" in subclass.__dataclass_fields__:
                type_field = subclass.__dataclass_fields__["type"]
                if type_field.default == event_type:
                    # Filter data to only include valid fields for this subclass
                    valid_keys = {f.name for f in subclass.__dataclass_fields__.values()}
                    filtered_data = {k: v for k, v in data.items() if k in valid_keys}
                    return subclass(**filtered_data)
                    
        # Fallback to base class if no match
        valid_keys = {f.name for f in cls.__dataclass_fields__.values()}
        filtered_data = {k: v for k, v in data.items() if k in valid_keys}
        return cls(**filtered_data)


@dataclass(slots=True)
class AssistantDeltaEvent(RuntimeEvent):
    """Fired when a new chunk of text is received from the assistant."""
    type: Literal["assistant_delta"] = "assistant_delta"
    text: str = ""


@dataclass(slots=True)
class AssistantMessageCompletedEvent(RuntimeEvent):
    """Fired when the assistant finishes generating a message."""
    type: Literal["assistant_message_completed"] = "assistant_message_completed"
    content: str = ""


@dataclass(slots=True)
class ToolCallStartedEvent(RuntimeEvent):
    """Fired when a tool execution is about to begin.

    `args_preview` is a short, human-readable summary of the tool's arguments
    (e.g. for bash it's the command string; for read_file it's the path).
    Computed by the runtime via render_args_preview() so the CLI can show a
    framework-level "what is the agent about to do" panel without trusting
    the model to narrate it.
    """
    type: Literal["tool_call_started"] = "tool_call_started"
    tool_call_id: str = ""
    tool_name: str = ""
    args_preview: str = ""


@dataclass(slots=True)
class ToolProgressEvent(RuntimeEvent):
    """Fired when a tool produces incremental progress (e.g. streaming stdout)."""
    type: Literal["tool_progress"] = "tool_progress"
    tool_call_id: str = ""
    tool_name: str = ""
    payload: dict[str, Any] | None = None


@dataclass(slots=True)
class ToolResultEvent(RuntimeEvent):
    """Fired when a tool execution completes and returns a result.

    `status` is "ok" | "error" parsed from the standardized tool_ok/tool_error
    payload. `summary` is a short human-readable line for the CLI panel
    (e.g. "3 files listed" / "Error: file not found"). `duration_ms` is the
    wall-clock execution time. These fields are framework-computed.
    """
    type: Literal["tool_result"] = "tool_result"
    tool_call_id: str = ""
    tool_name: str = ""
    result: str = ""
    status: Literal["ok", "error", "unknown"] = "unknown"
    summary: str = ""
    duration_ms: int = 0


@dataclass(slots=True)
class TurnStartedEvent(RuntimeEvent):
    """Fired at the very beginning of a turn so the CLI can show 'thinking'.

    The CLI uses this to render an early progress indicator before the first
    assistant delta arrives — addressing the perceived 'frozen' silent gap
    while the model is reasoning.
    """
    type: Literal["turn_started"] = "turn_started"
    user_input_preview: str = ""


@dataclass(slots=True)
class ToolBatchStartedEvent(RuntimeEvent):
    """Fired when the runtime is about to execute a batch of N tool calls."""
    type: Literal["tool_batch_started"] = "tool_batch_started"
    count: int = 0
    tool_names: list[str] = field(default_factory=list)


@dataclass(slots=True)
class PlanSnapshotEvent(RuntimeEvent):
    """Fired after a plan_* tool succeeds with a compact snapshot for the CLI panel.

    This lets the CLI render a live progress panel (todo / done / blocked / current focus)
    as a framework-level UX guarantee. Parsed by the runtime from the plan tool's
    JSON result; the agent does not need to narrate plan state in chat.
    """
    type: Literal["plan_snapshot"] = "plan_snapshot"
    title: str = ""
    goal: str = ""
    total_steps: int = 0
    completed_steps: int = 0
    in_progress_steps: int = 0
    blocked_steps: int = 0
    current_focus: str = ""
    version: int = 0


@dataclass(slots=True)
class WorkspaceViolationEvent(RuntimeEvent):
    """Fired when the framework rejects a write that escapes the project workspace
    or targets the agent's own protected source code.

    This is a **framework-level guarantee**: the violation is enforced by the
    write tools themselves (they call WorkspaceGuard.check_write before any
    disk I/O) and the rejection is broadcast to the CLI so the user can see
    that the agent tried to write somewhere it should not, even if the agent
    later glosses over the error in its narration.
    """
    type: Literal["workspace_violation"] = "workspace_violation"
    tool_name: str = ""
    path: str = ""
    status: Literal["outside", "protected"] = "outside"
    reason: str = ""
    suggested_fix: str = ""


@dataclass(slots=True)
class DataIntegrityWarningEvent(RuntimeEvent):
    """Fired when a tool result looks like a data-source failure that the
    agent must report rather than fabricate.

    Emitted as a framework-level safety signal so the user sees the issue
    explicitly, and so logs/replay can flag fabrication risk.
    """
    type: Literal["data_integrity_warning"] = "data_integrity_warning"
    tool_name: str = ""
    reason: str = ""
    suggested_action: str = ""


@dataclass(slots=True)
class SkillActivatedEvent(RuntimeEvent):
    """Fired when a skill is selected and injected into the model context."""
    type: Literal["skill_activated"] = "skill_activated"
    skill_name: str = ""
    reason: str = ""
    score: int = 0
    source: str = ""
    path: str = ""


@dataclass(slots=True)
class TurnCompletedEvent(RuntimeEvent):
    """Fired when an entire turn (including all tool executions and LLM generation) completes successfully."""
    type: Literal["turn_completed"] = "turn_completed"
    cost_report: TurnCostReport = field(default_factory=TurnCostReport)


@dataclass(slots=True)
class TurnFailedEvent(RuntimeEvent):
    """Fired when a turn fails due to an error."""
    type: Literal["turn_failed"] = "turn_failed"
    error: str = ""
    error_type: str = ""
    cost_report: TurnCostReport | None = None   # partial report up to failure


@dataclass(slots=True)
class TurnCancelledEvent(RuntimeEvent):
    """Fired when a turn is cancelled (e.g. via CancellationToken)."""
    type: Literal["turn_cancelled"] = "turn_cancelled"
    reason: str = ""
    cost_report: TurnCostReport | None = None   # partial report up to cancel
