import os
import sys
import unittest
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
import oracle
from agent_runner import AgentRunner, save_json
import logic_graph

class TestOracles(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        
        logic_graph.GRAPH_DIR = os.path.join(self.test_dir, ".proximity_swarm", "graph")
        logic_graph.init_graph()

    def tearDown(self):
        os.chdir(self.old_cwd)

    def test_oracle_numeric_pass(self):
        node = {
            "node_id": "n1",
            "oracle": {
                "type": "numeric",
                "spec": "assert 1 + 1 == 2"
            }
        }
        passed, msg = oracle.evaluate_oracle(node, self.test_dir)
        self.assertTrue(passed)

    def test_oracle_numeric_fail(self):
        node = {
            "node_id": "n2",
            "oracle": {
                "type": "numeric",
                "spec": "assert 1 + 1 == 3"
            }
        }
        passed, msg = oracle.evaluate_oracle(node, self.test_dir)
        self.assertFalse(passed)

    def test_oracle_shell_pass(self):
        node = {
            "node_id": "n3",
            "oracle": {
                "type": "shell",
                "spec": "echo hello"
            }
        }
        passed, msg = oracle.evaluate_oracle(node, self.test_dir)
        self.assertTrue(passed)

    def test_oracle_none_excluded(self):
        node = {
            "node_id": "n4",
            "oracle": {
                "type": "none"
            }
        }
        passed, msg = oracle.evaluate_oracle(node, self.test_dir)
        self.assertFalse(passed)
        
    def test_agent_runner_validator_with_none(self):
        logic_graph.add_node({
            "node_id": "none_node",
            "status": "proposed",
            "oracle": {"type": "none"}
        })
        
        validator = AgentRunner(
            agent_id="401",
            task_id="task_jwt_auth",
            llm_provider="rules",
            graph_mode="graph"
        )
        validator.state["role_mode"] = "validator"
        validator.state["status"] = "exploring"
        validator.state["active_node_id"] = "none_node"
        save_json(validator.state_file, validator.state)
        
        validator.execute_step()
        
        n = logic_graph.get_node("none_node")
        self.assertEqual(n["status"], "refuted")

if __name__ == "__main__":
    unittest.main()
