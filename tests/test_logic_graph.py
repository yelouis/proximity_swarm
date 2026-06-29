import os
import sys
import time
import json
import shutil
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor

# Make sure we can import from parent directory
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logic_graph
from agent_runner import load_json

class TestLogicGraph(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        # Re-initialize logic_graph paths based on new cwd
        logic_graph.GRAPH_DIR = os.path.join(os.getcwd(), ".proximity_swarm", "graph")
        logic_graph.SNAPSHOT_FILE = os.path.join(logic_graph.GRAPH_DIR, "snapshot.json")
        logic_graph.init_graph()
        logic_graph.set_monitor(True)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)
        logic_graph.set_monitor(False)

    def test_round_trip_and_api(self):
        # add_node
        node1 = {"node_id": "n1", "claim": "Premise A", "kind": "premise", "status": "validated"}
        self.assertTrue(logic_graph.add_node(node1))
        
        # get_node
        fetched = logic_graph.get_node("n1")
        self.assertEqual(fetched["claim"], "Premise A")
        
        # update_node
        self.assertTrue(logic_graph.update_node("n1", claim="Premise A updated"))
        fetched2 = logic_graph.get_node("n1")
        self.assertEqual(fetched2["claim"], "Premise A updated")
        
        # nodes_by_status
        self.assertEqual(len(logic_graph.nodes_by_status("validated")), 1)
        self.assertEqual(len(logic_graph.nodes_by_status("proposed")), 0)
        
        # to_mermaid smoke
        mermaid = logic_graph.to_mermaid()
        self.assertIn("graph TD", mermaid)
        self.assertIn("n1[n1: Premise A updated]", mermaid)

    def test_frontier_and_path(self):
        logic_graph.add_node({"node_id": "n1", "kind": "premise", "status": "validated"})
        logic_graph.add_node({"node_id": "n2", "kind": "lemma", "status": "validated", "depends_on": ["n1"], "oracle": {"type": "shell"}})
        logic_graph.add_node({"node_id": "g1", "kind": "goal", "status": "proposed", "depends_on": ["n2"]})
        
        # Frontier should be the unmet deps of the goal (n2 is validated, so it's not unmet)
        # Wait, the frontier logic says: "unmet deps of the goal". n2 is validated, so it IS met.
        # So the goal's deps are met. But goal itself is proposed.
        # Actually our frontier() implementation returns goal's unvalidated deps.
        # Since n2 is validated, frontier will be empty. Let's add an unvalidated dep.
        logic_graph.add_node({"node_id": "n3", "kind": "lemma", "status": "proposed", "depends_on": ["n1"]})
        logic_graph.update_node("g1", depends_on=["n2", "n3"])
        
        f = logic_graph.frontier()
        self.assertEqual(len(f), 1)
        self.assertEqual(f[0]["node_id"], "n3")

        # Test validated path
        path = logic_graph.validated_path_to_goal()
        self.assertIsNone(path) # goal depends on n3 which is proposed
        
        logic_graph.update_node("n3", status="validated", oracle={"type": "shell"})
        logic_graph.update_node("g1", status="validated")
        path2 = logic_graph.validated_path_to_goal()
        self.assertIsNotNone(path2)
        self.assertIn("n1", path2)
        self.assertIn("n2", path2)
        self.assertIn("g1", path2)

    def test_atomic_write_no_torn_reads(self):
        # A writer rewrites a node 1000x while a reader reads it
        logic_graph.add_node({"node_id": "n_atomic", "data": "initial"})
        
        stop_flag = False
        reader_errors = []
        
        def writer_thread():
            for i in range(1000):
                logic_graph.update_node("n_atomic", data="x" * i)
                
        def reader_thread():
            while not stop_flag:
                try:
                    data = logic_graph.get_node("n_atomic")
                    if data is None:
                        reader_errors.append("Got None")
                    elif not isinstance(data, dict):
                        reader_errors.append("Not a dict")
                except Exception as e:
                    reader_errors.append(str(e))

        r = threading.Thread(target=reader_thread)
        r.start()
        
        writer_thread()
        stop_flag = True
        r.join()
        
        self.assertEqual(len(reader_errors), 0)

    def test_concurrent_node_creation(self):
        def create_node(i):
            logic_graph.add_node({"node_id": f"n_{i}", "val": i})
            
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(create_node, range(100))
            
        nodes = logic_graph._get_all_nodes()
        self.assertEqual(len(nodes), 100)

    def test_concurrent_node_updates(self):
        # K writers update different nodes concurrently
        for i in range(100):
            logic_graph.add_node({"node_id": f"n_{i}", "val": 0})
            
        def update_node_val(i):
            logic_graph.update_node(f"n_{i}", val=1)
            
        with ThreadPoolExecutor(max_workers=10) as executor:
            executor.map(update_node_val, range(100))
            
        nodes = logic_graph._get_all_nodes()
        for i in range(100):
            self.assertEqual(nodes[f"n_{i}"]["val"], 1)

    def test_monitor_only_guard(self):
        logic_graph.set_monitor(False)
        # Structural ops should fail
        self.assertFalse(logic_graph.merge_nodes("x", ["y"]))
        self.assertFalse(logic_graph.prune_branch("A"))
        
        logic_graph.set_monitor(True)
        # Should proceed (returns True or False based on logic)
        # Adding dummy nodes
        logic_graph.add_node({"node_id": "s1", "depends_on": []})
        logic_graph.add_node({"node_id": "l1", "depends_on": []})
        logic_graph.add_node({"node_id": "dep1", "depends_on": ["l1"]})
        
        self.assertTrue(logic_graph.merge_nodes("s1", ["l1"]))
        dep1 = logic_graph.get_node("dep1")
        self.assertIn("s1", dep1["depends_on"])
        self.assertNotIn("l1", dep1["depends_on"])
        
        l1 = logic_graph.get_node("l1")
        self.assertEqual(l1["status"], "refuted")

    def test_validate_graph_violations(self):
        logic_graph.add_node({"node_id": "p1", "kind": "premise", "status": "validated"})
        logic_graph.add_node({"node_id": "g1", "kind": "goal", "status": "proposed"})
        
        # Base healthy
        self.assertEqual(len(logic_graph.validate_graph()), 0)
        
        # Two goal nodes
        logic_graph.add_node({"node_id": "g2", "kind": "goal"})
        v = logic_graph.validate_graph()
        self.assertTrue(any("Expected 1 goal node" in x for x in v))
        os.remove(logic_graph._node_path("g2"))
        
        # Cycle
        logic_graph.add_node({"node_id": "c1", "depends_on": ["c2"]})
        logic_graph.add_node({"node_id": "c2", "depends_on": ["c1"]})
        v = logic_graph.validate_graph()
        self.assertTrue(any("Cycle detected" in x for x in v))
        os.remove(logic_graph._node_path("c1"))
        os.remove(logic_graph._node_path("c2"))
        
        # Dangling dep
        logic_graph.update_node("g1", depends_on=["missing"])
        v = logic_graph.validate_graph()
        self.assertTrue(any("dangling dependency missing" in x for x in v))
        
        # Validated depends on refuted
        logic_graph.add_node({"node_id": "r1", "status": "refuted"})
        logic_graph.add_node({"node_id": "v1", "status": "validated", "depends_on": ["r1"]})
        v = logic_graph.validate_graph()
        self.assertTrue(any("depends on refuted node r1" in x for x in v))

    def test_repair_graph(self):
        logic_graph.add_node({"node_id": "p1", "kind": "premise", "status": "validated"})
        logic_graph.add_node({"node_id": "g1", "kind": "goal", "status": "proposed", "depends_on": ["missing"]})
        
        # Repair should drop missing dep
        logic_graph.repair_graph()
        g1 = logic_graph.get_node("g1")
        self.assertEqual(len(g1["depends_on"]), 0)

if __name__ == "__main__":
    unittest.main()
