from pathlib import Path
from agent.basic_agent import BasicAgent
from agent.infrastructure.config import Config, settings as settings_mod
import argparse
import os
import sys

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Quanora — autonomous quant-research agent")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode (non-streaming output)")
    parser.add_argument("--allow-unsafe-bash", action="store_true", help="Allow potentially dangerous shell commands")
    parser.add_argument("--session", type=str, default=None, help="Session ID to load")
    parser.add_argument("-c", "--resume-latest", action="store_true", help="Resume the latest session if available")
    parser.add_argument("--session-dir", type=str, default=None, help="Session storage directory")
    parser.add_argument(
        "--self-dev",
        action="store_true",
        help=(
            "Enter self-development mode. The agent gains permission to edit "
            "its own source code (agent/, test/, prompts.py, .quanora/skills/, "
            "main.py, docs/, etc.), run its own tests, commit, push, and open "
            "pull requests. .git/ and .env remain protected. Sessions are "
            "stored under .quanora/sessions/self-dev/ so they don't mix with "
            "normal project sessions."
        ),
    )
    parser.add_argument(
        "--self-doc",
        action="store_true",
        help=(
            "Enter self-documentation mode. The agent can read all files in "
            "the Quanora repo but may only WRITE .md (Markdown) files. "
            "Source code, configs, and other non-markdown files are protected. "
            "This mode is ideal for documentation audits, README improvements, "
            "and doc-debt cleanup. Sessions are stored under "
            ".quanora/sessions/self-doc/."
        ),
    )
    parser.add_argument(
        "--quant-research",
        action="store_true",
        help=(
            "Enter quant-research mode. The agent runs with a systematic "
            "quantitative research workflow: mandatory planning, hypothesis "
            "generation, experimentation, evaluation, and knowledge distillation. "
            "Data integrity rules are enforced with extra rigor. WorldQuant "
            "Brain alpha mining tools are available. Sessions are stored under "
            ".quanora/sessions/quant-research/."
        ),
    )
    parser.add_argument(
        "--list-sessions",
        action="store_true",
        help="List past sessions with IDs, titles, and project directories, then exit.",
    )
    args = parser.parse_args()

    # Handle --list-sessions: print session list and exit
    if args.list_sessions:
        import json
        from agent.infrastructure.persistence.session_files import SessionFiles
        from agent.infrastructure.persistence.session_index_repository import SessionIndexRepository

        # Scan ALL mode subdirs so sessions from any mode are visible
        sessions_root = args.session_dir or str(Config.QUANORA_HOME / ".quanora" / "sessions")
        all_sessions: list[dict] = []
        mode_subdirs = ["default", "self-dev", "self-doc", "quant-research"]

        for subdir in mode_subdirs:
            candidate = os.path.join(sessions_root, subdir)
            index_path = os.path.join(candidate, "index.json")
            if os.path.exists(index_path):
                repo = SessionIndexRepository(SessionFiles(), index_path)
                index_data = repo.load_index()
                for s in index_data.get("sessions", []):
                    s["_mode"] = subdir
                all_sessions.extend(index_data.get("sessions", []))

        # Also check sessions_root itself (flat layout without mode subdir)
        root_index = os.path.join(sessions_root, "index.json")
        if os.path.exists(root_index) and not any(
            os.path.exists(os.path.join(sessions_root, s, "index.json")) for s in mode_subdirs
        ):
            repo = SessionIndexRepository(SessionFiles(), root_index)
            index_data = repo.load_index()
            for s in index_data.get("sessions", []):
                s["_mode"] = "default"
            all_sessions.extend(index_data.get("sessions", []))

        if not all_sessions:
            print("No sessions found.")
            sys.exit(0)

        # Sort by created_at descending (newest first)
        all_sessions.sort(key=lambda s: s.get("created_at", ""), reverse=True)

        print(f"{'Session ID':<32} {'Mode':<16} {'Title':<44} {'Project Dir'}")
        print("-" * 130)
        for s in all_sessions:
            sid = s.get("id", "?")
            mode = s.get("_mode", "default")
            title = s.get("title", "Untitled")[:42]
            pdir = s.get("project_dir", "")
            print(f"{sid:<32} {mode:<16} {title:<44} {pdir}")
        print()
        print(f"Total: {len(all_sessions)} sessions")
        print(f"To resume a session: python main.py --session <SESSION_ID>")
        sys.exit(0)
    

    # Handle --session <ID> auto-resolution: if the user specifies a session
    # ID without also specifying --session-dir, scan ALL mode subdirs to find
    # it and auto-set the correct session_dir (and mode flags).
    if args.session and args.session_dir is None:
        import json as _json
        _sessions_root = str(Config.QUANORA_HOME / ".quanora" / "sessions")
        _mode_subdirs = ["default", "self-dev", "self-doc", "quant-research"]
        _found = False
        for _subdir in _mode_subdirs:
            _idx = os.path.join(_sessions_root, _subdir, "index.json")
            if os.path.exists(_idx):
                try:
                    with open(_idx) as _f:
                        _data = _json.load(_f)
                    for _s in _data.get("sessions", []):
                        if _s.get("id") == args.session:
                            args.session_dir = os.path.join(_sessions_root, _subdir)
                            # Auto-set mode flags so workspace guard etc. match
                            if _subdir == "self-dev":
                                args.self_dev = True
                            elif _subdir == "self-doc":
                                args.self_doc = True
                            elif _subdir == "quant-research":
                                args.quant_research = True
                            print(
                                f"[resume] session {args.session} found in {_subdir} mode",
                                file=sys.stderr,
                            )
                            _found = True
                            break
                except (OSError, _json.JSONDecodeError):
                    pass
            if _found:
                break
        if not _found:
            # Also check flat layout (no mode subdir)
            _root_idx = os.path.join(_sessions_root, "index.json")
            if os.path.exists(_root_idx):
                try:
                    with open(_root_idx) as _f:
                        _data = _json.load(_f)
                    for _s in _data.get("sessions", []):
                        if _s.get("id") == args.session:
                            args.session_dir = _sessions_root
                            print(
                                f"[resume] session {args.session} found in default location",
                                file=sys.stderr,
                            )
                            _found = True
                            break
                except (OSError, _json.JSONDecodeError):
                    pass

    Config.validate()
    if args.allow_unsafe_bash:
        os.environ["AGENT_ALLOW_UNSAFE_BASH"] = "1"

    # Self-dev mode: swap the workspace guard BEFORE bootstrap so every
    # downstream component (tools, prompts, CLI) sees the new boundary.
    if args.self_dev:
        new_guard = settings_mod.enable_self_dev_mode()
        print(
            f"[self-dev] workspace = {new_guard.root}",
            file=sys.stderr,
        )
        print(
            f"[self-dev] protected paths ({len(new_guard.protected_paths)}): "
            + ", ".join(p.name for p in new_guard.protected_paths),
            file=sys.stderr,
        )
        # Default session dir for self-dev runs: keep them out of the
        # user's normal session log so a normal `--resume-latest` doesn't
        # accidentally drag a self-dev session into a user project.
        if args.session_dir is None:
            args.session_dir = str(Config.QUANORA_HOME / ".quanora" / "sessions" / "self-dev")

    # Self-doc mode: same principle as self-dev, but only .md writes are
    # allowed inside the protected Quanora repo tree.
    if args.self_doc and not args.self_dev:
        new_guard = settings_mod.enable_self_doc_mode()
        print(
            f"[self-doc] workspace = {new_guard.root}",
            file=sys.stderr,
        )
        print(
            f"[self-doc] protected paths ({len(new_guard.protected_paths)}): "
            + ", ".join(p.name for p in new_guard.protected_paths),
            file=sys.stderr,
        )
        print(
            "[self-doc] allowed write extensions: "
            + ", ".join(new_guard._cfg.protected_write_extensions),
            file=sys.stderr,
        )
        # Separate session directory for self-doc runs.
        if args.session_dir is None:
            args.session_dir = str(Config.QUANORA_HOME / ".quanora" / "sessions" / "self-doc")

    # Quant-research mode: systematic quant research workflow with
    # enforced data integrity, hypothesis lifecycle, and knowledge capture.
    if args.quant_research and not args.self_dev and not args.self_doc:
        new_guard = settings_mod.enable_self_quant_mode()
        print(
            f"[quant-research] workspace = {new_guard.root}",
            file=sys.stderr,
        )
        print(
            f"[quant-research] protected paths ({len(new_guard.protected_paths)}): "
            + ", ".join(p.name for p in new_guard.protected_paths),
            file=sys.stderr,
        )
        # Separate session directory for quant-research runs.
        if args.session_dir is None:
            args.session_dir = str(Config.QUANORA_HOME / ".quanora" / "sessions" / "quant-research")

    agent = BasicAgent(
        debug=args.debug,
        session_dir=args.session_dir,
        session_id=args.session,
        resume_latest=args.resume_latest,
        self_dev=args.self_dev,
        self_doc=args.self_doc,
        self_quant=args.quant_research,
    )
    agent.chat()
