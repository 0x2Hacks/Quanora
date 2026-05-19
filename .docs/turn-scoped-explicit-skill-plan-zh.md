# 显式触发 + Turn-Scoped Skill 注入方案

> 目标：将当前 skill 激活逻辑收敛为“用户显式 `$skill-name` 触发，并且只在当前 turn 内保持注入”。不再依赖最近 user message 在每次 context build 时重新解析，也不再通过普通 skill name / trigger 自动注入 skill body。

---

## 1. 设计结论

当前实现是“近似 turn-scoped + 混合触发”：

- `$skill-name` 会触发；
- 普通文本包含 skill name 也会触发；
- 普通文本包含 trigger 也会触发；
- 每次 `ContextManager.build_messages_async()` 都会重新读取最近 user message 并重新选择 skill。

目标实现应改为：

```text
用户输入 query
  ↓
AsyncRuntimeFacade 持久化 user message
  ↓
AsyncTurnRunner 在 turn 开始时解析一次 $skill-name
  ↓
得到 turn_active_skills
  ↓
本 turn 内每次 build context 都传入同一批 turn_active_skills
  ↓
ContextManager 只负责注入，不再自行解析最近 user message
  ↓
turn 结束后 active skill 自动释放，不跨 turn 持久化
```

生命周期定义：

- `available_skills`：文件系统级，由 `SkillRepository` 扫描；
- `turn_active_skills`：本轮用户输入级，仅存在于 `AsyncTurnRunner.run_turn()` 局部变量；
- `skill body`：context-only，每次 LLM request 需要时注入，不持久化；
- `SkillActivatedEvent`：展示/观测事件，每个 turn 内同名 skill 只发一次。

---

## 2. 核心改动

### 2.1 收敛 SkillSelector：只解析 `$skill-name`

文件：`agent/application/services/skill_selector.py`

修改 `SkillSelector.select()`：

- 保留 `$skill-name` 解析；
- 删除普通 skill name 文本匹配；
- 删除 trigger 匹配；
- 返回 reason 固定为 `explicit_dollar_name`；
- 保留 `max_active_skills`；
- 保留排序：按用户输入中出现顺序优先，其次 skill name 稳定排序。

建议实现：

```python
explicit_names = re.findall(r"\$([a-zA-Z0-9_-]+)", user_message)
```

只匹配 `explicit_names` 与 skill name 相同的 skill。

验收：

- `please use $demo` 命中；
- `please use demo` 不命中；
- `demo trigger` 不命中；
- 多个 `$skill` 时不超过 `max_active_skills`。

### 2.2 ContextManager 不再解析最近 user message

文件：`agent/application/services/context_manager.py`

修改 `build_messages_async()` 签名：

```python
async def build_messages_async(
    self,
    session,
    pending_messages: list[dict] | None = None,
    active_skill_matches: list | None = None,
) -> ContextBuildResult:
```

行为变化：

- 删除或停止使用 `_latest_user_content()`；
- `_build_skill_messages()` 不再接收 `user_message`；
- `_build_skill_messages(active_skill_matches)` 只使用传入的 matches；
- 如果 `active_skill_matches` 为空：
  - 仍注入 skill index（保持当前行为）；
  - 不注入 active skill body；
- 如果 `active_skill_matches` 非空：
  - 注入 skill index；
  - 注入 active skill body；
  - decisions/stats 继续填充 `active_skills`。

建议方法签名：

```python
def _build_skill_messages(self, active_skill_matches: list | None = None) -> tuple[list[dict], dict, dict]:
```

注意：

- `ContextManager` 不应再依赖 `self._skill_selector`；
- 构造函数可以暂时保留 `skill_selector` 参数以避免大范围改动，但不再使用；
- 更干净的后续清理可以另做，不在本次范围内。

### 2.3 AsyncTurnRunner 在 turn 开始时解析一次

文件：`agent/application/runtime/async_turn_runner.py`

在 `while True` 之前新增本轮状态：

```python
turn_active_skill_matches = None
emitted_skill_names = set()
```

在第一次 context build 前解析一次：

```python
if turn_active_skill_matches is None:
    turn_active_skill_matches = await self._resolve_turn_active_skills(session)
```

每次 context build 都传入：

```python
context = await self._context_manager.build_messages_async(
    session=session,
    active_skill_matches=turn_active_skill_matches,
)
```

新增私有 async helper：

```python
async def _resolve_turn_active_skills(self, session) -> list:
    ...
```

职责：

- 从 session 读取当前 messages；
- 找到最近一条 user message；
- 从 `self._context_manager` 拿到 selector/repository 不够优雅，因此推荐把 skill 解析能力放在 `ContextManager` 提供的新方法中，见 2.4。

### 2.4 给 ContextManager 增加 turn 解析入口

文件：`agent/application/services/context_manager.py`

新增：

```python
def select_active_skills_for_turn(self, user_message: str) -> list:
    ...
```

职责：

- 读取 `self._skill_repository.list_skills()`；
- 调用 `self._skill_selector.select(user_message, skills)`；
- 捕获异常，失败返回 `[]`；
- 不构建 context；
- 不持久化 snapshot；
- 不注入 message。

这样 `AsyncTurnRunner` 不需要知道 repository/selector 细节，只调用：

```python
turn_active_skill_matches = self._context_manager.select_active_skills_for_turn(latest_user_message)
```

### 2.5 latest user message 只在 runner 里读取一次

文件：`agent/application/runtime/async_turn_runner.py`

新增 helper：

```python
async def _latest_user_content(self, session) -> str:
    messages = await session.get_messages_slice()
    for message in reversed(messages):
        if message.get("role") == "user":
            content = message.get("content", "")
            return content if isinstance(content, str) else ""
    return ""
```

注意：

- 这是 turn 开始解析 `$skill` 的唯一地方；
- context build 后续不再重新读取最近 user message 做 skill selection；
- tool call 后进入下一次 `while True` 时复用同一 `turn_active_skill_matches`。

### 2.6 保持 SkillActivatedEvent 去重

现有 `emitted_skill_names` 逻辑保留。

事件来源仍是：

```python
context.decisions["active_skills"]
```

由于每次 context build 都会带同一批 active skills，runner 仍需要事件去重，避免 tool call 后重复打印。

---

## 3. 测试计划

### 3.1 更新 SkillSelector 测试

文件：`test/test_skill_selector.py`

修改或新增：

- `$skill-creator` 命中；
- 普通 `skill-creator` 不命中；
- trigger 不命中；
- 多个 `$skill` 命中时按用户出现顺序返回；
- `max_active_skills=0` 不命中。

### 3.2 更新 ContextManager skill 测试

文件：`test/test_context_manager_skills.py`

调整测试为显式传入 `active_skill_matches`：

- 无 skill：不注入；
- 有 skill + `active_skill_matches=[]`：只注入 index；
- 传入 active match：注入 active body；
- user message 包含 trigger 但未传 active match：不注入 active body。

### 3.3 新增 turn-scoped runner 测试

文件：`test/test_skill_activation_event.py`

新增或扩展：

- 构造 session：最近 user message 包含 `$demo`；
- fake context manager 的 `select_active_skills_for_turn()` 记录调用次数并返回 `[SkillMatch(...)]`；
- fake stream 第一次返回 tool call，第二次返回空 tool calls；
- 断言：
  - `select_active_skills_for_turn()` 只调用一次；
  - `build_messages_async()` 至少调用两次；
  - 每次 `build_messages_async()` 都收到同一批 `active_skill_matches`；
  - `SkillActivatedEvent` 只发一次。

再加一条：

- 最近 user message 只有 `demo trigger`，没有 `$demo`；
- selector 返回空；
- 不发 `SkillActivatedEvent`。

### 3.4 回归命令

运行：

```bash
python -m compileall -q .
python test/test_skill_selector.py
python test/test_context_manager_skills.py
python test/test_skill_activation_event.py
pytest test/test_skill_selector.py test/test_context_manager_skills.py test/test_skill_activation_event.py test/test_runtime_events.py -q
```

---

## 4. 验收标准

功能验收：

- `$demo` 会在当前 turn 激活并注入 skill body；
- 同一个 turn 内 tool call 后再次请求 LLM 时，仍注入同一个 skill body；
- `SkillActivatedEvent` 只展示一次；
- 下一条用户 prompt 不包含 `$demo` 时，不继承上一 turn 的 active skill；
- 普通文本 `demo` 不触发；
- trigger 文本不触发。

工程验收：

- `ContextManager` 不再从最近 user message 解析 skill；
- `AsyncTurnRunner` 是唯一决定 turn_active_skills 生命周期的位置；
- active skill 不持久化到 session；
- 不新增工具；
- 不修改 `skill_create`；
- 现有 skill index 仍保持可见，用于让模型知道有哪些可显式使用的 skill。

