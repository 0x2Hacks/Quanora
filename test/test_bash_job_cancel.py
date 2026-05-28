import unittest
import json
import asyncio

from agent.infrastructure.tools.impl.tools.bash import bash

class TestBashJobCancel(unittest.TestCase):
    # This test acts as a stub to verify the refactored bash runs.
    # True asynchronous cancellation will be tested more thoroughly in Phase 3
    # once start_job returns a real background job handle.
    # Here we just verify that bash doesn't crash with the new parameters.
    
    def test_bash_runs_with_new_signature(self):
        res = asyncio.run(bash("echo 'testing bash'", session_id="test_session"))
        parsed = json.loads(res)
        self.assertTrue(parsed["ok"])
        self.assertIn("testing bash", parsed["data"]["stdout"])

if __name__ == "__main__":
    unittest.main()
