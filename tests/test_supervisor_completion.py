import os
import sys
import json
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import supervisor
import logic_graph

class TestSupervisorCompletion(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        
        # Reset paths
        supervisor.STATE_DIR = os.path.join(self.test_dir, ".proximity_swarm")
        supervisor.orchestrator_file = os.path.join(supervisor.STATE_DIR, "orchestrator.json")
        os.makedirs(supervisor.STATE_DIR, exist_ok=True)
        
        logic_graph.GRAPH_DIR = os.path.join(supervisor.STATE_DIR, "graph")
        logic_graph.SNAPSHOT_FILE = os.path.join(logic_graph.GRAPH_DIR, "snapshot.json")
        logic_graph.init_graph()
        logic_graph.set_monitor(True)
        
        # Seed orchestrator state
        with open(supervisor.orchestrator_file, 'w') as f:
            json.dump({
                "macro_goal": "Prove Collatz",
                "sub_swarms": {
                    "swarm_001": {
                        "id": "swarm_001",
                        "goal": "Prove Collatz",
                        "status": "active",
                        "agent_ids": ["001"]
                    }
                }
            }, f, indent=2)

    def tearDown(self):
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)
        logic_graph.set_monitor(False)

    def test_rules_provider_auto_promotes(self):
        # Rules provider should auto-promote immediately when deps are validated
        logic_graph.add_node({"node_id": "goal_0", "kind": "goal", "status": "proposed", "depends_on": ["lemma_1"]})
        logic_graph.add_node({"node_id": "lemma_1", "kind": "lemma", "status": "validated"})
        
        # Evaluate sub swarm completion with provider='rules'
        supervisor.evaluate_sub_swarm_completion(llm_provider="rules")
        
        goal = logic_graph.get_node("goal_0")
        self.assertEqual(goal["status"], "validated")

    @patch("judge.validate_step")
    def test_llm_provider_checks_frontier_and_minimum_structure(self, mock_validate_step):
        # 1. Goal with unvalidated dependency (frontier is not empty)
        logic_graph.add_node({"node_id": "goal_0", "kind": "goal", "status": "proposed", "depends_on": ["lemma_1", "lemma_2"]})
        logic_graph.add_node({"node_id": "lemma_1", "kind": "lemma", "status": "validated"})
        logic_graph.add_node({"node_id": "lemma_2", "kind": "lemma", "status": "proposed"})
        
        supervisor.evaluate_sub_swarm_completion(llm_provider="ollama", ollama_model="gemma4:latest")
        
        # Should not promote, nor call Judge, because lemma_2 is proposed (frontier not empty)
        mock_validate_step.assert_not_called()
        self.assertEqual(logic_graph.get_node("goal_0")["status"], "proposed")
        
        # 2. All deps validated, but only 1 validated lemma (lone first lemma)
        logic_graph.update_node("goal_0", depends_on=["lemma_1"])
        os.remove(logic_graph._node_path("lemma_2"))
        
        supervisor.evaluate_sub_swarm_completion(llm_provider="ollama", ollama_model="gemma4:latest")
        
        # Should not promote, nor call Judge, because only 1 validated lemma exists
        mock_validate_step.assert_not_called()
        self.assertEqual(logic_graph.get_node("goal_0")["status"], "proposed")
        
        # 3. All deps validated, >=2 validated lemmas, Judge rejects
        logic_graph.update_node("goal_0", depends_on=["lemma_1", "lemma_3"])
        logic_graph.add_node({"node_id": "lemma_3", "kind": "lemma", "status": "validated"})
        
        mock_validate_step.return_value = {"valid": False, "reason": "Proof incomplete."}
        
        supervisor.evaluate_sub_swarm_completion(llm_provider="ollama", ollama_model="gemma4:latest")
        
        mock_validate_step.assert_called_once()
        self.assertEqual(logic_graph.get_node("goal_0")["status"], "proposed")
        # Failed attempt should be stored in oracle.result to prevent re-querying
        goal = logic_graph.get_node("goal_0")
        self.assertFalse(goal["oracle"]["result"]["passed"])
        self.assertEqual(goal["oracle"]["result"]["evaluated_deps"], ["lemma_1", "lemma_3"])
        
        # Reset call count
        mock_validate_step.reset_mock()
        
        # 4. Running again with same deps should skip Judge re-query
        supervisor.evaluate_sub_swarm_completion(llm_provider="ollama", ollama_model="gemma4:latest")
        mock_validate_step.assert_not_called()
        
        # 5. All deps validated, >=2 validated lemmas, Judge approves
        mock_validate_step.return_value = {"valid": True, "reason": "Proof complete."}
        # Add new dep to clear last failed result cache
        logic_graph.update_node("goal_0", depends_on=["lemma_1", "lemma_3", "lemma_4"])
        logic_graph.add_node({"node_id": "lemma_4", "kind": "lemma", "status": "validated"})
        
        supervisor.evaluate_sub_swarm_completion(llm_provider="ollama", ollama_model="gemma4:latest")
        mock_validate_step.assert_called_once()
        self.assertEqual(logic_graph.get_node("goal_0")["status"], "validated")

if __name__ == "__main__":
    unittest.main()
