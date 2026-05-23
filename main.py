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
    args = parser.parse_args()

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

    agent = BasicAgent(
        debug=args.debug,
        session_dir=args.session_dir,
        session_id=args.session,
        resume_latest=args.resume_latest,
        self_dev=args.self_dev,
        self_doc=args.self_doc,
    )
    agent.chat()
