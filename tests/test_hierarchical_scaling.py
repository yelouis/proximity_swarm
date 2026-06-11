import os
import sys
import unittest
import unittest.mock
import json
import shutil
import tempfile

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import supervisor
import proximity_monitor
import terminal_dashboard
import agent_runner
from agent_runner import AgentRunner


class TestHierarchicalScaling(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Override STATE_DIR and other directories in modules to run in sandboxed temp directory
        self.orig_state_dir_sup = supervisor.STATE_DIR
        self.orig_orch_file_sup = supervisor.orchestrator_file
        
        self.orig_state_dir_mon = proximity_monitor.STATE_DIR
        self.orig_agents_dir_mon = proximity_monitor.AGENTS_DIR
        self.orig_collisions_dir_mon = proximity_monitor.COLLISIONS_DIR
        self.orig_workspaces_dir_mon = proximity_monitor.WORKSPACES_DIR
        
        self.orig_state_dir_run = agent_runner.STATE_DIR
        self.orig_agents_dir_run = agent_runner.AGENTS_DIR
        self.orig_collisions_dir_run = agent_runner.COLLISIONS_DIR
        self.orig_workspaces_dir_run = agent_runner.WORKSPACES_DIR
        
        self.orig_state_dir_tui = terminal_dashboard.STATE_DIR
        
        supervisor.STATE_DIR = self.test_dir
        supervisor.orchestrator_file = os.path.join(self.test_dir, "orchestrator.json")
        
        proximity_monitor.STATE_DIR = self.test_dir
        proximity_monitor.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        proximity_monitor.COLLISIONS_DIR = os.path.join(self.test_dir, "collisions")
        proximity_monitor.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        
        agent_runner.STATE_DIR = self.test_dir
        agent_runner.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        agent_runner.COLLISIONS_DIR = os.path.join(self.test_dir, "collisions")
        agent_runner.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        
        terminal_dashboard.STATE_DIR = self.test_dir
        
        # Re-initialize folders
        os.makedirs(os.path.join(self.test_dir, "agents"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "collisions"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "workspaces"), exist_ok=True)

    def tearDown(self):
        # Restore state paths
        supervisor.STATE_DIR = self.orig_state_dir_sup
        supervisor.orchestrator_file = self.orig_orch_file_sup
        
        proximity_monitor.STATE_DIR = self.orig_state_dir_mon
        proximity_monitor.AGENTS_DIR = self.orig_agents_dir_mon
        proximity_monitor.COLLISIONS_DIR = self.orig_collisions_dir_mon
        proximity_monitor.WORKSPACES_DIR = self.orig_workspaces_dir_mon
        
        agent_runner.STATE_DIR = self.orig_state_dir_run
        agent_runner.AGENTS_DIR = self.orig_agents_dir_run
        agent_runner.COLLISIONS_DIR = self.orig_collisions_dir_run
        agent_runner.WORKSPACES_DIR = self.orig_workspaces_dir_run
        
        terminal_dashboard.STATE_DIR = self.orig_state_dir_tui
        shutil.rmtree(self.test_dir)

    @unittest.mock.patch("terminal_dashboard.is_ollama_running")
    @unittest.mock.patch("terminal_dashboard.call_ollama")
    def test_decompose_macro_goal_parsing(self, mock_call, mock_is_running):
        # 1. Test offline fallback
        mock_is_running.return_value = False
        res_fallback = terminal_dashboard.decompose_macro_goal("test macro task")
        self.assertEqual(len(res_fallback["sub_swarms"]), 1)
        self.assertEqual(res_fallback["sub_swarms"][0]["id"], "swarm_001")
        
        # 2. Test dynamic planning with mock LLM response
        mock_is_running.return_value = True
        mock_call.return_value = json.dumps({
            "sub_swarms": [
                {
                    "id": "swarm_001",
                    "goal": "Goal 1",
                    "role": "Role 1",
                    "dependencies": []
                },
                {
                    "id": "swarm_002",
                    "goal": "Goal 2",
                    "role": "Role 2",
                    "dependencies": ["swarm_001"]
                }
            ]
        })
        
        res = terminal_dashboard.decompose_macro_goal("test macro task")
        self.assertEqual(len(res["sub_swarms"]), 2)
        self.assertEqual(res["sub_swarms"][0]["id"], "swarm_001")
        self.assertEqual(res["sub_swarms"][1]["dependencies"], ["swarm_001"])

    def test_supervisor_dependency_resolution(self):
        # Initialize mock orchestrator state file in sandbox
        orchestrator_file = os.path.join(self.test_dir, "orchestrator.json")
        orchestrator_state = {
            "macro_goal": "Integrate feature",
            "sub_swarms": {
                "swarm_001": {
                    "id": "swarm_001",
                    "goal": "Task 1",
                    "dependencies": [],
                    "status": "active",
                    "agent_ids": ["001"]
                },
                "swarm_002": {
                    "id": "swarm_002",
                    "goal": "Task 2",
                    "dependencies": ["swarm_001"],
                    "status": "pending",
                    "agent_ids": ["002"]
                }
            }
        }
        with open(orchestrator_file, 'w') as f:
            json.dump(orchestrator_state, f, indent=2)

        # Mock workspace database paths inside supervisor module
        orig_file = supervisor.orchestrator_file
        supervisor.orchestrator_file = orchestrator_file
        
        try:
            # 1. swarm_002 is pending, so agent 002 is inactive
            self.assertTrue(supervisor.is_agent_sub_swarm_active("001"))
            self.assertFalse(supervisor.is_agent_sub_swarm_active("002"))
            
            # 2. Simulate agent 001 completion by writing its state JSON as "completed"
            agent_001_file = os.path.join(self.test_dir, "agents", "agent_001.json")
            with open(agent_001_file, 'w') as f:
                json.dump({"id": "001", "status": "completed"}, f)
                
            # Trigger evaluation loop
            supervisor.evaluate_sub_swarm_completion()
            
            # 3. Reload state and verify swarm_001 is completed, and swarm_002 is activated!
            with open(orchestrator_file, 'r') as f:
                updated_state = json.load(f)
            self.assertEqual(updated_state["sub_swarms"]["swarm_001"]["status"], "completed")
            self.assertEqual(updated_state["sub_swarms"]["swarm_002"]["status"], "active")
            
            # 4. Now agent 002 must be active
            self.assertTrue(supervisor.is_agent_sub_swarm_active("002"))
        finally:
            supervisor.orchestrator_file = orig_file

    @unittest.mock.patch("agent_runner.is_ollama_running")
    @unittest.mock.patch("agent_runner.load_json")
    @unittest.mock.patch("agent_runner.save_json")
    def test_dynamic_multi_parent_takeover(self, mock_save, mock_load, mock_is_running):
        mock_is_running.return_value = False
        
        # Instantiating AgentRunner
        mock_load.return_value = {
            "id": "001",
            "parent_id": "parent_001",
            "parent_ids": ["parent_001"],
            "goal": "Goal A",
            "personality": "Specialist",
            "status": "syncing",
            "steps_completed": 0,
            "touched_files": []
        }
        
        runner = AgentRunner(
            agent_id="001",
            task_id="task_jwt_auth",
            ollama_model="gemma4:latest",
            personality="Specialist",
            goal="Goal A"
        )
        
        # Prepopulate dummy collision record
        collision_id = "001_002"
        collision_file = os.path.join(self.test_dir, "collisions", f"collision_{collision_id}.json")
        collision_data = {
            "collision_id": collision_id,
            "status": "negotiating",
            "agent_a": {
                "id": "001",
                "goal": "Goal A",
                "progress": 80,
                "current_step": {"name": "step1", "description": "desc1"},
                "personality": "Specialist",
                "parent_id": "parent_001",
                "parent_ids": ["parent_001"]
            },
            "agent_b": {
                "id": "002",
                "goal": "Goal B",
                "progress": 40,
                "current_step": {"name": "step2", "description": "desc2"},
                "personality": "Specialist",
                "parent_id": "parent_002",
                "parent_ids": ["parent_002"]
            },
            "similarity_metrics": {"goal_cosine": 0.8},
            "negotiation_log": []
        }
        with open(collision_file, 'w') as f:
            json.dump(collision_data, f)
            
        # Write Agent 002 state file (losing agent)
        agent_002_file = os.path.join(self.test_dir, "agents", "agent_002.json")
        agent_002_state = {
            "id": "002",
            "parent_id": "parent_002",
            "parent_ids": ["parent_002"],
            "goal": "Goal B",
            "personality": "Specialist",
            "status": "syncing",
            "steps_completed": 0,
            "touched_files": []
        }
        with open(agent_002_file, 'w') as f:
            json.dump(agent_002_state, f)
            
        # Mock load_json sequence inside perform_negotiation
        mock_load.side_effect = lambda path: (
            mock_load.return_value if "agent_001.json" in path else (
                agent_002_state if "agent_002.json" in path else (
                    collision_data if f"collision_{collision_id}.json" in path else {}
                )
            )
        )
        
        # Override class workspace paths for testing
        runner.workspace_dir = self.test_dir
        runner.state_file = os.path.join(self.test_dir, "agents", "agent_001.json")
        
        # Run negotiation, should kill_b (because A has progress 80 >= B's progress 40)
        runner.perform_negotiation()
        
        # Verify Agent 001 inherits Agent 002's parent!
        # Fetch mock save calls
        saved_agent_a = None
        for args, kwargs in mock_save.call_args_list:
            if "agent_001.json" in args[0]:
                saved_agent_a = args[1]
                
        self.assertIsNotNone(saved_agent_a)
        self.assertIn("parent_001", saved_agent_a["parent_ids"])
        self.assertIn("parent_002", saved_agent_a["parent_ids"])

    def test_cascading_kills_bypass_multi_parent(self):
        # Populate agent files in sandbox
        agents_dir = os.path.join(self.test_dir, "agents")
        
        # Parent 001 is DEAD, Parent 002 is ACTIVE (exploring)
        # Child 003 has parent_ids = ["parent_001", "parent_002"]
        p001 = {"id": "parent_001", "status": "dead", "children": ["003"]}
        p002 = {"id": "parent_002", "status": "exploring", "children": ["003"]}
        c003 = {"id": "003", "parent_id": "parent_001", "parent_ids": ["parent_001", "parent_002"], "status": "exploring"}
        
        with open(os.path.join(agents_dir, "agent_parent_001.json"), 'w') as f:
            json.dump(p001, f)
        with open(os.path.join(agents_dir, "agent_parent_002.json"), 'w') as f:
            json.dump(p002, f)
        with open(os.path.join(agents_dir, "agent_003.json"), 'w') as f:
            json.dump(c003, f)
            
        # Run cascade check. Parent 001 is dead, but Parent 002 is still active.
        # So Child 003 must survive (not be cascadingly killed).
        proximity_monitor.run_cascading_kills()
        
        # Load child state and verify it is still active/exploring
        with open(os.path.join(agents_dir, "agent_003.json"), 'r') as f:
            updated_c003 = json.load(f)
        self.assertEqual(updated_c003["status"], "exploring")
        
        # Now kill Parent 002
        p002["status"] = "dead"
        with open(os.path.join(agents_dir, "agent_parent_002.json"), 'w') as f:
            json.dump(p002, f)
            
        # Run cascade again. Both parents are now dead, so Child 003 should be killed!
        proximity_monitor.run_cascading_kills()
        
        # Verify Child 003 status is now dead
        with open(os.path.join(agents_dir, "agent_003.json"), 'r') as f:
            killed_c003 = json.load(f)
        self.assertEqual(killed_c003["status"], "dead")


if __name__ == "__main__":
    unittest.main()
