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
from agent_runner import AgentRunner, load_json, save_json, get_iso_timestamp


class TestSkillsIntegration(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Save original paths
        self.old_state_dir = agent_runner.STATE_DIR
        self.old_agents_dir = agent_runner.AGENTS_DIR
        self.old_collisions_dir = agent_runner.COLLISIONS_DIR
        self.old_workspaces_dir = agent_runner.WORKSPACES_DIR
        self.old_mock_tasks = agent_runner.MOCK_TASKS_FILE
        self.old_tombstones = agent_runner.TOMBSTONES_FILE
        
        # Override paths
        agent_runner.STATE_DIR = self.test_dir
        agent_runner.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        agent_runner.COLLISIONS_DIR = os.path.join(self.test_dir, "collisions")
        agent_runner.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        agent_runner.MOCK_TASKS_FILE = os.path.join(self.test_dir, "mock_tasks.json")
        agent_runner.TOMBSTONES_FILE = os.path.join(self.test_dir, "tombstones.json")
        
        import memory_store
        self.old_db_dir = memory_store.DB_DIR
        self.old_db_path = memory_store.DB_PATH
        memory_store.DB_DIR = self.test_dir
        memory_store.DB_PATH = os.path.join(self.test_dir, "test_memory.db")
        memory_store.init_db()
        
        os.makedirs(agent_runner.AGENTS_DIR, exist_ok=True)
        os.makedirs(agent_runner.COLLISIONS_DIR, exist_ok=True)
        os.makedirs(agent_runner.WORKSPACES_DIR, exist_ok=True)
        
        # Write mock_tasks.json
        self.mock_tasks = {
            "tasks": {
                "task_test": {
                    "goal": "Test task",
                    "steps": [
                        {
                            "step_id": 1,
                            "name": "Step A",
                            "description": "First step description",
                            "touched_files": ["file_a.txt"],
                            "tools": []
                        },
                        {
                            "step_id": 2,
                            "name": "Step B",
                            "description": "Second step description",
                            "touched_files": ["file_b.txt"],
                            "tools": []
                        }
                    ]
                },
                "task_trap": {
                    "goal": "Trap task",
                    "steps": [
                        {
                            "step_id": 1,
                            "name": "Step Trap",
                            "description": "Trap step description",
                            "touched_files": ["trap_file.txt"],
                            "tools": ["gcc"],
                            "is_trap": True,
                            "trap_error": "gcc: compilation error",
                            "trap_fix": "Use clang instead"
                        }
                    ]
                },
                "task_blocked": {
                    "goal": "Blocked task",
                    "steps": [
                        {
                            "step_id": 1,
                            "name": "Step Blocked",
                            "description": "Blocked step description",
                            "touched_files": ["blocked_file.txt"],
                            "tools": ["make"]
                        }
                    ]
                }
            }
        }
        with open(agent_runner.MOCK_TASKS_FILE, 'w') as f:
            json.dump(self.mock_tasks, f, indent=2)
            
        with open(agent_runner.TOMBSTONES_FILE, 'w') as f:
            json.dump([], f)

    def tearDown(self):
        # Restore paths
        agent_runner.STATE_DIR = self.old_state_dir
        agent_runner.AGENTS_DIR = self.old_agents_dir
        agent_runner.COLLISIONS_DIR = self.old_collisions_dir
        agent_runner.WORKSPACES_DIR = self.old_workspaces_dir
        agent_runner.MOCK_TASKS_FILE = self.old_mock_tasks
        agent_runner.TOMBSTONES_FILE = self.old_tombstones
        
        import memory_store
        memory_store.DB_DIR = self.old_db_dir
        memory_store.DB_PATH = self.old_db_path
        
        shutil.rmtree(self.test_dir)

    def test_iso_timestamp_format(self):
        timestamp = get_iso_timestamp()
        # Verify it follows ISO-8601 format ending with Z
        self.assertTrue(timestamp.endswith("Z"))
        self.assertIn("T", timestamp)
        self.assertEqual(len(timestamp.split("-")), 3)

    def test_start_of_step_state_synchronization(self):
        runner = AgentRunner(agent_id="001", task_id="task_test")
        
        # Modify the state file on disk to simulate external changes or verifying starting step state is written
        # Make sure current_step is correctly initialized
        state_on_disk = load_json(runner.state_file)
        self.assertEqual(state_on_disk["current_step"]["name"], "Step A")
        self.assertEqual(state_on_disk["status"], "exploring")
        
        # Change state status in memory, check if execute_step writes it on start
        runner.state["progress"] = 10
        
        # Run step (with mocked subprocess / LLM bypass)
        with unittest.mock.patch("agent_runner.call_ollama_raw", return_value="dummy"):
            runner.execute_step()
            
        # Verify state was saved to disk
        state_on_disk_new = load_json(runner.state_file)
        self.assertEqual(state_on_disk_new["progress"], 50)  # completed step 1 of 2
        self.assertEqual(state_on_disk_new["steps_completed"], 1)

    def test_tombstone_absolute_blockade(self):
        # Register an absolute tombstone blocker
        tombstone_data = {
            "file_path": "blocked_file.txt",
            "tool_used": "make",
            "error_message": "unsupported platform blocker",
            "fix_action": "no workaround available",
            "timestamp": "2026-06-13T01:00:00Z"
        }
        with open(agent_runner.TOMBSTONES_FILE, 'w') as f:
            json.dump([tombstone_data], f, indent=2)
            
        runner = AgentRunner(agent_id="002", task_id="task_blocked")
        
        # Run step. It should hit the absolute tombstone, fail to apply a workaround,
        # and transition to pending_termination without executing.
        runner.execute_step()
        
        self.assertEqual(runner.state["status"], "pending_termination")
        state_on_disk = load_json(runner.state_file)
        self.assertEqual(state_on_disk["status"], "pending_termination")

    def test_tombstone_timestamp_in_iso_format(self):
        runner = AgentRunner(agent_id="003", task_id="task_trap")
        
        # Run step. It should crash (is_trap is true) and register a tombstone
        runner.execute_step()
        
        self.assertEqual(runner.state["status"], "pending_termination")
        
        tombstones = load_json(agent_runner.TOMBSTONES_FILE)
        self.assertEqual(len(tombstones), 1)
        t = tombstones[0]
        self.assertEqual(t["file_path"], "trap_file.txt")
        self.assertEqual(t["tool_used"], "gcc")
        # Verify timestamp is in ISO format
        self.assertTrue(t["timestamp"].endswith("Z"))
        self.assertIn("T", t["timestamp"])

    def test_negotiation_redundancy_resolution(self):
        runner_a = AgentRunner(agent_id="004", task_id="task_test")
        runner_b = AgentRunner(agent_id="005", task_id="task_test")
        
        # Advance runner_a progress to make it survivor
        runner_a.state["steps_completed"] = 1
        runner_a.state["progress"] = 50
        runner_a.state["touched_files"] = ["file_a.txt"]
        runner_a.state["tools_used"] = ["editor"]
        save_json(runner_a.state_file, runner_a.state)
        
        # Write dummy workspace files for runner_b (loser) to test knowledge sharing
        b_ws = os.path.join(agent_runner.WORKSPACES_DIR, "agent_005")
        os.makedirs(b_ws, exist_ok=True)
        with open(os.path.join(b_ws, "temp.py"), 'w') as f:
            f.write("print('hello')")
            
        # Create collision file
        collision_id = "004_005"
        collision_file = os.path.join(agent_runner.COLLISIONS_DIR, f"collision_{collision_id}.json")
        collision_data = {
            "collision_id": collision_id,
            "timestamp": 12345.67,
            "distance": 0.1,
            "similarity_metrics": {"goal_cosine": 0.9, "file_jaccard": 0.0, "tool_jaccard": 0.0},
            "agent_a": runner_a.state,
            "agent_b": runner_b.state,
            "status": "pending_negotiation",
            "negotiation_log": []
        }
        save_json(collision_file, collision_data)
        
        # Set runner_b status to syncing and trigger negotiation
        runner_b.state["status"] = "syncing"
        save_json(runner_b.state_file, runner_b.state)
        
        # Mock LLM negotiation to propose kill_b (since B has 0% and A has 50%)
        with unittest.mock.patch("agent_runner.call_ollama_api", return_value={"action": "kill_b", "reason": "Redundant goals"}):
            runner_b.execute_step()
            
        # Verify runner_b is pending_termination
        b_state = load_json(runner_b.state_file)
        self.assertEqual(b_state["status"], "pending_termination")
        
        # Verify runner_a is exploring
        a_state = load_json(runner_a.state_file)
        self.assertEqual(a_state["status"], "exploring")
        
        # Verify survivor runner_a absorbed loser runner_b state (since loser had empty touched files in initialized dict, but let's check tools/files)
        # Verify copy to survivor's workspace and shared workspace
        survivor_file = os.path.join(agent_runner.WORKSPACES_DIR, "agent_004", "temp.py")
        shared_file = os.path.join(agent_runner.WORKSPACES_DIR, "shared", "temp.py")
        self.assertTrue(os.path.exists(survivor_file))
        self.assertTrue(os.path.exists(shared_file))

    def test_negotiation_complementary_resolution_and_bypass(self):
        runner_a = AgentRunner(agent_id="006", task_id="task_test")
        runner_b = AgentRunner(agent_id="007", task_id="task_test")
        
        # runner_a has completed Step A
        runner_a.state["steps_completed"] = 1
        runner_a.state["progress"] = 50
        save_json(runner_a.state_file, runner_a.state)
        
        # Create files to transfer
        a_ws = os.path.join(agent_runner.WORKSPACES_DIR, "agent_006")
        os.makedirs(a_ws, exist_ok=True)
        with open(os.path.join(a_ws, "file_a.txt"), 'w') as f:
            f.write("A done")
            
        collision_id = "006_007"
        collision_file = os.path.join(agent_runner.COLLISIONS_DIR, f"collision_{collision_id}.json")
        collision_data = {
            "collision_id": collision_id,
            "timestamp": 12345.67,
            "distance": 0.3,
            "similarity_metrics": {"goal_cosine": 0.4, "file_jaccard": 0.0, "tool_jaccard": 0.0},
            "agent_a": runner_a.state,
            "agent_b": runner_b.state,
            "status": "pending_negotiation",
            "negotiation_log": []
        }
        save_json(collision_file, collision_data)
        
        runner_b.state["status"] = "syncing"
        save_json(runner_b.state_file, runner_b.state)
        
        # Mock LLM negotiation to propose keep_both
        with unittest.mock.patch("agent_runner.call_ollama_api", return_value={"action": "keep_both", "reason": "Complementary tasks"}):
            runner_b.execute_step()
            
        # Verify both are exploring
        a_state = load_json(runner_a.state_file)
        b_state = load_json(runner_b.state_file)
        self.assertEqual(a_state["status"], "exploring")
        self.assertEqual(b_state["status"], "exploring")
        
        # Verify mutual state file transfer (file_a.txt exists in agent_007's workspace)
        self.assertTrue(os.path.exists(os.path.join(agent_runner.WORKSPACES_DIR, "agent_007", "file_a.txt")))
        
        # Verify Agent B bypassed step A (since Agent A completed it, and they have the same task steps)
        # So Agent B's steps_completed should be advanced to 1, and progress to 50
        self.assertEqual(b_state["steps_completed"], 1)
        self.assertEqual(b_state["progress"], 50)
        self.assertEqual(b_state["current_step"]["name"], "Step B")

    def test_evaluate_isolation_spawn(self):
        runner = AgentRunner(agent_id="008", task_id="task_test")
        
        # Trigger isolated spawn check
        # We need steps_completed = 5. Let's make a mock task with 6 steps so we can test steps_completed = 5
        runner.mock_tasks = {
            "tasks": {
                "task_test": {
                    "goal": "Test task",
                    "steps": [{"step_id": i, "name": f"S{i}", "description": f"D{i}"} for i in range(1, 7)]
                }
            }
        }
        # Override mock tasks file content to match
        with open(agent_runner.MOCK_TASKS_FILE, 'w') as f:
            json.dump(runner.mock_tasks, f, indent=2)
            
        runner.state["steps_completed"] = 5
        save_json(runner.state_file, runner.state)
        
        # With active_others = 0 (only agent 008 exists in agents dir), evaluating spawn should trigger request_spawn_agent
        with unittest.mock.patch("agent_runner.call_ollama_api", return_value=None): # Bypass LLM evaluation
            runner.evaluate_isolation_spawn()
            
        # Verify spawn_request was registered
        state = load_json(runner.state_file)
        self.assertIn("spawn_request", state)
        self.assertIn("Parallel sub-task", state["spawn_request"]["goal"])
        self.assertEqual(state["spawn_request"]["status"], "pending")

    def test_monitor_spawn_request_interactive(self):
        import proximity_monitor
        # Save old values to restore
        old_interactive = proximity_monitor.INTERACTIVE
        old_agents_dir = proximity_monitor.AGENTS_DIR
        old_workspaces_dir = proximity_monitor.WORKSPACES_DIR
        old_state_dir = proximity_monitor.STATE_DIR
        
        try:
            # Set up an agent with a spawn request
            agent_data = {
                "id": "009",
                "goal": "Parent goal",
                "status": "exploring",
                "spawn_request": {
                    "goal": "Child goal",
                    "initial_files": ["child.py"],
                    "status": "pending"
                }
            }
            agent_file = os.path.join(agent_runner.AGENTS_DIR, "agent_009.json")
            save_json(agent_file, agent_data)
            
            # In interactive mode, if spawn request is pending, it should NOT be provisioned
            proximity_monitor.INTERACTIVE = True
            proximity_monitor.AGENTS_DIR = agent_runner.AGENTS_DIR
            proximity_monitor.WORKSPACES_DIR = agent_runner.WORKSPACES_DIR
            proximity_monitor.STATE_DIR = agent_runner.STATE_DIR
            
            proximity_monitor.handle_spawn_requests([agent_data])
            
            # Verify it wasn't provisioned (no agent_010.json created, spawn_request remains)
            self.assertFalse(os.path.exists(os.path.join(agent_runner.AGENTS_DIR, "agent_010.json")))
            
            # Now set it to approved
            agent_data["spawn_request"]["status"] = "approved"
            save_json(agent_file, agent_data)
            
            proximity_monitor.handle_spawn_requests([agent_data])
            
            # Verify it was provisioned (agent 010 should be next, but we need to check directory listing)
            # Find any new agent files
            agent_files = os.listdir(agent_runner.AGENTS_DIR)
            new_agents = [f for f in agent_files if f.startswith("agent_") and not f.endswith("agent_009.json") and not f.endswith("agent_008.json")]
            self.assertTrue(len(new_agents) > 0)
            
            # Parent spawn_request should be cleared
            parent_state = load_json(agent_file)
            self.assertIsNone(parent_state["spawn_request"])
            
            # Now test rejected status
            agent_data_rej = {
                "id": "011",
                "goal": "Parent goal 2",
                "status": "exploring",
                "spawn_request": {
                    "goal": "Child goal 2",
                    "initial_files": ["child2.py"],
                    "status": "rejected"
                }
            }
            agent_file_rej = os.path.join(agent_runner.AGENTS_DIR, "agent_011.json")
            save_json(agent_file_rej, agent_data_rej)
            
            proximity_monitor.handle_spawn_requests([agent_data_rej])
            
            # Parent spawn_request should be cleared
            parent_state_rej = load_json(agent_file_rej)
            self.assertIsNone(parent_state_rej["spawn_request"])
        finally:
            # Restore values
            proximity_monitor.INTERACTIVE = old_interactive
            proximity_monitor.AGENTS_DIR = old_agents_dir
            proximity_monitor.WORKSPACES_DIR = old_workspaces_dir
            proximity_monitor.STATE_DIR = old_state_dir

    def test_negotiation_step_review_mocked(self):
        # Set up a complementary negotiation scenario to test LLM review logic
        runner_a = AgentRunner(agent_id="020", task_id="task_test")
        runner_b = AgentRunner(agent_id="021", task_id="task_test")
        
        # agent_a has completed Step A
        runner_a.state["steps_completed"] = 1
        runner_a.state["progress"] = 50
        save_json(runner_a.state_file, runner_a.state)
        
        # Write peer-generated file
        a_ws = os.path.join(agent_runner.WORKSPACES_DIR, "agent_020")
        os.makedirs(a_ws, exist_ok=True)
        with open(os.path.join(a_ws, "file_a.txt"), 'w') as f:
            f.write("Completed Step A")
            
        collision_id = "020_021"
        collision_file = os.path.join(agent_runner.COLLISIONS_DIR, f"collision_{collision_id}.json")
        collision_data = {
            "collision_id": collision_id,
            "timestamp": 12345.67,
            "distance": 0.3,
            "similarity_metrics": {"goal_cosine": 0.4, "file_jaccard": 0.0, "tool_jaccard": 0.0},
            "agent_a": runner_a.state,
            "agent_b": runner_b.state,
            "status": "pending_negotiation",
            "negotiation_log": []
        }
        save_json(collision_file, collision_data)
        
        runner_b.state["status"] = "syncing"
        save_json(runner_b.state_file, runner_b.state)
        
        # Case 1: LLM says should_bypass = True
        with unittest.mock.patch("agent_runner.call_ollama_api") as mock_api:
            # First call for keep_both negotiation outcome, second for LLM step review
            mock_api.side_effect = [
                {"action": "keep_both", "reason": "Complementary tasks"},
                {"should_bypass": True, "reason": "Verified generated files satisfy requirements"}
            ]
            # Override provider to force LLM review path
            runner_b.llm_provider = "ollama"
            runner_b.execute_step()
            
        b_state = load_json(runner_b.state_file)
        # Verify bypassed (steps_completed advanced to 1)
        self.assertEqual(b_state["steps_completed"], 1)

    def test_budget_pruning_system_logic(self):
        import proximity_monitor
        import terminal_dashboard
        import time
        
        # 1. Setup mock agents
        # Agent 001: Parent (active)
        # Agent 002: Child of 001 (active, progress 30%)
        # Agent 003: Child of 001 (active, progress 50%)
        # Agent 004: Dead agent (should not count)
        
        agent_001 = {
            "id": "001",
            "parent_id": None,
            "parent_ids": [],
            "status": "exploring",
            "goal": "Parent goal",
            "progress": 20,
            "last_updated": time.time() - 100
        }
        agent_002 = {
            "id": "002",
            "parent_id": "001",
            "parent_ids": ["001"],
            "status": "exploring",
            "goal": "Child 002 goal",
            "progress": 30,
            "last_updated": time.time() - 50
        }
        agent_003 = {
            "id": "003",
            "parent_id": "001",
            "parent_ids": ["001"],
            "status": "exploring",
            "goal": "Child 003 goal",
            "progress": 50,
            "last_updated": time.time() - 200  # older / more inactive
        }
        agent_004 = {
            "id": "004",
            "parent_id": None,
            "parent_ids": [],
            "status": "dead",
            "goal": "Dead agent goal",
            "progress": 100,
            "last_updated": time.time()
        }
        
        save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_001.json"), agent_001)
        save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_002.json"), agent_002)
        save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_003.json"), agent_003)
        save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_004.json"), agent_004)
        
        # Override monitor state directories
        old_agents_dir = proximity_monitor.AGENTS_DIR
        old_state_dir = proximity_monitor.STATE_DIR
        proximity_monitor.AGENTS_DIR = agent_runner.AGENTS_DIR
        proximity_monitor.STATE_DIR = agent_runner.STATE_DIR
        
        try:
            # 2. Test get_active_leaf_agents
            active_agents = [agent_001, agent_002, agent_003]
            leafs = proximity_monitor.get_active_leaf_agents(active_agents)
            leaf_ids = [l["id"] for l in leafs]
            
            # Agent 001 is a parent of active agents, so 002 and 003 should be the leaves
            self.assertIn("002", leaf_ids)
            self.assertIn("003", leaf_ids)
            self.assertNotIn("001", leaf_ids)
            
            # 3. Test fallback heuristic ranking
            with unittest.mock.patch("proximity_monitor.is_ollama_running", return_value=False), \
                 unittest.mock.patch("os.environ.get", return_value=None):
                ranked = proximity_monitor.rank_leaf_agents_llm(leafs, "Macro goal")
                
            # Fallback sort key: progress ascending, then inactivity descending (more inactive comes first)
            # Leafs: 
            # - 002 (progress: 30%, inactivity: 50s)
            # - 003 (progress: 50%, inactivity: 200s)
            # Since progress of 002 (30) < 003 (50), 002 must be ranked first (least productive).
            self.assertEqual(ranked[0]["id"], "002")
            self.assertEqual(ranked[1]["id"], "003")
            
            # Adjust progress of 002 to 50% so they have equal progress.
            # Then we look at inactivity: 003 is more inactive (200s vs 50s), so 003 must be ranked first.
            agent_002["progress"] = 50
            save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_002.json"), agent_002)
            leafs_updated = [agent_001, agent_002, agent_003]
            leafs_filtered = proximity_monitor.get_active_leaf_agents(leafs_updated)
            with unittest.mock.patch("proximity_monitor.is_ollama_running", return_value=False), \
                 unittest.mock.patch("os.environ.get", return_value=None):
                ranked_equal = proximity_monitor.rank_leaf_agents_llm(leafs_filtered, "Macro goal")
            self.assertEqual(ranked_equal[0]["id"], "003")
            self.assertEqual(ranked_equal[1]["id"], "002")
            
            # Now set output tokens of 002 to 1000 and 003 to 10.
            # Since 002 has consumed more tokens, it should be ranked first (pruned first) despite being more active.
            agent_002["output_tokens"] = 1000
            agent_003["output_tokens"] = 10
            save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_002.json"), agent_002)
            save_json(os.path.join(agent_runner.AGENTS_DIR, "agent_003.json"), agent_003)
            leafs_updated_t = [agent_001, agent_002, agent_003]
            leafs_filtered_t = proximity_monitor.get_active_leaf_agents(leafs_updated_t)
            with unittest.mock.patch("proximity_monitor.is_ollama_running", return_value=False), \
                 unittest.mock.patch("os.environ.get", return_value=None):
                ranked_tokens = proximity_monitor.rank_leaf_agents_llm(leafs_filtered_t, "Macro goal")
            self.assertEqual(ranked_tokens[0]["id"], "002")
            self.assertEqual(ranked_tokens[1]["id"], "003")
            
            # 4. Test dashboard pruning commands and safety
            terminal_dashboard.AGENTS_DIR = agent_runner.AGENTS_DIR
            terminal_dashboard.STATE_DIR = agent_runner.STATE_DIR
            terminal_dashboard.TOMBSTONES_FILE = agent_runner.TOMBSTONES_FILE
            
            # Verify: Pruning non-leaf agent (001) should fail (leaf safety restriction)
            success_prune_parent, msg_parent = terminal_dashboard.handle_dashboard_pruning("001")
            self.assertFalse(success_prune_parent)
            self.assertIn("not a leaf agent", msg_parent)
            
            # Verify: Pruning leaf agent (003) should succeed
            success_prune_child, msg_child = terminal_dashboard.handle_dashboard_pruning("003")
            self.assertTrue(success_prune_child)
            
            # State of 003 should transition to dead
            state_003 = load_json(os.path.join(agent_runner.AGENTS_DIR, "agent_003.json"))
            self.assertEqual(state_003["status"], "dead")
            
            # Check registered tombstone
            tombstones = load_json(agent_runner.TOMBSTONES_FILE)
            pruned_tombstone = next((t for t in tombstones if t.get("is_pruned")), None)
            self.assertIsNotNone(pruned_tombstone)
            self.assertEqual(pruned_tombstone["goal"], "Child 003 goal")
            self.assertTrue(pruned_tombstone.get("is_pruned"))
            
            # 5. Verify agent runner ignores pruned tombstone blockade
            runner = AgentRunner(agent_id="002", task_id="task_test")
            runner.state["status"] = "exploring"
            # Set touched files/tools to trigger match
            runner.state["touched_files"] = [pruned_tombstone["file_path"]]
            runner.state["tools_used"] = [pruned_tombstone["tool_used"]]
            save_json(runner.state_file, runner.state)
            
            # Ensure it is parsed by check_tombstones as NOT an absolute blockade
            matched_blocker = runner.check_tombstones(runner.state["touched_files"], runner.state["tools_used"])
            self.assertIsNone(matched_blocker)
            
            # Verify that check_pruned_tombstones actually detects it
            matched_pruned = runner.check_pruned_tombstones(runner.state["touched_files"], runner.state["tools_used"])
            self.assertEqual(len(matched_pruned), 1)
            self.assertEqual(matched_pruned[0]["goal"], "Child 003 goal")
            
        finally:
            proximity_monitor.AGENTS_DIR = old_agents_dir
            proximity_monitor.STATE_DIR = old_state_dir


if __name__ == "__main__":
    unittest.main()
