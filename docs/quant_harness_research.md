# Quant Research Harness & Version Management 调研报告

> 调研日期: 2026-06-04
> 目标: 为 ChainPeer quant-research 模式选择任务级版本管理方案

---

## 1. 现有方案对比

### 1.1 DVC (Data Version Control)

| 维度 | 评价 |
|------|------|
| **原理** | 在 Git 之上增加数据版本层，用 `.dvc` 文件追踪大文件/模型，实际数据存于远程存储 (S3/GS/本地) |
| **优势** | 与 Git 深度集成；支持 pipeline (`dvc.yaml`)；数据去重节省空间；ML 社区成熟 |
| **劣势** | 依赖外部存储后端；学习曲线陡；对"每个任务独立 repo"场景过重；`dvc push/pull` 在离线环境不可用 |
| **适用** | 大规模 ML 项目，需要版本化数据集和模型 |

### 1.2 MLflow

| 维度 | 评价 |
|------|------|
| **原理** | 集中式 Tracking Server 记录实验参数/metrics/artifacts，代码版本通过 `git commit hash` 关联 |
| **优势** | UI 直观；自动记录参数；支持模型注册；社区庞大 |
| **劣势** | 需要 Tracking Server（额外运维）；代码版本管理仍是 git 的责任；不解决"任务级独立 repo"问题；artifact 存储依赖外部 |
| **适用** | 团队共享实验追踪，已有 MLflow 基础设施 |

### 1.3 Weights & Biases (W&B)

| 维度 | 评价 |
|------|------|
| **原理** | SaaS 实验追踪平台，自动记录代码 diff/参数/metrics/artifacts |
| **优势** | 最强 UI；自动 diff 可视化；协作功能强；Sweep 超参搜索 |
| **劣势** | SaaS 依赖（数据上传到 W&B 服务器）；商业产品有配额限制；不适合敏感量化策略代码 |
| **适用** | 非敏感 ML 研究，需要团队协作和可视化 |

### 1.4 Sacred + Omniboard

| 维度 | 评价 |
|------|------|
| **原理** | Sacred 装饰器自动记录实验配置和结果，Omniboard 提供 Web UI |
| **优势** | 轻量；与 Python 深度集成；MongoDB 后端 |
| **劣势** | 维护不活跃；不解决代码版本管理；MongoDB 运维负担 |
| **适用** | 学术研究，小规模实验 |

### 1.5 Git Worktree

| 维度 | 评价 |
|------|------|
| **原理** | 一个 git repo 多个工作目录，每个 worktree 对应一个分支 |
| **优势** | 原生 git 能力；零额外依赖；共享 .git 对象节省空间 |
| **劣势** | 所有 worktree 共享同一个 repo（违反"独立隔离"需求）；branch 管理复杂；不适合"每个任务一个 repo" |
| **适用** | 同一项目多分支并行开发 |

### 1.6 独立 git init per task（**选定方案**）

| 维度 | 评价 |
|------|------|
| **原理** | 每个任务目录执行 `git init`，创建完全独立的 `.git/`，与 agent 自身的 git 严格隔离 |
| **优势** | ✅ 零外部依赖；✅ 完全隔离（每个 task repo 独立）；✅ 支持 commit/rollback/diff/log 全套；✅ 轻量无运维；✅ 符合用户"严格分割"需求 |
| **劣势** | 不追踪大文件（可后续加 DVC）；无 Web UI（可后续加 gitweb）；无跨任务关联（可后续加索引） |
| **适用** | **当前场景：quant research 任务级版本管理** |

---

## 2. 选型结论

**选择方案：独立 git init per task**

核心理由：

1. **严格隔离需求**：用户明确要求"git 和 agent git 完全独立，不能混淆，严格分割"。DVC/MLflow/W&B 都在 agent 的 git 之上叠加层，无法实现真正隔离。只有独立 `git init` 能保证任务 repo 的 `.git/` 与 agent repo 的 `.git/` 毫无关系。

2. **零依赖**：quant research 经常在受限环境中运行，不需要 S3/MongoDB/Tracking Server。

3. **完整 git 能力**：commit/rollback/diff/log/branch/tag 全部原生可用，无需额外学习。

4. **可扩展**：未来如需跨任务索引，可在任务 repo 之上加元数据层；如需大文件版本管理，可加 DVC。

---

## 3. 设计方案

### 3.1 架构图

```
ChainPeer Agent Repo (agent git)          Task Repo (task git)
/home/wesley/ChainPeer/                   <workspace>/xauusd_reversal/
├── .git/          ← agent git            ├── .git/        ← task git (独立)
├── agent/                                  ├── src/
├── main.py                                 ├── scripts/
├── ...                                     ├── results/
                                            └── data/
  ┌──────────────────┐                     ┌──────────────────┐
  │  Agent Runtime    │                     │  Task Git Manager │
  │  (genspark_ai_    │  ──wq_task_git──>  │  init/commit/     │
  │   developer)     │                     │  rollback/diff/   │
  └──────────────────┘                     └──────────────────┘
```

### 3.2 隔离保证

| 保证项 | 实现方式 |
|--------|---------|
| 不同的 `.git/` 目录 | task repo `git init` 在 `<workspace>/<task_name>/` 下 |
| 不同的 GIT_DIR | TaskGitManager 使用 `git -C <task_dir> --git-dir=<task_dir>/.git` |
| 不同的 GIT_AUTHOR | task commit 使用 `QuantTaskBot <task@quant.local>` |
| 禁止跨 repo 操作 | TaskGitManager 验证路径不在 agent repo 内 |
| WorkspaceGuard 扩展 | 检测 `.git/` 目录防止误操作 |

### 3.3 TaskGitManager API

```python
class TaskGitManager:
    def __init__(self, task_dir: Path, task_name: str): ...
    
    # 初始化
    def init_task_repo(self) -> dict:
        """git init + .gitignore + initial commit"""
    
    # 版本管理
    def commit_all(self, message: str) -> dict:
        """git add -A + git commit，返回 commit hash"""
    
    def rollback(self, ref: str = "HEAD~1") -> dict:
        """git reset --hard <ref>，回滚到指定版本"""
    
    # 查询
    def log(self, n: int = 10) -> list[dict]:
        """git log --oneline -n"""
    
    def status(self) -> dict:
        """git status --porcelain"""
    
    def diff(self, ref: str = "HEAD") -> str:
        """git diff <ref>"""
    
    def has_changes(self) -> bool:
        """是否有未提交的变更"""
    
    # 辅助
    def is_initialized(self) -> bool:
        """task repo 是否已初始化"""
    
    def current_commit(self) -> str:
        """当前 HEAD commit hash"""
```

### 3.4 工作流

```
Onboarding Phase B
    ↓
用户选择任务目录 <workspace>/xauusd_reversal/
    ↓
TaskGitManager.init_task_repo()
    → git init
    → 创建 .gitignore
    → git add -A && git commit -m "init: task xauusd_reversal"
    ↓
研发循环:
    1. Agent 修改代码/数据
    2. TaskGitManager.has_changes() → True
    3. Agent 调用 commit_all("feat: 添加均线策略")
    4. 研发继续...
    ↓
需要回滚:
    TaskGitManager.log() → 查看历史
    TaskGitManager.rollback("HEAD~2") → 回滚到2个版本前
```

### 3.5 与 Agent Git 的隔离规则

1. **路径隔离**: TaskGitManager 的 `task_dir` 必须在 `<workspace>/` 下，且不能是 agent repo 的根目录或子目录
2. **环境隔离**: 使用 `git -C <task_dir>` 而非 `cd`，避免影响 agent 的 git 上下文
3. **作者隔离**: task commit 的 author 是 `QuantTaskBot`，agent commit 的 author 是 agent 的 git config
4. **禁止嵌套**: 如果检测到 `<task_dir>/.git` 的父目录已经有 `.git`，报错拒绝初始化（防止 git submodule 混淆）
5. **WorkspaceGuard 扩展**: 允许在 task workspace 下创建 `.git/`，但禁止修改 agent repo 的 `.git/`

---

## 4. 实现计划

1. **TaskGitManager** (`agent/infrastructure/task_git.py`)
   - 核心类，封装所有 task 级 git 操作
   - 使用 `subprocess.run` 调用 git CLI（零依赖）
   - 严格的路径验证和隔离检查

2. **wq_task_git 工具** (`agent/tools/wq_task_git.py`)
   - 注册为 agent tool，支持 7 个子命令
   - 输入: action + params
   - 输出: 结构化 JSON

3. **Prompts 集成** (`agent/prompts.py`)
   - §5 onboarding: 任务创建时自动 `init_task_repo`
   - §6 guardrails: 每轮代码变动后必须 `commit_all`
   - 新增 §7 Git SOP: 版本管理标准操作流程

4. **测试** (`test/test_task_git.py`)
   - init/commit/rollback/log/diff/isolation 全覆盖
