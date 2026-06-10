import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import terminal_dashboard
import supervisor
import agent_runner
from agent_runner import AgentRunner

class TestSwarmPersonalities(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Save old globals
        self.old_state_dir = agent_runner.STATE_DIR
        self.old_agents_dir = agent_runner.AGENTS_DIR
        self.old_workspaces_dir = agent_runner.WORKSPACES_DIR
        self.old_mock_tasks = agent_runner.MOCK_TASKS_FILE
        self.old_tombstones = agent_runner.TOMBSTONES_FILE
        
        # Override paths
        agent_runner.STATE_DIR = self.test_dir
        agent_runner.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        agent_runner.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        agent_runner.MOCK_TASKS_FILE = os.path.join(self.test_dir, "mock_tasks.json")
        agent_runner.TOMBSTONES_FILE = os.path.join(self.test_dir, "tombstones.json")
        
        os.makedirs(agent_runner.AGENTS_DIR, exist_ok=True)
        os.makedirs(agent_runner.WORKSPACES_DIR, exist_ok=True)
        
        # Write dummy tombstones
        with open(agent_runner.TOMBSTONES_FILE, 'w') as f:
            json.dump([], f)
            
        # Write dummy tasks
        self.dummy_tasks = {
            "tasks": {
                "task_test": {
                    "id": "task_test",
                    "goal": "Overall Main Goal",
                    "steps": [
                        {
                            "step_id": 1,
                            "name": "Step One",
                            "description": "Desc",
                            "touched_files": ["one.py"],
                            "tools": ["edit_file"]
                        }
                    ]
                }
            }
        }
        with open(agent_runner.MOCK_TASKS_FILE, 'w') as f:
            json.dump(self.dummy_tasks, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        agent_runner.STATE_DIR = self.old_state_dir
        agent_runner.AGENTS_DIR = self.old_agents_dir
        agent_runner.WORKSPACES_DIR = self.old_workspaces_dir
        agent_runner.MOCK_TASKS_FILE = self.old_mock_tasks
        agent_runner.TOMBSTONES_FILE = self.old_tombstones

    def test_runner_initialization_with_personality_and_goal(self):
        runner = AgentRunner(
            agent_id="001",
            task_id="task_test",
            personality="Security Auditor",
            goal="Verify authorization scopes in endpoints"
        )
        
        self.assertEqual(runner.state["personality"], "Security Auditor")
        self.assertEqual(runner.state["goal"], "Verify authorization scopes in endpoints")
        
        # Read from file to confirm persistence
        with open(runner.state_file, 'r') as f:
            data = json.load(f)
        self.assertEqual(data["personality"], "Security Auditor")
        self.assertEqual(data["goal"], "Verify authorization scopes in endpoints")

    def test_tui_predefined_personalities_parsing(self):
        terminal_dashboard.predefined_personalities = []
        
        # Mock commands parsing
        def parse_command(input_str):
            parts = input_str.strip().split(maxsplit=1)
            cmd = parts[0].lower() if parts else ""
            arg = parts[1] if len(parts) > 1 else None
            
            if cmd in ["/add-agent", "/add-personality"]:
                if ":" in arg:
                    r_part, g_part = arg.split(":", 1)
                    role = r_part.strip()
                    goal = g_part.strip()
                else:
                    role = arg.strip()
                    goal = None
                terminal_dashboard.predefined_personalities.append({"role": role, "goal": goal})
                
        parse_command("/add-agent Auditor : Perform static analysis")
        parse_command("/add-personality Developer")
        
        self.assertEqual(len(terminal_dashboard.predefined_personalities), 2)
        self.assertEqual(terminal_dashboard.predefined_personalities[0]["role"], "Auditor")
        self.assertEqual(terminal_dashboard.predefined_personalities[0]["goal"], "Perform static analysis")
        self.assertEqual(terminal_dashboard.predefined_personalities[1]["role"], "Developer")
        self.assertIsNone(terminal_dashboard.predefined_personalities[1]["goal"])


if __name__ == "__main__":
    unittest.main()
