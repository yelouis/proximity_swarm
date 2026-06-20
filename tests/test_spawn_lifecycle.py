import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import proximity_monitor
import agent_runner

class TestSpawnLifecycle(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Save old proximity_monitor values
        self.old_pm_state_dir = proximity_monitor.STATE_DIR
        self.old_pm_agents_dir = proximity_monitor.AGENTS_DIR
        self.old_pm_collisions_dir = proximity_monitor.COLLISIONS_DIR
        self.old_pm_workspaces_dir = proximity_monitor.WORKSPACES_DIR
        self.old_pm_tombstones = proximity_monitor.TOMBSTONES_FILE
        
        # Overwrite proximity_monitor values
        proximity_monitor.STATE_DIR = self.test_dir
        proximity_monitor.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        proximity_monitor.COLLISIONS_DIR = os.path.join(self.test_dir, "collisions")
        proximity_monitor.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        proximity_monitor.TOMBSTONES_FILE = os.path.join(self.test_dir, "tombstones.json")
        
        # Save old agent_runner values
        self.old_ar_state_dir = agent_runner.STATE_DIR
        self.old_ar_agents_dir = agent_runner.AGENTS_DIR
        self.old_ar_collisions_dir = agent_runner.COLLISIONS_DIR
        self.old_ar_workspaces_dir = agent_runner.WORKSPACES_DIR
        self.old_ar_tombstones = agent_runner.TOMBSTONES_FILE
        self.old_ar_mock_tasks = agent_runner.MOCK_TASKS_FILE
        
        # Overwrite agent_runner values
        agent_runner.STATE_DIR = self.test_dir
        agent_runner.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        agent_runner.COLLISIONS_DIR = os.path.join(self.test_dir, "collisions")
        agent_runner.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        agent_runner.TOMBSTONES_FILE = os.path.join(self.test_dir, "tombstones.json")
        agent_runner.MOCK_TASKS_FILE = os.path.join(os.path.dirname(__file__), "..", "mock_tasks.json")
        
        os.makedirs(proximity_monitor.AGENTS_DIR, exist_ok=True)
        os.makedirs(proximity_monitor.COLLISIONS_DIR, exist_ok=True)
        os.makedirs(proximity_monitor.WORKSPACES_DIR, exist_ok=True)
        
        with open(proximity_monitor.TOMBSTONES_FILE, 'w') as f:
            json.dump([], f)
            
    def tearDown(self):
        shutil.rmtree(self.test_dir)
        
        # Restore proximity_monitor values
        proximity_monitor.STATE_DIR = self.old_pm_state_dir
        proximity_monitor.AGENTS_DIR = self.old_pm_agents_dir
        proximity_monitor.COLLISIONS_DIR = self.old_pm_collisions_dir
        proximity_monitor.WORKSPACES_DIR = self.old_pm_workspaces_dir
        proximity_monitor.TOMBSTONES_FILE = self.old_pm_tombstones
        
        # Restore agent_runner values
        agent_runner.STATE_DIR = self.old_ar_state_dir
        agent_runner.AGENTS_DIR = self.old_ar_agents_dir
        agent_runner.COLLISIONS_DIR = self.old_ar_collisions_dir
        agent_runner.WORKSPACES_DIR = self.old_ar_workspaces_dir
        agent_runner.TOMBSTONES_FILE = self.old_ar_tombstones
        agent_runner.MOCK_TASKS_FILE = self.old_ar_mock_tasks

    def test_requires_approval_by_default(self):
        proximity_monitor.AUTO_APPROVE_SPAWNS = False
        
        parent = {
            "id": "001",
            "status": "awaiting_child",
            "goal": "Parent goal",
            "spawn_request": {
                "goal": "Child goal",
                "initial_files": ["child.py"],
                "status": "pending"
            }
        }
        proximity_monitor.save_agent_state(parent)
        
        # 1. Pending request should NOT spawn
        proximity_monitor.handle_spawn_requests([parent])
        parent_state = proximity_monitor.load_active_agents()[0]
        self.assertIsNotNone(parent_state.get("spawn_request"))
        self.assertFalse(os.path.exists(os.path.join(proximity_monitor.AGENTS_DIR, "agent_002.json")))
        
        # 2. Rejected request should clear spawn_request
        parent["spawn_request"]["status"] = "rejected"
        proximity_monitor.save_agent_state(parent)
        proximity_monitor.handle_spawn_requests([parent])
        parent_state = agent_runner.load_json(os.path.join(proximity_monitor.AGENTS_DIR, "agent_001.json"))
        self.assertIsNone(parent_state.get("spawn_request"))
        
        # 3. Approved request should spawn child agent
        parent["spawn_request"] = {
            "goal": "Child goal",
            "initial_files": ["child.py"],
            "status": "approved"
        }
        proximity_monitor.save_agent_state(parent)
        proximity_monitor.handle_spawn_requests([parent])
        parent_state = agent_runner.load_json(os.path.join(proximity_monitor.AGENTS_DIR, "agent_001.json"))
        self.assertIsNone(parent_state.get("spawn_request"))
        self.assertIn("002", parent_state.get("children", []))
        self.assertTrue(os.path.exists(os.path.join(proximity_monitor.AGENTS_DIR, "agent_002.json")))

    def test_auto_approve_spawns_immediately(self):
        proximity_monitor.AUTO_APPROVE_SPAWNS = True
        
        parent = {
            "id": "001",
            "status": "awaiting_child",
            "goal": "Parent goal",
            "spawn_request": {
                "goal": "Child goal",
                "initial_files": ["child.py"],
                "status": "pending"
            }
        }
        proximity_monitor.save_agent_state(parent)
        
        proximity_monitor.handle_spawn_requests([parent])
        parent_state = agent_runner.load_json(os.path.join(proximity_monitor.AGENTS_DIR, "agent_001.json"))
        self.assertIsNone(parent_state.get("spawn_request"))
        self.assertIn("002", parent_state.get("children", []))
        self.assertTrue(os.path.exists(os.path.join(proximity_monitor.AGENTS_DIR, "agent_002.json")))

    def test_parent_awaits_child_before_completion(self):
        runner = agent_runner.AgentRunner(
            agent_id="001",
            task_id="task_jwt_auth",
            llm_provider="rules",
            step_delay=0.01
        )
        runner.state["children"] = ["002"]
        child = {
            "id": "002",
            "status": "exploring",
            "progress": 50,
            "goal": "Child task"
        }
        agent_runner.save_json(runner.state_file, runner.state)
        agent_runner.save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_002.json"), child)
        
        # Finish steps
        runner.state["steps_completed"] = 2
        agent_runner.save_json(runner.state_file, runner.state)
        
        completed = runner.finalize_or_await()
        self.assertFalse(completed)
        self.assertEqual(runner.state["status"], "awaiting_child")

    def test_parent_ingests_then_completes(self):
        runner = agent_runner.AgentRunner(
            agent_id="001",
            task_id="task_jwt_auth",
            llm_provider="rules",
            step_delay=0.01
        )
        runner.state["children"] = ["002"]
        child_ws = os.path.join(agent_runner.WORKSPACES_DIR, "agent_002")
        os.makedirs(child_ws, exist_ok=True)
        with open(os.path.join(child_ws, "output.md"), "w") as fh:
            fh.write("Child finished successfully.")
            
        child = {
            "id": "002",
            "status": "completed",
            "progress": 100,
            "goal": "Child task"
        }
        agent_runner.save_json(runner.state_file, runner.state)
        agent_runner.save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_002.json"), child)
        
        runner.state["status"] = "awaiting_child"
        runner.check_in_on_children()
        
        self.assertEqual(runner.state["status"], "completed")
        self.assertEqual(runner.state["progress"], 100)
        
        parent_results_file = os.path.join(runner.workspace_dir, "child_results.md")
        self.assertTrue(os.path.exists(parent_results_file))
        with open(parent_results_file, "r") as fh:
            content = fh.read()
        self.assertIn("Child finished successfully.", content)

    def test_rejected_spawn_unblocks_parent(self):
        runner = agent_runner.AgentRunner(
            agent_id="001",
            task_id="task_jwt_auth",
            llm_provider="rules",
            step_delay=0.01
        )
        runner.state["spawn_request"] = None
        runner.state["children"] = []
        runner.state["steps_completed"] = 2
        runner.state["status"] = "awaiting_child"
        
        runner.check_in_on_children()
        self.assertEqual(runner.state["status"], "completed")

    def test_await_deadlock_cap(self):
        runner = agent_runner.AgentRunner(
            agent_id="001",
            task_id="task_jwt_auth",
            llm_provider="rules",
            step_delay=0.01
        )
        runner.state["children"] = ["002"]
        child = {
            "id": "002",
            "status": "exploring",
            "progress": 50,
            "goal": "Child task"
        }
        agent_runner.save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_002.json"), child)
        
        runner.state["status"] = "awaiting_child"
        runner.state["await_iters"] = 20
        
        runner.check_in_on_children()
        self.assertEqual(runner.state["status"], "completed")
        self.assertEqual(runner.state["progress"], 100)

if __name__ == "__main__":
    unittest.main()
