import os
import sys
import tempfile
import unittest
import unittest.mock

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

    @unittest.mock.patch("agent_runner.call_gemini_api")
    def test_validate_step_llm(self, mock_gemini):
        mock_gemini.return_value = {"valid": False, "reason": "Failed assertion."}
        node = {"node_id": "test_node"}
        result = judge.validate_step(node, "gemini", "gemini-1.5-pro")
        self.assertFalse(result["valid"])
        self.assertEqual(result["reason"], "Failed assertion.")

    @unittest.mock.patch("agent_runner.call_gemini_api")
    def test_resolve_collision_llm(self, mock_gemini):
        mock_gemini.return_value = {"action": "merge", "reason": "Nodes are redundant."}
        collision = {"agent_a": {"id": "1"}, "agent_b": {"id": "2"}}
        result = judge.resolve_collision(collision, "gemini", "gemini-1.5-pro")
        self.assertEqual(result["action"], "merge")
        self.assertEqual(result["reason"], "Nodes are redundant.")

    @unittest.mock.patch("agent_runner.call_gemini_api")
    def test_rank_branches_llm(self, mock_gemini):
        mock_gemini.return_value = {"ranked_agent_ids": ["b", "a"]}
        leaves = [
            {"id": "a", "active_node_id": "n1"},
            {"id": "b", "active_node_id": "n2"}
        ]
        ranked = judge.rank_branches(leaves, "gemini", "gemini-1.5-pro")
        self.assertEqual(len(ranked), 2)
        self.assertEqual(ranked[0]["id"], "b")
        self.assertEqual(ranked[1]["id"], "a")

if __name__ == "__main__":
    unittest.main()
