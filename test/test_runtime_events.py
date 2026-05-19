import unittest
import json
import dataclasses
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from agent.domain.events import (
    RuntimeEvent,
    AssistantDeltaEvent,
    SkillActivatedEvent,
    ToolProgressEvent,
    TurnCompletedEvent
)


class TestRuntimeEvents(unittest.TestCase):
    def test_event_initialization(self):
        event = AssistantDeltaEvent(text="Hello")
        self.assertEqual(event.type, "assistant_delta")
        self.assertEqual(event.text, "Hello")
        self.assertTrue(isinstance(event.ts, str))

    def test_event_serialization(self):
        event = ToolProgressEvent(tool_call_id="call_123", tool_name="bash", payload={"stdout": "test"})
        # Should be easily serializable using dataclasses.asdict
        event_dict = dataclasses.asdict(event)
        self.assertEqual(event_dict["type"], "tool_progress")
        self.assertEqual(event_dict["tool_call_id"], "call_123")
        self.assertEqual(event_dict["tool_name"], "bash")
        self.assertEqual(event_dict["payload"], {"stdout": "test"})
        
        # Ensure it can be dumped to JSON
        json_str = json.dumps(event_dict)
        self.assertIn("tool_progress", json_str)
        self.assertIn("call_123", json_str)

    def test_inheritance(self):
        event = TurnCompletedEvent()
        self.assertTrue(isinstance(event, RuntimeEvent))
        self.assertEqual(event.type, "turn_completed")

    def test_skill_activated_event_round_trip(self):
        event = SkillActivatedEvent(
            ts="2026-05-19T00:00:00Z",
            skill_name="demo",
            reason="explicit_dollar_name",
            score=100,
            source="project",
            path="/tmp/demo/SKILL.md",
        )

        event_dict = event.to_dict()
        self.assertEqual(event_dict["type"], "skill_activated")
        self.assertEqual(event_dict["skill_name"], "demo")
        restored = RuntimeEvent.from_dict(event_dict)

        self.assertTrue(isinstance(restored, SkillActivatedEvent))
        self.assertEqual(restored.skill_name, "demo")
        self.assertEqual(restored.reason, "explicit_dollar_name")


if __name__ == "__main__":
    unittest.main()
