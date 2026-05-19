# Skill 激活事件展示方案

> 目标：把 “本轮启用了哪些 skill” 接入现有 RuntimeEvent 信息流，让 CLI 先能打印展示，同时为未来 API / UI 标准化消费保留稳定事件格式。

---

## 1. 设计结论

Skill 激活信息的产生点在 `ContextManager.build_messages_async()`：

- 这里扫描 skill；
- 这里选择 active skills；
- 这里把 active skill instructions 注入 model-facing context；
- 当前已通过 `ContextBuildResult.decisions["active_skills"]` 记录决策。

但 `ContextManager` 不应直接打印，也不应直接产出 stream event。职责划分应保持为：

```text
ContextManager
  负责生成 active_skills 决策
        ↓
AsyncTurnRunner
  负责把 active_skills 转成 RuntimeEvent
        ↓
CLI / API / future UI
  统一展示或消费事件
```

这样 CLI、FastAPI SSE、未来前端都可以共享同一条标准事件流。

---

## 2. 核心改动

### 2.1 新增 RuntimeEvent

文件：`agent/domain/events.py`

新增：

```python
@dataclass(slots=True)
class SkillActivatedEvent(RuntimeEvent):
    """Fired when a skill is selected and injected into the model context."""

    type: Literal["skill_activated"] = "skill_activated"
    skill_name: str = ""
    reason: str = ""
    score: int = 0
    source: str = ""
    path: str = ""
```

字段含义：

- `skill_name`：skill 名称；
- `reason`：激活原因，如 `explicit_dollar_name`、`explicit_name`、`trigger`；
- `score`：selector 分数；
- `source`：`project` 或 `user`；
- `path`：`SKILL.md` 绝对路径。

同时在 `agent/domain/__init__.py` 中导出 `SkillActivatedEvent`。

### 2.2 丰富 active skill 决策字段

文件：`agent/application/services/context_manager.py`

当前 `decisions["active_skills"]` 已包含：

```python
{"name": ..., "reason": ..., "score": ...}
```

需要扩展为：

```python
{
    "name": match.skill.name,
    "reason": match.reason,
    "score": match.score,
    "source": match.skill.source,
    "path": match.skill.path,
}
```

保持原有字段不变，只新增 `source` / `path`，避免破坏现有测试。

### 2.3 在 AsyncTurnRunner 中发射事件

文件：`agent/application/runtime/async_turn_runner.py`

在：

```python
context = await self._context_manager.build_messages_async(session=session)
```

之后、调用 LLM stream 之前，读取：

```python
active_skills = context.decisions.get("active_skills") or []
```

对每个 active skill yield：

```python
yield SkillActivatedEvent(
    ts=session.now_iso(),
    skill_name=item.get("name", ""),
    reason=item.get("reason", ""),
    score=int(item.get("score") or 0),
    source=item.get("source", ""),
    path=item.get("path", ""),
)
```

放在 LLM stream 之前的理由：

- skill 已经完成选择与上下文注入；
- 用户能在模型输出前看到“本轮启用了哪个 skill”；
- API SSE 消费者也能在 assistant delta 前收到结构化事件。

### 2.4 CLI 展示

文件：`agent/interfaces/cli/chat_cli.py`

在 `_on_event()` 中处理 `SkillActivatedEvent`：

```python
elif isinstance(event, SkillActivatedEvent):
    self._console.print(
        f"[dim italic]🧩 技能启用: {event.skill_name} ({event.reason})[/dim italic]"
    )
```

如果要保持与现有 tool 文案风格一致，也可使用：

```text
技能启用: <skill_name> (<reason>)
```

注意：

- 不展示 path，避免 CLI 噪音；
- `path/source/score` 保留在 event data 中，供 API / future UI 使用；
- 不需要修改 API route，因为现有 SSE 已按 `event.type` 和 `event.to_dict()` 输出所有 runtime event。

---

## 3. 测试计划

### 3.1 Event 序列化测试

建议新增或扩展：`test/test_runtime_events.py`

覆盖：

- `SkillActivatedEvent(...).to_dict()` 包含全部字段；
- `RuntimeEvent.from_dict()` 能还原为 `SkillActivatedEvent`。

### 3.2 AsyncTurnRunner 事件测试

建议新增：`test/test_skill_activation_event.py`

构造 fake session、fake context manager、fake chat client：

- fake context manager 返回：
  - `messages=[{"role": "system", "content": "sys"}, {"role": "user", "content": "use $demo"}]`
  - `decisions={"active_skills": [{"name": "demo", "reason": "explicit_dollar_name", "score": 100, "source": "project", "path": ".../SKILL.md"}]}`
- fake chat client 返回一个空 assistant stream 或简单文本 stream；
- 断言 `run_turn()` 产出的第一个或靠前事件包含 `SkillActivatedEvent`；
- 断言事件出现在 assistant delta 之前。

### 3.3 CLI 处理测试

如果现有 CLI 测试容易接入，新增一条轻量测试：

- 实例化 `ChatCLI`；
- 调用 `_on_event(SkillActivatedEvent(...))`；
- 断言不抛异常。

若 CLI 输出捕获成本较高，可以先不测具体 rich 文案，只测 event 分支安全。

### 3.4 回归命令

建议运行：

```bash
python -m compileall -q .
python test/test_runtime_events.py
python test/test_skill_activation_event.py
pytest test/test_runtime_events.py test/test_skill_activation_event.py test/test_context_manager_skills.py -q
```

如新增 CLI 测试，再加入对应测试文件。

---

## 4. 验收标准

功能验收：

- 用户消息触发 active skill 时，runtime event 流中出现 `skill_activated`；
- CLI 在 assistant 输出前打印 skill 启用信息；
- API SSE 自动输出：

```json
{
  "event": "skill_activated",
  "data": {
    "type": "skill_activated",
    "skill_name": "demo",
    "reason": "explicit_dollar_name",
    "score": 100,
    "source": "project",
    "path": ".../SKILL.md"
  }
}
```

工程验收：

- `ContextManager` 仍只负责 context 决策，不直接打印；
- `AsyncTurnRunner` 是唯一把 skill decision 转成 runtime event 的位置；
- 不修改 tool schema；
- 不影响未启用 skill 的普通 turn；
- 现有 skill 注入测试继续通过。

