import os
import sys
import json
import tempfile
import shutil
import unittest
import unittest.mock

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import terminal_dashboard
from terminal_dashboard import (
    build_agent_tree,
    get_agent_workspace_content,
    synthesize_node,
    generate_combined_synthesis,
    compute_swarm_state_hash,
    synthesis_cache,
    bg_generate_synthesis
)


class TestArtifactCombination(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Save old values
        self.old_state_dir = terminal_dashboard.STATE_DIR
        
        # Overwrite values for testing
        terminal_dashboard.STATE_DIR = self.test_dir
        
        os.makedirs(os.path.join(self.test_dir, "agents"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "workspaces"), exist_ok=True)
        
        # Reset cache
        synthesis_cache.update({"last_hash": None, "content": None, "is_generating": False})

    def tearDown(self):
        shutil.rmtree(self.test_dir)
        terminal_dashboard.STATE_DIR = self.old_state_dir

    def test_build_agent_tree(self):
        # Create mock agent JSON state files
        agent_001 = {"id": "001", "parent_id": None, "goal": "Write core library", "personality": "Architect"}
        agent_002 = {"id": "002", "parent_id": "001", "goal": "Write unit tests", "personality": "QA"}
        agent_003 = {"id": "003", "parent_id": "001", "goal": "Write docs", "personality": "Technical Writer"}
        
        agents_dir = os.path.join(self.test_dir, "agents")
        for agent in [agent_001, agent_002, agent_003]:
            with open(os.path.join(agents_dir, f"agent_{agent['id']}.json"), 'w') as f:
                json.dump(agent, f)
                
        tree = build_agent_tree()
        
        # Verify structure
        self.assertIn("001", tree)
        self.assertIn("002", tree)
        self.assertIn("003", tree)
        
        self.assertIsNone(tree["001"]["parent_id"])
        self.assertEqual(tree["002"]["parent_id"], "001")
        self.assertEqual(tree["003"]["parent_id"], "001")
        
        # Sorted children checking
        self.assertEqual(sorted(tree["001"]["children"]), ["002", "003"])
        self.assertEqual(tree["002"]["children"], [])
        self.assertEqual(tree["003"]["children"], [])

    def test_get_agent_workspace_content(self):
        agent_id = "004"
        ws_dir = os.path.join(self.test_dir, "workspaces", f"agent_{agent_id}")
        os.makedirs(os.path.join(ws_dir, "src"), exist_ok=True)
        
        # Create test files
        with open(os.path.join(ws_dir, "answer.md"), 'w') as f:
            f.write("Unified Answer Report")
        with open(os.path.join(ws_dir, "src", "helper.py"), 'w') as f:
            f.write("def helper():\n    pass")
            
        # 1. Test get raw single file (should fail/return merged if len > 1)
        content_all = get_agent_workspace_content(agent_id, raw_if_single=True)
        self.assertIn("### File: `answer.md`", content_all)
        self.assertIn("### File: `src/helper.py`", content_all)
        self.assertIn("Unified Answer Report", content_all)
        self.assertIn("def helper():", content_all)
        self.assertIn("```python", content_all)
        
        # 2. Test get single file raw content
        shutil.rmtree(ws_dir)
        os.makedirs(ws_dir, exist_ok=True)
        with open(os.path.join(ws_dir, "answer.md"), 'w') as f:
            f.write("Unified Answer Report Only")
            
        content_single = get_agent_workspace_content(agent_id, raw_if_single=True)
        self.assertEqual(content_single.strip(), "Unified Answer Report Only")

    @unittest.mock.patch('terminal_dashboard.is_ollama_running')
    def test_generate_combined_synthesis_fallback(self, mock_is_running):
        mock_is_running.return_value = False
        
        # Create hierarchy
        agent_001 = {"id": "001", "parent_id": None, "goal": "Write core library", "personality": "Architect"}
        agent_002 = {"id": "002", "parent_id": "001", "goal": "Write unit tests", "personality": "QA"}
        agent_003 = {"id": "003", "parent_id": "001", "goal": "Write docs", "personality": "Technical Writer"}
        
        agents_dir = os.path.join(self.test_dir, "agents")
        for agent in [agent_001, agent_002, agent_003]:
            with open(os.path.join(agents_dir, f"agent_{agent['id']}.json"), 'w') as f:
                json.dump(agent, f)
                
        # Create workspaces
        for aid, text in [("001", "Core API logic"), ("002", "Unit test implementation"), ("003", "API docs markdown")]:
            ws_dir = os.path.join(self.test_dir, "workspaces", f"agent_{aid}")
            os.makedirs(ws_dir, exist_ok=True)
            with open(os.path.join(ws_dir, "answer.md"), 'w') as f:
                f.write(text)
                
        # Generate combined synthesis
        synthesis = generate_combined_synthesis()
        # Initial run triggers generating state
        self.assertIn("Generating LLM hierarchical synthesis", synthesis)
        
        # Call bg worker directly to populate cache (fallback since Ollama is forced to False)
        h = compute_swarm_state_hash()
        bg_generate_synthesis(h)
        
        # Now call generate_combined_synthesis again, it should return cached synthesis fallback content
        result = generate_combined_synthesis()
        self.assertIn("## Agent 001 (Architect): Write core library", result)
        self.assertIn("Core API logic", result)
        self.assertIn("#### Agent 002 (QA): Write unit tests", result)

    @unittest.mock.patch('terminal_dashboard.is_ollama_running')
    @unittest.mock.patch('terminal_dashboard.call_ollama_raw')
    def test_generate_combined_synthesis_llm(self, mock_call, mock_is_running):
        mock_is_running.return_value = True
        mock_call.return_value = "Mocked LLM Synthesis Content"
        
        # Create hierarchy
        agent_001 = {"id": "001", "parent_id": None, "goal": "Write core library", "personality": "Architect"}
        agents_dir = os.path.join(self.test_dir, "agents")
        with open(os.path.join(agents_dir, "agent_001.json"), 'w') as f:
            json.dump(agent_001, f)
                
        ws_dir = os.path.join(self.test_dir, "workspaces", "agent_001")
        os.makedirs(ws_dir, exist_ok=True)
        with open(os.path.join(ws_dir, "answer.md"), 'w') as f:
            f.write("Some code")
            
        h = compute_swarm_state_hash()
        bg_generate_synthesis(h)
        
        result = generate_combined_synthesis()
        self.assertEqual(result, "Mocked LLM Synthesis Content")

    def test_compute_swarm_state_hash(self):
        h1 = compute_swarm_state_hash()
        
        # Create an agent state
        agent_001 = {"id": "001", "parent_id": None, "goal": "Goal"}
        agents_dir = os.path.join(self.test_dir, "agents")
        with open(os.path.join(agents_dir, "agent_001.json"), 'w') as f:
            json.dump(agent_001, f)
            
        h2 = compute_swarm_state_hash()
        self.assertNotEqual(h1, h2)
        
        # Create a workspace file
        ws_dir = os.path.join(self.test_dir, "workspaces", "agent_001")
        os.makedirs(ws_dir, exist_ok=True)
        with open(os.path.join(ws_dir, "answer.md"), 'w') as f:
            f.write("Some files")
            
        h3 = compute_swarm_state_hash()
        self.assertNotEqual(h2, h3)


if __name__ == "__main__":
    unittest.main()
