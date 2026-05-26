# 移除项目目录 sessions 与 Job/Output 中转修复计划

## 1. 目标

彻底修复“在任意项目目录运行 agent 会自动生成 `./sessions/`”的问题，并清理当前 tool 执行链中过重的 job/output 中转逻辑。

最终目标：

- 默认运行 agent 时，绝不在当前项目目录创建 `sessions/`。
- 会话、tool call、summary、plan、必要运行时输出统一进入用户级持久化目录。
- ContextManager 的上下文拼接行为不受影响。
- 普通 tool 执行不再绕 `jobs.jsonl -> task_outputs -> read_output` 这一层。
- 后台/长任务能力保留清晰边界：需要后台查询时才保留 job/output 类能力。
- 代码保持简洁，避免新增复杂抽象。

## 2. 当前问题确认

当前主 session 默认路径已经是：

```text
%USERPROFILE%\.chainpeer\sessions
```

但是 `agent/bootstrap/container.py` 中存在错误 fallback：

```python
store_dir = session._session_dir or getattr(session, "_default_session_root", lambda: "sessions")()
job_store = JobStoreJsonl(directory=store_dir)
output_store = TaskOutputStoreFile(directory=store_dir)
```

问题：

- `AsyncJsonlSessionStore` 没有 `_default_session_root()`。
- fallback 会变成相对路径 `"sessions"`。
- `JobStoreJsonl` / `TaskOutputStoreFile` 初始化时会创建目录。
- 所以在任意 cwd 启动 agent 都会生成：

```text
./sessions/jobs.jsonl
./sessions/task_outputs/
```

这些数据不参与 ContextManager 的上下文拼接。

## 3. 当前数据流

### 3.1 ContextManager 实际依赖

ContextManager 读取的是 session store：

```text
~/.chainpeer/sessions/<session_id>/messages.jsonl
~/.chainpeer/sessions/<session_id>/tool_calls.jsonl
~/.chainpeer/sessions/<session_id>/tool_call_summaries.jsonl
~/.chainpeer/sessions/<session_id>/conversation_summaries.jsonl
```

不读取：

```text
./sessions/jobs.jsonl
./sessions/task_outputs/
```

因此移除项目目录 `sessions/` 不会影响上下文拼接。

### 3.2 当前普通 tool 执行流

现在所有 tool 都被迫经过：

```text
create_job
update_status(running)
execute tool
append_output(result)
update_status(completed/failed)
read_output(job_id)
persist_tool_call(...)
```

这对普通同步 tool 是冗余的。

更合理的普通 tool 流程应为：

```text
parse tool args
emit ToolCallStartedEvent
execute tool
build tool_result_str
emit ToolResultEvent
persist_tool_call(...)
persist tool message
```

### 3.3 当前 bash 后台能力

`bash(run_in_background=true)` 的后台进程和输出主要由：

```text
agent/infrastructure/tools/impl/tools/bash_runner.py
```

中的内存态 `_bg` 管理。

后续通过：

```text
bash_output(bg_id)
```

读取后台输出。

也就是说，当前 `JobService` 并不是 bash 后台能力的核心数据源。

## 4. 设计原则

1. 默认不污染项目目录。
2. `--session-dir` 是唯一允许用户显式指定本地持久化目录的方式。
3. 普通 tool 不走 job/output 中转。
4. 后台/长任务能力通过明确的后台接口维护，不让所有 tool 背负 job 语义。
5. ContextManager 继续只依赖 session store，不直接读取 job/output。
6. 不自动删除旧项目目录 `sessions/`，避免误删用户历史数据。

## 5. 存储规则

### 5.1 默认规则

未传 `--session-dir` 时：

```text
session root = <CHAINPEER_HOME or ~/.chainpeer>/sessions
```

所有主会话数据写入此处。

### 5.2 显式规则

传入：

```bash
python main.py --session-dir <path>
```

则 session root 使用 `<path>`。

这是唯一允许改变 session root 的入口。

### 5.3 禁止规则

代码中不得再出现用于默认路径的：

```python
"sessions"
lambda: "sessions"
Path("sessions")
os.path.join(os.getcwd(), "sessions")
```

测试代码临时目录除外。

## 6. 实施方案

### 6.1 增加公开的 session root resolver

在 `AsyncJsonlSessionStore` 中增加公开方法：

```python
@classmethod
def resolve_session_root(cls, session_dir: str | None = None) -> str:
    ...
```

行为：

- `session_dir` 非空：返回 `os.path.abspath(os.path.expanduser(session_dir))`
- 否则：返回 `os.path.join(cls.default_chainpeer_home(), "sessions")`

同时把 `_default_chainpeer_home()` 改为公开或类方法：

```python
@classmethod
def default_chainpeer_home(cls) -> str:
    ...
```

要求：

- `_setup_paths()` 复用这个 resolver。
- `container.py` 不再访问 `session._session_dir` 这类私有字段。
- 不引入新的 path helper 文件，保持改动集中。

### 6.2 修复 container 的存储目录

修改 `agent/bootstrap/container.py`：

```python
store_dir = AsyncJsonlSessionStore.resolve_session_root(session_dir)
```

删除：

```python
session._session_dir
getattr(session, "_default_session_root", lambda: "sessions")()
```

这样即使仍然保留 `JobService`，也只会写入用户级 session root，不会落到项目目录。

### 6.3 简化普通 tool 执行链

修改 `agent/application/runtime/async_tool_call_processor.py`。

目标：

- `AsyncToolCallProcessor` 不再要求 `JobService`。
- 普通 tool 执行结果直接生成 `tool_result_str`。
- 不再对每个 tool 创建 job。
- 不再对每个 tool 先写 `task_outputs` 再读回。
- 参数解析成功后、真正执行 tool 前，必须 emit `ToolCallStartedEvent`。
- 参数解析失败时，不 emit `ToolCallStartedEvent`，直接生成失败的 `ToolResultEvent`。

建议新流程：

```python
for call in tool_calls:
    started_at = time.perf_counter()
    parsed_args, parse_error = parse_tool_args(call.raw_args)

    if parse_error:
        tool_result_str = tool_error(...)
        event_status = "failed"
        error_type = "ToolArgsJSONError"
    else:
        yield ToolCallStartedEvent(...)
        result = await execute_tool(...)
        if result.status == "ok":
            tool_result_str = normalize_result(result.result_str)
            event_status = "completed"
        else:
            tool_result_str = tool_error(...)
            event_status = "failed"

    yield ToolResultEvent(...)
    await session.persist_tool_call(...)
    await session.persist_message("tool", ...)
```

保留现有行为：

- `ToolRequestedEvent`
- `ToolCallStartedEvent`
- `ToolResultEvent`
- `persist_tool_call`
- `persist_message("tool")`
- parse error 处理
- bash cancellation token 注入

删除普通执行链中的：

- `create_job`
- `append_output`
- `read_output`
- `get_job`
- `update_status`

### 6.4 保留并收窄 JobService

本轮不强行删除 `JobService` 类和 API route，避免影响未来产品化接口。

但要收窄其定位：

- 它不再是普通 tool 执行的必经路径。
- 它只服务于未来明确的 API job / 后台任务查询能力。
- 默认 CLI 主链路不依赖它。

如果 `container.py` 仍然返回 `job_service` 以兼容 API：

- 必须使用 `AsyncJsonlSessionStore.resolve_session_root(session_dir)` 作为目录。
- 不得使用相对 `sessions`。

更清晰的可选做法：

- `build_basic_agent_dependencies(..., enable_job_service: bool = False)`
- CLI 默认 `False`
- API `create_app()` 显式传 `True`

若采用此做法：

- `deps["job_service"]` 在 CLI 下可以为 `None`
- `ToolExecutor` 不再需要 `job_service`
- API 初始化时仍可创建用户级 job store

优先推荐：

```text
先做最小安全版：保留 job_service，但路径修正到用户级。
再做主链路去中转：AsyncToolCallProcessor 不再使用 job_service。
```

### 6.5 清理 ToolExecutor 中无用依赖

当前 `ToolExecutor` 接收 `job_service`，但内部没有实际使用。

建议删除：

```python
job_service: JobService | None = None
self._job_service = job_service
```

并同步修改调用方：

```python
tool_executor = ToolExecutor(registry=tool_registry)
```

这是低风险清理。

### 6.6 不改变 bash 后台工具语义

保持：

```text
bash(run_in_background=true)
bash_output(bg_id)
kill_shell()
```

当前背景任务仍由 `BashRunner` 内存态管理。

注意：

- 本轮不承诺跨进程恢复后台 bash。
- 本轮不把后台 bash 输出自动塞入 context。
- 模型仍需显式调用 `bash_output(bg_id)` 才能把当前后台输出带回上下文。

这与当前语义一致。

## 7. 代码修改清单

### 7.1 必改文件

```text
agent/infrastructure/persistence/async_jsonl_session_store.py
agent/bootstrap/container.py
agent/application/runtime/async_tool_call_processor.py
agent/application/tool_executor.py
```

### 7.2 可能需要同步修改

```text
agent/interfaces/api/main.py
test/test_async_tool_call_processor.py
test/test_tool_executor.py
test/test_job_service.py
test/test_async_session_store.py
```

### 7.3 不应修改

```text
agent/application/services/context_manager.py
agent/infrastructure/persistence/message_repository.py
agent/infrastructure/persistence/tool_call_repository.py
agent/infrastructure/tools/impl/tools/bash.py
agent/infrastructure/tools/impl/tools/bash_runner.py
```

除非测试发现必须改。

## 8. 测试计划

### 8.1 session root resolver

新增或更新测试：

```text
test/test_async_session_store.py
```

覆盖：

- 未传 `session_dir` 时，root 是 `<CHAINPEER_HOME>/sessions`。
- 传入 `session_dir` 时，root 是该路径的绝对路径。
- `CHAINPEER_HOME` 生效。

### 8.2 不再创建项目目录 sessions

新增测试：

```text
test/test_no_project_sessions.py
```

测试逻辑：

1. 创建临时空目录 `workspace`。
2. `monkeypatch.chdir(workspace)`。
3. `monkeypatch.setenv("CHAINPEER_HOME", str(tmp_path / "home" / ".chainpeer"))`。
4. 调用 `build_basic_agent_dependencies()`。
5. 初始化 session。
6. 执行一个无网络的 fake tool call 或只初始化依赖。
7. 断言不存在：

```text
workspace/sessions
```

8. 断言存在：

```text
<CHAINPEER_HOME>/sessions
```

### 8.3 普通 tool 不走 job/output

更新：

```text
test/test_async_tool_call_processor.py
```

覆盖：

- `AsyncToolCallProcessor` 可以不传 `JobService`。
- 成功 tool 直接持久化 `tool_calls.jsonl` 所需内容。
- 失败 tool 直接持久化 `tool_error`。
- parse error 仍返回 `ToolArgsJSONError`。
- 不调用 `create_job/read_output/append_output`。

可以使用 fake executor 和 fake session，不需要真实文件。

### 8.4 ContextManager 不受影响

更新或复用：

```text
test/test_context_manager.py
```

覆盖：

- tool result 写入 `tool_calls.jsonl` 后，ContextManager 仍能通过 `get_messages_slice()` / `get_tool_records()` 构建 tool content。
- 不依赖 `jobs.jsonl`。
- 不依赖 `task_outputs`。

### 8.5 bash 后台能力不回退

更新：

```text
test/test_bash_tool.py
```

覆盖：

- `bash(command, run_in_background=True)` 返回 `bg_id`。
- `bash_output(bg_id)` 可以读取输出。
- `bash_output(bg_id, kill=True)` 可以终止。

本测试只验证现有内存态后台能力不被破坏。

### 8.6 API job 兼容

如果保留 API job service：

更新：

```text
test/test_api_jobs.py
```

覆盖：

- API 初始化不会在 cwd 创建 `sessions`。
- job service 使用用户级 session root。

如果明确不再支持 job API：

- 单独形成 API cleanup 计划。
- 本轮不要顺手删除 API route，避免扩大范围。

## 9. 验证命令

执行：

```bash
python -m compileall -q .
python test/test_async_tool_call_processor.py
python test/test_async_session_store.py
pytest test/test_no_project_sessions.py test/test_context_manager.py test/test_bash_tool.py -q
pytest test/test_api_jobs.py -q
```

再做一次手动验证：

```powershell
mkdir $env:TEMP\chainpeer-empty-test
cd $env:TEMP\chainpeer-empty-test
python E:\code\agent\agent_base\main.py
```

退出后确认：

```powershell
Test-Path .\sessions
```

必须返回：

```text
False
```

同时确认用户级目录有数据：

```powershell
Test-Path "$env:USERPROFILE\.chainpeer\sessions"
```

应返回：

```text
True
```

## 10. 旧数据处理

本次不自动删除旧项目目录：

```text
./sessions
```

理由：

- 可能包含用户历史 tool 输出。
- 自动删除存在数据损失风险。
- 这些目录不再被新版本读取后，用户可自行清理。

可以在最终说明中告知：

```text
旧的项目目录 sessions 不再参与 agent 运行；确认不需要历史 job 输出后可以手动删除。
```

## 11. 验收标准

- 在任意空目录运行 agent，不再创建 `./sessions`。
- 未传 `--session-dir` 时，所有 session 数据默认进入 `~/.chainpeer/sessions`。
- 显式传 `--session-dir` 时，所有相关数据进入该目录。
- ContextManager 测试全部通过。
- 普通 tool 执行不依赖 `JobService`。
- bash 后台工具现有能力不回退。
- `rg '"sessions"|Path\\("sessions"\\)|lambda: "sessions"' agent main.py` 不再发现生产代码里的默认相对 sessions fallback。
- 代码没有引入复杂的新抽象，核心改动集中在 session root resolver、container wiring、tool call processor。
