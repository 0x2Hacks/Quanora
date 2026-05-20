import io
import os
import sys
from contextlib import redirect_stdout
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.domain.events import TurnFailedEvent
from agent.interfaces.cli.chat_cli import ChatCLI


def test_chat_cli_turn_failed_event_prints_error_field() -> None:
    cli = ChatCLI(runtime=None, session=None)
    output = io.StringIO()

    with redirect_stdout(output):
        cli._on_event(TurnFailedEvent(error="boom"))

    text = output.getvalue()
    if "boom" not in text:
        raise AssertionError(f"Expected CLI failure output to include error field, got: {text!r}")
    if "unknown" in text:
        raise AssertionError(f"Did not expect fallback output when error exists, got: {text!r}")
