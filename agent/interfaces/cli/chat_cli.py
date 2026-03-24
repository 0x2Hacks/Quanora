"""Command-line interface adapter."""

from __future__ import annotations

from utils import print_rainbow_logo


class ChatCLI:
    """Interactive CLI that delegates core behavior to application runtime."""

    def __init__(self, runtime, session, debug: bool = False):
        self._runtime = runtime
        self._session = session
        self._debug = debug
        self.chat_history: list[dict] = []

    def start(self) -> None:
        self._render_banner()
        try:
            self._session.ensure_session()
        except Exception as exc:
            print(str(exc))
            return

        self._session.initialize_history()
        self.chat_history = self._session.chat_history
        self._render_loaded_messages()
        self._loop()

    def _render_banner(self) -> None:
        print_rainbow_logo()
        if self._debug:
            print("Chain Peer v0.1 (Debug Mode: True) 输入 'quit' 退出")
        else:
            print("Chain Peer v0.1")
            print("Welcome back!")
        print("-" * 50)

    def _render_loaded_messages(self) -> None:
        if not self._session.loaded_existing:
            return
        print("\n[历史会话]")
        for message in self.chat_history:
            role = message.get("role")
            content = message.get("content", "")
            if role in {"assistant", "user"} and content:
                print(f"{role}: {content}")

    def _loop(self) -> None:
        while True:
            try:
                user_input = input("\n> ").strip()
            except KeyboardInterrupt:
                print("\n再见！👋")
                break

            if user_input.lower() in {"quit", "exit", "q"}:
                print("再见！👋")
                break
            if not user_input:
                continue

            print("\nAgent: ", end="", flush=True)
            self.chat_history.append({"role": "user", "content": user_input})
            self._session.persist_message("user", user_input)

            try:
                self._runtime.process_user_turn(
                    chat_history=self.chat_history,
                    session=self._session,
                    on_content=self._on_content,
                    on_debug=self._on_debug if self._debug else None,
                )
                print()
            except Exception as exc:
                print(f"\nError: {exc}")

    def _on_content(self, text: str) -> None:
        print(text, end="", flush=True)

    def _on_debug(self, message: str) -> None:
        print(f"\n[Debug] {message}")
