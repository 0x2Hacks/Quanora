## Why

Agent 每次新会话都要从头探索项目结构（list_files / read_file / grep），这在大项目中会浪费大量 token 和时间。需要一个会话间项目理解缓存系统，让 agent 首次探索后生成压缩知识库，后续会话直接加载。

## What Changed

### 新增文件
- **`agent/infrastructure/persistence/project_knowledge_cache.py`** — 核心缓存模块
  - 自动检测项目类型（Python / Node / Go / Rust）
  - 自动收集关键文件、目录、依赖
  - git HEAD + 文件哈希的 stale 检测机制
  - `context_boost` 压缩摘要生成
  - 缓存存储在 `.quanora/cache/project_knowledge.json`

- **`agent/infrastructure/tools/impl/tools/project_knowledge.py`** — 工具处理器
  - `generate_project_knowledge` — 首次探索后生成缓存
  - `load_project_knowledge` — 加载缓存（返回 hit/stale/miss 状态）

- **`.quanora/skills/project_knowledge/SKILL.md`** — `$project_knowledge` skill
  - 触发词: `$project_knowledge`, `$pk`, "理解项目", "分析架构"
  - 完整的生成/加载/更新 playbook

- **`test/test_project_knowledge_cache.py`** — 32 个测试用例
  - 核心模块测试：生成、加载、保存、stale 检测、boost 生成
  - 工具处理器测试：generate / load 工具调用
  - Context Manager 集成测试：消息注入

### 增强文件
- **`agent/application/services/context_manager.py`**
  - 新增 `_build_knowledge_cache_messages()` 方法
  - 自动加载缓存并注入为 system 消息
  - 三种状态：hit（有效注入）、stale（注入+警告）、miss（不注入）
  - 将 knowledge_stats 合并到 build 统计中

- **`agent/prompts.py`**
  - 在 `<core_capabilities>` 第 7 项添加 Project Knowledge Cache 说明

- **`agent/infrastructure/tools/impl/__init__.py`**
  - 注册 `generate_project_knowledge` 和 `load_project_knowledge` 到 TOOLS 和 TOOL_SCHEMAS

- **`agent/infrastructure/tools/impl/tools/__init__.py`**
  - 导出新的工具函数

## Tests

```
$ python3 -m pytest test/test_project_knowledge_cache.py -v --no-header
32 passed

$ python3 -m pytest test/ --no-header -q
272 passed, 28 skipped (全量测试套件无回归)
```

## Files

**Created:**
- `agent/infrastructure/persistence/project_knowledge_cache.py`
- `agent/infrastructure/tools/impl/tools/project_knowledge.py`
- `.quanora/skills/project_knowledge/SKILL.md`
- `test/test_project_knowledge_cache.py`

**Modified:**
- `agent/application/services/context_manager.py`
- `agent/infrastructure/tools/impl/__init__.py`
- `agent/infrastructure/tools/impl/tools/__init__.py`
- `agent/prompts.py`
