"""测试 ChatCLI 中批量工具调用的分组渲染逻辑。

核心验证点：
1. ToolBatchStartedEvent 初始化 _batch_tool_counter 和 _batch_tool_totals
2. ToolCallStartedEvent 在重复工具时显示 (1/3) 累进序号
3. ToolResultEvent 在重复工具时显示分组序号
4. 单次工具调用时不显示序号
"""
import pytest
from unittest.mock import MagicMock, patch
from agent.domain.events import (
    ToolBatchStartedEvent,
    ToolCallStartedEvent,
    ToolResultEvent,
)


def _make_cli():
    """构造一个最小化的 ChatCLI 实例（仅用于测试事件处理）"""
    from agent.interfaces.cli.chat_cli import ChatCLI

    runtime = MagicMock()
    session = MagicMock()
    cli = ChatCLI(runtime=runtime, session=session, debug=False, self_dev=False)
    # 替换 _console 为 mock 以便于断言输出
    cli._console = MagicMock()
    cli._streaming_renderer = MagicMock()
    return cli


class TestBatchToolCounterInit:
    """ToolBatchStartedEvent 应正确初始化批次计数器"""

    def test_single_tool_batch(self):
        cli = _make_cli()
        event = ToolBatchStartedEvent(count=1, tool_names=["read_file"])
        cli._on_event(event)
        assert cli._batch_tool_totals == {"read_file": 1}
        assert cli._batch_tool_counter == {"read_file": 0}
        assert cli._batch_result_counter == {}

    def test_multi_same_tool_batch(self):
        cli = _make_cli()
        event = ToolBatchStartedEvent(count=3, tool_names=["read_file", "read_file", "read_file"])
        cli._on_event(event)
        assert cli._batch_tool_totals == {"read_file": 3}
        assert cli._batch_tool_counter == {"read_file": 0}

    def test_mixed_tool_batch(self):
        cli = _make_cli()
        event = ToolBatchStartedEvent(
            count=5, tool_names=["bash", "bash", "read_file", "grep", "grep"]
        )
        cli._on_event(event)
        assert cli._batch_tool_totals == {"bash": 2, "read_file": 1, "grep": 2}
        assert cli._batch_tool_counter == {"bash": 0, "read_file": 0, "grep": 0}

    def test_batch_summary_rendering(self):
        """合并展示格式：bash×2, read_file, grep×2"""
        cli = _make_cli()
        event = ToolBatchStartedEvent(
            count=5, tool_names=["bash", "bash", "read_file", "grep", "grep"]
        )
        cli._on_event(event)
        # 检查 console.print 的调用内容
        print_calls = cli._console.print.call_args_list
        batch_line = print_calls[0][0][0]  # 第一个 print 的第一个参数
        assert "bash×2" in batch_line
        assert "grep×2" in batch_line
        assert "read_file" in batch_line
        # 单次工具名不应带 ×1
        assert "read_file×1" not in batch_line


class TestToolCallStartedGroupIndex:
    """ToolCallStartedEvent 应在重复工具时显示分组序号"""

    def test_single_tool_no_index(self):
        """单次调用不显示序号"""
        cli = _make_cli()
        cli._batch_tool_totals = {"read_file": 1}
        cli._batch_tool_counter = {"read_file": 0}
        event = ToolCallStartedEvent(tool_name="read_file", args_preview="file.py")
        cli._on_event(event)
        # 检查输出不含 (1/1)
        print_calls = cli._console.print.call_args_list
        tool_line = print_calls[0][0][0]
        assert "(1/1)" not in tool_line
        assert "🔧 read_file" in tool_line

    def test_multi_tool_shows_incrementing_index(self):
        """多次调用逐步显示 (1/3), (2/3), (3/3)"""
        cli = _make_cli()
        cli._batch_tool_totals = {"read_file": 3}
        cli._batch_tool_counter = {"read_file": 0}

        # 第一次
        event1 = ToolCallStartedEvent(tool_name="read_file", args_preview="a.py")
        cli._on_event(event1)
        # print 调用两次: 工具名行 + preview行，取倒数第二行（工具名行）
        calls = cli._console.print.call_args_list
        line1 = calls[-2][0][0]  # 工具名行是倒数第二行
        assert "(1/3)" in line1

        # 第二次
        event2 = ToolCallStartedEvent(tool_name="read_file", args_preview="b.py")
        cli._on_event(event2)
        calls = cli._console.print.call_args_list
        line2 = calls[-2][0][0]
        assert "(2/3)" in line2

        # 第三次
        event3 = ToolCallStartedEvent(tool_name="read_file", args_preview="c.py")
        cli._on_event(event3)
        calls = cli._console.print.call_args_list
        line3 = calls[-2][0][0]
        assert "(3/3)" in line3


class TestToolResultGroupIndex:
    """ToolResultEvent 应在重复工具时显示分组序号"""

    def test_single_result_no_index(self):
        cli = _make_cli()
        cli._batch_tool_totals = {"bash": 1}
        cli._batch_result_counter = {}
        event = ToolResultEvent(tool_name="bash", status="ok", summary="done", duration_ms=10)
        cli._on_event(event)
        line = cli._console.print.call_args_list[-1][0][0]
        assert "(1/1)" not in line

    def test_multi_result_shows_index(self):
        cli = _make_cli()
        cli._batch_tool_totals = {"bash": 2}
        cli._batch_result_counter = {}

        # 第一个结果
        event1 = ToolResultEvent(tool_name="bash", status="ok", summary="ls", duration_ms=5)
        cli._on_event(event1)
        line1 = cli._console.print.call_args_list[-1][0][0]
        assert "(1/2)" in line1

        # 第二个结果
        event2 = ToolResultEvent(tool_name="bash", status="ok", summary="pwd", duration_ms=3)
        cli._on_event(event2)
        line2 = cli._console.print.call_args_list[-1][0][0]
        assert "(2/2)" in line2

    def test_mixed_batch_result_indexing(self):
        """混合批次：bash×2 + read_file×1"""
        cli = _make_cli()
        cli._batch_tool_totals = {"bash": 2, "read_file": 1}
        cli._batch_result_counter = {}

        # bash 第1个结果
        ev1 = ToolResultEvent(tool_name="bash", status="ok", summary="ls", duration_ms=5)
        cli._on_event(ev1)
        assert "(1/2)" in cli._console.print.call_args_list[-1][0][0]

        # read_file 结果（单次，不显示序号）
        ev2 = ToolResultEvent(tool_name="read_file", status="ok", summary="read", duration_ms=8)
        cli._on_event(ev2)
        assert "(1/1)" not in cli._console.print.call_args_list[-1][0][0]

        # bash 第2个结果
        ev3 = ToolResultEvent(tool_name="bash", status="ok", summary="pwd", duration_ms=3)
        cli._on_event(ev3)
        assert "(2/2)" in cli._console.print.call_args_list[-1][0][0]


class TestSessionStoreAttribute:
    """验证 ChatCLI.__init__ 正确设置了 _session_store 属性"""

    def test_session_store_is_set(self):
        from agent.interfaces.cli.chat_cli import ChatCLI

        session_mock = MagicMock()
        cli = ChatCLI(runtime=MagicMock(), session=session_mock, debug=False, self_dev=False)
        assert cli._session_store is session_mock
        assert cli._session is session_mock

    def test_session_store_has_persist_method(self):
        """确保 _session_store 可以调用 persist_turn_cost"""
        from agent.interfaces.cli.chat_cli import ChatCLI
        from agent.infrastructure.persistence.async_jsonl_session_store import AsyncJsonlSessionStore

        # 使用真实的 AsyncJsonlSessionStore 确认接口
        store = AsyncJsonlSessionStore(session_dir="/tmp/test_session_store_attr")
        cli = ChatCLI(runtime=MagicMock(), session=store, debug=False, self_dev=False)
        assert hasattr(cli._session_store, "persist_turn_cost")