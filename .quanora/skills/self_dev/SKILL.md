---
name: self_dev
description: >
  Self-development workflow. Activates when Quanora is running in
  self-development mode (main.py --self-dev) and the user asks the agent to
  modify, refactor, optimise, or extend its own source code. Provides the
  exact git workflow: branch → edit → test → commit → sync → squash → push →
  pull request → report URL.
triggers:
  - "$self_dev"
  - "$self_develop"
  - "$self_dev_mode"
  - "self-dev"
  - "self-development"
  - "self-improve"
  - "自我开发"
  - "自我优化"
  - "改自己"
  - "改进自己"
  - "优化自己"
  - "更新自己"
  - "提交 PR"
  - "open a PR"
  - "create a pull request"
  - "refactor agent"
  - "improve quanora"
  - "fix quanora"
  - "update agent"
---

# Self-Development Mode

You are running in `--self-dev` mode. You have framework-granted permission
to edit your own code (`agent/`, `test/`, `.quanora/skills/`, `main.py`,
`prompts.py`, `docs/`, etc.). Only `.git/` and `.env` remain protected.

The user has activated this mode to ask you to **improve yourself**.

## The Mandatory Workflow

Every self-development cycle follows EXACTLY these 10 steps. Skipping
steps is a bug; the user is watching every tool call via the framework
progress panel.

### 1. Understand the request
Read whatever files the user references (`read_file`, `grep`, `list_files`).
If the request is fuzzy, ask one clarifying question. If clear, proceed.

### 2. Plan
Call `plan_create` with a goal and 3–8 concrete steps. The 📋 panel will
render live progress to the user.

### 3. Branch
```
bash: cd /home/user/webapp && git rev-parse --abbrev-ref HEAD
```
If not on `genspark_ai_developer`:
```
bash: cd /home/user/webapp && git fetch origin && git checkout genspark_ai_developer || git checkout -b genspark_ai_developer origin/main
```

### 4. Make changes
- Prefer `edit_file` (surgical) over `write_file` (overwrites).
- Group related edits into one logical commit.
- After each batch of edits, **read** the modified file to confirm the
  change landed exactly as intended.

### 5. Test
After every meaningful change:
```
bash: cd /home/user/webapp && python3 -m pytest test/<file> -v --no-header 2>&1 | tail -30
```
Before declaring done:
```
bash: cd /home/user/webapp && python3 -m pytest test/ --no-header -q 2>&1 | tail -10
```
The full suite MUST stay green. If you broke a test, fix it.

### 6. Add tests for new functionality
If you added a public function, class, event type, or skill — write tests
for it. **No new feature ships without tests.**

### 7. Commit
```
bash: cd /home/user/webapp && git status --short
bash: cd /home/user/webapp && git add -A && git commit -m "type(scope): one-line summary

Longer paragraph describing motivation, the change, and any
non-obvious decisions. Mention test results."
```

### 8. Sync with remote (before opening PR)
```
bash: cd /home/user/webapp && git fetch origin main
bash: cd /home/user/webapp && git rebase origin/main
```
If conflicts: resolve them, preferring remote `main` unless your change
is the whole point. Then `git rebase --continue`. NEVER `git rebase --abort`
silently — tell the user.

### 9. Squash multiple incremental commits into one
Only if you made multiple commits in this session. Use the non-interactive
form:
```
bash: cd /home/user/webapp && git log --oneline origin/main..HEAD
bash: cd /home/user/webapp && git reset --soft HEAD~N && git commit -m "comprehensive message"
```
Where `N` is the count from the previous command.

### 10. Push and PR
```
bash: cd /home/user/webapp && git push -f origin genspark_ai_developer
```

Then create the PR. **Use `--body-file`** to avoid shell-quoting nightmares:
```
write_file: /tmp/pr_body.md  → the full markdown PR description
bash: cd /home/user/webapp && gh pr create --base main --head genspark_ai_developer --title "type(scope): summary" --body-file /tmp/pr_body.md
```

If `gh` returns `Bad credentials`, extract the token from the git creds:
```
bash: cd /home/user/webapp && TOK=$(sed -nE 's#.*x-access-token:([^@]+)@.*#\1#p' ~/.git-credentials | head -1) && GH_TOKEN="$TOK" gh pr create --base main --head genspark_ai_developer --title "..." --body-file /tmp/pr_body.md
```

**Report the PR URL** as the final message to the user. That URL is the
deliverable.

## PR Body Template

```markdown
## Why
<user-facing motivation — 2–4 sentences>

## What changed
- <bullet per logical change, mention file path>

## Tests
- New: <list new test files>
- Full suite: <X passed, Y skipped, 0 failed>

## Files
**Created**: ...
**Modified**: ...
```

## Decision table

| User says | Action |
|---|---|
| "optimise the planner" | self_dev workflow on `agent/.../plan*` files |
| "add a new event type" | edit `agent/domain/events.py` + tests + CLI render + commit + PR |
| "the prompt is too long" | edit `agent/prompts.py` + commit + PR |
| "add a skill for X" | create `.quanora/skills/X/SKILL.md` + tests + PR |
| "fix the bug where Y" | reproduce with a failing test FIRST, then fix |
| "rewrite this in async" | propose plan first, get user confirmation, then execute |

## Non-negotiables

- ❌ Never delete tests to make builds pass.
- ❌ Never `pytest.mark.skip` to "fix" a failing test unless there's a
     real environmental reason and you explicitly tell the user.
- ❌ Never push to `main` directly. Always via `genspark_ai_developer` → PR.
- ❌ Never tamper with `.git/` directly. Always use the `git` CLI.
- ❌ Never modify `.env` (secrets live there). If a config change is
     needed, edit `.env.example` and tell the user.
- ❌ Never fabricate test results. If a test fails, report it. Do not
     "fix" output by editing the expected value to match buggy code.

## If things go wrong

- **Test failures you can't fix**: stop. Report the failure with the
  pytest output. Ask the user how to proceed.
- **Merge conflicts**: resolve them, mention each resolution in the
  commit / PR body.
- **`gh` 401**: try the `GH_TOKEN` extraction recipe above. If that
  also fails, push the branch anyway and ask the user to open the PR.
- **Sandbox auth dropped mid-session**: re-run `setup_github_environment`
  workflow (the platform tool, not bash).
