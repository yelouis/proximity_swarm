import os
import sys
import unittest

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from proximity_monitor import (
    tokenize,
    calculate_tfidf_cosine_similarity,
    calculate_jaccard_similarity,
    calculate_proximity
)


class TestProximityMath(unittest.TestCase):
    def test_tokenize(self):
        text = "Hello, World! This is a test."
        tokens = tokenize(text)
        # Filters out words <= 2 chars (is, a) and lowers hello, world, this, test
        self.assertIn("hello", tokens)
        self.assertIn("world", tokens)
        self.assertNotIn("is", tokens)
        self.assertNotIn("a", tokens)

    def test_jaccard_similarity(self):
        s1 = ["file1.txt", "file2.txt"]
        s2 = ["file2.txt", "file3.txt"]
        # Intersection = {"file2.txt"} (size 1)
        # Union = {"file1.txt", "file2.txt", "file3.txt"} (size 3)
        # Jaccard = 1/3 = 0.333...
        sim = calculate_jaccard_similarity(s1, s2)
        self.assertAlmostEqual(sim, 1.0 / 3.0)

        # Empty sets
        self.assertEqual(calculate_jaccard_similarity([], []), 0.0)

        # Identical sets
        self.assertEqual(calculate_jaccard_similarity(s1, s1), 1.0)

    def test_tfidf_cosine_similarity(self):
        doc1 = "Implement JWT signature token verification in authentication library"
        doc2 = "Write JWT token validation routines in auth.py module"
        doc3 = "Setup PostgreSQL database migration and tables"
        
        corpus = [doc1, doc2, doc3]
        
        # doc1 and doc2 should have positive similarity due to overlap ("jwt", "token", "verification/validation", etc)
        sim12 = calculate_tfidf_cosine_similarity(doc1, doc2, corpus)
        self.assertGreater(sim12, 0.15)
        
        # doc1 and doc3 should have extremely low or zero similarity
        sim13 = calculate_tfidf_cosine_similarity(doc1, doc3, corpus)
        self.assertLess(sim13, 0.1)

    def test_proximity_metric(self):
        agent1 = {
            "goal": "Implement JWT signature token verification in auth",
            "current_step": {"description": "Write jwt sign code"},
            "touched_files": ["src/auth.py", "src/helper.py"],
            "tools_used": ["edit_file"]
        }
        
        agent2 = {
            "goal": "Write JWT token validation routines in auth module",
            "current_step": {"description": "Write jwt verify code"},
            "touched_files": ["src/auth.py", "src/helper.py"],
            "tools_used": ["edit_file"]
        }
        
        corpus = [
            agent1["goal"] + " " + agent1["current_step"]["description"],
            agent2["goal"] + " " + agent2["current_step"]["description"]
        ]
        
        distance, cosine_sim, file_jaccard, tool_jaccard = calculate_proximity(agent1, agent2, corpus)
        
        # Since touched files are identical (Jaccard = 1.0) and tools are identical (Jaccard = 1.0) and goals are similar,
        # Distance should be small (below 0.5)
        self.assertLess(distance, 0.5)
        self.assertEqual(file_jaccard, 1.0)
        self.assertEqual(tool_jaccard, 1.0)

    def test_proximity_with_active_node_id(self):
        import logic_graph
        import tempfile
        import shutil
        
        test_dir = tempfile.mkdtemp()
        old_cwd = os.getcwd()
        os.chdir(test_dir)
        try:
            logic_graph.GRAPH_DIR = os.path.join(test_dir, ".proximity_swarm", "graph")
            logic_graph.init_graph()
            logic_graph.add_node({
                "node_id": "n1",
                "claim": "Extract database connection string"
            })
            
            agent1 = {
                "goal": "Database logic",
                "active_node_id": "n1"
            }
            agent2 = {
                "goal": "Different logic",
                "active_node_id": "n1"
            }
            
            # Since they share the same active node, the claim "Extract database connection string" will be in both goals
            corpus = [
                "Database logic Extract database connection string",
                "Different logic Extract database connection string"
            ]
            
            distance, cosine_sim, _, _ = calculate_proximity(agent1, agent2, corpus)
            # They share the claim so cosine sim should be non-zero
            self.assertGreater(cosine_sim, 0.1)
        finally:
            os.chdir(old_cwd)
            shutil.rmtree(test_dir)


if __name__ == "__main__":
    unittest.main()
