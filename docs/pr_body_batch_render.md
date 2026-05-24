## Why

ChatCLI 有三个关键问题需要修复：
1. **`_session_store` AttributeError**：`__init__` 中没有定义 `self._session_store`，但 `_on_event` 代码中使用了 `self._session_store.persist_turn_cost`，导致运行时崩溃。
2. **缺少项目级 workspace 分区**：所有任务共享同一个 workspace 目录，没有按项目自动分区的机制。
3. **批量工具渲染缺少分组信息**：当 LLM 一次发出多个同类工具调用（如 3 个 `read_file`）时，ToolCallStartedEvent 和 ToolResultEvent 逐个显示但不标明序号，用户难以区分哪个是哪个。

## What changed

### agent/interfaces/cli/chat_cli.py
- **Bug fix**: `__init__` 中添加 `self._session_store = session`（第 31 行）
- **Project workspace**: `_loop` 方法中首次用户输入时调用 `switch_to_project_workspace()`，自动切换到项目子目录并显示路径
- **Batch rendering**: 新增 `_batch_tool_counter`, `_batch_tool_totals`, `_batch_result_counter` 属性，用于在 ToolCallStartedEvent 中显示 `(1/3)` 分组序号，在 ToolResultEvent 中同理显示序号

### agent/infrastructure/config/settings.py
- **New function**: `switch_to_project_workspace(task_description)` — 根据任务描述提取 project slug，创建/复用项目子目录，动态更新全局 `_WORKSPACE_ROOT` 和 `_WORKSPACE_GUARD`

### test/test_batch_tool_render.py (新增)
- 11 个单元测试覆盖：
  - `TestBatchToolCounterInit` — 验证 ToolBatchStartedEvent 初始化计数器
  - `TestToolCallStartedGroupIndex` — 验证 (1/3) 分组序号显示
  - `TestToolResultGroupIndex` — 验证结果分组序号显示
  - `TestSessionStoreAttribute` — 验证 `_session_store` 属性正确设置

## Tests

- 全量测试：`python3 -m pytest test/ --no-header -q` → **240 passed, 28 skipped** (0 failed)
- 新增测试：`python3 -m pytest test/test_batch_tool_render.py -v` → **11 passed**

## Files

- **Modified**: `agent/infrastructure/config/settings.py`
- **Modified**: `agent/interfaces/cli/chat_cli.py`
- **Created**: `test/test_batch_tool_render.py`
