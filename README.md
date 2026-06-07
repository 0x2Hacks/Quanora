# 🤖 ChainPeer Agent

![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)
![Architecture](https://img.shields.io/badge/Architecture-Layered-success.svg)
![Status](https://img.shields.io/badge/Status-Active-brightgreen.svg)

A context-aware autonomous coding agent with a clean layered architecture. It uses **append-only session records** for resume, a **DAG-based plan tool**, and runtime context management built around compaction, tool-result normalization, and context-length rescue.

---

## ✨ Why ChainPeer?

Most open-source agents suffer from two fatal flaws: they crash when tool outputs are too large, and they lose state if interrupted. ChainPeer solves this with enterprise-grade engineering:

- 🧠 **Context Management**: `ContextManager` builds model input from persisted records, `ContextEstimator` tracks budget pressure, `CompactionService` creates compact handoffs, and `ToolResultNormalizer` keeps large tool outputs model-safe.
- 💾 **Fail-Safe Resume**: Messages, tool calls, compactions, and session metadata are stored as append-only local records. Run `python main.py -c` to resume the latest session.
- 🗺️ **DAG Task Planning**: The plan tool validates dependency graphs, persists control state, and blocks dependent steps until prerequisites are completed.
- 🏗️ **Layered Architecture**: The `application` layer owns runtime orchestration and service logic, `infrastructure` owns LLM/persistence/tool adapters, and `interfaces` exposes the CLI and session API adapters.

---

## 🚀 Quick Start

### 1. Prerequisites
- Python 3.12+
- An OpenAI-compatible API key

### 2. Installation
```bash
git clone https://github.com/your-username/chainpeer.git
cd chainpeer

# Create and activate a virtual environment
python -m venv venv
source venv/Scripts/activate  # On Windows
# source venv/bin/activate    # On Mac/Linux

# Install dependencies
pip install -r requirements.txt
```

### 3. Configuration
Create a `.env` file in the root directory:
```env
OPENAI_API_KEY=your_api_key_here
# Optional: Use an alternative API base (e.g., DeepSeek, Claude via proxy)
# OPENAI_API_BASE=https://api.deepseek.com/v1 
```

### 4. Run the Agent
```bash
python main.py
```

---

## 🛠️ CLI Usage

ChainPeer comes with a powerful CLI interface for managing sessions and debugging.

| Command | Description |
|---|---|
| `python main.py` | Start a brand new agent session. |
| `python main.py -c` | **Resume** the latest session from your local `.jsonl` storage. |
| `python main.py --session <ID>` | Resume a specific session by its ID. |
| `python main.py --debug` | Run in debug mode. Displays raw tool inputs/outputs and detailed context stats without streaming. |
| `python main.py --doctor` | Run setup diagnostics without requiring a valid API key. |
| `python main.py --allow-unsafe-bash` | Allow the agent to execute potentially dangerous shell commands. |

Inside the interactive CLI, the input toolbar shows the active session, model, cwd, and key hints. Slash commands complete with Tab after typing `/`. Resumed sessions show a compact recent-message preview while keeping the full context loaded. Tool activity lines summarize what is running, such as the shell command or file path, instead of only showing raw tool names. Run `/doctor` for a local setup check covering Python, Git, settings, API key state, model, context window, session storage, and shell detection. Run `/sessions` to list recent local sessions before resuming one with `python main.py --session <id>`. Use `/model set <model>` to switch the default model and the active session model.

---

## 🏗️ Architecture at a Glance

ChainPeer strictly follows the Dependency Inversion Principle.

```text
agent/
├── application/
│   ├── runtime/       # AsyncRuntimeFacade, AsyncTurnRunner, AsyncToolCallProcessor
│   ├── services/      # ContextManager, ContextEstimator, CompactionService, ToolResultNormalizer
│   └── ports/         # AsyncChatClient, AsyncSessionStore, ToolRegistry
├── infrastructure/
│   ├── llm/           # OpenAI-compatible async chat client
│   ├── persistence/   # AsyncJsonlSessionStore and record repositories
│   ├── plans/         # Plan state, DAG validation, plan context injection
│   └── tools/impl/    # Bash, file, web, PDF, plan, and skill tools
└── interfaces/
    ├── cli/           # Interactive CLI, slash commands, status rendering
    └── api/           # FastAPI session turn streaming
```

Runtime and persistence stream boundaries are documented in `docs/runtime-and-persistence.md`.

---

## 🔧 Core Tools Built-in

The agent is equipped with a powerful arsenal of tools to interact with your codebase:

- **`plan`**: Creates, updates, and tracks DAG-based task trees.
- **`bash`**: Executes shell commands with robust timeout, cwd awareness, and auto-fallback decoding for Windows `gbk`/`utf-8` issues.
- **`file_ops`**: Reads, edits, and creates files.
- **`web`**: Fetches and parses web pages for documentation and search.

---

## 🧪 Testing

We believe in reliable agents. Run the test suite:
```bash
pytest test/ -q
```
The repository includes focused tests for context budgets, tool-result normalization, compaction, append-only session records, resume behavior, runtime events, plans, skills, and CLI slash commands.

---

## 🤝 Contributing

We welcome contributions! Please follow our `feat:`, `fix:`, `refactor:` commit conventions. Keep single Python files compact (<= 400 lines preferred). 

When adding new tools, ensure you define the interfaces in `application/ports` and implement the messy details in `infrastructure/tools`.

---

## 📄 License

MIT License. See `LICENSE` for details.
