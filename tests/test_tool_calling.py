import os
import sys
import json
import tempfile
import shutil
import unittest
import unittest.mock

# Ensure parent directory is in path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import web_search
import agent_runner
from agent_runner import AgentRunner, call_ollama_chat_with_tools


class TestWebSearch(unittest.TestCase):
    def test_clean_html(self):
        text = "<b>Python</b> is &quot;great&quot; &amp; easy&#x27;s."
        cleaned = web_search.clean_html(text)
        self.assertEqual(cleaned, "Python is \"great\" & easy's.")

    def test_search_web_mock_mode(self):
        # Force mock mode
        results = web_search.search_web("test query", force_mock=True)
        self.assertEqual(len(results), 2)
        self.assertIn("Mock Search Result 1", results[0]["title"])
        self.assertEqual(results[0]["url"], "https://example.com/result1")

    @unittest.mock.patch("urllib.request.urlopen")
    def test_search_web_parsing(self, mock_urlopen):
        # Sample DuckDuckGo Lite search result page snippet
        sample_html = """
        <table>
          <tr>
            <td>1.&nbsp;</td>
            <td><a rel="nofollow" href="https://python.org" class='result-link'>Welcome to Python.org</a></td>
          </tr>
          <tr>
            <td>&nbsp;</td>
            <td class='result-snippet'><b>Python</b> is programming language.</td>
          </tr>
          <tr>
            <td>2.&nbsp;</td>
            <td><a rel="nofollow" href="https://w3schools.com" class='result-link'>Python Tutorial</a></td>
          </tr>
          <tr>
            <td>&nbsp;</td>
            <td class='result-snippet'>Learn Python basics.</td>
          </tr>
        </table>
        """
        
        mock_response = unittest.mock.MagicMock()
        mock_response.read.return_value = sample_html.encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        # Execute search without mock mode
        results = web_search.search_web("python programming", max_results=2, force_mock=False)
        
        self.assertEqual(len(results), 2)
        self.assertEqual(results[0]["title"], "Welcome to Python.org")
        self.assertEqual(results[0]["url"], "https://python.org")
        self.assertEqual(results[0]["snippet"], "Python is programming language.")
        
        self.assertEqual(results[1]["title"], "Python Tutorial")
        self.assertEqual(results[1]["url"], "https://w3schools.com")
        self.assertEqual(results[1]["snippet"], "Learn Python basics.")

    @unittest.mock.patch("urllib.request.urlopen")
    def test_search_web_exception(self, mock_urlopen):
        # Simulate network error
        mock_urlopen.side_effect = Exception("Connection timed out")
        
        results = web_search.search_web("crash test", force_mock=False)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Search Error")
        self.assertIn("Connection timed out", results[0]["snippet"])


class TestOllamaToolCalling(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        
        # Save original paths
        self.old_state_dir = agent_runner.STATE_DIR
        self.old_agents_dir = agent_runner.AGENTS_DIR
        self.old_workspaces_dir = agent_runner.WORKSPACES_DIR
        self.old_mock_tasks = agent_runner.MOCK_TASKS_FILE
        self.old_tombstones = agent_runner.TOMBSTONES_FILE
        
        # Override paths
        agent_runner.STATE_DIR = self.test_dir
        agent_runner.AGENTS_DIR = os.path.join(self.test_dir, "agents")
        agent_runner.WORKSPACES_DIR = os.path.join(self.test_dir, "workspaces")
        agent_runner.MOCK_TASKS_FILE = os.path.join(self.test_dir, "mock_tasks.json")
        agent_runner.TOMBSTONES_FILE = os.path.join(self.test_dir, "tombstones.json")
        
        os.makedirs(agent_runner.AGENTS_DIR, exist_ok=True)
        os.makedirs(agent_runner.WORKSPACES_DIR, exist_ok=True)
        
        # Write empty tombstones list
        with open(agent_runner.TOMBSTONES_FILE, 'w') as f:
            json.dump([], f)

    def tearDown(self):
        # Restore paths
        agent_runner.STATE_DIR = self.old_state_dir
        agent_runner.AGENTS_DIR = self.old_agents_dir
        agent_runner.WORKSPACES_DIR = self.old_workspaces_dir
        agent_runner.MOCK_TASKS_FILE = self.old_mock_tasks
        agent_runner.TOMBSTONES_FILE = self.old_tombstones
        shutil.rmtree(self.test_dir)

    @unittest.mock.patch("urllib.request.urlopen")
    def test_call_ollama_chat_no_tools(self, mock_urlopen):
        # Mock simple direct response
        mock_response = unittest.mock.MagicMock()
        mock_response.read.return_value = json.dumps({
            "message": {
                "role": "assistant",
                "content": "Paris is the capital of France."
            }
        }).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_response

        messages = [{"role": "user", "content": "What is the capital of France?"}]
        res = call_ollama_chat_with_tools(messages, model="gemma4:latest")
        self.assertEqual(res, "Paris is the capital of France.")

    @unittest.mock.patch("urllib.request.urlopen")
    @unittest.mock.patch("web_search.search_web")
    def test_call_ollama_chat_with_search_tool_call(self, mock_search, mock_urlopen):
        # Set mock search return value
        mock_search.return_value = [{"title": "Go 1.22 Notes", "url": "", "snippet": "Released with loop var improvements."}]
        
        # We want to mock two sequential responses from Ollama /api/chat:
        # 1. First response: requesting a tool call 'search_web'
        # 2. Second response: final text answer using tool output
        response_1 = json.dumps({
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "search_web",
                            "arguments": {"query": "Go 1.22 release notes"}
                        }
                    }
                ]
            }
        }).encode("utf-8")
        
        response_2 = json.dumps({
            "message": {
                "role": "assistant",
                "content": "Go 1.22 was released with loop variable improvements."
            }
        }).encode("utf-8")

        mock_resp_1 = unittest.mock.MagicMock()
        mock_resp_1.read.return_value = response_1
        
        mock_resp_2 = unittest.mock.MagicMock()
        mock_resp_2.read.return_value = response_2
        
        # urlopen returns response_1 then response_2
        mock_urlopen.return_value.__enter__.side_effect = [mock_resp_1, mock_resp_2]

        messages = [{"role": "user", "content": "Search for Go 1.22 release notes"}]
        res = call_ollama_chat_with_tools(messages, tools=[agent_runner.SEARCH_WEB_TOOL], model="gemma4:latest")
        
        self.assertEqual(res, "Go 1.22 was released with loop variable improvements.")
        mock_search.assert_called_once_with("Go 1.22 release notes")

    @unittest.mock.patch("agent_runner.is_ollama_running")
    @unittest.mock.patch("agent_runner.call_ollama_chat_with_tools")
    @unittest.mock.patch("agent_runner.call_ollama_raw")
    def test_agent_runner_execute_step_fallback(self, mock_raw, mock_chat_tools, mock_ollama):
        mock_ollama.return_value = True
        
        # Configure tool call to raise exception (e.g. model doesn't support chat tools endpoint or fails)
        mock_chat_tools.side_effect = Exception("API 404: Not Found")
        
        # Configure raw call to succeed
        mock_raw.return_value = "Fallback raw content generation succeeded."

        # Create dummy agent state
        agent_id = "007"
        agent_state = {
            "id": agent_id,
            "task_id": "task_007",
            "goal": "Write draft",
            "status": "exploring",
            "progress": 0,
            "steps_completed": 0,
            "touched_files": [],
            "tools_used": [],
            "current_step": {
                "step_id": 1,
                "name": "Write answer",
                "description": "Output response into file"
            }
        }
        
        # Write agent state to temp directory
        state_file = os.path.join(agent_runner.AGENTS_DIR, f"agent_{agent_id}.json")
        with open(state_file, 'w') as f:
            json.dump(agent_state, f)
            
        # Write dummy tasks config file
        dummy_tasks = {
            "tasks": {
                "task_007": {
                    "id": "task_007",
                    "goal": "Write draft",
                    "steps": [
                        {
                            "step_id": 1,
                            "name": "Write answer",
                            "description": "Output response into file",
                            "touched_files": ["result.txt"],
                            "tools": []
                        }
                    ]
                }
            }
        }
        with open(agent_runner.MOCK_TASKS_FILE, 'w') as f:
            json.dump(dummy_tasks, f)

        # Initialize and run runner
        runner = AgentRunner(
            agent_id=agent_id,
            task_id="task_007",
            llm_provider="ollama",
            step_delay=0.01
        )
        
        runner.execute_step()
        
        # Verify fallback raw call was invoked
        mock_raw.assert_called_once()
        
        # Verify the generated file has the fallback content
        workspace_file = os.path.join(agent_runner.WORKSPACES_DIR, "agent_007", "result.txt")
        self.assertTrue(os.path.exists(workspace_file))
        with open(workspace_file, 'r') as f:
            content = f.read()
        self.assertEqual(content, "Fallback raw content generation succeeded.")

    @unittest.mock.patch("urllib.request.urlopen")
    def test_call_ollama_chat_with_spawn_tool_call(self, mock_urlopen):
        # We mock Ollama returning a tool call to 'spawn_agent'
        response_1 = json.dumps({
            "message": {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "function": {
                            "name": "spawn_agent",
                            "arguments": {
                                "goal": "Write subagent goal tests",
                                "initial_files": ["tests/test_sub.py"]
                            }
                        }
                    }
                ]
            }
        }).encode("utf-8")
        
        response_2 = json.dumps({
            "message": {
                "role": "assistant",
                "content": "I have successfully spawned the child agent to work on the tests."
            }
        }).encode("utf-8")

        mock_resp_1 = unittest.mock.MagicMock()
        mock_resp_1.read.return_value = response_1
        
        mock_resp_2 = unittest.mock.MagicMock()
        mock_resp_2.read.return_value = response_2
        
        mock_urlopen.return_value.__enter__.side_effect = [mock_resp_1, mock_resp_2]

        agent_id = "008"
        agent_state = {
            "id": agent_id,
            "task_id": "task_008",
            "goal": "Primary goal",
            "status": "exploring",
            "progress": 0,
            "steps_completed": 0,
            "touched_files": [],
            "tools_used": [],
            "current_step": {
                "step_id": 1,
                "name": "Write answer",
                "description": "Output response into file"
            }
        }
        state_file = os.path.join(agent_runner.AGENTS_DIR, f"agent_{agent_id}.json")
        with open(state_file, 'w') as f:
            json.dump(agent_state, f)

        runner = AgentRunner(
            agent_id=agent_id,
            goal="Primary goal",
            llm_provider="ollama",
            step_delay=0.01
        )
        
        local_registry = {
            "spawn_agent": lambda goal, initial_files: runner.request_spawn_agent(goal, initial_files)
        }

        messages = [{"role": "user", "content": "Spawn a test agent to help write tests"}]
        res = call_ollama_chat_with_tools(
            messages=messages, 
            tools=[agent_runner.SPAWN_AGENT_TOOL], 
            model="gemma4:latest",
            registry=local_registry
        )
        
        self.assertEqual(res, "I have successfully spawned the child agent to work on the tests.")
        
        # Verify that spawn_request block was written to state file on disk
        state_file = os.path.join(agent_runner.AGENTS_DIR, f"agent_{agent_id}.json")
        self.assertTrue(os.path.exists(state_file))
        with open(state_file, 'r') as f:
            saved_state = json.load(f)
            
        self.assertIn("spawn_request", saved_state)
        self.assertEqual(saved_state["spawn_request"]["goal"], "Write subagent goal tests")
        self.assertEqual(saved_state["spawn_request"]["initial_files"], ["tests/test_sub.py"])


if __name__ == "__main__":
    unittest.main()
