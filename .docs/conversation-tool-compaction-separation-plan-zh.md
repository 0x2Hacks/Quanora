# 对话压缩与 Tool 压缩职责分离修复方案

> 目标：修复当前 `ContextManager` 中 conversation hot zone 被 tool messages 挤占的问题。保证“会话压缩只管会话，tool 压缩只管 tool”，避免同一 turn 内用户问题被 tool 调用链挤出热区并被 summary 替换。

## 背景问题

当前 context build 流程中，tool 输出冷热压缩和 conversation 冷区摘要本来是两套策略：

- tool 输出由 `ToolContextPolicy` 按 tool batch 做 hot/warm/cold 降级。
- conversation 冷区摘要只应该处理普通 `user` / 普通 `assistant` 文本。

但当前实现里，conversation hot zone 的计算使用：

```python
non_system_indices = [
    index
    for index, message in enumerate(messages)
    if message.get("role") != "system"
]
return set(non_system_indices[-self._hot_message_limit:])
```

这会把以下消息都计入 conversation 热区：

- `user`
- 普通 `assistant`
- `assistant` with `tool_calls`
- `tool`

同时，conversation summary 的可摘要判断又排除了 tool 相关消息：

```python
if message.get("role") not in {"user", "assistant"}:
    return False
if message.get("tool_calls"):
    return False
```

于是出现不一致：

```text
tool messages 会占用 conversation hot zone 名额
但 tool messages 不会被 conversation summary 摘要
```

在同一 turn 内多轮 tool call 时，当前用户问题可能被大量 tool messages 挤出 hot zone，进而被 conversation summary 替换。最终发送给模型的尾部可能变成：

```text
Conversation summary: 包含本轮用户问题
assistant tool_calls: search_web x3
tool: search result
tool: search result
tool: search result
assistant tool_calls: fetch_web_page x3
tool: page result
tool: page result
tool: page result
```

某些 OpenAI-compatible 模型服务会认为这类 messages 结构非法，尤其是当前 turn 的原始 `user` 消息不在 tool-call 链条附近时。

## 设计原则

1. **conversation hot zone 只看 conversation 消息**
   - 包含普通 `user`
   - 包含普通文本 `assistant`
   - 不包含 `tool`
   - 不包含 `assistant` with `tool_calls`

2. **conversation summary 只摘要 conversation 消息**
   - 与 hot zone 使用同一套“conversation message”判断。
   - 避免 hot zone 和 cold zone 的分类标准不一致。

3. **tool messages 完全交给 tool policy**
   - tool 输出继续由 `ToolContextPolicy` 做 hot/warm/cold。
   - tool batch 分类不受 conversation hot zone 影响。

4. **保持改动小**
   - 不新增工具。
   - 不重构持久化格式。
   - 不修改 tool output 降级策略。
   - 不引入复杂 turn state。

## 最小实现方案

### 1. 在 `ContextManager` 中抽出 conversation message 判断

文件：

```text
agent/application/services/context_manager.py
```

新增一个私有方法：

```python
def _is_conversation_message(self, message: dict) -> bool:
    if message.get("role") not in {"user", "assistant"}:
        return False
    if message.get("tool_calls"):
        return False
    content = message.get("content", "")
    return isinstance(content, str) and bool(content.strip())
```

这个方法表示：

```text
可参与 conversation hot/cold 判断的普通对话消息
```

### 2. 修改 `_hot_message_indices`

将当前实现：

```python
def _hot_message_indices(self, messages: list[dict]) -> set[int]:
    non_system_indices = [index for index, message in enumerate(messages) if message.get("role") != "system"]
    return set(non_system_indices[-self._hot_message_limit :])
```

改为：

```python
def _hot_message_indices(self, messages: list[dict]) -> set[int]:
    conversation_indices = [
        index
        for index, message in enumerate(messages)
        if self._is_conversation_message(message)
    ]
    return set(conversation_indices[-self._hot_message_limit :])
```

效果：

- `tool` 不再占用 conversation hot zone。
- `assistant tool_calls` 不再占用 conversation hot zone。
- 最近 N 条普通 conversation 消息被稳定保护。

### 3. 复用 `_is_conversation_message` 简化 `_is_summarizable_cold_message`

将：

```python
def _is_summarizable_cold_message(self, message: dict) -> bool:
    if message.get("role") not in {"user", "assistant"}:
        return False
    if message.get("tool_calls"):
        return False
    content = message.get("content", "")
    return isinstance(content, str) and bool(content.strip())
```

改为：

```python
def _is_summarizable_cold_message(self, message: dict) -> bool:
    return self._is_conversation_message(message)
```

这样 hot zone 和 summary cold zone 使用同一标准，避免再次漂移。

### 4. 修正 `hot_message_count` 统计

当前统计：

```python
hot_message_count = min(
    self._hot_message_limit,
    len([message for message in full_messages if message.get("role") != "system"]),
)
```

应改为：

```python
hot_message_count = min(
    self._hot_message_limit,
    len([message for message in full_messages if self._is_conversation_message(message)]),
)
```

这样 stats 中的 `hot_message_count` 与真实 conversation hot zone 一致。

## 需要保持不变的行为

以下行为不应改变：

- `ToolContextPolicy.classify_temperatures()` 仍按 assistant `tool_calls` batch 分类。
- tool message 内容仍通过 `_apply_tool_context_policy_async()` 渲染。
- conversation summary 仍渲染为一条 assistant message。
- `summary_step_threshold` 复用逻辑不变。
- `hot_message_limit` 参数名不变，但语义变为“最近 N 条 conversation messages”。
- `rescue_context()` 暂不改，仍作为 hard limit 兜底。

## 测试计划

### 1. 新增回归测试：tool messages 不挤占 conversation hot zone

建议文件：

```text
test/test_context_manager.py
```

新增测试名：

```python
test_context_manager_conversation_hot_zone_ignores_tool_messages
```

测试构造：

```python
session_messages = [
    {"role": "system", "content": "sys"},
]

# 构造足够多的旧 conversation，使 conversation budget 触发 summary。
for index in range(1, 5):
    session_messages.append({"role": "user", "content": f"old user {index} " + "x" * 80})
    session_messages.append({"role": "assistant", "content": f"old assistant {index} " + "y" * 80})

current_question = "current user question should stay hot"
session_messages.append({"role": "user", "content": current_question})
session_messages.append({
    "role": "assistant",
    "tool_calls": [
        {"id": "call_1", "type": "function", "function": {"name": "search_web", "arguments": "{}"}},
        {"id": "call_2", "type": "function", "function": {"name": "search_web", "arguments": "{}"}},
        {"id": "call_3", "type": "function", "function": {"name": "search_web", "arguments": "{}"}},
    ],
})
session_messages.extend([
    {"role": "tool", "tool_call_id": "call_1", "content": "placeholder"},
    {"role": "tool", "tool_call_id": "call_2", "content": "placeholder"},
    {"role": "tool", "tool_call_id": "call_3", "content": "placeholder"},
])
session_messages.append({
    "role": "assistant",
    "tool_calls": [
        {"id": "call_4", "type": "function", "function": {"name": "fetch_web_page", "arguments": "{}"}},
        {"id": "call_5", "type": "function", "function": {"name": "fetch_web_page", "arguments": "{}"}},
        {"id": "call_6", "type": "function", "function": {"name": "fetch_web_page", "arguments": "{}"}},
    ],
})
session_messages.extend([
    {"role": "tool", "tool_call_id": "call_4", "content": "placeholder"},
    {"role": "tool", "tool_call_id": "call_5", "content": "placeholder"},
    {"role": "tool", "tool_call_id": "call_6", "content": "placeholder"},
])
```

为 fake session 填入对应 `tool_records`。

ContextManager 设置：

```python
manager = ContextManager(
    estimator=ContextEstimator(
        ContextBudget(
            hard_limit_tokens=4000,
            conversation_budget_tokens=20,
            tool_budget_tokens=1200,
        )
    ),
    hot_message_limit=2,
)
```

断言：

```python
result = await manager.build_messages_async(session=session)

assert result.decisions["rolling_summary_applied"] is True
assert any(
    message.get("role") == "user" and message.get("content") == current_question
    for message in result.messages
)
assert result.messages[-1]["role"] == "tool"
```

关键断言是：

```text
即使尾部有 6 条 tool 相关 messages，current_question 仍保留原文。
```

这正是修复目标。

### 2. 更新或检查已有测试

运行：

```powershell
python -m pytest test\test_context_manager.py -q
python -m pytest test\test_context_manager.py test\test_context_manager_plan_summary.py test\test_context_manager_skills.py test\test_plan_context_summary.py -q
python -m compileall -q agent test\test_context_manager.py
```

如果已有测试中对 `hot_message_count` 的断言依赖旧语义，需要同步调整为 conversation-message 语义。

## 验收标准

修复完成后必须满足：

- conversation hot zone 不再被 `tool` 或 `assistant tool_calls` 占用。
- conversation summary 只替换普通 `user` / 普通 `assistant` 冷区文本。
- 同一 turn 中，即使发生多轮 tool call，本轮用户问题也不会因为 tool messages 数量多而被压进 summary。
- tool output 仍正常按 hot/warm/cold 降级。
- 相关 tests 和 compileall 通过。

## 非目标

本方案不处理以下事项：

- 不修改 OpenAI/GLM 请求适配器。
- 不改变 tool call 持久化格式。
- 不新增 turn anchor 状态。
- 不改变 `summary_step_threshold` 逻辑。
- 不优化 `latest_context_snapshot` 大小。
- 不处理 `.docs/runtime-bug-and-optimization-audit-zh.md` 中 P2 项。

## 后续可选增强

如果后续仍遇到 provider 对 tool continuation 特别严格的问题，可以再追加 turn-scoped protection：

```text
在 AsyncTurnRunner 的一个 turn 内，记录本轮 user message 之后的 message 起点。
ContextManager 在本 turn 内禁止压缩该起点之后的普通 conversation messages。
```

但这不是本次最小修复的必要条件。当前最该先修的是：

```text
conversation hot zone 不应统计 tool messages。
```
