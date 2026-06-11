import os
import sys
import unittest
import unittest.mock
import json
import shutil
import tempfile

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import proximity_monitor


class TestProximityWeighting(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Override STATE_DIR and other directories in proximity_monitor
        self.orig_state_dir_mon = proximity_monitor.STATE_DIR
        self.orig_agents_dir_mon = proximity_monitor.AGENTS_DIR
        self.orig_collisions_dir_mon = proximity_monitor.COLLISIONS_DIR
        self.orig_workspaces_dir_mon = proximity_monitor.WORKSPACES_DIR
        
        proximity_monitor.STATE_DIR = self.test_dir
        proximity_monitor.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        proximity_monitor.COLLISIONS_DIR = os.path.join(self.test_dir, "collisions")
        proximity_monitor.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        
        # Re-initialize folders
        os.makedirs(os.path.join(self.test_dir, "agents"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "collisions"), exist_ok=True)
        os.makedirs(os.path.join(self.test_dir, "workspaces"), exist_ok=True)

    def tearDown(self):
        # Restore state paths
        proximity_monitor.STATE_DIR = self.orig_state_dir_mon
        proximity_monitor.AGENTS_DIR = self.orig_agents_dir_mon
        proximity_monitor.COLLISIONS_DIR = self.orig_collisions_dir_mon
        proximity_monitor.WORKSPACES_DIR = self.orig_workspaces_dir_mon
        shutil.rmtree(self.test_dir)

    def test_fallback_classify_phase(self):
        # 1. Debugging fallback
        self.assertEqual(
            proximity_monitor.fallback_classify_phase("Initialize and compile", "Fixing auth crash error bug"),
            "Debugging"
        )
        # 2. Documentation fallback
        self.assertEqual(
            proximity_monitor.fallback_classify_phase("Update docs", "Write synthesis report in markdown"),
            "Documentation"
        )
        # 3. Planning fallback
        self.assertEqual(
            proximity_monitor.fallback_classify_phase("Architect plans", "Prepare swarm initialization roadmap"),
            "Planning"
        )
        # 4. Coding default fallback
        self.assertEqual(
            proximity_monitor.fallback_classify_phase("Build quicksort", "Implement functional feature logic"),
            "Coding"
        )

    @unittest.mock.patch("proximity_monitor.is_ollama_running")
    def test_classify_phase_caching_and_save(self, mock_ollama):
        mock_ollama.return_value = False
        
        # Agent state with no phase in current_step
        agent = {
            "id": "001",
            "goal": "Write code",
            "current_step": {
                "name": "Design DB schema",
                "description": "Prepare db initialization steps"
            }
        }
        
        # 1. Classify (should fall back to Planning)
        phase = proximity_monitor.classify_phase(agent)
        self.assertEqual(phase, "Planning")
        
        # 2. Verify cached inside dict
        self.assertEqual(agent["current_step"]["phase"], "Planning")
        
        # 3. Verify saved to disk in temp test_dir
        saved_file = os.path.join(self.test_dir, "agents", "agent_001.json")
        self.assertTrue(os.path.exists(saved_file))
        with open(saved_file, "r") as f:
            disk_agent = json.load(f)
        self.assertEqual(disk_agent["current_step"]["phase"], "Planning")

        # 4. If phase is already cached, it should not check/reclassify
        agent["current_step"]["phase"] = "Documentation"
        # We manually modify it. Running classify_phase should return cached value immediately
        phase_cached = proximity_monitor.classify_phase(agent)
        self.assertEqual(phase_cached, "Documentation")

    @unittest.mock.patch("proximity_monitor.is_ollama_running")
    @unittest.mock.patch("urllib.request.urlopen")
    def test_classify_phase_ollama(self, mock_urlopen, mock_ollama):
        mock_ollama.return_value = True
        
        # Mock API response
        mock_response = unittest.mock.MagicMock()
        mock_response.read.return_value = json.dumps({
            "response": json.dumps({"phase": "Coding"})
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response
        
        agent = {
            "id": "002",
            "goal": "Integrate JWT",
            "current_step": {
                "name": "Write code",
                "description": "Develop auth endpoints"
            }
        }
        
        phase = proximity_monitor.classify_phase(agent)
        self.assertEqual(phase, "Coding")
        self.assertEqual(agent["current_step"]["phase"], "Coding")

    def test_calculate_proximity_dynamic_weights(self):
        # Setup two agents in different phases: Planning and Coding
        agent1 = {
            "id": "001",
            "goal": "Test goal 1",
            "current_step": {
                "name": "Planning DB",
                "description": "init setup",
                "phase": "Planning"  # Pre-cached to bypass Ollama/fallback
            },
            "touched_files": ["db.py"],
            "tools_used": ["sql"]
        }
        agent2 = {
            "id": "002",
            "goal": "Test goal 2",
            "current_step": {
                "name": "Write db logic",
                "description": "implement coding logic",
                "phase": "Coding"   # Pre-cached
            },
            "touched_files": ["db.py", "auth.py"],
            "tools_used": ["sql", "python"]
        }
        
        # Distance calculation properties:
        # cosine_sim is computed over (goal + step description)
        # goal1: "Test goal 1 init setup"
        # goal2: "Test goal 2 implement coding logic"
        corpus = [
            "Test goal 1 init setup",
            "Test goal 2 implement coding logic"
        ]
        
        # Let's call calculate_proximity
        distance, cosine_sim, file_jaccard, tool_jaccard = proximity_monitor.calculate_proximity(agent1, agent2, corpus)
        
        # Expected components:
        d_goal = 1.0 - cosine_sim
        d_workspace = 1.0 - file_jaccard
        d_tools = 1.0 - tool_jaccard
        
        # Expected weights:
        # Planning: (0.8, 0.1, 0.1)
        # Coding: (0.4, 0.4, 0.2)
        # Averaged: w1 = 0.6, w2 = 0.25, w3 = 0.15
        expected_distance = 0.6 * d_goal + 0.25 * d_workspace + 0.15 * d_tools
        
        self.assertAlmostEqual(distance, expected_distance, places=5)


if __name__ == "__main__":
    unittest.main()
