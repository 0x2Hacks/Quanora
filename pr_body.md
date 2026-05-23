## Why

Quanora 的 `read_file` 工具在实际使用中频繁出现以下痛点：
1. 路径拼错（大小写、扩展名缺失、把文件夹当文件读）导致反复读取失败，agent 需要多轮试错
2. 同一文件被不同 offset/limit 参数反复读磁盘，浪费 IO 和时间
3. 所有项目共享同一个 workspace flat 目录，文件混乱无分区

本 PR 通过三项基础设施改进显著提升 agent 的文件操作效率和项目管理能力。

## What changed

- **`read_file` 智能路径检索** (`file_ops.py`)
  - 新增 `_smart_resolve()` 函数，路径不存在时自动尝试 4 种策略：
    1. 目录→查找入口文件（__init__.py, index.js 等）
    2. 追加常见后缀（.py/.js/.md 等 20+ 种）
    3. 大小写模糊匹配（MyModule.py ← mymodule.py）
    4. 分隔符边界前缀匹配（config_loader.py ← config）
  - 全部失败时返回附近文件列表供参考，而非沉默报错

- **`read_file` session 级缓存** (`file_ops.py`)
  - 新增 `_read_cache` 字典，首次读取缓存完整文件行列表
  - 后续任意 offset/limit 查询直接命中缓存，零磁盘 IO
  - `meta.cached` 字段标记缓存命中情况

- **项目级 workspace 分区** (`project_manager.py` — 新文件)
  - 从任务描述 / MD 文件名自动提取项目标识
  - `_slugify()` 生成 URL-safe 目录名
  - `_fuzzy_match_score()` 支持 keyword overlap + Levenshtein 模糊匹配已有项目
  - `find_or_create_project_dir()` 在 workspace_root 下按项目建子目录，匹配则复用
  - `settings.py` 新增 `QUANORA_PROJECT_NAME` 环境变量触发分区模式

## Tests

```
test/test_file_ops_smart_read.py  — 20 tests (smart resolve + cache + basic)
test/test_project_manager.py      — 19 tests (slugify + extract + fuzzy + dir creation)

Full suite: 142 passed, 28 skipped, 0 failed
```

## Files

**Created:**
- `agent/domain/project_manager.py`
- `test/test_file_ops_smart_read.py`
- `test/test_project_manager.py`

**Modified:**
- `agent/infrastructure/tools/impl/tools/file_ops.py` (smart resolve + cache)
- `agent/infrastructure/config/settings.py` (project workspace integration)