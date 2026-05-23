---
name: "self_dev_workflow"
description: "Quanora 自开发模式的标准 Git 工作流：分支策略、push 目标、PR 创建流程、常见错误禁令。强制推送到 0x2Hacks/ChainPeer repo。"
triggers:
  - "自开发"
  - "self-dev"
  - "self development"
  - "push"
  - "PR"
  - "pull request"
  - "提交代码"
  - "git push"
---

# Self-Development Workflow — ChainPeer Repo

**本 skill 定义 Quanora 自开发的完整 Git 工作流，所有自开发任务必须严格遵守。**

## 1. Git 仓库信息（不可更改）

| 项目 | 值 |
|------|-----|
| **Remote URL** | `https://github.com/0x2Hacks/ChainPeer.git` |
| **Base Branch** | `main` |
| **Dev Branch** | `genspark_ai_developer` |
| **PR Target** | `main` ← `genspark_ai_developer` |

⚠ **绝不直接 push 到 main！** 所有改动必须走 dev branch → PR 流程。

## 2. 工作流步骤（每次自开发必执行）

### Step 1: 确认分支
```bash
git branch --show-current
# 如果不在 genspark_ai_developer：
git checkout genspark_ai_developer
# 如果分支不存在：
git checkout -b genspark_ai_developer
```

### Step 2: 确认 remote 指向正确仓库
```bash
git remote -v
# 必须显示 0x2Hacks/ChainPeer.git
# 如果不对，修正：
git remote set-url origin https://github.com/0x2Hacks/ChainPeer.git
```

### Step 3: Plan → Edit → Test 循环
- 用 `plan_create` 建计划，`plan_update_step` 跟进度
- 用 `edit_file` 做手术式修改，`write_file` 建新文件
- 每次改动后跑受影响测试：`python3 -m pytest test/<file> -v --no-header`
- 完成前跑全量测试：`python3 -m pytest test/ --no-header -q`
- **全量必须全绿，0 failed**

### Step 4: Rebase + Push
```bash
git fetch origin main
git rebase origin/main
# 如有冲突，优先保留 remote main 的改动（除非本地改动是本 PR 的核心）
git push -f origin genspark_ai_developer
```

### Step 5: 创建 PR
```bash
# 提取 GitHub token（从 remote URL 中）
export GH_TOKEN="$(git remote get-url origin | sed -E 's#.*://([^@]+)@.*#\1#' | head -1)"

# 写 PR body 文件（必须放在 workspace 内，不是 /tmp）
# ~/bin/gh 位置（如系统无 gh CLI，需先安装）

~/bin/gh pr create \
  --base main \
  --head genspark_ai_developer \
  --title "feat(scope): 简要描述" \
  --body-file pr_body.md \
  --repo 0x2Hacks/ChainPeer
```

### Step 6: 报告 PR URL
- 将 PR URL 作为最终交付物报告给用户

## 3. PR Body 模板

```markdown
## Why
用户侧动机 / 为什么要做这个改动

## What changed
- 文件1: 改动描述
- 文件2: 改动描述

## Tests
跑了什么测试，结果是什么

## Files
**Created:** 新文件列表
**Modified:** 修改文件列表
```

## 4. 常见错误 & 禁令

| ❌ 禁止 | ✅ 正确做法 |
|---------|-----------|
| push 到 main | push 到 genspark_ai_developer → PR |
| 写文件到 /tmp | 写文件到 workspace 内相对路径 |
| 删测试让它通过 | 修代码让测试通过 |
| 用 pytest.mark.skip 跳过失败测试 | 只在环境问题时 skip，且告知用户 |
| 改 .git/ 或 .env | 绝不触碰 |
| git commit 不带 message | 必须带 conventional-commit message |
| 未跑全量测试就提交 | 先全量绿再提交 |

## 5. gh CLI 安装（如缺失）

```bash
curl -sL https://github.com/cli/cli/releases/download/v2.42.1/gh_2.42.1_linux_amd64.tar.gz | tar -xz -C /tmp
mkdir -p ~/bin && cp /tmp/gh_2.42.1_linux_amd64/bin/gh ~/bin/gh
export PATH="$HOME/bin:$PATH"
```
