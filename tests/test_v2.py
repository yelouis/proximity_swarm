import os
import sys
import json
import tempfile
import shutil
import unittest

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import proximity_monitor
from proximity_monitor import (
    save_agent_state,
    evaluate_consensus_gate,
    run_cascading_kills
)
from agent_runner import AgentRunner


class TestV2Supervision(unittest.TestCase):
    def setUp(self):
        # Create temp environment
        self.test_dir = tempfile.mkdtemp()
        
        # Save old values
        self.old_state_dir = proximity_monitor.STATE_DIR
        self.old_agents_dir = proximity_monitor.AGENTS_DIR
        self.old_collisions_dir = proximity_monitor.COLLISIONS_DIR
        self.old_workspaces_dir = proximity_monitor.WORKSPACES_DIR
        self.old_tombstones = proximity_monitor.TOMBSTONES_FILE
        
        # Overwrite values for testing
        proximity_monitor.STATE_DIR = self.test_dir
        proximity_monitor.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        proximity_monitor.COLLISIONS_DIR = os.path.join(self.test_dir, "collisions")
        proximity_monitor.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        proximity_monitor.TOMBSTONES_FILE = os.path.join(self.test_dir, "tombstones.json")
        
        os.makedirs(proximity_monitor.AGENTS_DIR, exist_ok=True)
        os.makedirs(proximity_monitor.COLLISIONS_DIR, exist_ok=True)
        os.makedirs(proximity_monitor.WORKSPACES_DIR, exist_ok=True)
        
        with open(proximity_monitor.TOMBSTONES_FILE, 'w') as f:
            json.dump([], f)

    def tearDown(self):
        # Clean up temp files
        shutil.rmtree(self.test_dir)
        
        # Restore old values
        proximity_monitor.STATE_DIR = self.old_state_dir
        proximity_monitor.AGENTS_DIR = self.old_agents_dir
        proximity_monitor.COLLISIONS_DIR = self.old_collisions_dir
        proximity_monitor.WORKSPACES_DIR = self.old_workspaces_dir
        proximity_monitor.TOMBSTONES_FILE = self.old_tombstones

    def test_consensus_gate_approved(self):
        """If another active agent covers the task, termination is approved (status -> dead)."""
        agent1 = {
            "id": "001",
            "task_id": "task_jwt_auth",
            "status": "exploring",
            "goal": "Implement JWT auth",
            "current_step": {"description": "Write JWT sign"}
        }
        agent2 = {
            "id": "002",
            "task_id": "task_jwt_auth",
            "status": "pending_termination",
            "goal": "Implement JWT auth",
            "current_step": {"description": "Write JWT sign"}
        }
        save_agent_state(agent1)
        save_agent_state(agent2)
        
        evaluate_consensus_gate([agent1, agent2])
        
        # Reload state files
        with open(os.path.join(proximity_monitor.AGENTS_DIR, "agent_002.json"), 'r') as f:
            data = json.load(f)
        self.assertEqual(data["status"], "dead")

    def test_consensus_gate_rejected(self):
        """If no other active agent covers the task, termination is rejected to prevent extinction (status -> exploring)."""
        agent3 = {
            "id": "003",
            "task_id": "task_jwt_auth",
            "status": "pending_termination",
            "goal": "Implement JWT auth",
            "current_step": {"description": "Write JWT sign"}
        }
        save_agent_state(agent3)
        
        evaluate_consensus_gate([agent3])
        
        with open(os.path.join(proximity_monitor.AGENTS_DIR, "agent_003.json"), 'r') as f:
            data = json.load(f)
        self.assertEqual(data["status"], "exploring")

    def test_cascading_kill(self):
        """Parent dead status cascades to children processes."""
        parent = {
            "id": "004",
            "status": "dead",
            "children": ["005"]
        }
        child = {
            "id": "005",
            "status": "exploring",
            "children": ["006"]
        }
        grandchild = {
            "id": "006",
            "status": "exploring"
        }
        save_agent_state(parent)
        save_agent_state(child)
        save_agent_state(grandchild)
        
        run_cascading_kills()
        
        # Verify both child and grandchild were set to dead
        with open(os.path.join(proximity_monitor.AGENTS_DIR, "agent_005.json"), 'r') as f:
            child_data = json.load(f)
        self.assertEqual(child_data["status"], "dead")
        
        with open(os.path.join(proximity_monitor.AGENTS_DIR, "agent_006.json"), 'r') as f:
            grandchild_data = json.load(f)
        self.assertEqual(grandchild_data["status"], "dead")

    def test_deconfliction_offsets(self):
        """Touched file parameters offset correctly based on suffix."""
        # Temporarily mock the agents dir of runner to the temp test dir
        import agent_runner
        old_agents_dir = agent_runner.AGENTS_DIR
        old_workspaces_dir = agent_runner.WORKSPACES_DIR
        old_tasks_file = agent_runner.MOCK_TASKS_FILE
        
        agent_runner.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        agent_runner.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        agent_runner.MOCK_TASKS_FILE = os.path.join(os.path.abspath(os.path.dirname(__file__)), "..", "mock_tasks.json")
        
        try:
            runner = AgentRunner(
                agent_id="007",
                task_id="task_jwt_auth",
                offset_suffix="offset_z",
                step_delay=0.1
            )
            # Verify touched files has suffix applied
            self.assertEqual(runner.state["touched_files"], ["src/auth_offset_z.py"])
            
        finally:
            # Restore
            agent_runner.AGENTS_DIR = old_agents_dir
            agent_runner.WORKSPACES_DIR = old_workspaces_dir
            agent_runner.MOCK_TASKS_FILE = old_tasks_file


if __name__ == "__main__":
    unittest.main()
