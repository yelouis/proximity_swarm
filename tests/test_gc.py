import unittest
import os
import shutil
import json
import sqlite3
import datetime
import tarfile

import memory_store
import logic_graph
import workspace_gc
from agent_runner import STATE_DIR, TOMBSTONES_FILE

class TestGarbageCollection(unittest.TestCase):
    def setUp(self):
        self.test_dir = os.path.join(os.getcwd(), ".test_proximity_gc")
        os.makedirs(self.test_dir, exist_ok=True)
        
        # Override paths for testing
        self.orig_db_dir = memory_store.DB_DIR
        self.orig_db_path = memory_store.DB_PATH
        memory_store.DB_DIR = self.test_dir
        memory_store.DB_PATH = os.path.join(self.test_dir, "memory.db")
        
        self.orig_graph_dir = logic_graph.GRAPH_DIR
        self.orig_snapshot = logic_graph.SNAPSHOT_FILE
        logic_graph.GRAPH_DIR = os.path.join(self.test_dir, "graph")
        logic_graph.SNAPSHOT_FILE = os.path.join(logic_graph.GRAPH_DIR, "snapshot.json")
        logic_graph._IS_MONITOR = True
        
        self.orig_workspaces_dir = workspace_gc.WORKSPACES_DIR
        workspace_gc.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        os.makedirs(workspace_gc.WORKSPACES_DIR, exist_ok=True)
        
        self.orig_tombstones = workspace_gc.TOMBSTONES_FILE
        workspace_gc.TOMBSTONES_FILE = os.path.join(self.test_dir, "tombstones.json")
        workspace_gc.STATE_DIR = self.test_dir

    def tearDown(self):
        memory_store.DB_DIR = self.orig_db_dir
        memory_store.DB_PATH = self.orig_db_path
        logic_graph.GRAPH_DIR = self.orig_graph_dir
        logic_graph.SNAPSHOT_FILE = self.orig_snapshot
        workspace_gc.WORKSPACES_DIR = self.orig_workspaces_dir
        workspace_gc.TOMBSTONES_FILE = self.orig_tombstones
        
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_memory_enforce_limit(self):
        memory_store.init_db()
        conn = memory_store.get_db_connection()
        cursor = conn.cursor()
        
        # Insert 10 mock episodes
        for i in range(10):
            cursor.execute("""
                INSERT INTO episodic_memories (goal, role, status, steps, errors, deliverable_summary, reflection, embedding)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (f"Goal {i}", "Role", "completed", "[]", "", "Summary", "Reflect", "[]"))
        conn.commit()
        conn.close()
        
        # Enforce limit of 5
        memory_store.enforce_memory_limit(max_episodes=5)
        
        conn = memory_store.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM episodic_memories")
        count = cursor.fetchone()[0]
        
        cursor.execute("SELECT MIN(id) FROM episodic_memories")
        min_id = cursor.fetchone()[0]
        conn.close()
        
        self.assertEqual(count, 5, "Memory limit was not enforced to 5")
        self.assertGreater(min_id, 5, "Oldest rows were not deleted properly")

    def test_graph_garbage_collect(self):
        logic_graph.init_graph()
        
        # Add 3 nodes
        for i in range(3):
            logic_graph.add_node({
                "node_id": f"n00{i}",
                "status": "validated"
            })
            
        nodes = logic_graph._get_all_nodes()
        self.assertEqual(len(nodes), 3)
        
        # Run GC
        success = logic_graph.garbage_collect_post_run()
        self.assertTrue(success)
        
        # Ensure individual files are deleted
        node_files = [f for f in os.listdir(logic_graph.GRAPH_DIR) if f.startswith("node_")]
        self.assertEqual(len(node_files), 0, "Node files were not deleted by GC")
        
        # Ensure snapshot exists and has 3 nodes
        snap_data = logic_graph.load_json(logic_graph.SNAPSHOT_FILE)
        self.assertEqual(len(snap_data["nodes"]), 3)
        
        # Ensure archive exists
        archives_dir = os.path.join(logic_graph.GRAPH_DIR, "archives")
        archives = os.listdir(archives_dir)
        self.assertEqual(len(archives), 1)
        self.assertTrue(archives[0].endswith(".tar.gz"))

    def test_workspace_cleanup_safe(self):
        # Create a mock file in the safe workspace
        safe_file = os.path.join(workspace_gc.WORKSPACES_DIR, "dead_script.py")
        with open(safe_file, 'w') as f:
            f.write("print('dead')")
            
        # Create tombstones file
        tombstones = [
            {"file_path": safe_file, "is_pruned": False}
        ]
        with open(workspace_gc.TOMBSTONES_FILE, 'w') as f:
            json.dump(tombstones, f)
            
        # Run dry run
        success = workspace_gc.cleanup_workspace(dry_run=True)
        self.assertTrue(success)
        self.assertTrue(os.path.exists(safe_file), "Dry run deleted a file")
        
        # Run real cleanup
        success = workspace_gc.cleanup_workspace(dry_run=False)
        self.assertTrue(success)
        self.assertFalse(os.path.exists(safe_file), "GC failed to delete safe workspace file")
        
        # Check manifest
        manifests = [f for f in os.listdir(self.test_dir) if f.startswith("gc_manifest_")]
        self.assertEqual(len(manifests), 2) # 1 for dry-run, 1 for real run

    def test_workspace_cleanup_jail_rejects_escape(self):
        # Create a mock file OUTSIDE the workspace jail
        unsafe_dir = os.path.join(self.test_dir, "outside")
        os.makedirs(unsafe_dir, exist_ok=True)
        unsafe_file = os.path.join(unsafe_dir, "system.cfg")
        with open(unsafe_file, 'w') as f:
            f.write("secret")
            
        # Use relative path escape in tombstone
        escape_path = os.path.join(workspace_gc.WORKSPACES_DIR, "..", "outside", "system.cfg")
        
        tombstones = [
            {"file_path": escape_path}
        ]
        with open(workspace_gc.TOMBSTONES_FILE, 'w') as f:
            json.dump(tombstones, f)
            
        success = workspace_gc.cleanup_workspace(dry_run=False)
        self.assertTrue(success)
        
        # Assert file was NOT deleted
        self.assertTrue(os.path.exists(unsafe_file), "GC failed to respect the path jail!")

if __name__ == "__main__":
    unittest.main()
