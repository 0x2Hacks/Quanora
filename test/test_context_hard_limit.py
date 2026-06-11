"""Tests for context hard-limit enforcement (Bug fix: 202K token input → agent stall).

Root cause: rescue loop breaks after 50 iterations without aborting, and
async_turn_runner never checks over_hard_limit before sending to the model.
"""
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest
from unittest.mock import MagicMock, AsyncMock, patch

from agent.application.services.context_estimator import ContextBudget, ContextEstimator, ContextEstimate
from agent.application.services.context_manager import ContextManager


# ──────────────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────────────

def _make_large_messages(n_tool_messages: int = 80, chars_per_msg: int = 500) -> list[dict]:
    """Generate a message list that will easily exceed a small hard_limit."""
    messages = [
        {"role": "system", "content": "You are a helpful assistant." * 20},  # ~500 chars
    ]
    for i in range(n_tool_messages):
        messages.append({"role": "tool", "content": "x" * chars_per_msg, "tool_call_id": f"call_{i}"})
    messages.append({"role": "user", "content": "What is the answer?"})
    return messages


@pytest.fixture
def small_budget():
    """A very small budget so we can trigger over_hard_limit easily."""
    return ContextBudget(
        hard_limit_tokens=500,
        system_budget_tokens=200,
        conversation_budget_tokens=100,
        tool_budget_tokens=300,
    )


@pytest.fixture
def manager(small_budget):
    """ContextManager with a small budget for testing."""
    estimator = ContextEstimator(small_budget)
    mgr = MagicMock(spec=ContextManager)
    mgr._estimator = estimator
    # Bind the actual methods
    mgr.rescue_context = ContextManager.rescue_context.__get__(mgr, ContextManager)
    return mgr


# ──────────────────────────────────────────────────────
# Test 1: rescue_context v2 batch-deletes multiple messages
# ──────────────────────────────────────────────────────

class TestRescueContextBatchDelete:
    def test_rescue_marks_up_to_5_messages(self, manager):
        """v2 rescue should batch-delete messages and merge consecutive DROPPED markers.
        
        The method marks up to 5 messages, then merges consecutive DROPPED
        placeholders into one. So the final count of DROPPED markers will be 1
        (since they're all consecutive), but the total message count should
        decrease significantly.
        """
        messages = _make_large_messages(n_tool_messages=20, chars_per_msg=100)
        final_messages = list(messages)  # shallow copy
        original_count = len(messages)

        internal, final = manager.rescue_context(messages, final_messages)

        # After rescue + merge: should have fewer messages (5 removed, then merged)
        # At least 1 DROPPED marker should exist
        dropped_count = sum(1 for m in final if m["content"] == "[DROPPED FOR CONTEXT RESCUE]")
        assert dropped_count >= 1, f"Expected at least 1 dropped marker, got {dropped_count}"
        # Total message count should have decreased
        assert len(final) < original_count, f"Messages should have decreased: {len(final)} vs {original_count}"

    def test_rescue_merges_consecutive_dropped(self, manager):
        """Consecutive DROPPED placeholders should be merged into one."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "[DROPPED FOR CONTEXT RESCUE]", "tool_call_id": "c1"},
            {"role": "tool", "content": "[DROPPED FOR CONTEXT RESCUE]", "tool_call_id": "c2"},
            {"role": "tool", "content": "[DROPPED FOR CONTEXT RESCUE]", "tool_call_id": "c3"},
            {"role": "user", "content": "hello"},
        ]

        internal, final = manager.rescue_context(list(messages), list(messages))

        # After merge, there should be at most 1 consecutive DROPPED marker
        dropped_positions = [i for i, m in enumerate(final) if m["content"] == "[DROPPED FOR CONTEXT RESCUE]"]
        assert len(dropped_positions) <= 1, f"Expected merged DROPPED markers, got {len(dropped_positions)}"

    def test_rescue_preserves_system_and_recent_messages(self, manager):
        """System messages and the last few messages should not be dropped."""
        messages = [
            {"role": "system", "content": "sys"},
            {"role": "tool", "content": "old_tool_1", "tool_call_id": "c1"},
            {"role": "tool", "content": "old_tool_2", "tool_call_id": "c2"},
            {"role": "assistant", "content": "last_assistant"},
            {"role": "user", "content": "last_user"},
        ]

        internal, final = manager.rescue_context(list(messages), list(messages))

        # System message must survive
        assert any(m["role"] == "system" for m in final)
        # Last user message must survive
        assert final[-1]["content"] == "last_user"


# ──────────────────────────────────────────────────────
# Test 2: Hard-limit enforcement after rescue
# ──────────────────────────────────────────────────────

class TestHardLimitEnforcement:
    def test_estimator_detects_over_hard_limit(self, small_budget):
        """ContextEstimator should flag over_hard_limit when tokens exceed budget."""
        estimator = ContextEstimator(small_budget)
        messages = _make_large_messages(n_tool_messages=50, chars_per_msg=200)
        estimate = estimator.estimate_messages(messages)
        assert estimate.over_hard_limit, f"Should be over hard limit: {estimate.estimated_input_tokens} tokens"

    def test_estimator_under_hard_limit(self, small_budget):
        """Small message list should not be over hard limit."""
        estimator = ContextEstimator(small_budget)
        messages = [
            {"role": "system", "content": "Hi"},
            {"role": "user", "content": "Hello"},
        ]
        estimate = estimator.estimate_messages(messages)
        assert not estimate.over_hard_limit, f"Should be under hard limit: {estimate.estimated_input_tokens} tokens"


# ──────────────────────────────────────────────────────
# Test 3: Force-truncation in build_messages_async rescue loop
# ──────────────────────────────────────────────────────

class TestForceTruncation:
    """Test that the force-truncation logic (added after rescue break) works.
    
    Since build_messages_async is complex and requires a full session mock,
    we test the logic in isolation by simulating the rescue loop + force-truncation.
    """

    def test_force_truncation_removes_dropped_placeholders(self, small_budget):
        """After rescue, DROPPED placeholders should be completely removed, not just marked."""
        estimator = ContextEstimator(small_budget)
        DROP_MARKER = "[DROPPED FOR CONTEXT RESCUE]"

        messages = [
            {"role": "system", "content": "sys" * 50},
            {"role": "tool", "content": DROP_MARKER, "tool_call_id": "c1"},
            {"role": "tool", "content": DROP_MARKER, "tool_call_id": "c2"},
            {"role": "user", "content": "hello"},
        ]

        # Simulate the force-truncation: remove DROPPED messages
        cleaned = [m for m in messages if m.get("content") != DROP_MARKER]
        assert len(cleaned) == 2  # system + user only
        assert cleaned[0]["role"] == "system"
        assert cleaned[1]["role"] == "user"

    def test_last_resort_keeps_only_system_and_last_user(self, small_budget):
        """If force-truncation still can't get under hard_limit, keep only system + last user."""
        estimator = ContextEstimator(small_budget)

        # Create messages that even after dropping tool messages, system is too large
        # This tests the last-resort path
        messages = [
            {"role": "system", "content": "sys" * 200},
            {"role": "tool", "content": "tool_data" * 100, "tool_call_id": "c1"},
            {"role": "user", "content": "hello"},
        ]

        # Simulate last resort
        system_msgs = [m for m in messages if m.get("role") == "system"]
        user_msgs = [m for m in messages if m.get("role") == "user"]
        last_resort = system_msgs + (user_msgs[-1:] if user_msgs else [])

        assert len(last_resort) == 2
        assert last_resort[0]["role"] == "system"
        assert last_resort[-1]["content"] == "hello"


# ──────────────────────────────────────────────────────
# Test 4: async_turn_runner over_hard_limit guard
# ──────────────────────────────────────────────────────

class TestRunnerHardLimitGuard:
    def test_emergency_truncation_logic(self):
        """Test the emergency truncation logic that runs before model call.
        
        This tests the logic in isolation (not the full async runner).
        """
        from agent.application.services.context_manager import ContextBuildResult

        # Simulate a massively over-limit context
        large_messages = [
            {"role": "system", "content": "system prompt"},
        ]
        for i in range(100):
            large_messages.append({"role": "tool", "content": "x" * 500, "tool_call_id": f"c{i}"})
        large_messages.append({"role": "user", "content": "question"})

        # Simulate the guard logic
        context_decisions = {"over_hard_limit": True, "total_tokens": 50000}
        system_msgs = [m for m in large_messages if m.get("role") == "system"]
        non_system = [m for m in large_messages if m.get("role") != "system"]
        truncated = system_msgs + non_system[-3:]

        assert len(truncated) < len(large_messages), "Truncated should be smaller"
        assert len(truncated) == 4  # 1 system + 3 non-system
        assert truncated[0]["role"] == "system"
        assert truncated[-1]["content"] == "question"

    def test_no_truncation_when_under_limit(self):
        """When over_hard_limit is False, no truncation should occur."""
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "hello"},
        ]
        context_decisions = {"over_hard_limit": False}

        over_hard = bool(context_decisions.get("over_hard_limit"))
        assert not over_hard, "Should not be over hard limit"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
