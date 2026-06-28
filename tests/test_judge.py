import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import judge

class TestJudge(unittest.TestCase):
    def test_select_judge_model(self):
        provider, model = judge.select_judge_model("rules", None, None, None)
        self.assertEqual(provider, "rules")

        provider, model = judge.select_judge_model(None, None, "gemini", "gemini-1.5-pro")
        self.assertEqual(provider, "gemini")
        self.assertEqual(model, "gemini-1.5-pro")

    def test_validate_step_rules(self):
        node = {"node_id": "test_node"}
        result = judge.validate_step(node, "rules", "rules")
        self.assertTrue(result["valid"])

    def test_resolve_collision_rules(self):
        collision = {"id": "col_1"}
        result = judge.resolve_collision(collision, "rules", "rules")
        self.assertEqual(result["action"], "keep_both")

    def test_rank_branches_rules(self):
        leaves = [
            {"id": "a", "last_updated": 10},
            {"id": "b", "last_updated": 20}
        ]
        ranked = judge.rank_branches(leaves, "rules", "rules")
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["id"], "b")
        self.assertEqual(ranked[1]["id"], "a")

if __name__ == "__main__":
    unittest.main()
