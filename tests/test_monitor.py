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
    load_active_agents,
    save_agent_state,
    handle_spawn_requests
)


class TestMonitorLogic(unittest.TestCase):
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

    def test_load_active_agents(self):
        # Create one active, one completed, one dead agent
        agent1 = {"id": "001", "status": "exploring", "goal": "A"}
        agent2 = {"id": "002", "status": "completed", "goal": "B"}
        agent3 = {"id": "003", "status": "dead", "goal": "C"}
        
        save_agent_state(agent1)
        save_agent_state(agent2)
        save_agent_state(agent3)
        
        active = load_active_agents()
        self.assertEqual(len(active), 1)
        self.assertEqual(active[0]["id"], "001")

    def test_handle_spawn_requests(self):
        parent = {
            "id": "001",
            "status": "exploring",
            "goal": "Parent goal",
            "spawn_request": {
                "goal": "Child goal",
                "initial_files": ["child.py"]
            }
        }
        save_agent_state(parent)
        
        # Trigger spawn handler
        handle_spawn_requests([parent])
        
        # Verify parent state file is updated (spawn_request is cleared)
        with open(os.path.join(proximity_monitor.AGENTS_DIR, "agent_001.json"), 'r') as f:
            updated_parent = json.load(f)
        self.assertIsNone(updated_parent.get("spawn_request"))
        self.assertIn("002", updated_parent.get("children", []))
        
        # Verify child state file is created
        child_path = os.path.join(proximity_monitor.AGENTS_DIR, "agent_002.json")
        self.assertTrue(os.path.exists(child_path))
        
        with open(child_path, 'r') as f:
            child = json.load(f)
        self.assertEqual(child["id"], "002")
        self.assertEqual(child["parent_id"], "001")
        self.assertEqual(child["goal"], "Child goal")
        self.assertEqual(child["status"], "exploring")
        
        # Verify workspace directory is provisioned
        self.assertTrue(os.path.exists(os.path.join(proximity_monitor.WORKSPACES_DIR, "agent_002")))


if __name__ == "__main__":
    unittest.main()
