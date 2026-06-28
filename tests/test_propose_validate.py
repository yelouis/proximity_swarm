import os
import sys
import shutil
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

import logic_graph
from agent_runner import AgentRunner, save_json, load_json

class TestProposeValidate(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.old_cwd = os.getcwd()
        os.chdir(self.test_dir)
        import agent_runner
        self.old_state_dir = agent_runner.STATE_DIR
        self.old_agents_dir = agent_runner.AGENTS_DIR
        self.old_workspaces_dir = agent_runner.WORKSPACES_DIR
        self.old_mock_tasks = agent_runner.MOCK_TASKS_FILE
        
        agent_runner.STATE_DIR = os.path.join(self.test_dir, ".proximity_swarm")
        agent_runner.AGENTS_DIR = os.path.join(agent_runner.STATE_DIR, "agents")
        agent_runner.WORKSPACES_DIR = os.path.join(agent_runner.STATE_DIR, "workspaces")
        agent_runner.MOCK_TASKS_FILE = os.path.join(agent_runner.STATE_DIR, "mock_tasks.json")
        os.makedirs(agent_runner.STATE_DIR, exist_ok=True)
        shutil.copy(self.old_mock_tasks, agent_runner.MOCK_TASKS_FILE)
        
        logic_graph.GRAPH_DIR = os.path.join(agent_runner.STATE_DIR, "graph")
        logic_graph.SNAPSHOT_FILE = os.path.join(logic_graph.GRAPH_DIR, "snapshot.json")
        logic_graph.init_graph()
        logic_graph.set_monitor(True)
        
        logic_graph.add_node({
            "node_id": "g1",
            "kind": "goal",
            "claim": "Root Goal",
            "status": "proposed",
            "depends_on": ["sg1"]
        })
        logic_graph.add_node({
            "node_id": "sg1",
            "kind": "goal",
            "claim": "Sub Goal",
            "status": "proposed",
            "depends_on": []
        })
        logic_graph.add_node({
            "node_id": "p1",
            "kind": "premise",
            "claim": "Context",
            "status": "validated",
            "depends_on": []
        })

    def tearDown(self):
        import agent_runner
        agent_runner.STATE_DIR = self.old_state_dir
        agent_runner.AGENTS_DIR = self.old_agents_dir
        agent_runner.WORKSPACES_DIR = self.old_workspaces_dir
        agent_runner.MOCK_TASKS_FILE = self.old_mock_tasks
        
        os.chdir(self.old_cwd)
        shutil.rmtree(self.test_dir)
        logic_graph.set_monitor(False)

    def test_propose_and_validate(self):
        # 1. Proposer agent
        proposer = AgentRunner(
            agent_id="301",
            task_id="task_jwt_auth",
            llm_provider="rules",
            graph_mode="graph"
        )
        proposer.state["role_mode"] = "proposer"
        proposer.state["status"] = "exploring"
        save_json(proposer.state_file, proposer.state)
        
        # Pick and propose from frontier
        proposer.execute_step()
        self.assertIsNone(proposer.state["active_node_id"])
        
        proposed_nodes = logic_graph.nodes_by_status("proposed")
        new_nodes = [n for n in proposed_nodes if n["node_id"] not in ["g1", "sg1"]]
        self.assertEqual(len(new_nodes), 1)
        new_node = new_nodes[0]
        self.assertEqual(new_node["depends_on"], ["sg1"])
        
        # 2. Validator agent (mocked to pass)
        validator = AgentRunner(
            agent_id="302",
            task_id="task_jwt_auth",
            llm_provider="rules",
            graph_mode="graph"
        )
        validator.state["role_mode"] = "validator"
        validator.state["status"] = "exploring"
        validator.state["active_node_id"] = new_node["node_id"]
        save_json(validator.state_file, validator.state)
        
        # Poll and validate
        validator.execute_step()
        self.assertIsNone(validator.state["active_node_id"])
        
        validated_node = logic_graph.get_node(new_node["node_id"])
        self.assertEqual(validated_node["status"], "validated")
        self.assertEqual(validator.state["progress"], 20)

    def test_propose_and_refute(self):
        # 1. Proposer agent
        proposer = AgentRunner(
            agent_id="201",
            task_id="task_jwt_auth",
            llm_provider="rules",
            graph_mode="graph"
        )
        proposer.state["role_mode"] = "proposer"
        proposer.state["status"] = "exploring"
        # We can add a hook in rules provider to fail validation based on a state flag
        proposer.state["force_fail"] = True
        save_json(proposer.state_file, proposer.state)
        
        proposer.execute_step() # pick and propose
        
        proposed_nodes = logic_graph.nodes_by_status("proposed")
        new_nodes = [n for n in proposed_nodes if n["node_id"] not in ["g1", "sg1"]]
        new_node = new_nodes[0]
        
        # 2. Validator agent
        validator = AgentRunner(
            agent_id="202",
            task_id="task_jwt_auth",
            llm_provider="rules",
            graph_mode="graph"
        )
        validator.state["role_mode"] = "validator"
        validator.state["status"] = "exploring"
        validator.state["active_node_id"] = new_node["node_id"]
        validator.state["force_fail"] = True # We'll read this in agent_runner.py to simulate failure
        save_json(validator.state_file, validator.state)
        
        validator.execute_step() # pick and validate (fail)
        
        refuted_node = logic_graph.get_node(new_node["node_id"])
        self.assertEqual(refuted_node["status"], "refuted")
        
        # Make sure validator's progress didn't advance
        self.assertEqual(validator.state.get("progress", 0), 0)

if __name__ == "__main__":
    unittest.main()
