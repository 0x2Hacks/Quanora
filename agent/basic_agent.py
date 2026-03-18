import json
import traceback
from openai import OpenAI
from config.settings import Config
from tools import TOOLS, TOOL_SCHEMAS
from agent.prompts import SYSTEM_PROMPT
from utils import print_rainbow_logo
from tools.base import tool_ok, tool_error
from session import SessionManager

class BasicAgent:
    def __init__(
        self,
        tools=None,
        debug: bool = False,
        session_dir: str | None = None,
        session_id: str | None = None,
        resume_latest: bool = False,
        resume_mode: str = "summary",
    ):
        self.client = Config.get_client()
        self.model = Config.DEFAULT_MODEL
        self.tool_schemas = tools or TOOL_SCHEMAS
        self.chat_history = []
        self.debug = debug
        self.session = SessionManager(
            session_dir=session_dir,
            session_id=session_id,
            resume_latest=resume_latest,
            resume_mode=resume_mode,
            model=self.model,
            system_prompt=SYSTEM_PROMPT,
            looks_like_tool_payload=self._looks_like_tool_payload,
        )

    def _looks_like_tool_payload(self, s: str) -> bool:
        if not s:
            return False
        t = s.lstrip()
        if not t.startswith("{"):
            return False
        try:
            obj = json.loads(t)
        except Exception:
            return False
        return isinstance(obj, dict) and "ok" in obj and "tool" in obj

    def _safe_execute_tool(self, name: str, args: dict, raw_args: str | None = None) -> str:
        if name not in TOOLS:
            return tool_error(name, f"Unknown tool: {name}", "ToolNotFound")
        try:
            result = TOOLS[name](**args)
            if isinstance(result, str) and self._looks_like_tool_payload(result):
                return result
            return tool_ok(name, result)
        except TypeError as e:
            meta = {}
            if raw_args:
                meta["raw_args"] = raw_args[:2000]
            return tool_error(name, str(e), type(e).__name__, meta=meta or None)
        except Exception as e:
            meta = {"traceback": traceback.format_exc()[-4000:]}
            if raw_args:
                meta["raw_args"] = raw_args[:2000]
            return tool_error(name, str(e), type(e).__name__, meta=meta)

    def run(self, query: str) -> str:
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": query}]
        while True:
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, tools=self.tool_schemas, tool_choice="auto"
            )
            msg = resp.choices[0].message
            messages.append(msg)

            if msg.content and not msg.tool_calls:
                return msg.content

            if msg.tool_calls:
                for tc in msg.tool_calls:
                    raw_args = tc.function.arguments or ""
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except Exception as e:
                        result = tool_error(tc.function.name, f"Invalid tool arguments JSON: {e}", "ToolArgsJSONError", meta={"raw_args": raw_args[:2000]})
                        messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                        continue
                    result = self._safe_execute_tool(tc.function.name, args, raw_args=raw_args)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": result})

    def chat(self):
        print_rainbow_logo()
        if self.debug:
            print(f"Chain Peer v0.1(Debug Mode: {self.debug}) 输入 'quit' 退出")
        else:
            print(f"Chain Peer v0.1")
            print("Welcome back!")
        print("-" * 50)
        try:
            self.session.ensure_session()
        except Exception as e:
            print(str(e))
            return
        self.session.initialize_history()
        self.chat_history = self.session.chat_history
        if self.session.loaded_existing:
            print("\n[历史会话]")
            for msg in self.chat_history:
                role = msg.get("role")
                content = msg.get("content", "")
                if role in {"assistant", "user"} and content:
                    print(f"{role}: {content}")

        while True:
            try:
                user_input = input("\n> ").strip()
            except KeyboardInterrupt:
                print("\n再见！👋")
                break
            if user_input.lower() in ['quit', 'exit', 'q']:
                print("再见！👋")
                break
            if not user_input:
                continue

            print("\nAgent: ", end="", flush=True)
            self.chat_history.append({"role": "user", "content": user_input})
            self.session.persist_message("user", user_input)

            try:
                while True:
                    if self.debug:
                        resp = self.client.chat.completions.create(
                            model=self.model, messages=self.chat_history,
                            tools=self.tool_schemas, tool_choice="auto", stream=False
                        )
                        msg = resp.choices[0].message
                        print(msg)
                        if msg.content:
                            self.chat_history.append({"role": "assistant", "content": msg.content})
                            self.session.persist_message("assistant", msg.content)
                        
                        if msg.tool_calls:
                            self.chat_history.append(msg)
                            self.session.persist_message(
                                "assistant",
                                "",
                                meta={"tool_calls": [{"id": tc.id, "name": tc.function.name} for tc in msg.tool_calls]},
                            )
                            for tc in msg.tool_calls:
                                print(f"\n[Debug] Tool Call: {tc.function.name}({tc.function.arguments})")
                                raw_args = tc.function.arguments or ""
                                ts_start = self.session.now_iso()
                                try:
                                    args = json.loads(raw_args) if raw_args else {}
                                except Exception as e:
                                    args = {}
                                    result = tool_error(tc.function.name, f"Invalid tool arguments JSON: {e}", "ToolArgsJSONError", meta={"raw_args": raw_args[:2000]})
                                    ts_end = self.session.now_iso()
                                    self.session.persist_tool_call(tc.id, tc.function.name, args, raw_args, ts_start, ts_end, result)
                                    print(f"[Debug] Tool executed. Tool Result: {result}")
                                    self.chat_history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                                    self.session.persist_message("tool", "", tool_call_id=tc.id, tool_name=tc.function.name)
                                    continue
                                result = self._safe_execute_tool(tc.function.name, args, raw_args=raw_args)
                                ts_end = self.session.now_iso()
                                self.session.persist_tool_call(tc.id, tc.function.name, args, raw_args, ts_start, ts_end, result)
                                print(f"[Debug] Tool executed. Tool Result: {result}")
                                self.chat_history.append({"role": "tool", "tool_call_id": tc.id, "content": result})
                                self.session.persist_message("tool", "", tool_call_id=tc.id, tool_name=tc.function.name)
                                
                                if not msg.content:
                                    print()
                        else:
                            break
                    else:
                        resp = self.client.chat.completions.create(
                            model=self.model, messages=self.chat_history,
                            tools=self.tool_schemas, tool_choice="auto", stream=True
                        )

                        tool_calls, content_parts = [], []

                        for chunk in resp:
                            delta = chunk.choices[0].delta
                            if delta.content:
                                print(delta.content, end="", flush=True)
                                content_parts.append(delta.content)
                            if delta.tool_calls:
                                for tc in delta.tool_calls:
                                    idx = tc.index
                                    while len(tool_calls) <= idx:
                                        tool_calls.append({"id": "", "name": "", "arguments": ""})
                                    if tc.id: tool_calls[idx]["id"] = tc.id
                                    if tc.function:
                                        if tc.function.name: tool_calls[idx]["name"] = tc.function.name
                                        if tc.function.arguments: tool_calls[idx]["arguments"] += tc.function.arguments

                        if content_parts:
                            content_text = "".join(content_parts)
                            self.chat_history.append({"role": "assistant", "content": content_text})
                            self.session.persist_message("assistant", content_text)

                        if tool_calls:
                            msg = {"role": "assistant", "tool_calls": [
                                {"id": tc["id"], "type": "function", "function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                for tc in tool_calls
                            ]}
                            self.chat_history.append(msg)
                            self.session.persist_message(
                                "assistant",
                                "",
                                meta={"tool_calls": [{"id": tc["id"], "name": tc["name"]} for tc in tool_calls]},
                            )

                            for tc in tool_calls:
                                raw_args = tc.get("arguments") or ""
                                ts_start = self.session.now_iso()
                                try:
                                    args = json.loads(raw_args) if raw_args else {}
                                except Exception as e:
                                    args = {}
                                    result = tool_error(tc["name"], f"Invalid tool arguments JSON: {e}", "ToolArgsJSONError", meta={"raw_args": raw_args[:2000]})
                                    ts_end = self.session.now_iso()
                                    self.session.persist_tool_call(tc["id"], tc["name"], args, raw_args, ts_start, ts_end, result)
                                    self.chat_history.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                                    self.session.persist_message("tool", "", tool_call_id=tc["id"], tool_name=tc["name"])
                                    continue
                                result = self._safe_execute_tool(tc["name"], args, raw_args=raw_args)
                                ts_end = self.session.now_iso()
                                self.session.persist_tool_call(tc["id"], tc["name"], args, raw_args, ts_start, ts_end, result)
                                self.chat_history.append({"role": "tool", "tool_call_id": tc["id"], "content": result})
                                self.session.persist_message("tool", "", tool_call_id=tc["id"], tool_name=tc["name"])
                                print()
                            
                        else:
                            break

                print()

            except Exception as e:
                print(f"\nError: {e}")
