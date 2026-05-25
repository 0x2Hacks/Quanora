---
name: "project_knowledge"
description: "项目知识缓存系统：首次探索项目后生成压缩知识库，后续会话直接加载，避免重复理解"
triggers:
  - "$project_knowledge"
  - "$pk"
  - "理解项目"
  - "分析架构"
  - "项目知识"
  - "知识缓存"
---

# $project_knowledge — 会话间项目理解加速

## 目标
避免 agent 每次新会话都从头探索项目结构。首次探索后生成压缩知识缓存，后续会话直接加载。

## 触发时机
- 用户请求涉及项目理解时（如"分析架构"、"帮我理解项目"、"优化代码"等）
- 用户显式输入 `$project_knowledge` 或 `$pk`
- self-dev 模式下理解 Quanora 自身代码库时

## 操作流程

### Step 1: 检查缓存
调用 `load_project_knowledge(project_root, self_dev=...)`:
- **hit**: 缓存有效 → 直接使用返回的 `context_boost`，跳过探索阶段
- **stale**: 缓存过期 → 提示用户缓存已过期，询问是否重新生成
- **miss**: 无缓存 → 进入 Step 2

### Step 2: 快速探索项目（仅在 miss/stale 时）
按以下顺序探索，每步不超过 3 次工具调用：
1. `list_files` — 获取目录树（max_depth=3）
2. `grep` — 搜索入口文件、类定义、import 模式
3. `read_file` — 读取关键配置和入口文件

### Step 3: 生成缓存
基于探索结果，调用 `generate_project_knowledge`，关键参数：
- `project_root`: 项目根目录（必须）
- `description`: 一句话项目描述
- `architecture_pattern`: DDD / MVC / 分层 / 单体 / 微服务 等
- `conventions`: JSON 数组字符串，如 `'["使用pytest测试","snake_case命名"]'`
- `important_patterns`: JSON 数组字符串，如 `'["工具注册在__init__.py","Skill通过context_manager注入"]'`
- `key_files_override`: JSON 对象字符串，手动指定关键文件
- `context_boost`: **最重要的参数** — 一段 500 字以内的压缩摘要，涵盖：
  - 项目做什么
  - 核心架构和分层
  - 关键文件和它们的职责
  - 重要的设计模式和约定
  - 新 agent 最需要知道的 3-5 件事
- `self_dev`: self-dev 模式设为 True

### Step 4: 缓存命中时的行为
当 `load_project_knowledge` 返回 `status: "hit"` 时：
- 将 `context_boost` 内容作为项目上下文使用
- 不再重复执行 `list_files` / `read_file` 探索
- 可直接基于缓存中的关键文件列表进行精确操作

### 缓存更新策略
- git HEAD 变更时自动标记 stale
- 关键配置文件（pyproject.toml / package.json 等）变更时自动标记 stale
- agent 也可主动重新生成：先探索，再调用 `generate_project_knowledge`

## Self-dev 模式特殊处理
当处理 Quanora 自身代码库时：
- `self_dev=True`
- 缓存存储在 `<quanora_repo>/.quanora/cache/self_knowledge.json`
- context_boost 应包含：agent 架构分层、tool 注册机制、skill 注入流程、prompt 组装逻辑

## 注意事项
- context_boost 是给未来 agent 自己看的，要精炼、准确、有结构
- 不要把整个文件内容塞进缓存，只放文件名+职责描述
- 缓存不是替代 read_file，而是在需要定位时减少搜索范围
- 如果项目很小（< 10 个源文件），可能不需要缓存
