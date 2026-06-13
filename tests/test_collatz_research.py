import os
import sys
import json
import tempfile
import shutil
import unittest
import unittest.mock

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import agent_runner
from agent_runner import AgentRunner, load_json, save_json
import proximity_monitor

class TestCollatzConjectureSwarmSpawning(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Override state paths to isolate test execution
        self.old_state_dir = agent_runner.STATE_DIR
        self.old_agents_dir = agent_runner.AGENTS_DIR
        self.old_collisions_dir = agent_runner.COLLISIONS_DIR
        self.old_workspaces_dir = agent_runner.WORKSPACES_DIR
        self.old_mock_tasks = agent_runner.MOCK_TASKS_FILE
        self.old_tombstones = agent_runner.TOMBSTONES_FILE
        
        agent_runner.STATE_DIR = self.test_dir
        agent_runner.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        agent_runner.COLLISIONS_DIR = os.path.join(self.test_dir, "collisions")
        agent_runner.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        agent_runner.MOCK_TASKS_FILE = os.path.join(self.test_dir, "mock_tasks.json")
        agent_runner.TOMBSTONES_FILE = os.path.join(self.test_dir, "tombstones.json")
        
        os.makedirs(agent_runner.AGENTS_DIR, exist_ok=True)
        os.makedirs(agent_runner.COLLISIONS_DIR, exist_ok=True)
        os.makedirs(agent_runner.WORKSPACES_DIR, exist_ok=True)
        
        # Define the unsolved Collatz Conjecture task with 7 steps
        self.collatz_task = {
            "tasks": {
                "task_collatz_research": {
                    "id": "task_collatz_research",
                    "goal": "Verify or prove the Collatz Conjecture, or find counterexamples.",
                    "steps": [
                        {
                            "step_id": i,
                            "name": f"Step {i}",
                            "description": f"Description {i}",
                            "touched_files": [f"file_{i}.txt"],
                            "tools": []
                        } for i in range(1, 8)
                    ]
                }
            }
        }
        with open(agent_runner.MOCK_TASKS_FILE, 'w') as f:
            json.dump(self.collatz_task, f, indent=2)
            
        with open(agent_runner.TOMBSTONES_FILE, 'w') as f:
            json.dump([], f)

    def tearDown(self):
        agent_runner.STATE_DIR = self.old_state_dir
        agent_runner.AGENTS_DIR = self.old_agents_dir
        agent_runner.COLLISIONS_DIR = self.old_collisions_dir
        agent_runner.WORKSPACES_DIR = self.old_workspaces_dir
        agent_runner.MOCK_TASKS_FILE = self.old_mock_tasks
        agent_runner.TOMBSTONES_FILE = self.old_tombstones
        shutil.rmtree(self.test_dir)

    @unittest.mock.patch("agent_runner.is_ollama_running")
    @unittest.mock.patch("agent_runner.call_ollama_api")
    def test_collatz_parallel_hypothesis_spawning(self, mock_ollama_api, mock_is_ollama_running):
        """
        Verify that when the agent is assigned an unsolved math theorem, it identifies 
        the necessity of parallel investigation and registers spawn requests.
        """
        mock_is_ollama_running.return_value = True
        
        # Mock LLM behavior to decide to spawn multiple specialized subagents for research angles
        mock_ollama_api.return_value = {
            "should_spawn": True,
            "goal": "Run computational search for counterexamples in large integer ranges",
            "initial_files": ["config/test_ranges.json"]
        }
        
        # Initialize parent research coordinator agent
        runner = AgentRunner(
            agent_id="001", 
            task_id="task_collatz_research",
            personality="Lead Researcher",
            goal="Coordinate Collatz Conjecture verification"
        )
        
        # Advance state to trigger isolated spawn check (or simulate LLM requesting spawning during step)
        runner.state["steps_completed"] = 5
        save_json(runner.state_file, runner.state)
        
        # Force evaluation loop
        runner.evaluate_isolation_spawn()
        
        # Verify spawn request is registered in the state file
        state = load_json(runner.state_file)
        self.assertIn("spawn_request", state)
        self.assertEqual(state["spawn_request"]["goal"], "Run computational search for counterexamples in large integer ranges")
        self.assertEqual(state["spawn_request"]["status"], "pending")
        
        # Simulate supervisor provisioning the spawn request
        proximity_monitor.AGENTS_DIR = agent_runner.AGENTS_DIR
        proximity_monitor.WORKSPACES_DIR = agent_runner.WORKSPACES_DIR
        proximity_monitor.STATE_DIR = agent_runner.STATE_DIR
        proximity_monitor.INTERACTIVE = False
        
        proximity_monitor.handle_spawn_requests([state])
        
        # Verify that Child Agent 002 is spawned
        self.assertTrue(os.path.exists(os.path.join(agent_runner.AGENTS_DIR, "agent_002.json")))
        child_state = load_json(os.path.join(agent_runner.AGENTS_DIR, "agent_002.json"))
        self.assertEqual(child_state["parent_id"], "001")
        self.assertEqual(child_state["goal"], "Run computational search for counterexamples in large integer ranges")

if __name__ == "__main__":
    unittest.main()
