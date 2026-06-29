#!/usr/bin/env python3
import os
import sys
import json
import time
import subprocess
import urllib.request
import urllib.error
import argparse

# Try to import web_search (for local search tool access)
try:
    import web_search
except ImportError:
    web_search = None


STATE_DIR = os.path.join(os.getcwd(), ".proximity_swarm")
AGENTS_DIR = os.path.join(STATE_DIR, "agents")
COLLISIONS_DIR = os.path.join(STATE_DIR, "collisions")
WORKSPACES_DIR = os.path.join(STATE_DIR, "workspaces")
TOMBSTONES_FILE = os.path.join(STATE_DIR, "tombstones.json")
MOCK_TASKS_FILE = os.path.join(os.getcwd(), "mock_tasks.json")

# Max self-healing iterations for a step's verification command (design_doc §13).
MAX_HEAL_ATTEMPTS = int(os.environ.get("PROXIMITY_MAX_HEAL_ATTEMPTS", "3"))


CURRENT_AGENT_STATE_FILE = None

def _accumulate_tokens(count):
    global CURRENT_AGENT_STATE_FILE
    if not CURRENT_AGENT_STATE_FILE or count <= 0:
        return
    try:
        import os
        if os.path.exists(CURRENT_AGENT_STATE_FILE):
            data = load_json(CURRENT_AGENT_STATE_FILE)
            if data:
                data["output_tokens"] = data.get("output_tokens", 0) + count
                save_json(CURRENT_AGENT_STATE_FILE, data)
    except Exception:
        pass


def load_json(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def save_json(filepath, data):
    if isinstance(data, dict):
        import time
        data["last_updated"] = time.time()
    try:
        import os
        tmp_path = filepath + ".tmp"
        with open(tmp_path, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp_path, filepath)
        return True
    except Exception:
        return False


def get_iso_timestamp():
    import datetime
    return datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")



def call_gemini_api(prompt):
    """Call the Gemini API using urllib to avoid external library dependencies."""
    api_key = os.environ.get("GEMINI_API_KEY")
    if not api_key:
        return None
        
    url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    body = {
        "contents": [{
            "parts": [{"text": prompt}]
        }],
        "generationConfig": {
            "responseMimeType": "application/json"
        }
    }
    
    try:
        req = urllib.request.Request(
            url, 
            data=json.dumps(body).encode("utf-8"), 
            headers=headers, 
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["candidates"][0]["content"]["parts"][0]["text"]
            
            # Extract output tokens from candidatesTokenCount
            usage = res_data.get("usageMetadata", {})
            tokens = usage.get("candidatesTokenCount", len(text) // 4)
            if tokens <= 0:
                tokens = 1
            _accumulate_tokens(tokens)
            
            return json.loads(text.strip())
    except Exception as e:
        print(f"[LLM ERROR] Gemini API call failed: {e}")
        return None


def call_ollama_api(prompt, model="gemma4:latest"):
    """Call local Ollama API using urllib to avoid library dependencies."""
    url = "http://localhost:11434/api/generate"
    headers = {"Content-Type": "application/json"}
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "format": "json"
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["response"]
            
            tokens = res_data.get("eval_count", len(text) // 4)
            if tokens <= 0:
                tokens = 1
            _accumulate_tokens(tokens)
            
            return json.loads(text.strip())
    except Exception as e:
        print(f"[LLM ERROR] Ollama API call failed (Model: {model}): {e}")
        return None


def call_ollama_raw(prompt, model="gemma4:latest"):
    """Call local Ollama API using urllib to generate raw text responses."""
    url = "http://localhost:11434/api/generate"
    headers = {"Content-Type": "application/json"}
    body = {
        "model": model,
        "prompt": prompt,
        "stream": False
    }
    try:
        req = urllib.request.Request(
            url,
            data=json.dumps(body).encode("utf-8"),
            headers=headers,
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data.get("response", "").strip()
            
            tokens = res_data.get("eval_count", len(text) // 4)
            if tokens <= 0:
                tokens = 1
            _accumulate_tokens(tokens)
            
            return text
    except Exception as e:
        print(f"[LLM ERROR] Raw Ollama call failed (Model: {model}): {e}")
        return None

# Ollama Search Tool schema representation
SEARCH_WEB_TOOL = {
    "type": "function",
    "function": {
        "name": "search_web",
        "description": "Searches the web for up-to-date information about a given query.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to run."
                }
            },
            "required": ["query"]
        }
    }
}

# Ollama Spawn Tool schema representation
SPAWN_AGENT_TOOL = {
    "type": "function",
    "function": {
        "name": "spawn_agent",
        "description": "Spawns a specialized sub-agent to work in parallel on a sub-task when handling a complex multi-stage goal.",
        "parameters": {
            "type": "object",
            "properties": {
                "goal": {
                    "type": "string",
                    "description": "A clear, narrow task goal for the sub-agent."
                },
                "initial_files": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of relative file paths the sub-agent should initially edit or create."
                }
            },
            "required": ["goal", "initial_files"]
        }
    }
}

# New Research Tools
RUN_PYTHON_TOOL = {
    "type": "function",
    "function": {
        "name": "run_python",
        "description": "Executes python code in a sandboxed environment and returns the output. Use this for math and simulations.",
        "parameters": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "The python code to execute."
                }
            },
            "required": ["code"]
        }
    }
}

READ_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Reads a file from the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file."
                }
            },
            "required": ["path"]
        }
    }
}

WRITE_FILE_TOOL = {
    "type": "function",
    "function": {
        "name": "write_file",
        "description": "Writes content to a file in the workspace.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Relative path to the file."
                },
                "content": {
                    "type": "string",
                    "description": "Content to write."
                }
            },
            "required": ["path", "content"]
        }
    }
}

# Simple registry mapping tool names to actual execution functions
TOOL_REGISTRY = {}
if web_search:
    TOOL_REGISTRY["search_web"] = lambda query: json.dumps(web_search.search_web(query))
else:
    # Fallback mock search if module import failed
    TOOL_REGISTRY["search_web"] = lambda query: json.dumps([
        {"title": f"Fallback Mock for query: {query}", "url": "", "snippet": "Search module unavailable."}
    ])

try:
    import research_tools
    TOOL_REGISTRY["run_python"] = lambda code: research_tools.run_python(code)
    TOOL_REGISTRY["read_file"] = lambda path: research_tools.read_file(path)
    TOOL_REGISTRY["write_file"] = lambda path, content: research_tools.write_file(path, content)
except ImportError:
    pass



def call_ollama_chat_with_tools(messages, tools=None, model="gemma4:latest", registry=None):
    """
    Call Ollama Chat API with tool-use capability.
    Executes tools locally if requested by the LLM, and submits results back
    to continue the conversation.
    """
    url = "http://localhost:11434/api/chat"
    headers = {"Content-Type": "application/json"}
    
    current_messages = list(messages)
    active_registry = registry if registry is not None else TOOL_REGISTRY
    
    for iteration in range(5):
        body = {
            "model": model,
            "messages": current_messages,
            "stream": False
        }
        if tools:
            body["tools"] = tools
            
        try:
            req = urllib.request.Request(
                url,
                data=json.dumps(body).encode("utf-8"),
                headers=headers,
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=60) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                
            assistant_msg = res_data.get("message", {})
            content_str = assistant_msg.get("content", "")
            tool_calls_str = json.dumps(assistant_msg.get("tool_calls", []))
            fallback_tokens = (len(content_str) + len(tool_calls_str)) // 4
            tokens = res_data.get("eval_count", fallback_tokens)
            if tokens <= 0:
                tokens = 1
            _accumulate_tokens(tokens)
            tool_calls = assistant_msg.get("tool_calls", [])
            
            # If the model requested tool calls, we must execute them
            if tool_calls:
                # Add the assistant's message with tool call requests to history
                current_messages.append(assistant_msg)
                
                # Execute each tool call
                for tc in tool_calls:
                    func_info = tc.get("function", {})
                    func_name = func_info.get("name")
                    func_args = func_info.get("arguments", {})
                    
                    print(f"  [Tool Call] Model requested: {func_name} with args: {func_args}")
                    
                    # Execute tool
                    if func_name in active_registry:
                        try:
                            # Try generic kwargs invocation
                            if isinstance(func_args, dict):
                                result = active_registry[func_name](**func_args)
                            else:
                                result = active_registry[func_name](func_args)
                        except TypeError:
                            try:
                                # Fallback logic for search_web if parameters are not dict kwargs
                                if func_name == "search_web":
                                    query = func_args.get("query") if isinstance(func_args, dict) else func_args
                                    if not query:
                                        if isinstance(func_args, str):
                                            query = func_args
                                        elif isinstance(func_args, dict) and func_args:
                                            query = str(list(func_args.values())[0])
                                        else:
                                            query = ""
                                    result = active_registry[func_name](query)
                                else:
                                    raise
                            except Exception as ex:
                                print(f"[Tool Execution Inner Exception]: {ex}")
                                result = json.dumps({"error": f"Tool execution failed: {ex}"})
                        except Exception as ex:
                            print(f"[Tool Execution Exception]: {ex}")
                            result = json.dumps({"error": f"Tool execution failed: {ex}"})
                    else:
                        result = json.dumps({"error": f"Tool '{func_name}' is not registered."})
                    
                    # Append tool result message
                    current_messages.append({
                        "role": "tool",
                        "content": result,
                        "name": func_name
                    })
                
                # Continue loop to send tool results back to Ollama
                continue
            else:
                # No tool calls; return final text response content
                return assistant_msg.get("content", "").strip()
                
        except Exception as e:
            print(f"[LLM ERROR] Ollama Chat API call failed: {e}")
            raise e
            
    print("[LLM WARNING] Reached maximum tool call iterations.")
    for msg in reversed(current_messages):
        if msg.get("role") == "assistant" and msg.get("content"):
            return msg["content"].strip()
    return None


def is_ollama_running():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.0) as response:
            return response.status == 200
    except Exception:
        return False


class AgentRunner:
    def __init__(self, agent_id, task_id=None, interactive=False, step_delay=3.0, offset_suffix=None, llm_provider=None, ollama_model="gemma4:latest", personality=None, goal=None, sub_swarm_id=None, graph_mode="graph"):
        self.agent_id = agent_id
        self.interactive = interactive
        self.step_delay = step_delay
        self.task_id = task_id
        self.offset_suffix = offset_suffix
        self.llm_provider = llm_provider
        self.ollama_model = ollama_model
        self.personality = personality or "Generalist"
        self.custom_goal = goal
        self.sub_swarm_id = sub_swarm_id
        self.graph_mode = graph_mode
        
        self.state_file = os.path.join(AGENTS_DIR, f"agent_{self.agent_id}.json")
        global CURRENT_AGENT_STATE_FILE
        CURRENT_AGENT_STATE_FILE = self.state_file
        self.workspace_dir = os.path.join(WORKSPACES_DIR, f"agent_{self.agent_id}")
        
        os.makedirs(AGENTS_DIR, exist_ok=True)
        os.makedirs(WORKSPACES_DIR, exist_ok=True)
        os.makedirs(self.workspace_dir, exist_ok=True)
        
        self.state = self.load_or_init_state()
        self.historical_context = None
        self.load_historical_context()

    def add_thought_trace(self, content, thought_type="info", details=None):
        disk_state = load_json(self.state_file)
        if disk_state:
            for key in ["chat_messages", "spawn_request", "goal", "personality", "output_token_budget", "subtree_token_budget"]:
                if key in disk_state:
                    self.state[key] = disk_state[key]
        if "thought_traces" not in self.state:
            self.state["thought_traces"] = []
        self.state["thought_traces"].append({
            "timestamp": time.time(),
            "content": content,
            "type": thought_type,
            "details": details or {}
        })
        save_json(self.state_file, self.state)

    def apply_offset_to_files(self, files):
        result = []
        for f in files:
            # Clean and sanitize the path to keep it relative and safe
            clean_f = f.lstrip('/')
            clean_f = os.path.normpath(clean_f)
            if clean_f.startswith("..") or os.path.isabs(clean_f):
                clean_f = os.path.basename(clean_f)
                
            if not self.offset_suffix:
                result.append(clean_f)
            else:
                base, ext = os.path.splitext(clean_f)
                result.append(f"{base}_{self.offset_suffix}{ext}")
        return result


    def load_or_init_state(self):
        state = load_json(self.state_file)
        if state:
            needs_save = False
            if "personality" not in state and self.personality:
                state["personality"] = self.personality
                needs_save = True
            if "goal" not in state and self.custom_goal:
                state["goal"] = self.custom_goal
                needs_save = True
            if "sub_swarm_id" not in state and self.sub_swarm_id:
                state["sub_swarm_id"] = self.sub_swarm_id
                needs_save = True
            if "parent_ids" not in state:
                state["parent_ids"] = [state.get("parent_id")] if state.get("parent_id") else []
                needs_save = True
            if needs_save:
                save_json(self.state_file, state)
            return state
            
        # Initialize new agent state
        if not self.task_id:
            if getattr(self, "graph_mode", "graph") == "graph":
                state = {
                    "id": self.agent_id,
                    "parent_id": None,
                    "parent_ids": [],
                    "goal": self.custom_goal or "No goal specified",
                    "personality": self.personality,
                    "status": "exploring",
                    "progress": 0,
                    "steps_completed": 0,
                    "role_mode": "proposer",
                    "files_completed": [],
                    "tools_used": [],
                    "active_node_id": None,
                    "chat_messages": []
                }
                if getattr(self, "sub_swarm_id", None):
                    state["sub_swarm_id"] = self.sub_swarm_id
                save_json(self.state_file, state)
                return state
            else:
                print(f"Error: Agent state file not found for {self.agent_id} and no --task-id was specified.")
                sys.exit(1)
                
        tasks_data = load_json(MOCK_TASKS_FILE)
        if not tasks_data or self.task_id not in tasks_data["tasks"]:
            print(f"Error: Task ID '{self.task_id}' not found in mock_tasks.json.")
            sys.exit(1)
            
        task = tasks_data["tasks"][self.task_id]
        first_step = task["steps"][0]
        first_files = self.apply_offset_to_files(first_step.get("touched_files", []))
        
        state = {
            "id": self.agent_id,
            "parent_id": None,
            "parent_ids": [],
            "goal": self.custom_goal or task["goal"],
            "personality": self.personality,
            "status": "exploring",
            "current_step": {
                "step_id": first_step["step_id"],
                "name": first_step["name"],
                "description": first_step["description"]
            },
            "touched_files": first_files,
            "tools_used": list(first_step.get("tools", [])),
            "progress": 0,
            "steps_completed": 0,
            "task_id": self.task_id
        }
        if self.sub_swarm_id:
            state["sub_swarm_id"] = self.sub_swarm_id
        
        if self.offset_suffix:
            state["offset_suffix"] = self.offset_suffix
            
        save_json(self.state_file, state)
        print(f"Initialized Agent {self.agent_id} for Task '{self.task_id}' (Offset: {self.offset_suffix}) with role '{self.personality}' and goal '{state['goal']}'.")
        return state

    def request_spawn_agent(self, goal, initial_files, reason=None):
        """Writes a spawn_request block to the agent's state file for supervisor monitoring."""
        disk_state = load_json(self.state_file)
        if disk_state:
            for key in ["chat_messages", "spawn_request", "goal", "personality", "output_token_budget", "subtree_token_budget"]:
                if key in disk_state:
                    self.state[key] = disk_state[key]
        self.state["spawn_request"] = {
            "goal": goal,
            "initial_files": list(initial_files),
            "status": "pending",
            "reason": reason or "Accelerate step execution and parallelize sub-task work."
        }
        save_json(self.state_file, self.state)
        self.add_thought_trace(
            f"Supervisor spawn request generated: spawn sub-agent for goal '{goal}'. Reason: {reason or 'none'}",
            "spawn",
            {"goal": goal, "initial_files": list(initial_files), "reason": reason}
        )
        print(f"  [Spawn Request] Registered request to spawn child agent with goal: '{goal}'")
        return json.dumps({
            "status": "success",
            "message": f"Spawn request registered for goal: '{goal}'. The supervisor will launch the child agent shortly."
        })

    def evaluate_isolation_spawn(self):
        # Prevent spawning if there's already an active spawn request on this agent
        spawn_req = self.state.get("spawn_request")
        if spawn_req and spawn_req.get("status") in ["pending", "approved"]:
            return

        # Check if the current agent already has an active child agent exploring
        has_active_child = False
        if os.path.exists(AGENTS_DIR):
            for filename in os.listdir(AGENTS_DIR):
                if filename.endswith(".json") and not filename.endswith(f"agent_{self.agent_id}.json"):
                    try:
                        filepath = os.path.join(AGENTS_DIR, filename)
                        with open(filepath, 'r') as f:
                            data = json.load(f)
                        if data.get("parent_id") == self.agent_id and data.get("status") in ["exploring", "syncing"]:
                            has_active_child = True
                            break
                    except Exception:
                        pass
        if has_active_child:
            return

        steps_comp = self.state.get("steps_completed", 0)
        if steps_comp < 0:
            return

        is_semantically_isolated = False
        active_peer_goals = []
        if os.path.exists(AGENTS_DIR):
            for filename in os.listdir(AGENTS_DIR):
                if filename.endswith(".json") and not filename.endswith(f"agent_{self.agent_id}.json"):
                    try:
                        filepath = os.path.join(AGENTS_DIR, filename)
                        with open(filepath, 'r') as f:
                            data = json.load(f)
                        if data.get("status") in ["exploring", "syncing"]:
                            if self.sub_swarm_id and data.get("sub_swarm_id") == self.sub_swarm_id:
                                active_peer_goals.append(data.get("goal", ""))
                            elif not self.sub_swarm_id:
                                active_peer_goals.append(data.get("goal", ""))
                    except Exception:
                        pass

        # Calculate semantic isolation (Suggestion 1)
        if not active_peer_goals:
            is_semantically_isolated = True
        else:
            try:
                import memory_store
                scores = memory_store.compute_tfidf_similarities(self.state["goal"], active_peer_goals)
                max_sim = max(scores) if scores else 0.0
                if max_sim < 0.35:
                    is_semantically_isolated = True
            except Exception:
                is_semantically_isolated = len(active_peer_goals) == 0
                
        # Calculate episodic novelty (Suggestion 2)
        is_novel = False
        try:
            import memory_store
            matches = memory_store.query_similar_episodes(self.state["goal"], top_k=1)
            if not matches or matches[0]["score"] < 0.5:
                is_novel = True
        except Exception:
            is_novel = True

        if is_semantically_isolated or is_novel:
            print(f"  [Explore Skill] Agent {self.agent_id} is isolated (semantically: {is_semantically_isolated}) or novel (novelty: {is_novel}). Evaluating spawn...")
            
            task_id = self.state.get("task_id")
            tasks_data = load_json(MOCK_TASKS_FILE)
            remaining_steps_desc = ""
            default_goal = f"Parallel sub-task helper for Agent {self.agent_id}"
            default_files = ["helper_output.txt"]
            
            if tasks_data and task_id in tasks_data.get("tasks", {}):
                task = tasks_data["tasks"][task_id]
                steps = task["steps"]
                completed_count = self.state["steps_completed"]
                if completed_count < len(steps):
                    next_step = steps[completed_count]
                    default_goal = f"Parallel sub-task: {next_step['description']}"
                    default_files = self.apply_offset_to_files(next_step.get("touched_files", []))
                    remaining_steps_desc = "\n".join([f"- Step {s['step_id']}: {s['name']} - {s['description']}" for s in steps[completed_count:]])

            goal = default_goal
            initial_files = default_files
            
            provider = self.llm_provider
            if not provider:
                if os.environ.get("GEMINI_API_KEY"):
                    provider = "gemini"
                elif is_ollama_running():
                    provider = "ollama"
            
            if provider in ["gemini", "ollama"] and remaining_steps_desc:
                if steps_comp == 0:
                    isolation_text = "You are starting this task without other agents' help."
                else:
                    isolation_text = f"You have been working in isolation for {steps_comp} steps without other agents' help."

                prompt = (
                    f"You are the Swarm Agent {self.agent_id} working on the task: '{self.state['goal']}'.\n"
                    f"{isolation_text}\n"
                    f"Here are your remaining steps:\n{remaining_steps_desc}\n\n"
                    f"Evaluate if spawning a helper agent with a specific sub-task will accelerate execution.\n"
                    f"Respond strictly in JSON with keys:\n"
                    f"1. 'should_spawn' (boolean: true/false)\n"
                    f"2. 'goal' (string: clear narrow task goal for the helper agent)\n"
                    f"3. 'initial_files' (array of strings: files for helper to edit/create)\n"
                    f"4. 'reason' (string: explanation of why this sub-task is needed and how it speeds up the main goal)\n"
                )
                res = None
                try:
                    if provider == "gemini":
                        res = call_gemini_api(prompt)
                    elif provider == "ollama":
                        res = call_ollama_api(prompt, model=self.ollama_model)
                except Exception:
                    pass
                
                if res:
                    if res.get("should_spawn"):
                        goal = res.get("goal", default_goal)
                        initial_files = res.get("initial_files", default_files)
                        reason = res.get("reason", "Accelerate step execution and parallelize sub-task work.")
                        if isinstance(initial_files, str):
                            initial_files = [initial_files]
                        self.request_spawn_agent(goal, initial_files, reason)
                        return
                    else:
                        # LLM decided not to spawn helper agent
                        return
 
            # If no LLM provider is active/available, we fallback to default rule-based spawn
            self.request_spawn_agent(goal, initial_files, "Rule-based isolation spawn fallback.")

    def load_historical_context(self):
        """Loads historical context from episodic memory matching the goal."""
        try:
            import memory_store
            query_goal = self.custom_goal or (self.state.get("goal") if hasattr(self, "state") else None)
            if query_goal:
                matches = memory_store.query_similar_episodes(query_goal, top_k=1, model=self.ollama_model)
                if matches and matches[0]["score"] >= 0.5:
                    match = matches[0]
                    self.historical_context = (
                        f"=== HISTORICAL EPISODE CONTEXT ===\n"
                        f"A similar task was previously executed.\n"
                        f"Past Goal: {match['goal']}\n"
                        f"Role: {match['role']}\n"
                        f"Status: {match['status']}\n"
                        f"Reflection: {match['reflection']}\n"
                        f"Errors encountered: {match['errors']}\n"
                        f"Final workspace files summary: {match['deliverable_summary']}\n"
                        f"=================================="
                    )
                    print(f"[Memory] Loaded historical episode from memory (Score: {match['score']:.2f})")
        except Exception as e:
            print(f"[Memory Error] Failed to retrieve episodic memory: {e}")

    def save_memory_episode(self, status=None, error_message=None):
        """Generates self-reflection/summary and saves this agent run to the memory store."""
        if not status:
            status = self.state.get("status", "unknown")
            
        if hasattr(self, "_memory_saved") and self._memory_saved:
            return
        self._memory_saved = True
        
        # Get list of executed steps
        tasks_data = load_json(MOCK_TASKS_FILE)
        task_id = self.state.get("task_id")
        steps_info = []
        if tasks_data and task_id in tasks_data.get("tasks", {}):
            task_steps = tasks_data["tasks"][task_id].get("steps", [])
            completed_steps = self.state.get("steps_completed", 0)
            for idx in range(min(completed_steps, len(task_steps))):
                steps_info.append({
                    "step_id": task_steps[idx].get("step_id"),
                    "name": task_steps[idx].get("name"),
                    "description": task_steps[idx].get("description")
                })
                
        # Collect final deliverable summary
        touched_files = self.state.get("touched_files", [])
        files_summary = ""
        for f in touched_files:
            f_path = os.path.join(self.workspace_dir, f)
            if os.path.exists(f_path):
                try:
                    with open(f_path, 'r') as file_obj:
                        lines = file_obj.read().splitlines()
                        summary_snippet = "\n".join(lines[:10])
                        if len(lines) > 10:
                            summary_snippet += "\n..."
                        files_summary += f"File '{f}':\n{summary_snippet}\n\n"
                except Exception:
                    pass
                    
        # Generate LLM-based deliverable summary and reflection
        reflection = ""
        deliverable_desc = ""
        steps_summary_text = "\n".join([f"- Step {s['step_id']}: {s['name']} - {s['description']}" for s in steps_info])
        errors_text = error_message or ""
        
        if self.llm_provider == "ollama" and is_ollama_running():
            # Generate Reflection
            refl_prompt = (
                f"You are Agent {self.agent_id} with the role/personality: '{self.state.get('personality', 'Generalist')}' and goal: '{self.state['goal']}'.\n"
                f"You finished execution with status: '{status}'.\n"
                f"Steps executed:\n{steps_summary_text}\n"
                f"Errors/Tombstones hit: '{errors_text}'\n\n"
                f"Write a brief, 2-3 sentence self-reflection summarizing what you accomplished, what went wrong (if anything), and lessons learned for future agents. "
                f"Do not include any conversational intro/outro or explanations. Output ONLY the self-reflection."
            )
            reflection = call_ollama_raw(refl_prompt, model=self.ollama_model)
            
            # Generate Deliverable summary
            deliv_prompt = (
                f"Summarize the final output files and accomplishments of the task in one concise sentence based on the following files content:\n"
                f"{files_summary}\n\n"
                f"Output ONLY the one-sentence summary."
            )
            deliverable_desc = call_ollama_raw(deliv_prompt, model=self.ollama_model)
            
        # Fallbacks if LLM failed or offline
        if not reflection:
            if status == "completed":
                reflection = f"Completed all {len(steps_info)} steps of the task successfully. Delivered the required artifacts without encountering blocking traps."
            else:
                reflection = f"Failed to complete task. Encountered blocking trap error: {errors_text or 'unknown error'}. Tombstone registered for future runs."
                
        if not deliverable_desc:
            deliverable_desc = f"Generated {len(touched_files)} files: {', '.join(touched_files)}"
            
        try:
            import memory_store
            memory_store.save_episode(
                goal=self.state["goal"],
                role=self.state.get("personality", "Generalist"),
                status=status,
                steps=steps_info,
                errors=errors_text,
                deliverable_summary=deliverable_desc.strip(),
                reflection=reflection.strip(),
                model=self.ollama_model
            )
            print(f"[Memory] Successfully saved execution episode to memory store (Status: {status})")
        except Exception as e:
            print(f"[Memory Error] Failed to save episodic memory: {e}")

    def check_tombstones(self, files, tools):
        """Query tombstones.json to check if any upcoming command/file matches a known dead-end."""
        tombstones_data = load_json(TOMBSTONES_FILE) or []
        tombstones = tombstones_data if isinstance(tombstones_data, list) else tombstones_data.get("dead_ends", [])
        for t in tombstones:
            if t.get("is_pruned"):
                continue
            file_match = any(f in t.get("file_path", "") for f in files)
            tool_match = any(tool == t.get("tool_used", "") for tool in tools)
            if file_match and tool_match:
                return t
        return None

    def check_pruned_tombstones(self, files, tools):
        """Query tombstones.json to retrieve warning context for pruned paths."""
        tombstones_data = load_json(TOMBSTONES_FILE) or []
        tombstones = tombstones_data if isinstance(tombstones_data, list) else tombstones_data.get("pruned_agents", [])
        pruned_matches = []
        for t in tombstones:
            if not t.get("is_pruned") and isinstance(tombstones_data, list):
                continue
            file_match = any(f in t.get("file_path", "") for f in files)
            tool_match = any(tool == t.get("tool_used", "") for tool in tools)
            if file_match and tool_match:
                pruned_matches.append(t)
        return pruned_matches

    def run_verification(self, command, timeout=60):
        """Run a step's verification command inside the agent workspace (design_doc §13).

        Returns (passed: bool, output: str). A non-zero exit code, timeout, or launch
        failure all count as not-passed so the self-healing loop can react to them.
        """
        try:
            proc = subprocess.run(
                command, shell=True, cwd=self.workspace_dir,
                capture_output=True, text=True, timeout=timeout
            )
            output = ((proc.stdout or "") + (proc.stderr or "")).strip()
            return proc.returncode == 0, output
        except subprocess.TimeoutExpired:
            return False, f"Verification timed out after {timeout}s."
        except Exception as ex:
            return False, f"Verification command could not run: {ex}"

    def heal_file(self, filename, current_step, error_output):
        """Re-prompt the LLM with a RESET context window to patch a failing file.

        Per §13, the context contains only the goal, the current file contents, and the
        raw verification error — prior failed attempts are intentionally not accumulated,
        which keeps a local model's instruction-following sharp. Returns the patched file
        content, or None when no LLM patcher is available (offline → loop stops gracefully).
        """
        file_path = os.path.join(self.workspace_dir, filename)
        try:
            with open(file_path) as fh:
                current_content = fh.read()
        except Exception:
            current_content = ""

        if not (self.llm_provider == "ollama" and is_ollama_running()):
            return None

        prompt = (
            f"You are Agent {self.agent_id} ({self.state.get('personality', 'Generalist')}). "
            f"Goal: '{self.state.get('goal', '')}'.\n"
            f"Step: {current_step.get('name', 'step')} — {current_step.get('description', '')}\n"
            f"The file '{filename}' failed its verification command. Fix it so verification passes.\n\n"
            f"=== CURRENT CONTENT OF {filename} ===\n{current_content}\n\n"
            f"=== RAW VERIFICATION ERROR ===\n{error_output}\n\n"
            f"Output ONLY the corrected, complete raw content of '{filename}'. "
            f"No markdown fences, no commentary."
        )
        res = call_ollama_raw(prompt, model=self.ollama_model)
        if not res:
            return None
        if res.startswith("```"):
            lines = res.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            res = "\n".join(lines)
        return res

    def run_verification_loop(self, verification_cmd, primary_file, current_step):
        """Self-healing inner loop (design_doc §13). Runs verification, and on failure
        re-prompts the LLM to patch `primary_file` with a reset context, retrying up to
        MAX_HEAL_ATTEMPTS. Returns (passed: bool, attempts: int, last_output: str)."""
        passed, output = self.run_verification(verification_cmd)
        attempts = 0
        while not passed and attempts < MAX_HEAL_ATTEMPTS:
            attempts += 1
            self.add_thought_trace(
                f"Verification failed for '{current_step.get('name', 'step')}' "
                f"(attempt {attempts}/{MAX_HEAL_ATTEMPTS}). Self-healing '{primary_file}' "
                f"with a reset context window...",
                "debugging",
                {"attempt": attempts, "error": output[:500]}
            )
            try:
                import causal_tracer
                causal_tracer.log_step_execution(
                    self.agent_id, current_step.get("step_id", 0),
                    current_step.get("name", "step"), f"Self-heal attempt {attempts}",
                    "debugging", {"error": output[:500]}
                )
            except Exception:
                pass
            patched = self.heal_file(primary_file, current_step, output)
            if not patched:
                print("  [Self-Heal] No patch available (LLM offline?). Stopping heal loop.")
                break
            with open(os.path.join(self.workspace_dir, primary_file), 'w') as fh:
                fh.write(patched)
            passed, output = self.run_verification(verification_cmd)
        return passed, attempts, output

    def has_unresolved_spawn(self):
        sr = self.state.get("spawn_request") or {}
        if sr.get("status") in ("pending", "approved"):
            return True
        for child_id in self.state.get("children", []):
            child = load_json(os.path.join(AGENTS_DIR, f"agent_{child_id}.json"))
            if child and child.get("status") not in ("completed", "dead"):
                return True
        return False

    def finalize_or_await(self):
        """Complete, unless a spawned child is still unresolved — then await it."""
        if self.has_unresolved_spawn():
            if self.state.get("status") != "awaiting_child":
                self.state["status"] = "awaiting_child"
                self.add_thought_trace(
                    "Finished my own steps but a spawned child is unresolved. "
                    "Holding completion to check in on it.", "evaluating")
                save_json(self.state_file, self.state)
            return False
        self.state["status"] = "completed"
        self.state["progress"] = 100
        save_json(self.state_file, self.state)
        return True

    def check_in_on_children(self):
        if not self.has_unresolved_spawn():
            self.ingest_child_outputs()
            self.finalize_or_await()
            if self.state.get("status") == "completed":
                self.save_memory_episode()
            return

        iters = self.state.get("await_iters", 0) + 1
        self.state["await_iters"] = iters
        
        MAX_AWAIT_ITERS = 20
        if iters > MAX_AWAIT_ITERS:
            self.add_thought_trace("Waited too long for child result; finalizing without it.", "decision")
            self.ingest_child_outputs(partial=True)
            self.state["status"] = "completed"
            self.state["progress"] = 100
            save_json(self.state_file, self.state)
            self.save_memory_episode()
            return

        decision = self._decide_wait_or_proceed()
        if decision == "PROCEED":
            self.add_thought_trace("Child result not worth waiting for; finalizing now.", "decision")
            self.ingest_child_outputs(partial=True)
            self.state["status"] = "completed"
            self.state["progress"] = 100
            save_json(self.state_file, self.state)
            self.save_memory_episode()
        else:
            self.add_thought_trace("Decided to keep waiting for the child's result.", "evaluating")
            save_json(self.state_file, self.state)
            time.sleep(self.step_delay)

    def _decide_wait_or_proceed(self):
        """Query LLM (or rule fallback) to decide whether to wait for child agent(s) or proceed/finalize."""
        children_info = []
        for child_id in self.state.get("children", []):
            child = load_json(os.path.join(AGENTS_DIR, f"agent_{child_id}.json"))
            if child:
                children_info.append({
                    "id": child_id,
                    "goal": child.get("goal", ""),
                    "status": child.get("status", ""),
                    "progress": child.get("progress", 0)
                })
        
        provider = self.llm_provider
        if not provider:
            if os.environ.get("GEMINI_API_KEY"):
                provider = "gemini"
            elif is_ollama_running():
                provider = "ollama"
            else:
                provider = "rules"
                
        if provider in ["gemini", "ollama"] and children_info:
            prompt = (
                f"You are Proximity Swarm Agent {self.agent_id} working on goal: '{self.state.get('goal', '')}'.\n"
                f"You have finished executing your own steps but are waiting for child agent(s) to finish.\n"
                f"Here is the status of your child agent(s):\n"
                f"{json.dumps(children_info, indent=2)}\n\n"
                f"Decide whether you should continue waiting for the children to complete ('WAIT') or "
                f"proceed and finalize without waiting any longer ('PROCEED').\n"
                f"Respond strictly in JSON with a single key 'decision' whose value is either 'WAIT' or 'PROCEED'."
            )
            try:
                res = None
                if provider == "gemini":
                    res = call_gemini_api(prompt)
                else:
                    res = call_ollama_api(prompt, model=self.ollama_model)
                if res and "decision" in res:
                    dec = res["decision"].strip().upper()
                    if dec in ["WAIT", "PROCEED"]:
                        return dec
            except Exception as ex:
                print(f"  [Wait/Proceed Decision LLM Error]: {ex}")
                
        iters = self.state.get("await_iters", 0)
        any_child_running = False
        for c in children_info:
            if c["status"] not in ["completed", "dead"] and c["progress"] < 100:
                any_child_running = True
                break
        if any_child_running and iters < 8:
            return "WAIT"
        return "PROCEED"

    def ingest_child_outputs(self, partial=False):
        """Finds completed or in-progress child agent workspace files and appends them to a results summary file in parent's workspace."""
        parent_results_file = os.path.join(self.workspace_dir, "child_results.md")
        
        existing_content = ""
        if os.path.exists(parent_results_file):
            try:
                with open(parent_results_file, 'r') as fh:
                    existing_content = fh.read()
            except Exception:
                pass
                
        new_sections = []
        for child_id in self.state.get("children", []):
            child_ws = os.path.join(WORKSPACES_DIR, f"agent_{child_id}")
            child_json_path = os.path.join(AGENTS_DIR, f"agent_{child_id}.json")
            child_data = load_json(child_json_path) or {}
            
            ingested_marker = f"<!-- ingested:{child_id} -->"
            if ingested_marker in existing_content and not partial:
                continue
                
            child_files_summary = ""
            if os.path.exists(child_ws):
                for root, dirs, files in os.walk(child_ws):
                    for file in files:
                        file_path = os.path.join(root, file)
                        rel_path = os.path.relpath(file_path, child_ws)
                        if rel_path.startswith(".") or rel_path.endswith(".log"):
                            continue
                        try:
                            with open(file_path, 'r') as fh:
                                content = fh.read()
                            child_files_summary += f"### File: `{rel_path}`\n\n{content}\n\n"
                        except Exception:
                            pass
                            
            if child_files_summary:
                header = f"\n\n## Results from Child Agent {child_id} (Goal: '{child_data.get('goal', '')}')\n"
                if not partial:
                    header += f"{ingested_marker}\n"
                new_sections.append(header + child_files_summary)
                self.add_thought_trace(f"Ingested results from child {child_id}.", "info")
                print(f"  [Ingestion] Ingested results from child Agent {child_id} workspace.")
                
        if new_sections:
            try:
                with open(parent_results_file, 'a') as fh:
                    for section in new_sections:
                        fh.write(section)
            except Exception as e:
                print(f"  [Ingestion Error] Failed to write results to parent workspace: {e}")

    def execute_step(self):
        self.state = load_json(self.state_file)
        
        if self.state["status"] == "dead":
            print(f"Agent {self.agent_id} is DEAD. Exiting.")
            sys.exit(0)
            
        if self.state["status"] == "pending_termination":
            print(f"\n[PAUSED] Agent {self.agent_id} is pending termination approval from Supervisor...")
            while True:
                time.sleep(1.0)
                self.state = load_json(self.state_file)
                if self.state["status"] == "dead":
                    print(f"Agent {self.agent_id} termination APPROVED by Supervisor. Exiting.")
                    sys.exit(0)
                if self.state["status"] == "exploring":
                    print(f"Agent {self.agent_id} termination REJECTED by Supervisor (extinction prevention). Resuming.")
                    break
            return
            
        if self.state["status"] == "syncing":
            print(f"\n[SYNC REQUIRED] Agent {self.agent_id} has been PAUSED. Starting Negotiation Skill...")
            self.perform_negotiation()
            return

        if self.state["status"] == "awaiting_child":
            print(f"\n[PAUSED] Agent {self.agent_id} is awaiting child agent resolution...")
            self.check_in_on_children()
            return

        # 1. Process pending operator chat messages (Pivot / Add Context Decision Loop)
        chat_messages = self.state.get("chat_messages", [])
        unprocessed = [m for m in chat_messages if not m.get("processed", False) and m.get("role") == "user"]
        if unprocessed:
            self.add_thought_trace(
                f"New operator message received. Evaluating implications on current goal...",
                "evaluating"
            )
            msg_content = "\n".join([f"- {msg['content']}" for msg in unprocessed])
            prompt = (
                f"You are Agent {self.agent_id} (Role: {self.state.get('personality', 'Generalist')}) currently working with goal: '{self.state.get('goal', '')}'.\n"
                f"You received the following message(s) from the human operator:\n"
                f"{msg_content}\n\n"
                f"You must decide how to handle this input. Choose between:\n"
                f"1. ADD_CONTEXT: Keep your current goal but incorporate this message as additional context for your work.\n"
                f"2. PIVOT: Change/update your goal/direction in response to the operator's instructions.\n\n"
                f"Respond strictly in JSON format with keys:\n"
                f"- 'decision': must be either 'ADD_CONTEXT' or 'PIVOT'\n"
                f"- 'thought': 2-3 sentences explaining your reasoning (why you chose this action and how it affects your task)\n"
                f"- 'updated_goal': if you chose 'PIVOT', write the new/modified goal description. If 'ADD_CONTEXT', keep it the same as the current goal.\n"
            )
            
            provider = self.llm_provider
            if not provider:
                if os.environ.get("GEMINI_API_KEY"):
                    provider = "gemini"
                elif is_ollama_running():
                    provider = "ollama"
                else:
                    provider = "rules"
                    
            res = None
            try:
                if provider == "gemini":
                    res = call_gemini_api(prompt)
                elif provider == "ollama":
                    res = call_ollama_api(prompt, model=self.ollama_model)
            except Exception as ex:
                print(f"[Chat Decision LLM Error]: {ex}")
                
            if not res:
                res = {
                    "decision": "ADD_CONTEXT",
                    "thought": "LLM offline or error. Defaulting to adding message as context.",
                    "updated_goal": self.state.get("goal")
                }
            
            decision = res.get("decision", "ADD_CONTEXT")
            thought = res.get("thought", "Incorporating user message.")
            updated_goal = res.get("updated_goal", self.state.get("goal"))
            
            self.add_thought_trace(
                f"Operator message decision: {decision}. Reasoning: {thought}" + (f" (New Goal: '{updated_goal}')" if decision == "PIVOT" else ""),
                "decision",
                {"decision": decision, "thought": thought, "updated_goal": updated_goal}
            )
            
            if decision == "PIVOT":
                self.state["goal"] = updated_goal
                print(f"  [Chat Pivot] Agent {self.agent_id} goal updated to: '{updated_goal}'")
            
            chat_messages.append({
                "role": "assistant",
                "content": f"Decision: {decision}\nReasoning: {thought}" + (f"\nNew Goal: {updated_goal}" if decision == "PIVOT" else ""),
                "timestamp": time.time(),
                "processed": True
            })
            
            # Note: We do NOT mark the operator user messages as processed here.
            # They will remain unprocessed so that the step execution file prompt generator
            # sees them and incorporates them as OPERATOR DIRECTIVES, and then marks them processed.
            self.state["chat_messages"] = chat_messages
            save_json(self.state_file, self.state)

        # Start-of-step state save to ensure coordinates (status, progress, current_step, files, tools) are synced
        save_json(self.state_file, self.state)
        
        # Evaluate isolated spawn every 5 steps
        self.evaluate_isolation_spawn()

        if getattr(self, "graph_mode", "graph") == "graph":
            self.execute_step_graph()
        else:
            self.execute_step_linear()

    def execute_step_graph(self):
        import logic_graph
        role_mode = self.state.get("role_mode", "proposer")
        active_node_id = self.state.get("active_node_id")
        
        # Proposer picks from frontier
        if role_mode == "proposer" and not active_node_id:
            frontier = logic_graph.frontier()
            if not frontier:
                print(f"Agent {self.agent_id} found no frontier nodes. Waiting.")
                return
            target = frontier[0]
            approach = self.state.get("approach")
            if approach:
                approach_nodes = [n for n in frontier if n.get("approach") == approach]
                if approach_nodes:
                    target = approach_nodes[0]
            
            active_node_id = target["node_id"]
            self.state["active_node_id"] = active_node_id
            save_json(self.state_file, self.state)
            
        # Validator polls for proposed nodes
        if role_mode == "validator" and not active_node_id:
            proposed = logic_graph.nodes_by_status("proposed")
            proposed = [n for n in proposed if n.get("kind") != "goal"]
            approach = self.state.get("approach")
            if approach:
                proposed = [n for n in proposed if n.get("approach") == approach]
            if proposed:
                active_node_id = proposed[0]["node_id"]
                self.state["active_node_id"] = active_node_id
                save_json(self.state_file, self.state)
            else:
                return

        if not active_node_id:
            return
            
        node = logic_graph.get_node(active_node_id)
        if not node:
            self.state["active_node_id"] = None
            save_json(self.state_file, self.state)
            return
            
        if role_mode == "proposer":
            if self.llm_provider == "rules":
                new_claim = f"Proposed step from {active_node_id}"
                oracle = {"type": "shell", "spec": "echo ok"}
            else:
                # LLM call
                new_claim = "LLM Proposed claim"
                oracle = {"type": "shell", "spec": "echo ok"}
                
            similar = logic_graph.similar_open_nodes(new_claim)
            if similar:
                existing_node_id = similar[0]
                print(f"Agent {self.agent_id} found similar open node {existing_node_id}. Joining.")
                self.state["active_node_id"] = existing_node_id
                self.state["role_mode"] = "validator"
                save_json(self.state_file, self.state)
                return
                
            new_node_id = f"n_{self.agent_id}_{int(time.time())}"
            validated_nodes = logic_graph.nodes_by_status("validated")
            validated_ids = [n["node_id"] for n in validated_nodes]
            if not validated_ids:
                validated_ids = ["premise_0"]
            logic_graph.add_node({
                "node_id": new_node_id,
                "claim": new_claim,
                "justification": "Proposed justification",
                "depends_on": validated_ids,
                "approach": self.state.get("approach", "A"),
                "status": "proposed",
                "kind": "lemma",
                "oracle": oracle,
                "provenance": {"proposed_by": self.agent_id}
            })
            logic_graph.update_node(active_node_id, depends_on=node.get("depends_on", []) + [new_node_id])
            self.state["active_node_id"] = None
            save_json(self.state_file, self.state)
            print(f"Agent {self.agent_id} PROPOSED node {new_node_id}")
            try:
                import causal_tracer
                causal_tracer.log_propose(self.agent_id, new_node_id, new_claim)
            except Exception:
                pass
            
        elif role_mode == "validator":
            if node.get("status") != "proposed":
                self.state["active_node_id"] = None
                save_json(self.state_file, self.state)
                return
                
            import judge
            import oracle
            
            judge_provider, judge_model = judge.select_judge_model(
                getattr(self, "judge_provider", None),
                getattr(self, "judge_model", None),
                self.llm_provider,
                getattr(self, "ollama_model", None) or getattr(self, "gemini_model", None)
            )
            
            node_oracle_type = node.get("oracle", {}).get("type", "none")
            passed = False
            
            if node_oracle_type == "none":
                # Unverifiable
                passed = False
            elif node_oracle_type == "checker_model":
                result = judge.validate_step(node, judge_provider, judge_model, self.agent_id)
                passed = result["valid"]
            else:
                passed, msg = oracle.evaluate_oracle(node, self.workspace_dir)
                if passed is None:
                    # Defer to judge
                    result = judge.validate_step(node, judge_provider, judge_model, self.agent_id)
                    passed = result["valid"]
            
            if self.llm_provider == "rules":
                passed = not self.state.get("force_fail", False)
                if node_oracle_type == "none":
                    passed = False
            
            if passed:
                logic_graph.update_node(active_node_id, status="validated")
                self.state["steps_completed"] = self.state.get("steps_completed", 0) + 1
                self.state["progress"] = min(100, self.state["steps_completed"] * 20)
                print(f"Agent {self.agent_id} VALIDATED node {active_node_id}")
                try:
                    import causal_tracer
                    causal_tracer.log_validate(self.agent_id, active_node_id)
                except Exception:
                    pass
            else:
                # To do: self healing loop for shell/numeric
                logic_graph.update_node(active_node_id, status="refuted")
                print(f"Agent {self.agent_id} REFUTED node {active_node_id}")
                try:
                    import causal_tracer
                    causal_tracer.log_refute(self.agent_id, active_node_id)
                except Exception:
                    pass
                
                tombstones = load_json(TOMBSTONES_FILE) or {"pruned_agents": [], "dead_ends": [], "refuted_nodes": []}
                if "refuted_nodes" not in tombstones:
                    tombstones["refuted_nodes"] = []
                tombstones["refuted_nodes"].append({
                    "node_id": active_node_id,
                    "claim": node.get("claim"),
                    "approach": node.get("approach"),
                    "reason": "Validation failed"
                })
                save_json(TOMBSTONES_FILE, tombstones)
                
            self.state["active_node_id"] = None
            save_json(self.state_file, self.state)

    def execute_step_linear(self):

        # 2. Progress task step (Linear)
        task_id = self.state.get("task_id")
        tasks_data = load_json(MOCK_TASKS_FILE)
        if not tasks_data or task_id not in tasks_data["tasks"]:
            print(f"Error: Task data missing for task {task_id}.")
            self.finalize_or_await()
            return
            
        task = tasks_data["tasks"][task_id]
        steps = task["steps"]
        completed_count = self.state["steps_completed"]
        
        if completed_count >= len(steps):
            print(f"Agent {self.agent_id} has completed all steps of Task {task_id}.")
            self.finalize_or_await()
            return
            
        current_step = steps[completed_count]
        print(f"\n[Agent {self.agent_id}] Executing Step {current_step['step_id']}/{len(steps)}: {current_step['name']}")
        try:
            import causal_tracer
            causal_tracer.log_step_execution(
                self.agent_id,
                current_step["step_id"],
                current_step["name"],
                current_step["description"],
                "executing"
            )
        except Exception:
            pass
        print(f"  Description: {current_step['description']}")
        
        step_files = self.apply_offset_to_files(current_step.get("touched_files", []))
        step_tools = current_step.get("tools", [])
        
        self.add_thought_trace(
            f"Starting Step {current_step['step_id']}: '{current_step['name']}' (Goal: '{self.state['goal']}'). Target files: {', '.join(step_files) if step_files else 'None'}",
            "executing",
            {"step_id": current_step['step_id'], "step_name": current_step['name']}
        )
        
        tombstone = self.check_tombstones(step_files, step_tools)
        applied_workaround = False
        
        if tombstone:
            print(f"  [!WARNING] Known Dead-end warning found in Tombstone database!")
            print(f"  Blocker: {tombstone['error_message']}")
            print(f"  Applying Workaround: {tombstone['fix_action']}")
            if "gcc" in step_tools:
                step_tools = [t if t != "gcc" else "clang" for t in step_tools]
                applied_workaround = True
                print(f"  Action: Swapped compilation tool from 'gcc' to 'clang'.")
            
            if not applied_workaround:
                print(f"  [ABSOLUTE BLOCKADE] Blocker is absolute and no workaround could be applied.")
                self.state["status"] = "pending_termination"
                self.state["blocker_details"] = {
                    "file_path": tombstone.get("file_path", "unknown"),
                    "tool_used": tombstone.get("tool_used", "unknown"),
                    "error_message": tombstone.get("error_message", "unknown"),
                    "fix_action": tombstone.get("fix_action", "unknown")
                }
                self.add_thought_trace(
                    f"Hit absolute blockade: {tombstone['error_message']}. Proposing pending termination.",
                    "failed",
                    {"error": tombstone['error_message']}
                )
                save_json(self.state_file, self.state)
                self.save_memory_episode(status="failed", error_message=tombstone['error_message'])
                try:
                    import causal_tracer
                    causal_tracer.log_step_execution(
                        self.agent_id,
                        current_step["step_id"],
                        current_step["name"],
                        current_step["description"],
                        "failed",
                        {"error": tombstone['error_message']}
                    )
                    causal_tracer.log_state_transition(
                        self.agent_id, "exploring", "pending_termination",
                        {"error": f"Absolute blockade from tombstone: {tombstone['error_message']}"}
                    )
                except Exception:
                    pass
                return
                
        # If final step and no files specified, use fallback answer.md to display output in dashboard
        is_final_step = (self.state["steps_completed"] + 1) >= len(steps)
        if not step_files and is_final_step:
            step_files = ["answer.md"]

        # Check for pruned tombstones warning context
        pruned_matches = self.check_pruned_tombstones(step_files, step_tools)
        pruned_context_str = ""
        if pruned_matches:
            print(f"  [!WARNING] Previous agent(s) were pruned on a similar step. Ingesting context...")
            pruned_context_str = "=== ADVISORY: PREVIOUS PRUNING ENCOUNTERED ===\n"
            for pm in pruned_matches:
                pruned_context_str += (
                    f"- A previous agent working on goal '{pm.get('goal', 'unknown')}' was pruned at step '{pm.get('step_name', 'unknown')}' "
                    f"due to being unproductive or taking too long. Explanation/Reason: {pm.get('error_message', 'none')}\n"
                )
            pruned_context_str += "Please analyze this and adjust your strategy to avoid taking too long, or consider breaking the task down into smaller sub-tasks to improve productivity.\n\n"

        # Simulate execution / Touch files in local sandbox workspace
        for filename in step_files:
            file_path = os.path.join(self.workspace_dir, filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            content = f"# Agent {self.agent_id} completed {current_step['name']} at {time.time()}\n"
            if self.llm_provider == "ollama" and is_ollama_running():
                prompt = ""
                if pruned_context_str:
                    prompt += pruned_context_str + "\n"
                if getattr(self, "historical_context", None):
                    prompt += self.historical_context + "\n\n"
                prompt += (
                    f"You are Agent {self.agent_id} with the role/personality: '{self.state.get('personality', 'Generalist')}' working on the task: '{self.state['goal']}'.\n"
                    f"Current Step: {current_step['name']}\n"
                    f"Description: {current_step['description']}\n"
                    f"You are generating/updating the file: '{filename}'.\n\n"
                    f"Generate the complete, high-quality, actual code or report content for this file. "
                    f"You must perform your work in character based on your assigned role/personality. "
                    f"Do not include any conversational dialogue, chat introduction, or explaining text outside the file content. "
                    f"Output ONLY the raw content of the file."
                )
                
                res_content = None
                try:
                    # Attempt native Ollama tool-calling loop with search and spawn tools
                    system_prompt = (
                        f"You are Agent {self.agent_id} with the role/personality: '{self.state.get('personality', 'Generalist')}' working on the task: '{self.state['goal']}'.\n"
                        f"You must perform your work in character based on your assigned role/personality. "
                        f"Do not include any conversational dialogue, chat introduction, or explaining text outside the file content. "
                        f"Output ONLY the raw content of the file. No markdown code fence wrapper or conversational noise.\n\n"
                        f"SPAWNING ABILITY: If you are working on a complex, multi-stage goal and realize that a sub-task "
                        f"can be executed independently in parallel (e.g. building a helper script, testing a sub-module, or parsing config), "
                        f"you can call the `spawn_agent` tool to request the supervisor to spawn a specialized sub-agent. "
                        f"Do not block on the sub-agent; spawn it and continue with your main tasks.\n\n"
                        f"RESEARCH TOOLS: You have access to a Python sandbox (`run_python`) and file system access (`read_file`, `write_file`). "
                        f"Use them to test math properties, run simulations, or persist intermediate data when exploring complex logic."
                    )
                    user_prompt = ""
                    if pruned_context_str:
                        user_prompt += pruned_context_str + "\n"
                    if getattr(self, "historical_context", None):
                        user_prompt += self.historical_context + "\n\n"

                    # Inject chat directives from human operator
                    chat_messages = self.state.get("chat_messages", [])
                    unprocessed = [m for m in chat_messages if not m.get("processed", False)]
                    if unprocessed:
                        user_prompt += "=== HUMAN OPERATOR DIRECTIVES ===\n"
                        user_prompt += "The human operator has sent you the following messages. Follow these directives carefully:\n\n"
                        for msg in unprocessed:
                            user_prompt += f"- {msg.get('content', '')}\n"
                        user_prompt += "\nPlease incorporate these directives into your current work.\n"
                        user_prompt += "=== END OPERATOR DIRECTIVES ===\n\n"
                        # Mark messages as processed
                        for msg in chat_messages:
                            if not msg.get("processed", False):
                                msg["processed"] = True
                        self.state["chat_messages"] = chat_messages
                        save_json(CURRENT_AGENT_STATE_FILE, self.state)
                        print(f"  [Chat] Injected {len(unprocessed)} operator directive(s) into prompt.")

                    user_prompt += (
                        f"Current Step: {current_step['name']}\n"
                        f"Description: {current_step['description']}\n"
                        f"You are generating/updating the file: '{filename}'.\n\n"
                        f"Generate the complete, high-quality, actual code or report content for this file."
                    )
                    
                    messages = [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt}
                    ]
                    
                    local_registry = {
                        "search_web": lambda query: json.dumps(web_search.search_web(query) if web_search else []),
                        "spawn_agent": lambda goal, initial_files: self.request_spawn_agent(goal, initial_files)
                    }
                    try:
                        import research_tools
                        local_registry["run_python"] = lambda code: research_tools.run_python(code)
                        local_registry["read_file"] = lambda path: research_tools.read_file(path)
                        local_registry["write_file"] = lambda path, content: research_tools.write_file(path, content)
                    except ImportError:
                        pass
                    
                    print(f"  [Tool Use Check] Querying Ollama with search and spawn tool capabilities...")
                    res_content = call_ollama_chat_with_tools(
                        messages=messages,
                        tools=[SEARCH_WEB_TOOL, SPAWN_AGENT_TOOL, RUN_PYTHON_TOOL, READ_FILE_TOOL, WRITE_FILE_TOOL],
                        model=self.ollama_model,
                        registry=local_registry
                    )
                except Exception as tool_ex:
                    print(f"  [Tool Use Bypass] Ollama tool-calling failed/unsupported: {tool_ex}. Falling back to raw generate.")
                    res_content = None
                
                # If tool calling failed, returned empty, or was bypassed, fall back to generate endpoint
                if not res_content:
                    res_content = call_ollama_raw(prompt, model=self.ollama_model)
                
                if res_content:
                    # Strip any markdown code fence wrappers if output by the LLM
                    if res_content.startswith("```"):
                        lines = res_content.splitlines()
                        if lines[0].startswith("```"):
                            lines = lines[1:]
                        if lines and lines[-1].strip() == "```":
                            lines = lines[:-1]
                        res_content = "\n".join(lines)
                    content = res_content
            
            with open(file_path, 'w') as f:
                f.write(content)
            print(f"  Touched sandbox file: {filename}")
            
        # Check if the step is a trap and we failed to apply the workaround
        if current_step.get("is_trap") and not applied_workaround:
            error_msg = current_step.get("trap_error", "Fatal compilation crash.")
            fix_msg = current_step.get("trap_fix", "Use an alternative compiler.")
            print(f"  [CRASH] Step execution failed: {error_msg}")
            
            # Write a tombstone
            tombstones_data = load_json(TOMBSTONES_FILE) or []
            tombstones = tombstones_data if isinstance(tombstones_data, list) else tombstones_data.get("dead_ends", [])
            new_tombstone = {
                "file_path": step_files[0] if step_files else "unknown",
                "tool_used": step_tools[0] if step_tools else "unknown",
                "error_message": error_msg,
                "fix_action": fix_msg,
                "timestamp": get_iso_timestamp()
            }
            tombstones.append(new_tombstone)
            if isinstance(tombstones_data, dict):
                tombstones_data["dead_ends"] = tombstones
                save_json(TOMBSTONES_FILE, tombstones_data)
            else:
                save_json(TOMBSTONES_FILE, tombstones)
            self.add_thought_trace(
                f"Step execution CRASHED: {error_msg}. Tombstone registered.",
                "failed",
                {"error": error_msg}
            )
            print(f"  [TOMBSTONE REGISTERED] Saved failure context to tombstones.json.")
            
            self.state["status"] = "pending_termination"
            self.state["blocker_details"] = {
                "file_path": step_files[0] if step_files else "unknown",
                "tool_used": step_tools[0] if step_tools else "unknown",
                "error_message": error_msg,
                "fix_action": fix_msg
            }
            save_json(self.state_file, self.state)
            self.save_memory_episode(status="failed", error_message=error_msg)
            try:
                import causal_tracer
                causal_tracer.log_step_execution(
                    self.agent_id,
                    current_step["step_id"],
                    current_step["name"],
                    current_step["description"],
                    "failed",
                    {"error": error_msg}
                )
                causal_tracer.log_state_transition(self.agent_id, "exploring", "pending_termination", {"error": error_msg})
            except Exception:
                pass
            print(f"  Agent {self.agent_id} is pending termination approval from Supervisor.")
            return
            
        time.sleep(self.step_delay)

        # === Self-Healing Verification Gate (design_doc §13) ===
        # If the step declares a verification command, progress only advances once it passes.
        # On failure we self-heal up to MAX_HEAL_ATTEMPTS; if still failing, the step is
        # blocked and a tombstone is registered — steps_completed/progress are NOT advanced.
        verification_cmd = current_step.get("verification")
        if verification_cmd and step_files:
            primary_file = step_files[0]
            passed, attempts, vout = self.run_verification_loop(verification_cmd, primary_file, current_step)
            if not passed:
                error_msg = f"Step '{current_step['name']}' verification failed after {attempts} self-heal attempt(s)."
                print(f"  [VERIFICATION BLOCKER] {error_msg}\n  Output: {vout[:300]}")
                tombstones_data = load_json(TOMBSTONES_FILE) or []
                tombstones = tombstones_data if isinstance(tombstones_data, list) else tombstones_data.get("dead_ends", [])
                tombstones.append({
                    "file_path": primary_file,
                    "tool_used": step_tools[0] if step_tools else "verification",
                    "error_message": f"{error_msg} Last output: {vout[:300]}",
                    "fix_action": "Manual review required; verification command did not pass.",
                    "timestamp": get_iso_timestamp()
                })
                if isinstance(tombstones_data, dict):
                    tombstones_data["dead_ends"] = tombstones
                    save_json(TOMBSTONES_FILE, tombstones_data)
                else:
                    save_json(TOMBSTONES_FILE, tombstones)
                self.add_thought_trace(
                    error_msg + " Registering tombstone and proposing termination.",
                    "failed", {"error": vout[:500], "attempts": attempts}
                )
                self.state["status"] = "pending_termination"
                self.state["blocker_details"] = {
                    "file_path": primary_file,
                    "tool_used": step_tools[0] if step_tools else "verification",
                    "error_message": error_msg,
                    "fix_action": "Manual review required; verification command did not pass."
                }
                save_json(self.state_file, self.state)
                self.save_memory_episode(status="failed", error_message=error_msg)
                try:
                    import causal_tracer
                    causal_tracer.log_step_execution(
                        self.agent_id, current_step["step_id"], current_step["name"],
                        current_step["description"], "failed", {"error": error_msg}
                    )
                    causal_tracer.log_state_transition(
                        self.agent_id, "exploring", "pending_termination", {"error": error_msg}
                    )
                except Exception:
                    pass
                return
            heal_note = f" after {attempts} self-heal attempt(s)" if attempts else ""
            self.add_thought_trace(
                f"Verification passed for step '{current_step['name']}'{heal_note}.",
                "completed", {"step_id": current_step.get("step_id"), "attempts": attempts}
            )
            print(f"  [VERIFICATION PASSED] {current_step['name']}{heal_note}")

        self.state["steps_completed"] += 1
        self.state["progress"] = int((self.state["steps_completed"] / len(steps)) * 100)
        
        self.add_thought_trace(
            f"Step '{current_step['name']}' completed successfully (Progress: {self.state['progress']}%). Touched files: {', '.join(step_files) if step_files else 'None'}",
            "completed",
            {"step_id": current_step['step_id'], "step_name": current_step['name']}
        )
        
        for f in step_files:
            if f not in self.state["touched_files"]:
                self.state["touched_files"].append(f)
        for t in step_tools:
            if t not in self.state["tools_used"]:
                self.state["tools_used"].append(t)
                
        if self.state["steps_completed"] < len(steps):
            next_step = steps[self.state["steps_completed"]]
            self.state["current_step"] = {
                "step_id": next_step["step_id"],
                "name": next_step["name"],
                "description": next_step["description"]
            }
        else:
            self.finalize_or_await()
            self.state["current_step"] = None
            
        # Check if supervisor updated our status during step execution (e.g. to syncing, pending_termination, or dead)
        disk_state = load_json(self.state_file)
        if disk_state and disk_state.get("status") in ["syncing", "pending_termination", "dead"]:
            self.state["status"] = disk_state["status"]

        try:
            import causal_tracer
            causal_tracer.log_step_execution(
                self.agent_id,
                current_step["step_id"],
                current_step["name"],
                current_step["description"],
                "completed",
                {"progress": self.state["progress"]}
            )
            if self.state["status"] == "completed":
                causal_tracer.log_state_transition(self.agent_id, "exploring", "completed")
        except Exception:
            pass
        save_json(self.state_file, self.state)
        print(f"Step completed. Progress: {self.state['progress']}%")

    def perform_negotiation(self):
        """Finds the active collision record and resolves it via LLM, Rules, or Interactive inputs."""
        collision_file = None
        collision_id = None
        for filename in os.listdir(COLLISIONS_DIR):
            if filename.startswith("collision_") and filename.endswith(".json"):
                parts = filename.replace("collision_", "").replace(".json", "").split("_")
                if self.agent_id in parts:
                    collision_id = filename.replace("collision_", "").replace(".json", "")
                    collision_file = os.path.join(COLLISIONS_DIR, filename)
                    break
                    
        if not collision_file:
            print(f"Error: Paused for syncing but no collision file found for Agent {self.agent_id}.")
            self.state["status"] = "exploring"
            save_json(self.state_file, self.state)
            return
            
        collision = load_json(collision_file)
        if not collision:
            return
            
        if collision["status"] == "resolved":
            print(f"Collision resolved by peer. Reloading status...")
            self.state = load_json(self.state_file)
            return
            
        collision["status"] = "negotiating"
        save_json(collision_file, collision)
        
        agent_a = collision["agent_a"]
        agent_b = collision["agent_b"]
        
        peer_id = agent_b["id"] if agent_a["id"] == self.agent_id else agent_a["id"]
        peer_state_file = os.path.join(AGENTS_DIR, f"agent_{peer_id}.json")
        peer_state = load_json(peer_state_file)
        
        self.add_thought_trace(
            f"Collision detected with Agent {peer_id}. Entering syncing state to negotiate goal overlap.",
            "syncing",
            {"peer_id": peer_id, "collision_id": collision_id}
        )
        
        print("\n" + "="*50)
        print("          NEGOTIATION CONVERSE PROTOCOL")
        print("="*50)
        print(f"Agent A (ID: {agent_a['id']}): Goal: {agent_a['goal']}")
        print(f"  Progress: {agent_a['progress']}% | Current: {agent_a['current_step']['name']}")
        print(f"Agent B (ID: {agent_b['id']}): Goal: {agent_b['goal']}")
        print(f"  Progress: {agent_b['progress']}% | Current: {agent_b['current_step']['name']}")
        print("-"*50)
        
        import judge
        judge_provider, judge_model = judge.select_judge_model(
            getattr(self, "judge_provider", None),
            getattr(self, "judge_model", None),
            self.llm_provider,
            getattr(self, "ollama_model", None) or getattr(self, "gemini_model", None)
        )
        
        result = judge.resolve_collision(collision, judge_provider, judge_model, self.agent_id)
        action = result["action"]
        reason = result["reason"]
        
        self.add_thought_trace(f"Collision resolved by Judge. Action: {action}. Reason: {reason}", "decision")
        
        # Apply resolution
        if action == "kill_a":
            agent_a["status"] = "pending_termination"
            agent_b["status"] = "exploring"
            self.share_knowledge_files(agent_a["id"], agent_b["id"])
            
            # Survivor absorbs loser's files/tools state
            for f in agent_a.get("touched_files", []):
                if f not in agent_b["touched_files"]:
                    agent_b["touched_files"].append(f)
            for t in agent_a.get("tools_used", []):
                if t not in agent_b["tools_used"]:
                    agent_b["tools_used"].append(t)

            # Dynamic Multi-Parent link: agent_b (survivor) inherits agent_a's parents!
            b_parents = agent_b.get("parent_ids") or ([agent_b.get("parent_id")] if agent_b.get("parent_id") else [])
            a_parents = agent_a.get("parent_ids") or ([agent_a.get("parent_id")] if agent_a.get("parent_id") else [])
            for p in a_parents:
                if p and p not in b_parents:
                    b_parents.append(p)
            agent_b["parent_ids"] = b_parents
            if b_parents:
                agent_b["parent_id"] = b_parents[0]
                
            try:
                import causal_tracer
                causal_tracer.log_takeover(collision_id, agent_b["id"], agent_a["id"], reason)
                causal_tracer.log_state_transition(agent_b["id"], "syncing", "exploring")
                causal_tracer.log_state_transition(agent_a["id"], "syncing", "pending_termination")
            except Exception:
                pass
                
        elif action == "kill_b":
            agent_a["status"] = "exploring"
            agent_b["status"] = "pending_termination"
            self.share_knowledge_files(agent_b["id"], agent_a["id"])
            
            # Survivor absorbs loser's files/tools state
            for f in agent_b.get("touched_files", []):
                if f not in agent_a["touched_files"]:
                    agent_a["touched_files"].append(f)
            for t in agent_b.get("tools_used", []):
                if t not in agent_a["tools_used"]:
                    agent_a["tools_used"].append(t)

            # Dynamic Multi-Parent link: agent_a (survivor) inherits agent_b's parents!
            a_parents = agent_a.get("parent_ids") or ([agent_a.get("parent_id")] if agent_a.get("parent_id") else [])
            b_parents = agent_b.get("parent_ids") or ([agent_b.get("parent_id")] if agent_b.get("parent_id") else [])
            for p in b_parents:
                if p and p not in a_parents:
                    a_parents.append(p)
            agent_a["parent_ids"] = a_parents
            if a_parents:
                agent_a["parent_id"] = a_parents[0]
                
            try:
                import causal_tracer
                causal_tracer.log_takeover(collision_id, agent_a["id"], agent_b["id"], reason)
                causal_tracer.log_state_transition(agent_a["id"], "syncing", "exploring")
                causal_tracer.log_state_transition(agent_b["id"], "syncing", "pending_termination")
            except Exception:
                pass
                
        else:  # keep_both
            agent_a["status"] = "exploring"
            agent_b["status"] = "exploring"
            
            # Exchange knowledge by mutually sharing files
            self.share_knowledge_files(agent_a["id"], agent_b["id"])
            self.share_knowledge_files(agent_b["id"], agent_a["id"])
            
            def apply_offset(files, offset_suffix):
                if not offset_suffix:
                    return list(files)
                result = []
                for f in files:
                    base, ext = os.path.splitext(f)
                    result.append(f"{base}_{offset_suffix}{ext}")
                return result

            def review_peer_step(our_step, peer_step, our_id, peer_id, our_offset):
                provider = self.llm_provider
                if not provider:
                    if os.environ.get("GEMINI_API_KEY"):
                        provider = "gemini"
                    elif is_ollama_running():
                        provider = "ollama"
                    else:
                        provider = "rules"
                
                peer_ws = os.path.join(WORKSPACES_DIR, f"agent_{peer_id}")
                peer_files_content = {}
                peer_touched_files = peer_step.get("touched_files", [])
                
                for f in peer_touched_files:
                    f_path = os.path.join(peer_ws, f)
                    if not os.path.exists(f_path):
                        base, ext = os.path.splitext(f)
                        f_path = os.path.join(peer_ws, f"{base}_{our_offset}{ext}" if our_offset else f)
                    if os.path.exists(f_path):
                        try:
                            with open(f_path, 'r') as file_obj:
                                peer_files_content[f] = file_obj.read()
                        except Exception:
                            pass
                
                if provider in ["gemini", "ollama"] and peer_files_content:
                    files_str = "\n".join([f"=== File: {fname} ===\n{content}\n" for fname, content in peer_files_content.items()])
                    prompt = (
                        f"You are Proximity Swarm Agent {our_id}.\n"
                        f"You are evaluating whether you need to execute your next step:\n"
                        f"Step Name: {our_step.get('name')}\n"
                        f"Step Description: {our_step.get('description')}\n\n"
                        f"Another agent (Agent {peer_id}) has already completed the following step:\n"
                        f"Completed Step Name: {peer_step.get('name')}\n"
                        f"Completed Step Description: {peer_step.get('description')}\n\n"
                        f"The peer agent generated/modified these files with the following content:\n"
                        f"{files_str}\n"
                        f"Review if the output files satisfy the goal of your step so that you can safely bypass it (should_bypass: true) "
                        f"or if you still need to execute your step (should_bypass: false).\n\n"
                        f"Respond strictly in JSON with keys:\n"
                        f"1. 'should_bypass' (boolean: true or false)\n"
                        f"2. 'reason' (string explanation of your review decision)\n"
                    )
                    try:
                        if provider == "gemini":
                            res = call_gemini_api(prompt)
                        else:
                            res = call_ollama_api(prompt, model=self.ollama_model)
                        if res and "should_bypass" in res:
                            print(f"  [Step Review] Agent {our_id} reviewed Agent {peer_id}'s step '{peer_step.get('name')}': should_bypass={res['should_bypass']}, Reason: {res.get('reason')}")
                            return res["should_bypass"]
                    except Exception as ex:
                        print(f"  [Step Review Exception] LLM call failed: {ex}")
                
                name_match = our_step["name"] == peer_step["name"]
                touched_intersect = bool(set(apply_offset(our_step.get("touched_files", []), our_offset)) & set(apply_offset(peer_touched_files, our_offset)))
                return name_match or touched_intersect

            # Bypass steps completed by the other agent
            tasks_data = load_json(MOCK_TASKS_FILE)
            if tasks_data and "tasks" in tasks_data:
                a_task_id = agent_a.get("task_id")
                b_task_id = agent_b.get("task_id")
                
                a_steps = tasks_data["tasks"].get(a_task_id, {}).get("steps", []) if a_task_id else []
                b_steps = tasks_data["tasks"].get(b_task_id, {}).get("steps", []) if b_task_id else []
                
                a_offset = agent_a.get("offset_suffix")
                b_offset = agent_b.get("offset_suffix")
                
                # Bypass for Agent B
                b_completed = agent_b["steps_completed"]
                while b_completed < len(b_steps):
                    b_step = b_steps[b_completed]
                    matched = False
                    
                    for i in range(agent_a["steps_completed"]):
                        if i < len(a_steps):
                            a_step = a_steps[i]
                            if review_peer_step(b_step, a_step, agent_b["id"], agent_a["id"], b_offset):
                                matched = True
                                break
                    if matched:
                        print(f"  [Deconfliction Bypass] Agent B ({agent_b['id']}) bypassing peer-reviewed step: '{b_step['name']}'")
                        b_completed += 1
                    else:
                        break
                agent_b["steps_completed"] = b_completed
                agent_b["progress"] = int((b_completed / len(b_steps)) * 100) if b_steps else 0
                if b_completed < len(b_steps):
                    next_step = b_steps[b_completed]
                    agent_b["current_step"] = {
                        "step_id": next_step["step_id"],
                        "name": next_step["name"],
                        "description": next_step["description"]
                    }
                else:
                    agent_b["status"] = "completed"
                    agent_b["current_step"] = None
                
                # Bypass for Agent A
                a_completed = agent_a["steps_completed"]
                while a_completed < len(a_steps):
                    a_step = a_steps[a_completed]
                    matched = False
                    
                    for i in range(agent_b["steps_completed"]):
                        if i < len(b_steps):
                            b_step = b_steps[i]
                            if review_peer_step(a_step, b_step, agent_a["id"], agent_b["id"], a_offset):
                                matched = True
                                break
                    if matched:
                        print(f"  [Deconfliction Bypass] Agent A ({agent_a['id']}) bypassing peer-reviewed step: '{a_step['name']}'")
                        a_completed += 1
                    else:
                        break
                agent_a["steps_completed"] = a_completed
                agent_a["progress"] = int((a_completed / len(a_steps)) * 100) if a_steps else 0
                if a_completed < len(a_steps):
                    next_step = a_steps[a_completed]
                    agent_a["current_step"] = {
                        "step_id": next_step["step_id"],
                        "name": next_step["name"],
                        "description": next_step["description"]
                    }
                else:
                    agent_a["status"] = "completed"
                    agent_a["current_step"] = None

            try:
                import causal_tracer
                causal_tracer.log_state_transition(agent_a["id"], "syncing", "exploring", {"reason": "keep both (complementary)"})
                causal_tracer.log_state_transition(agent_b["id"], "syncing", "exploring", {"reason": "keep both (complementary)"})
            except Exception:
                pass
            
        # Save states
        save_json(os.path.join(AGENTS_DIR, f"agent_{agent_a['id']}.json"), agent_a)
        save_json(os.path.join(AGENTS_DIR, f"agent_{agent_b['id']}.json"), agent_b)
        
        # Write resolved collision data
        collision["status"] = "resolved"
        collision["action_taken"] = action
        collision["reasoning"] = reason
        collision["negotiation_log"].append({
            "timestamp": time.time(),
            "action": action,
            "reason": reason
        })
        save_json(collision_file, collision)
        
        # Load the updated state from disk before writing thought trace
        self.state = load_json(self.state_file) or self.state
        
        self.add_thought_trace(
            f"Collision deconfliction negotiation resolved. Outcome: {action.upper()}. Reason: {reason}",
            "resolved",
            {"action": action, "reason": reason}
        )
        
        print(f"Negotiation Complete. Outcome: {action.upper()}")
        print(f"Reason: {reason}")
        print("="*50 + "\n")

    def share_knowledge_files(self, loser_id, survivor_id):
        """Copies any files created by the losing agent to the survivor's workspace and shared workspace."""
        loser_ws = os.path.join(WORKSPACES_DIR, f"agent_{loser_id}")
        survivor_ws = os.path.join(WORKSPACES_DIR, f"agent_{survivor_id}")
        shared_ws = os.path.join(WORKSPACES_DIR, "shared")
        
        os.makedirs(shared_ws, exist_ok=True)
        
        if os.path.exists(loser_ws):
            print(f"  [State Transfer] Migrating partial files from Agent {loser_id} to Agent {survivor_id} and shared workspace...")
            for root, dirs, files in os.walk(loser_ws):
                for file in files:
                    src = os.path.join(root, file)
                    rel = os.path.relpath(src, loser_ws)
                    
                    # Copy to survivor's workspace
                    dest = os.path.join(survivor_ws, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    try:
                        with open(src, 'r') as f_in:
                            content = f_in.read()
                        with open(dest, 'w') as f_out:
                            f_out.write(content)
                            f_out.write(f"\n# Inherited from Agent {loser_id} during collision resolution.\n")
                    except Exception as e:
                        print(f"    Failed to copy {file} to survivor: {e}")
                        
                    # Copy to shared workspace
                    shared_dest = os.path.join(shared_ws, rel)
                    os.makedirs(os.path.dirname(shared_dest), exist_ok=True)
                    try:
                        with open(src, 'r') as f_in:
                            content = f_in.read()
                        with open(shared_dest, 'w') as f_out:
                            f_out.write(content)
                            f_out.write(f"\n# Deposited by Agent {loser_id} to shared workspace.\n")
                    except Exception as e:
                        print(f"    Failed to copy {file} to shared workspace: {e}")


def main():
    parser = argparse.ArgumentParser(description="Proximity Swarm - Agent Execution Runner")
    parser.add_argument("--agent-id", required=True, help="Unique 3-digit agent ID")
    parser.add_argument("--task-id", help="Task ID from mock_tasks.json to initialize agent with")
    parser.add_argument("--interactive", action="store_true", help="Toggle interactive mode for collision resolutions")
    parser.add_argument("--step-delay", type=float, default=2.0, help="Simulation step delay in seconds")
    parser.add_argument("--steps", type=int, default=10, help="Max number of execution steps to run")
    parser.add_argument("--offset-suffix", help="Filename offset suffix to apply during step execution")
    parser.add_argument("--llm-provider", choices=["gemini", "ollama", "rules"], help="LLM API provider for deconfliction negotiation")
    parser.add_argument("--ollama-model", default="gemma4:latest", help="Ollama model string to query if provider is ollama")
    parser.add_argument("--personality", help="The personality/role assigned to this agent")
    parser.add_argument("--goal", help="The dedicated goal/subtask assigned to this agent")
    parser.add_argument("--sub-swarm-id", help="The sub-swarm functional group ID this agent belongs to")
    parser.add_argument("--graph-mode", choices=["linear", "graph"], default="graph", help="Execution mode")
    args = parser.parse_args()
    
    runner = AgentRunner(
        agent_id=args.agent_id, 
        task_id=args.task_id, 
        interactive=args.interactive,
        step_delay=args.step_delay,
        offset_suffix=args.offset_suffix,
        llm_provider=args.llm_provider,
        ollama_model=args.ollama_model,
        personality=args.personality,
        goal=args.goal,
        sub_swarm_id=args.sub_swarm_id,
        graph_mode=args.graph_mode
    )
    
    print(f"Starting Agent {args.agent_id} runner...")
    for _ in range(args.steps):
        runner.execute_step()
        if runner.state.get("status") in ["completed", "dead"]:
            break
            
    while runner.state.get("status") == "awaiting_child":
        runner.execute_step()

    if runner.state.get("status") == "completed":
        runner.save_memory_episode()


if __name__ == "__main__":
    main()
