"""Runtime orchestration for the Agent framework."""

__all__ = [
    "AsyncRuntimeFacade",
    "AsyncTurnRunner",
    "AsyncToolCallProcessor",
    "MessageStreamParser"
]


def __getattr__(name):
    if name == "AsyncRuntimeFacade":
        from .async_runtime_facade import AsyncRuntimeFacade
        return AsyncRuntimeFacade
    if name == "AsyncTurnRunner":
        from .async_turn_runner import AsyncTurnRunner
        return AsyncTurnRunner
    if name == "AsyncToolCallProcessor":
        from .async_tool_call_processor import AsyncToolCallProcessor
        return AsyncToolCallProcessor
    if name == "MessageStreamParser":
        from .message_stream_parser import MessageStreamParser
        return MessageStreamParser
    raise AttributeError(name)
