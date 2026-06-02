"""Prompt-toolkit completer for slash commands."""

from __future__ import annotations

from collections.abc import Iterable

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document


class SlashCommandCompleter(Completer):
    """Complete slash commands at the beginning of the current input."""

    def __init__(self, commands: Iterable[object]):
        entries: dict[str, str] = {}
        for command in commands:
            name = str(getattr(command, "name", command)).strip().lower()
            if not name:
                continue
            entries[name] = str(getattr(command, "description", "") or "").strip()
        self._commands = tuple(sorted(entries.items()))

    def get_completions(self, document: Document, complete_event):
        stripped = document.text_before_cursor.lstrip()
        if not stripped.startswith("/") or _has_command_args(stripped):
            return

        token = stripped[1:].lower()
        start_position = -len(stripped)
        for command, description in self._commands:
            if command.startswith(token):
                yield Completion(
                    f"/{command}",
                    start_position=start_position,
                    display=f"/{command}",
                    display_meta=description,
                )


def _has_command_args(value: str) -> bool:
    parts = value.split(maxsplit=1)
    return len(parts) > 1
