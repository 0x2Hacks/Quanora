"""Tests for creating a new plan after closing a completed plan in the same session.

Covers the fix for: 'Active plan already exists' error when creating a new plan
after the previous one was completed/closed in the same session.
"""
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
os.chdir(PROJECT_ROOT)
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pytest

from agent.infrastructure.plans.operations import (
    close_plan,
    create_plan,
    update_step,
)
from agent.infrastructure.plans.store import archive_completed_plan, plan_paths


@pytest.fixture
def session_dir():
    """Create a temporary session directory with env vars set."""
    tmp = tempfile.mkdtemp()
    session_id = "test-session"
    session_path = Path(tmp) / session_id
    session_path.mkdir(parents=True, exist_ok=True)

    old_root = os.environ.get("AGENT_SESSION_ROOT")
    old_id = os.environ.get("AGENT_SESSION_ID")
    os.environ["AGENT_SESSION_ROOT"] = tmp
    os.environ["AGENT_SESSION_ID"] = session_id

    yield session_path

    # Cleanup
    if old_root is not None:
        os.environ["AGENT_SESSION_ROOT"] = old_root
    else:
        os.environ.pop("AGENT_SESSION_ROOT", None)
    if old_id is not None:
        os.environ["AGENT_SESSION_ID"] = old_id
    else:
        os.environ.pop("AGENT_SESSION_ID", None)
    shutil.rmtree(tmp, ignore_errors=True)


def _complete_all_steps(plan: dict) -> dict:
    """Helper: mark all steps in the plan as completed, return updated plan."""
    from agent.infrastructure.plans.store import load_plan

    for step in plan.get("steps", []):
        sid = step["step_id"]
        if step.get("status") != "completed":
            plan, _, _ = load_plan()
            update_step(sid, {"status": "in_progress"}, expected_version=plan["version"])
            plan, _, _ = load_plan()
            update_step(sid, {"status": "completed"}, expected_version=plan["version"])
    # Reload final state
    plan, _, _ = load_plan()
    return plan


class TestCreatePlanAfterClose:
    """Verify that creating a new plan works after closing the previous one."""

    def test_create_plan_after_close_completed(self, session_dir):
        """Close a completed plan, then create a new one — should succeed."""
        # 1. Create first plan
        plan = create_plan(
            title="First Plan",
            goal="Do something",
            steps=[{"title": "Step A", "step_id": "sa"}],
        )
        assert plan["title"] == "First Plan"

        # 2. Complete all steps and close
        plan = _complete_all_steps(plan)
        plan = close_plan("First plan done", expected_version=plan["version"])
        assert plan["status"] == "completed"

        # 3. Create second plan — this should NOT raise "Active plan already exists"
        plan2 = create_plan(
            title="Second Plan",
            goal="Do something else",
            steps=[{"title": "Step B", "step_id": "sb"}],
        )
        assert plan2["title"] == "Second Plan"
        assert plan2["version"] == 1  # version resets for new plan

    def test_create_plan_fails_when_active(self, session_dir):
        """Creating a new plan while an active plan exists should still fail."""
        create_plan(
            title="Active Plan",
            goal="Still active",
            steps=[{"title": "Step A", "step_id": "sa"}],
        )

        # Try creating another — should raise
        with pytest.raises(ValueError, match="Active plan already exists"):
            create_plan(
                title="Another Plan",
                goal="Should fail",
                steps=[{"title": "Step B", "step_id": "sb"}],
            )

    def test_old_plan_archived_after_close(self, session_dir):
        """After closing a plan and creating a new one, the old plan should be archived."""
        # 1. Create and close first plan
        plan = create_plan(
            title="Old Plan",
            goal="To be archived",
            steps=[{"title": "Step A", "step_id": "sa"}],
        )
        plan = _complete_all_steps(plan)
        close_plan("Done", expected_version=plan["version"])

        # 2. Create new plan (triggers archiving of old plan)
        plan2 = create_plan(
            title="New Plan",
            goal="Fresh start",
            steps=[{"title": "Step B", "step_id": "sb"}],
        )
        assert plan2["title"] == "New Plan"

        # 3. Verify archive directory exists and contains old plan
        plan_file, events_file, _ = plan_paths()
        archive_dir = plan_file.parent / "archive"
        assert archive_dir.exists(), "Archive directory should exist"

        # There should be exactly one timestamped subdirectory
        archived_dirs = [d for d in archive_dir.iterdir() if d.is_dir()]
        assert len(archived_dirs) == 1, f"Expected 1 archived dir, got {len(archived_dirs)}"

        # The archived plan.json should contain the old plan
        archived_plan_file = archived_dirs[0] / "plan.json"
        assert archived_plan_file.exists(), "Archived plan.json should exist"
        archived_plan = json.loads(archived_plan_file.read_text())
        assert archived_plan["title"] == "Old Plan"
        assert archived_plan["status"] == "completed"

        # The current plan.json should contain the new plan
        current_plan = json.loads(plan_file.read_text())
        assert current_plan["title"] == "New Plan"

    def test_multiple_cycles(self, session_dir):
        """Multiple close→create cycles should all work."""
        for i in range(3):
            plan = create_plan(
                title=f"Plan {i}",
                goal=f"Goal {i}",
                steps=[{"title": f"Step {i}", "step_id": f"s{i}"}],
            )
            assert plan["title"] == f"Plan {i}", f"create_plan cycle {i} failed"

            plan = _complete_all_steps(plan)
            plan = close_plan(f"Cycle {i} done", expected_version=plan["version"])
            assert plan["status"] == "completed"

        # After 3 close→create cycles, the last closed plan is still on disk
        # (completed but not yet archived). Previous 2 are archived when the
        # next create_plan detected a completed plan on disk.
        plan_file, _, _ = plan_paths()
        archive_dir = plan_file.parent / "archive"
        archived_dirs = [d for d in archive_dir.iterdir() if d.is_dir()]
        assert len(archived_dirs) == 2, f"Expected 2 archived dirs, got {len(archived_dirs)}"

        # Verify the current plan on disk is the last completed one
        current_plan = json.loads(plan_file.read_text())
        assert current_plan["title"] == "Plan 2"
        assert current_plan["status"] == "completed"

        # One more create_plan should archive the last completed plan
        plan = create_plan(
            title="Plan 3",
            goal="Trigger last archive",
            steps=[{"title": "Step 3", "step_id": "s3"}],
        )
        assert plan["title"] == "Plan 3"
        archived_dirs = [d for d in archive_dir.iterdir() if d.is_dir()]
        assert len(archived_dirs) == 3, f"Expected 3 archived dirs after final create, got {len(archived_dirs)}"


class TestArchiveCompletedPlan:
    """Direct tests for the archive_completed_plan helper."""

    def test_archive_moves_files(self, session_dir):
        """archive_completed_plan should move plan.json and events file to archive."""
        plan_file, events_file, _ = plan_paths()

        # Create a fake completed plan
        plan_data = {"title": "Old", "status": "completed", "version": 5}
        plan_file.write_text(json.dumps(plan_data))
        events_file.write_text('{"event": "created"}\n')

        dest = archive_completed_plan(plan_file, events_file)

        assert dest is not None
        assert not plan_file.exists(), "Original plan.json should be moved"
        assert not events_file.exists(), "Original events file should be moved"
        assert (dest / "plan.json").exists()
        assert (dest / "plan_events.jsonl").exists()

        archived = json.loads((dest / "plan.json").read_text())
        assert archived["title"] == "Old"

    def test_archive_no_events_file(self, session_dir):
        """Archive should work even if events file doesn't exist."""
        plan_file, events_file, _ = plan_paths()

        plan_data = {"title": "No Events", "status": "completed"}
        plan_file.write_text(json.dumps(plan_data))
        # Don't create events file

        dest = archive_completed_plan(plan_file, events_file)
        assert dest is not None
        assert (dest / "plan.json").exists()
        assert not (dest / "plan_events.jsonl").exists()

    def test_archive_no_plan_file(self, session_dir):
        """Archive should return None if plan file doesn't exist."""
        plan_file, events_file, _ = plan_paths()
        result = archive_completed_plan(plan_file, events_file)
        assert result is None
