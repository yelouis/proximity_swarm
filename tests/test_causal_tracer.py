import os
import sys
import unittest
import json
import shutil
import tempfile

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import causal_tracer


class TestCausalTracer(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.orig_db_path = causal_tracer.DB_PATH
        causal_tracer.DB_PATH = os.path.join(self.test_dir, "causal_graph.db")

    def tearDown(self):
        causal_tracer.DB_PATH = self.orig_db_path
        shutil.rmtree(self.test_dir)

    def test_schema_initialization(self):
        # Database connection automatically runs init schema
        conn = causal_tracer.get_db_connection()
        cursor = conn.cursor()
        
        # Verify trace_nodes table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trace_nodes'")
        self.assertIsNotNone(cursor.fetchone())
        
        # Verify trace_edges table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='trace_edges'")
        self.assertIsNotNone(cursor.fetchone())
        conn.close()

    def test_log_agent_spawn(self):
        causal_tracer.log_agent_spawn("001", "002", "Sub-task quicksort")
        
        conn = causal_tracer.get_db_connection()
        # Verify nodes
        p_node = conn.execute("SELECT * FROM trace_nodes WHERE id='agent_001'").fetchone()
        c_node = conn.execute("SELECT * FROM trace_nodes WHERE id='agent_002'").fetchone()
        
        self.assertIsNotNone(p_node)
        self.assertEqual(p_node["type"], "agent")
        self.assertIsNotNone(c_node)
        self.assertEqual(c_node["type"], "agent")
        self.assertIn("Sub-task quicksort", c_node["metadata"])
        
        # Verify edge
        edge = conn.execute("SELECT * FROM trace_edges WHERE source='agent_001' AND target='agent_002'").fetchone()
        self.assertIsNotNone(edge)
        self.assertEqual(edge["type"], "spawn")
        self.assertIn("Sub-task quicksort", edge["details"])
        conn.close()

    def test_log_step_execution(self):
        causal_tracer.log_step_execution("001", 1, "Init DB", "Initialize SQL schema", "executing")
        causal_tracer.log_step_execution("001", 2, "Write endpoints", "Develop endpoints logic", "completed")
        
        conn = causal_tracer.get_db_connection()
        # Verify step nodes
        step1 = conn.execute("SELECT * FROM trace_nodes WHERE id='agent_001_step_1'").fetchone()
        step2 = conn.execute("SELECT * FROM trace_nodes WHERE id='agent_001_step_2'").fetchone()
        self.assertIsNotNone(step1)
        self.assertIsNotNone(step2)
        self.assertEqual(step2["type"], "step")
        self.assertIn("endpoints logic", step2["metadata"])
        
        # Verify progression edge (step 1 -> step 2)
        prog_edge = conn.execute("SELECT * FROM trace_edges WHERE source='agent_001_step_1' AND target='agent_001_step_2'").fetchone()
        self.assertIsNotNone(prog_edge)
        self.assertEqual(prog_edge["type"], "step_progression")
        conn.close()

    def test_log_collision_and_takeover(self):
        causal_tracer.log_collision("001_002", "001", "002", {"distance": 0.3})
        causal_tracer.log_takeover("001_002", "001", "002", "Agent 001 is further ahead")
        
        conn = causal_tracer.get_db_connection()
        collision_node = conn.execute("SELECT * FROM trace_nodes WHERE id='collision_001_002'").fetchone()
        self.assertIsNotNone(collision_node)
        self.assertEqual(collision_node["type"], "collision")
        
        # Verify entry edges
        entry_a = conn.execute("SELECT * FROM trace_edges WHERE source='agent_001' AND target='collision_001_002'").fetchone()
        entry_b = conn.execute("SELECT * FROM trace_edges WHERE source='agent_002' AND target='collision_001_002'").fetchone()
        self.assertIsNotNone(entry_a)
        self.assertIsNotNone(entry_b)
        
        # Verify exit/takeover edges
        survivor_edge = conn.execute("SELECT * FROM trace_edges WHERE source='collision_001_002' AND target='agent_001'").fetchone()
        loser_edge = conn.execute("SELECT * FROM trace_edges WHERE source='collision_001_002' AND target='agent_002'").fetchone()
        self.assertIsNotNone(survivor_edge)
        self.assertEqual(survivor_edge["type"], "takeover_survivor")
        self.assertIsNotNone(loser_edge)
        self.assertEqual(loser_edge["type"], "takeover_loser")
        conn.close()

    def test_bfs_filtering_and_mermaid(self):
        # Swarm 1: Agent 001 spawns Agent 002
        causal_tracer.log_agent_spawn("001", "002", "Goal A")
        
        # Swarm 2: Isolated Agent 003 spawns Agent 004
        causal_tracer.log_agent_spawn("003", "004", "Goal B")
        
        # Filter trace for Agent 002
        filtered_component = causal_tracer.get_connected_component("agent_002")
        
        # Should contain agent_001 and agent_002, but NOT agent_003 and agent_004
        self.assertIn("agent_001", filtered_component)
        self.assertIn("agent_002", filtered_component)
        self.assertNotIn("agent_003", filtered_component)
        self.assertNotIn("agent_004", filtered_component)
        
        # Generate Mermaid graph for Agent 002
        mermaid = causal_tracer.generate_mermaid_graph("002")
        self.assertIn("agent_001", mermaid)
        self.assertIn("agent_002", mermaid)
        self.assertNotIn("agent_003", mermaid)
        self.assertNotIn("agent_004", mermaid)
        self.assertIn("graph TD", mermaid)
        self.assertIn("-->|spawn|", mermaid)
        
        # Verify save markdown
        causal_tracer.save_mermaid_markdown()
        md_file = os.path.join(self.test_dir, "causal_graph.md")
        self.assertTrue(os.path.exists(md_file))
        with open(md_file, 'r') as f:
            md_text = f.read()
        self.assertIn("# Causal Swarm Timeline Flowchart", md_text)
        self.assertIn("```mermaid", md_text)


if __name__ == "__main__":
    unittest.main()
