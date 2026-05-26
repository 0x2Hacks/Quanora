# CLI 状态面板与 Tool 生命周期展示计划

## 1. 目标

依据 `.docs/productization-roadmap-cli-events-security-zh.md` 的第 3 步，建设一套轻量、清晰、可扩展的 CLI 状态展示层，让用户能稳定看到：

- 当前 turn 的运行状态。
- context build 的简要状态。
- skill / plan 等运行上下文提示。
- tool 从请求、启动、进度、完成、失败、取消的生命周期。
- turn 结束时的简洁汇总。

本阶段只做 CLI 展示层，不改变 runtime 执行语义、不新增安全确认逻辑、不新增 token 计费逻辑。

## 2. 参考原则

### 2.1 Claude Code 源码参考

从 `src` 中 Claude Code 的实现可以抽象出几条适合当前项目的原则：

- 进度展示应当是运行态信息，而不是对话内容的一部分。
- tool 请求、运行中、排队、完成、失败应分状态渲染。
- 展示层应维护一个轻量状态，而不是每个 event 都直接散落打印。
- 进度信息要克制，避免频繁刷屏。
- 普通模式展示用户关心的信息，debug 模式再展示 id、参数、上下文统计等细节。

### 2.2 Codex 风格参考

Codex 类 CLI Agent 的体验重点通常是：

- 模型回答是主内容，tool / status 是辅助信息。
- tool 状态要短、稳定、可扫读。
- 失败信息要明确，但不要把内部栈或完整参数直接塞进普通输出。
- 长任务中需要持续给出“还在做什么”的信号。

本项目本阶段采用“轻量事件行 + turn 级汇总”的实现，不引入复杂 TUI。

## 3. 设计边界

### 3.1 本阶段做

- 新增 CLI 状态渲染模块，集中处理 runtime events。
- 将 `ChatCLI._on_event` 中的状态打印逻辑迁移为委托调用。
- 维护本 turn 内 tool 状态表。
- 普通模式输出简洁生命周期信息。
- debug 模式输出更多事件细节。
- 增加聚焦测试，覆盖状态转换和输出格式。

### 3.2 本阶段不做

- 不实现 bash confirm / deny 安全策略。
- 不实现 token cost / billing 展示。
- 不实现复杂 Rich Live 面板或全屏 TUI。
- 不持久化 runtime event 日志。
- 不改变 agent runtime、tool executor、context manager 的行为。
- 不改变 tool schema。

## 4. 目标体验

### 4.1 普通模式

普通模式应做到“看得懂当前在做什么，但不刷屏”。

建议输出形态：

```text
Context: 18 messages, ~12.4k input tokens
Skill: poem-writer
Tool: search_web started
Tool: search_web completed in 1.42s
Tool: fetch_web_page failed in 0.88s (FetchError)
Done in 12.6s · tools 3 completed, 1 failed
```

说明：

- 具体文案可在实现时略微调整，但要保持短句和稳定结构。
- 普通模式不展示完整 tool args。
- 普通模式不展示完整 tool result。
- 对同一个 context build，不应因为后续 context rebuild 反复输出相同内容。

### 4.2 Debug 模式

debug 模式展示更多定位信息。

建议输出形态：

```text
[debug] context built: messages=18, estimated_input_tokens=12400
[debug] tool requested: search_web id=call_x args={"query":"..."}
[debug] tool started: search_web id=call_x
[debug] tool completed: search_web id=call_x duration_ms=1420
```

说明：

- debug 模式可以展示截断后的 args preview。
- args preview 必须限制长度，避免污染终端和泄露过多内容。
- result 内容仍不在状态行中展示，继续由 tool result 机制进入上下文。

## 5. 模块设计

新增一个轻量模块组：

```text
agent/interfaces/cli/status/
  __init__.py
  renderer.py
  state.py
```

### 5.1 `state.py`

定义展示层状态数据，不依赖 runtime 内部实现。

建议结构：

```python
@dataclass
class ToolDisplayState:
    tool_call_id: str
    name: str
    status: str
    args_preview: str | None = None
    started_at: float | None = None
    duration_ms: int | None = None
    error_type: str | None = None


@dataclass
class TurnDisplayState:
    turn_id: str | None = None
    tools: dict[str, ToolDisplayState] = field(default_factory=dict)
    context_signature: str | None = None
    activated_skills: set[str] = field(default_factory=set)
```

要求：

- 只保存 CLI 展示需要的最小信息。
- 不保存 tool result 内容。
- 不保存完整 context。

### 5.2 `renderer.py`

定义 `CliStatusRenderer`，负责接收 event 并输出。

建议接口：

```python
class CliStatusRenderer:
    def __init__(self, console: Console, debug: bool = False) -> None: ...
    def handle(self, event: AgentEvent) -> None: ...
```

内部按 event 类型分发：

- `TurnStartedEvent`
- `ContextBuiltEvent`
- `SkillActivatedEvent`
- `ToolRequestedEvent`
- `ToolCallStartedEvent`
- `ToolProgressEvent`
- `ToolResultEvent`
- `TurnCompletedEvent`
- `TurnFailedEvent`
- `TurnCancelledEvent`

要求：

- `ChatCLI` 不再直接拼接 tool 生命周期文案。
- 所有状态文案集中在 renderer 中。
- renderer 只关心展示，不调用业务逻辑。

## 6. Event 渲染规则

### 6.1 `TurnStartedEvent`

普通模式：

- 默认不输出，避免每轮都多一行噪音。

debug 模式：

- 输出 turn id、session id 等可用字段。

### 6.2 `ContextBuiltEvent`

普通模式：

- 每 turn 最多输出一次 context 简要信息。
- 如果没有 token 估算，可以只输出 message count。
- 如果 context 信息与上一次完全一致，不重复输出。

debug 模式：

- 每次 context build 都输出。
- 输出 message count、estimated input tokens、active skills count 等已有字段。

### 6.3 `SkillActivatedEvent`

普通模式：

- 同一个 turn 内同一个 skill 只输出一次。
- 输出 skill name 和 reason。

debug 模式：

- 可附带 event id / reason 等字段。

### 6.4 `ToolRequestedEvent`

普通模式：

- 默认不输出，避免 requested 和 started 连续刷两行。

debug 模式：

- 输出 tool name、tool_call_id、截断后的 args preview。

### 6.5 `ToolCallStartedEvent`

普通模式：

- 输出一行 tool started。

debug 模式：

- 输出 tool name、tool_call_id。

### 6.6 `ToolProgressEvent`

普通模式：

- 如果已有明确 progress message，按 tool id 做去重。
- 相同 progress 不重复输出。
- 高频 progress 可以只展示最近一条。

debug 模式：

- 输出 progress message 和 tool_call_id。

### 6.7 `ToolResultEvent`

普通模式：

- completed：输出 tool completed 和 duration。
- failed：输出 tool failed、duration、error type。
- 不输出完整 error traceback。

debug 模式：

- 可输出 tool_call_id、duration_ms、error type、截断后的 error message。

### 6.8 `TurnCompletedEvent`

普通模式：

- 如果本 turn 使用过 tool，输出一行汇总。
- 如果没有 tool，可不输出，避免打断纯文本问答。

debug 模式：

- 总是输出 turn duration 和 tool 状态计数。

### 6.9 `TurnFailedEvent` / `TurnCancelledEvent`

普通模式：

- 输出明确错误或取消信息。
- 保持现有 `[Error] Turn failed: ...` 这类清晰格式。

debug 模式：

- 可附带 event id、turn id、error type。

## 7. 与 `ChatCLI` 的集成

### 7.1 当前问题

目前 `ChatCLI._on_event` 中直接处理多类 event：

- assistant delta / completed
- context built
- skill activated
- tool requested / started / result
- turn failed / cancelled

这会导致：

- 展示逻辑散落。
- 后续加状态面板、debug 细节、去重逻辑时容易变长。
- 不利于测试。

### 7.2 修改方式

保留 `ChatCLI` 对 assistant streaming 的处理，把非 assistant 文本状态委托给 `CliStatusRenderer`。

建议结构：

```python
def _on_event(self, event: AgentEvent) -> None:
    if isinstance(event, AssistantDeltaEvent):
        self._streaming_renderer.append(event.delta)
        return

    if isinstance(event, AssistantMessageCompletedEvent):
        self._streaming_renderer.finish()
        return

    self._status_renderer.handle(event)
```

如当前 streaming renderer 没有 `finish()` 或 flush 能力，则沿用现有方法名，不为此做大改。

### 7.3 输出互不干扰

要求：

- 状态行不要插入到未完成的 assistant 文本中间。
- 在打印 tool/status 行前，必要时先结束或刷新当前 assistant 输出。
- 不改变最终 assistant message 的内容。

## 8. 格式化策略

实现少量私有 helper，放在 `renderer.py` 内即可，不必额外拆文件：

- `_format_duration(duration_ms: int | None) -> str`
- `_truncate(value: str, max_len: int) -> str`
- `_format_args_preview(args: object | str | None, max_len: int) -> str`
- `_tool_counts(state: TurnDisplayState) -> tuple[int, int, int]`

要求：

- 普通模式 args preview 默认不显示。
- debug 模式 args preview 限制在 300-500 字符。
- duration 小于 1000ms 用 `ms`，大于等于 1000ms 用 `s`。
- 文案保持统一，不混用多套前缀。

## 9. 安全与隐私

- 普通模式不要展示完整 shell command、完整 URL query、完整文件内容、完整错误栈。
- debug 模式也必须截断 args / error message。
- 不把 tool result 内容打印到状态行。
- 不新增任何文件日志。
- 不改变现有 session 持久化内容。

## 10. 测试计划

新增：

```text
test/test_cli_status_renderer.py
```

覆盖：

1. `ToolCallStartedEvent` 输出 started 行。
2. `ToolResultEvent(completed)` 输出 completed 和 duration。
3. `ToolResultEvent(failed)` 输出 failed 和 error type。
4. 同一个 `SkillActivatedEvent` 在同一 turn 内不重复输出。
5. `ContextBuiltEvent` 普通模式同签名不重复输出。
6. debug 模式下 `ToolRequestedEvent` 输出截断 args preview。
7. `TurnCompletedEvent` 能输出 tool 计数汇总。
8. 无 tool 的普通 turn completed 不输出多余汇总。

如已有 CLI event 测试，则补充：

```text
test/test_chat_cli_events.py
```

覆盖：

- `ChatCLI._on_event` 对 assistant streaming 仍走原逻辑。
- 非 assistant event 委托给 `CliStatusRenderer`。

## 11. 验证命令

执行：

```bash
python -m compileall -q .
python test/test_cli_status_renderer.py
pytest test/test_cli_status_renderer.py test/test_cli_slash_commands.py -q
```

如果已有 `test/test_chat_cli_events.py`，追加：

```bash
pytest test/test_chat_cli_events.py -q
```

## 12. 实施顺序

1. 新增 `agent/interfaces/cli/status/state.py`。
2. 新增 `agent/interfaces/cli/status/renderer.py`。
3. 新增 `agent/interfaces/cli/status/__init__.py`。
4. 修改 `ChatCLI`，初始化 `CliStatusRenderer`。
5. 将 `_on_event` 中的非 assistant 状态输出迁移到 renderer。
6. 添加 `test/test_cli_status_renderer.py`。
7. 如需要，补充 `ChatCLI` 委托测试。
8. 运行验证命令。
9. 检查普通模式输出是否简洁，debug 模式是否足够排查问题。

## 13. 验收标准

- 普通模式能清楚看到 tool started / completed / failed。
- 普通模式不会重复打印同一 skill activation。
- 普通模式不会因为多次 context build 刷屏。
- debug 模式能看到 tool_call_id 和截断 args。
- 状态展示逻辑集中在 CLI status renderer，不继续散落在 `ChatCLI`。
- 不改变 runtime event 定义和执行流程。
- 不新增复杂 TUI 依赖。
- 代码结构清晰，新增文件小而聚焦。
