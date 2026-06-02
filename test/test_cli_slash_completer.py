import os
import sys
from pathlib import Path

from prompt_toolkit.document import Document

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.interfaces.cli.commands.completer import SlashCommandCompleter


def _texts(completer: SlashCommandCompleter, text: str) -> list[str]:
    return [item.text for item in completer.get_completions(Document(text), None)]


def test_slash_completer_matches_command_prefix() -> None:
    completer = SlashCommandCompleter(["help", "status", "sessions"])

    assert _texts(completer, "/s") == ["/sessions", "/status"]


def test_slash_completer_ignores_non_slash_input() -> None:
    completer = SlashCommandCompleter(["help"])

    assert _texts(completer, "help") == []


def test_slash_completer_ignores_command_arguments() -> None:
    completer = SlashCommandCompleter(["model"])

    assert _texts(completer, "/model set") == []


def test_slash_completer_replaces_only_slash_token() -> None:
    completer = SlashCommandCompleter(["status"])
    completion = list(completer.get_completions(Document("  /st"), None))[0]

    assert completion.text == "/status"
    assert completion.start_position == -3


def main() -> int:
    test_slash_completer_matches_command_prefix()
    test_slash_completer_ignores_non_slash_input()
    test_slash_completer_ignores_command_arguments()
    test_slash_completer_replaces_only_slash_token()
    print("CLI slash completer tests passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
