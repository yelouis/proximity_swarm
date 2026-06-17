import os
import sys
import unittest
import unittest.mock
import sqlite3
import json
import shutil

# Add parent directory to path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import memory_store
from agent_runner import AgentRunner


class TestMemoryStore(unittest.TestCase):
    def setUp(self):
        # Redirect DB_DIR to a temporary folder during tests
        self.old_db_dir = memory_store.DB_DIR
        self.old_db_path = memory_store.DB_PATH
        self.test_dir = os.path.join(os.path.dirname(__file__), "tmp_state_memory")
        os.makedirs(self.test_dir, exist_ok=True)
        memory_store.DB_DIR = self.test_dir
        db_path = os.path.join(self.test_dir, "test_memory.db")
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
        memory_store.DB_PATH = db_path
        memory_store.init_db()

    def tearDown(self):
        memory_store.DB_DIR = self.old_db_dir
        memory_store.DB_PATH = self.old_db_path
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    def test_init_db(self):
        # Verify db file is created
        self.assertTrue(os.path.exists(memory_store.DB_PATH))
        
        # Verify schema
        conn = sqlite3.connect(memory_store.DB_PATH)
        cursor = conn.cursor()
        cursor.execute("PRAGMA table_info(episodic_memories)")
        columns = [row[1] for row in cursor.fetchall()]
        conn.close()
        
        expected_cols = ["id", "goal", "role", "status", "steps", "errors", "deliverable_summary", "reflection", "embedding", "created_at"]
        for col in expected_cols:
            self.assertIn(col, columns)

    @unittest.mock.patch("memory_store.is_ollama_running")
    def test_save_and_query_tfidf(self, mock_is_running):
        # Disable Ollama to force TF-IDF fallback
        mock_is_running.return_value = False
        
        # Insert test episodes
        memory_store.save_episode(
            goal="Write simple binary search algorithm in python",
            role="Algorithm Expert",
            status="completed",
            steps=[{"step_id": 1, "name": "Write search", "description": "impl"}],
            errors="None",
            deliverable_summary="Binary search in python",
            reflection="Worked flawlessly."
        )
        memory_store.save_episode(
            goal="Compile native cryptography dependencies",
            role="DevOps",
            status="failed",
            steps=[{"step_id": 1, "name": "Compile", "description": "gcc fail"}],
            errors="gcc: command not found",
            deliverable_summary="None",
            reflection="Failed compilation."
        )
        
        # Query for a goal related to algorithm/binary search
        matches = memory_store.query_similar_episodes("Write algorithm search", top_k=1)
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0]["role"], "Algorithm Expert")
        self.assertTrue(matches[0]["score"] > 0.0)
        
        # Query for something related to compile/cryptography
        matches_failed = memory_store.query_similar_episodes("Compile crypt code", top_k=1)
        self.assertEqual(len(matches_failed), 1)
        self.assertEqual(matches_failed[0]["role"], "DevOps")

    @unittest.mock.patch("memory_store.is_ollama_running")
    @unittest.mock.patch("memory_store.get_embedding")
    def test_query_vector_embeddings(self, mock_get_embedding, mock_is_running):
        # Enable Ollama vector search
        mock_is_running.return_value = True
        
        # Mock embeddings
        # Query: [1.0, 0.0]
        # Match 1: [0.9, 0.1] (Similarity near 1.0)
        # Match 2: [0.1, 0.9] (Similarity near 0.1)
        mock_get_embedding.side_effect = lambda text, model=None: (
            [1.0, 0.0] if "query" in text else (
                [0.9, 0.1] if "match1" in text else [0.1, 0.9]
            )
        )
        
        memory_store.save_episode(
            goal="target match1",
            role="Specialist",
            status="completed",
            steps=[],
            errors="",
            deliverable_summary="m1",
            reflection="r1"
        )
        memory_store.save_episode(
            goal="target match2",
            role="Helper",
            status="completed",
            steps=[],
            errors="",
            deliverable_summary="m2",
            reflection="r2"
        )
        
        matches = memory_store.query_similar_episodes("query goal", top_k=2)
        self.assertEqual(len(matches), 2)
        # Match 1 should be first
        self.assertEqual(matches[0]["goal"], "target match1")
        # Score calculation check: 1.0*0.9 + 0.0*0.1 = 0.9 / (1.0 * sqrt(0.81+0.01=0.82)=0.9055) = 0.993
        self.assertTrue(matches[0]["score"] > 0.9)
        self.assertEqual(matches[1]["goal"], "target match2")
        self.assertTrue(matches[1]["score"] < 0.2)

    def test_clean_memories(self):
        memory_store.save_episode("goal", "role", "completed", [], "", "", "")
        
        # Verify not empty
        conn = memory_store.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM episodic_memories")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 1)
        conn.close()
        
        # Clean
        memory_store.clean_memories()
        
        # Verify empty
        conn = memory_store.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT count(*) FROM episodic_memories")
        count = cursor.fetchone()[0]
        self.assertEqual(count, 0)
        conn.close()


class TestAgentRunnerMemoryHooks(unittest.TestCase):
    def setUp(self):
        self.old_db_dir = memory_store.DB_DIR
        self.old_db_path = memory_store.DB_PATH
        self.test_dir = os.path.join(os.path.dirname(__file__), "tmp_state_memory_runner")
        os.makedirs(self.test_dir, exist_ok=True)
        memory_store.DB_DIR = self.test_dir
        db_path = os.path.join(self.test_dir, "test_memory.db")
        if os.path.exists(db_path):
            try:
                os.remove(db_path)
            except OSError:
                pass
        memory_store.DB_PATH = db_path
        memory_store.init_db()

    def tearDown(self):
        memory_store.DB_DIR = self.old_db_dir
        memory_store.DB_PATH = self.old_db_path
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir)

    @unittest.mock.patch("agent_runner.is_ollama_running")
    @unittest.mock.patch("agent_runner.load_json")
    @unittest.mock.patch("agent_runner.save_json")
    def test_load_historical_context_no_match(self, mock_save, mock_load, mock_is_running):
        # Setup mock tasks and state files
        def side_effect(path):
            if "agent_001.json" in path:
                return {
                    "id": "001",
                    "goal": "Write simple search",
                    "personality": "Generalist",
                    "status": "exploring",
                    "steps_completed": 0,
                    "touched_files": []
                }
            return {
                "tasks": {
                    "task_jwt_auth": {
                        "goal": "Write simple search",
                        "steps": [{"step_id": 1, "name": "step1", "description": "desc1", "tools": []}]
                    }
                }
            }
        mock_load.side_effect = side_effect
        mock_is_running.return_value = False
        
        runner = AgentRunner(
            agent_id="001",
            task_id="task_jwt_auth",
            ollama_model="gemma4:latest",
            personality="Generalist",
            goal="Write simple search"
        )
        
        # Should start with no historical context
        self.assertIsNone(runner.historical_context)

    @unittest.mock.patch("agent_runner.is_ollama_running")
    @unittest.mock.patch("agent_runner.load_json")
    @unittest.mock.patch("agent_runner.save_json")
    def test_load_historical_context_with_match(self, mock_save, mock_load, mock_is_running):
        def side_effect(path):
            if "agent_001.json" in path:
                return {
                    "id": "001",
                    "goal": "Write simple search",
                    "personality": "Generalist",
                    "status": "exploring",
                    "steps_completed": 0,
                    "touched_files": []
                }
            return {
                "tasks": {
                    "task_jwt_auth": {
                        "goal": "Write simple search",
                        "steps": [{"step_id": 1, "name": "step1", "description": "desc1", "tools": []}]
                    }
                }
            }
        mock_load.side_effect = side_effect
        mock_is_running.return_value = False
        
        # Pre-populate DB with a similar goal
        memory_store.save_episode(
            goal="Write simple search",
            role="Generalist",
            status="completed",
            steps=[],
            errors="",
            deliverable_summary="search.py",
            reflection="Reflection on search"
        )
        
        runner = AgentRunner(
            agent_id="001",
            task_id="task_jwt_auth",
            ollama_model="gemma4:latest",
            personality="Generalist",
            goal="Write simple search"
        )
        
        # Since goal matches exactly, similarity is 1.0 (>= 0.5)
        self.assertIsNotNone(runner.historical_context)
        self.assertIn("Reflection on search", runner.historical_context)
        self.assertIn("search.py", runner.historical_context)

    @unittest.mock.patch("agent_runner.is_ollama_running")
    @unittest.mock.patch("agent_runner.load_json")
    @unittest.mock.patch("agent_runner.save_json")
    def test_save_memory_episode_hook(self, mock_save, mock_load, mock_is_running):
        def side_effect(path):
            if "agent_001.json" in path:
                return {
                    "id": "001",
                    "task_id": "task_jwt_auth",
                    "goal": "Write JWT",
                    "personality": "Generalist",
                    "status": "completed",
                    "steps_completed": 2,
                    "touched_files": ["auth.py"]
                }
            return {
                "tasks": {
                    "task_jwt_auth": {
                        "goal": "Write JWT",
                        "steps": [{"step_id": 1, "name": "step1", "description": "desc1", "tools": []}]
                    }
                }
            }
        mock_load.side_effect = side_effect
        mock_is_running.return_value = False
        
        runner = AgentRunner(
            agent_id="001",
            task_id="task_jwt_auth",
            ollama_model="gemma4:latest",
            personality="Generalist",
            goal="Write JWT"
        )
        
        # Mock workspace files check
        runner.workspace_dir = self.test_dir
        runner.state = {
            "id": "001",
            "task_id": "task_jwt_auth",
            "goal": "Write JWT",
            "personality": "Generalist",
            "status": "completed",
            "steps_completed": 2,
            "touched_files": ["auth.py"]
        }
        
        # Write dummy touched file
        with open(os.path.join(self.test_dir, "auth.py"), 'w') as f:
            f.write("import jwt\n")
            
        runner.save_memory_episode()
        
        # Query SQLite to verify save occurred
        conn = memory_store.get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT goal, role, status, deliverable_summary FROM episodic_memories")
        row = cursor.fetchone()
        conn.close()
        
        self.assertIsNotNone(row)
        self.assertEqual(row["goal"], "Write JWT")
        self.assertEqual(row["status"], "completed")
        self.assertIn("auth.py", row["deliverable_summary"])


if __name__ == "__main__":
    unittest.main()
