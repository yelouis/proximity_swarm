"""Tests for the §13 self-healing verification loop in agent_runner.

Covers the verification primitive, the self-healing inner loop (success, exhaustion,
offline), and the end-to-end test-driven progress gate (progress only advances when a
step's verification command passes).
"""
import os
import sys
import json
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import agent_runner
from agent_runner import AgentRunner

REAL_TASKS = os.path.join(os.path.dirname(__file__), "..", "mock_tasks.json")
STEP = {"step_id": 1, "name": "build cache", "description": "implement the cache"}


class TestSelfHealing(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self._orig = {
            "STATE_DIR": agent_runner.STATE_DIR,
            "AGENTS_DIR": agent_runner.AGENTS_DIR,
            "WORKSPACES_DIR": agent_runner.WORKSPACES_DIR,
            "TOMBSTONES_FILE": agent_runner.TOMBSTONES_FILE,
            "MOCK_TASKS_FILE": agent_runner.MOCK_TASKS_FILE,
            "MAX_HEAL_ATTEMPTS": agent_runner.MAX_HEAL_ATTEMPTS,
        }
        agent_runner.STATE_DIR = self.test_dir
        agent_runner.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        agent_runner.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        agent_runner.TOMBSTONES_FILE = os.path.join(self.test_dir, "tombstones.json")
        agent_runner.MOCK_TASKS_FILE = os.path.abspath(REAL_TASKS)
        agent_runner.MAX_HEAL_ATTEMPTS = 3

        self.runner = AgentRunner(agent_id="901", task_id="task_jwt_auth", step_delay=0.0)
        # Offline by default so heal_file returns None unless a test overrides it.
        self.runner.llm_provider = None

    def tearDown(self):
        for k, v in self._orig.items():
            setattr(agent_runner, k, v)
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _write(self, name, content):
        with open(os.path.join(self.runner.workspace_dir, name), "w") as f:
            f.write(content)

    def _read(self, name):
        with open(os.path.join(self.runner.workspace_dir, name)) as f:
            return f.read()

    # --- run_verification primitive ---
    def test_verification_passes_on_zero_exit(self):
        self._write("result.txt", "PASS\n")
        passed, _ = self.runner.run_verification("grep -q PASS result.txt")
        self.assertTrue(passed)

    def test_verification_fails_on_nonzero_exit(self):
        self._write("result.txt", "nope\n")
        passed, _ = self.runner.run_verification("grep -q PASS result.txt")
        self.assertFalse(passed)

    def test_verification_fails_when_command_cannot_run(self):
        passed, output = self.runner.run_verification("this_command_definitely_does_not_exist_42")
        self.assertFalse(passed)
        self.assertTrue(output)

    # --- self-healing inner loop ---
    def test_heal_loop_succeeds_after_patch(self):
        self._write("calc.py", "BROKEN")
        # Simulate an LLM that patches the file so verification passes.
        def fake_heal(filename, step, err):
            return "FIXED"
        self.runner.heal_file = fake_heal

        passed, attempts, _ = self.runner.run_verification_loop(
            "grep -q FIXED calc.py", "calc.py", STEP)

        self.assertTrue(passed)
        self.assertEqual(attempts, 1)
        self.assertEqual(self._read("calc.py"), "FIXED")

    def test_heal_loop_exhausts_then_fails(self):
        self._write("calc.py", "BROKEN")
        # Patcher "responds" but the verification can never pass.
        self.runner.heal_file = lambda filename, step, err: "still wrong"

        passed, attempts, _ = self.runner.run_verification_loop(
            "python3 -c \"import sys; sys.exit(1)\"", "calc.py", STEP)

        self.assertFalse(passed)
        self.assertEqual(attempts, agent_runner.MAX_HEAL_ATTEMPTS)

    def test_heal_loop_stops_when_offline(self):
        self._write("calc.py", "BROKEN")
        # llm_provider is None → heal_file returns None → loop stops after one attempt.
        passed, attempts, _ = self.runner.run_verification_loop(
            "grep -q FIXED calc.py", "calc.py", STEP)

        self.assertFalse(passed)
        self.assertEqual(attempts, 1)

    def test_heal_loop_passes_immediately_without_healing(self):
        self._write("calc.py", "FIXED")
        passed, attempts, _ = self.runner.run_verification_loop(
            "grep -q FIXED calc.py", "calc.py", STEP)
        self.assertTrue(passed)
        self.assertEqual(attempts, 0)

    # --- end-to-end progress gate via execute_step ---
    def test_execute_step_gate_blocks_progress_on_failed_verification(self):
        # A temp task whose current (2nd) step has a verification that cannot pass offline.
        tasks = {"tasks": {"task_ver": {
            "id": "task_ver",
            "goal": "verify gate",
            "steps": [
                {"step_id": 1, "name": "init", "description": "init", "touched_files": [], "tools": []},
                {"step_id": 2, "name": "gated", "description": "needs verify",
                 "touched_files": ["g.py"], "tools": [], "verification": "grep -q DONE g.py"},
            ],
        }}}
        temp_tasks = os.path.join(self.test_dir, "tasks.json")
        with open(temp_tasks, "w") as f:
            json.dump(tasks, f)
        agent_runner.MOCK_TASKS_FILE = temp_tasks

        # Start at step index 1 (steps_completed=1) so the gated step is current.
        self.runner.state["task_id"] = "task_ver"
        self.runner.state["status"] = "exploring"
        self.runner.state["steps_completed"] = 1
        agent_runner.save_json(self.runner.state_file, self.runner.state)

        self.runner.execute_step()

        # Progress must NOT advance; the step is blocked and a tombstone is recorded.
        self.assertEqual(self.runner.state["steps_completed"], 1)
        self.assertEqual(self.runner.state["status"], "pending_termination")
        tombstones = agent_runner.load_json(agent_runner.TOMBSTONES_FILE) or []
        self.assertTrue(any("g.py" in t.get("file_path", "") for t in tombstones))


if __name__ == "__main__":
    unittest.main()
