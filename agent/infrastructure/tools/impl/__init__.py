"""Default tool implementations and schemas."""

from __future__ import annotations

from typing import Callable

from .bash import bash, kill_shell
from .file_ops import edit_file, grep, list_files, read_file, write_file
from .schemas import TOOL_SCHEMAS
from .web import fetch_web_page, search_web

TOOLS: dict[str, Callable] = {
    "read_file": read_file,
    "write_file": write_file,
    "edit_file": edit_file,
    "list_files": list_files,
    "grep": grep,
    "bash": bash,
    "kill_shell": kill_shell,
    "search_web": search_web,
    "fetch_web_page": fetch_web_page,
}

__all__ = ["TOOLS", "TOOL_SCHEMAS"]
