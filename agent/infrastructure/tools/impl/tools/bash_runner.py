"""Executes bash commands asynchronously and handles streams."""

from __future__ import annotations

import asyncio
import os
import subprocess
import threading
from collections import deque
from typing import AsyncIterator

from agent.domain.events import RuntimeEvent, ToolProgressEvent, ToolResultEvent
from agent.domain.jobs import ToolExecutionResult
from agent.domain.tool_result import tool_error, tool_ok
from .bash_session_pool import ShellState


class BashRunner:
    """Executes bash commands and captures their streams."""

    def __init__(self, timeout: int = 120):
        self.timeout = timeout
        self.HEAD_LIMIT = 10000
        self.TAIL_LIMIT = 10000

    def run_sync(self, command: str, state: ShellState, output_callback=None) -> ToolExecutionResult:
        """Run a command synchronously, mostly for compatibility.
        If output_callback is provided, it will be called with incremental chunks.
        """
        # Handle internal 'cd' commands
        if command.strip().startswith("cd "):
            target_dir = command.strip()[3:].strip()
            if target_dir.startswith("~"):
                target_dir = os.path.expanduser(target_dir)
            
            new_path = os.path.abspath(os.path.join(state.cwd, target_dir))
            
            if os.path.exists(new_path) and os.path.isdir(new_path):
                state.cwd = new_path
                return ToolExecutionResult(
                    status="ok",
                    result_str=tool_ok("bash", {"stdout": f"Changed directory to: {state.cwd}", "stderr": "", "exit_code": 0, "cwd": state.cwd})
                )
            else:
                return ToolExecutionResult(
                    status="ok",
                    result_str=tool_ok("bash", {"stdout": "", "stderr": f"cd: no such file or directory: {target_dir}", "exit_code": 1, "cwd": state.cwd})
                )

        shell_cmd = [state.shell_executable]
        if "bash" in state.shell_executable.lower():
            shell_cmd.extend(["-c", command])
        elif "powershell" in state.shell_executable.lower():
            shell_cmd.extend(["-Command", command])
        else:
            shell_cmd.extend(["/c", command])

        try:
            process = subprocess.Popen(
                shell_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=state.cwd,
                env=state.env
            )
            
            stdout_head = []
            stdout_tail = deque(maxlen=self.TAIL_LIMIT)
            stdout_len = [0]
            
            stderr_head = []
            stderr_tail = deque(maxlen=self.TAIL_LIMIT)
            stderr_len = [0]
            
            def read_stream(stream, head_list, tail_deque, length_counter, is_stdout=True):
                while True:
                    chunk = stream.read(4096)
                    if not chunk:
                        break
                        
                    if output_callback:
                        output_callback(chunk, "stdout" if is_stdout else "stderr")
                    
                    chunk_len = len(chunk)
                    current_len = length_counter[0]
                    length_counter[0] += chunk_len
                    
                    head_space = self.HEAD_LIMIT - current_len
                    if head_space > 0:
                        if chunk_len <= head_space:
                            head_list.append(chunk)
                        else:
                            head_list.append(chunk[:head_space])
                            tail_deque.extend(chunk[head_space:])
                    else:
                        tail_deque.extend(chunk)

            t_out = threading.Thread(target=read_stream, args=(process.stdout, stdout_head, stdout_tail, stdout_len, True))
            t_err = threading.Thread(target=read_stream, args=(process.stderr, stderr_head, stderr_tail, stderr_len, False))
            
            t_out.start()
            t_err.start()
            
            timeout_msg = ""
            try:
                process.wait(timeout=self.timeout)
            except subprocess.TimeoutExpired:
                process.kill()
                timeout_msg = f"\n\n[PROCESS TERMINATED: Command timed out after {self.timeout} seconds.]"
                process.wait()
                
            t_out.join()
            t_err.join()

            def build_output(head, tail, total_len):
                if total_len <= self.HEAD_LIMIT:
                    return "".join(head)
                if total_len <= self.HEAD_LIMIT + self.TAIL_LIMIT:
                    return "".join(head) + "".join(tail)
                return "".join(head) + "\n\n...[OUTPUT TRUNCATED]...\n\n" + "".join(tail)

            stdout_final = build_output(stdout_head, stdout_tail, stdout_len[0])
            stderr_final = build_output(stderr_head, stderr_tail, stderr_len[0])
            
            if timeout_msg:
                stderr_final += timeout_msg
                
            return ToolExecutionResult(
                status="ok",
                result_str=tool_ok("bash", {
                    "stdout": stdout_final.strip(), 
                    "stderr": stderr_final.strip(), 
                    "exit_code": process.returncode, 
                    "cwd": state.cwd
                }),
                exit_code=process.returncode
            )

        except Exception as e:
            return ToolExecutionResult(
                status="error",
                error_msg=str(e),
                error_type=type(e).__name__
            )
