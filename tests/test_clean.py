import os
import sys
import json
import tempfile
import shutil
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import terminal_dashboard

class TestCleanGranular(unittest.TestCase):
    def setUp(self):
        # Create a temp directory for tests
        self.test_dir = tempfile.mkdtemp()
        
        # Save original paths
        self.orig_state_dir = terminal_dashboard.STATE_DIR
        self.orig_collisions_dir = terminal_dashboard.COLLISIONS_DIR
        self.orig_tombstones_file = terminal_dashboard.TOMBSTONES_FILE
        self.orig_log_file = terminal_dashboard.LOG_FILE
        self.orig_mock_tasks_file = terminal_dashboard.MOCK_TASKS_FILE
        
        # Override with temp paths
        terminal_dashboard.STATE_DIR = os.path.join(self.test_dir, ".proximity_swarm")
        terminal_dashboard.COLLISIONS_DIR = os.path.join(terminal_dashboard.STATE_DIR, "collisions")
        terminal_dashboard.TOMBSTONES_FILE = os.path.join(terminal_dashboard.STATE_DIR, "tombstones.json")
        terminal_dashboard.LOG_FILE = os.path.join(terminal_dashboard.STATE_DIR, "monitor.log")
        terminal_dashboard.MOCK_TASKS_FILE = os.path.join(self.test_dir, "mock_tasks.json")
        
        # Ensure parent directory of state files exists
        os.makedirs(terminal_dashboard.STATE_DIR, exist_ok=True)
        
        # Set up a fake mock_tasks.json
        self.mock_tasks_data = {
            "tasks": {
                "task_jwt_auth": {"goal": "Implement JWT"},
                "task_dynamic_12345": {"goal": "Decompose quicksort"},
                "task_dynamic_67890": {"goal": "Write code"}
            }
        }
        with open(terminal_dashboard.MOCK_TASKS_FILE, 'w') as f:
            json.dump(self.mock_tasks_data, f, indent=2)

    def tearDown(self):
        # Clean up the temp directory
        shutil.rmtree(self.test_dir)
        
        # Restore original paths
        terminal_dashboard.STATE_DIR = self.orig_state_dir
        terminal_dashboard.COLLISIONS_DIR = self.orig_collisions_dir
        terminal_dashboard.TOMBSTONES_FILE = self.orig_tombstones_file
        terminal_dashboard.LOG_FILE = self.orig_log_file
        terminal_dashboard.MOCK_TASKS_FILE = self.orig_mock_tasks_file

    def test_clean_logs(self):
        # Create log file
        log_path = terminal_dashboard.LOG_FILE
        with open(log_path, 'w') as f:
            f.write("Some logs here\n")
        self.assertTrue(os.path.exists(log_path))
        
        # Purge logs
        terminal_dashboard.purge_artifacts("logs")
        self.assertFalse(os.path.exists(log_path))

    def test_clean_collisions(self):
        collisions_dir = terminal_dashboard.COLLISIONS_DIR
        os.makedirs(collisions_dir, exist_ok=True)
        col_file = os.path.join(collisions_dir, "col_1.json")
        with open(col_file, 'w') as f:
            json.dump({"status": "pending"}, f)
            
        self.assertTrue(os.path.exists(col_file))
        
        # Purge collisions
        terminal_dashboard.purge_artifacts("collisions")
        self.assertTrue(os.path.exists(collisions_dir))
        self.assertEqual(os.listdir(collisions_dir), [])

    def test_clean_tombstones(self):
        ts_file = terminal_dashboard.TOMBSTONES_FILE
        with open(ts_file, 'w') as f:
            json.dump([{"file_path": "foo.py", "error_message": "err"}], f)
            
        # Purge tombstones
        terminal_dashboard.purge_artifacts("tombstones")
        self.assertTrue(os.path.exists(ts_file))
        with open(ts_file, 'r') as f:
            data = json.load(f)
        self.assertEqual(data, [])

    def test_clean_tasks(self):
        # Purge tasks
        terminal_dashboard.purge_artifacts("tasks")
        with open(terminal_dashboard.MOCK_TASKS_FILE, 'r') as f:
            data = json.load(f)
        self.assertIn("task_jwt_auth", data["tasks"])
        self.assertNotIn("task_dynamic_12345", data["tasks"])
        self.assertNotIn("task_dynamic_67890", data["tasks"])

    def test_clean_all(self):
        # Populate everything
        os.makedirs(terminal_dashboard.COLLISIONS_DIR, exist_ok=True)
        with open(os.path.join(terminal_dashboard.COLLISIONS_DIR, "col_1.json"), 'w') as f:
            json.dump({}, f)
        with open(terminal_dashboard.LOG_FILE, 'w') as f:
            f.write("log")
        with open(terminal_dashboard.TOMBSTONES_FILE, 'w') as f:
            json.dump([{"err": 1}], f)
            
        terminal_dashboard.purge_artifacts()
        
        # Everything in state dir should be gone/reset
        self.assertTrue(os.path.exists(terminal_dashboard.STATE_DIR))
        self.assertFalse(os.path.exists(terminal_dashboard.LOG_FILE))
        self.assertEqual(os.listdir(terminal_dashboard.COLLISIONS_DIR) if os.path.exists(terminal_dashboard.COLLISIONS_DIR) else [], [])
        
        # Tombstones should be reset to empty list
        with open(terminal_dashboard.TOMBSTONES_FILE, 'r') as f:
            data = json.load(f)
        self.assertEqual(data, [])
        
        # Tasks should have dynamic filtered out
        with open(terminal_dashboard.MOCK_TASKS_FILE, 'r') as f:
            tasks_data = json.load(f)
        self.assertNotIn("task_dynamic_12345", tasks_data["tasks"])

    def test_clean_specific_workspace_files(self):
        # Create workspaces structure
        workspaces_dir = os.path.join(terminal_dashboard.STATE_DIR, "workspaces")
        agent_dir = os.path.join(workspaces_dir, "agent_001")
        src_dir = os.path.join(agent_dir, "src")
        os.makedirs(src_dir, exist_ok=True)
        
        quicksort_path = os.path.join(src_dir, "quicksort.py")
        other_path = os.path.join(src_dir, "other.py")
        
        with open(quicksort_path, 'w') as f:
            f.write("def quicksort(): pass\n")
        with open(other_path, 'w') as f:
            f.write("other\n")
            
        self.assertTrue(os.path.exists(quicksort_path))
        self.assertTrue(os.path.exists(other_path))
        
        # Clean specific file (by relative path or name)
        terminal_dashboard.purge_artifacts("quicksort.py")
        self.assertFalse(os.path.exists(quicksort_path))
        self.assertTrue(os.path.exists(other_path))
        
        # Clean specific file by relative path containing agent ID
        with open(quicksort_path, 'w') as f:
            f.write("def quicksort(): pass\n")
        self.assertTrue(os.path.exists(quicksort_path))
        
        terminal_dashboard.purge_artifacts("agent_001/src/quicksort.py")
        self.assertFalse(os.path.exists(quicksort_path))
        self.assertTrue(os.path.exists(other_path))


if __name__ == "__main__":
    unittest.main()
