#!/usr/bin/env python3
import os
import sys
import json
import time
import urllib.request
import urllib.error
import argparse

STATE_DIR = os.path.join(os.getcwd(), ".proximity_swarm")
AGENTS_DIR = os.path.join(STATE_DIR, "agents")
COLLISIONS_DIR = os.path.join(STATE_DIR, "collisions")
WORKSPACES_DIR = os.path.join(STATE_DIR, "workspaces")
TOMBSTONES_FILE = os.path.join(STATE_DIR, "tombstones.json")
MOCK_TASKS_FILE = os.path.join(os.getcwd(), "mock_tasks.json")


def load_json(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def save_json(filepath, data):
    try:
        with open(filepath, 'w') as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


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
            return res_data.get("response", "").strip()
    except Exception as e:
        print(f"[LLM ERROR] Raw Ollama call failed (Model: {model}): {e}")
        return None


def is_ollama_running():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.0) as response:
            return response.status == 200
    except Exception:
        return False


class AgentRunner:
    def __init__(self, agent_id, task_id=None, interactive=False, step_delay=3.0, offset_suffix=None, llm_provider=None, ollama_model="gemma4:latest", personality=None, goal=None, sub_swarm_id=None):
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
        
        self.state_file = os.path.join(AGENTS_DIR, f"agent_{self.agent_id}.json")
        self.workspace_dir = os.path.join(WORKSPACES_DIR, f"agent_{self.agent_id}")
        
        os.makedirs(AGENTS_DIR, exist_ok=True)
        os.makedirs(WORKSPACES_DIR, exist_ok=True)
        os.makedirs(self.workspace_dir, exist_ok=True)
        
        self.state = self.load_or_init_state()
        self.historical_context = None
        self.load_historical_context()

    def apply_offset_to_files(self, files):
        if not self.offset_suffix:
            return list(files)
        result = []
        for f in files:
            base, ext = os.path.splitext(f)
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
        tombstones = load_json(TOMBSTONES_FILE) or []
        for t in tombstones:
            file_match = any(f in t.get("file_path", "") for f in files)
            tool_match = any(tool == t.get("tool_used", "") for tool in tools)
            if file_match and tool_match:
                return t
        return None

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

        # 2. Progress task step
        task_id = self.state.get("task_id")
        tasks_data = load_json(MOCK_TASKS_FILE)
        if not tasks_data or task_id not in tasks_data["tasks"]:
            print(f"Error: Task data missing for task {task_id}.")
            self.state["status"] = "completed"
            save_json(self.state_file, self.state)
            return
            
        task = tasks_data["tasks"][task_id]
        steps = task["steps"]
        completed_count = self.state["steps_completed"]
        
        if completed_count >= len(steps):
            print(f"Agent {self.agent_id} has completed all steps of Task {task_id}.")
            self.state["status"] = "completed"
            self.state["progress"] = 100
            save_json(self.state_file, self.state)
            self.save_memory_episode()
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
                
        # If final step and no files specified, use fallback answer.md to display output in dashboard
        is_final_step = (self.state["steps_completed"] + 1) >= len(steps)
        if not step_files and is_final_step:
            step_files = ["answer.md"]

        # Simulate execution / Touch files in local sandbox workspace
        for filename in step_files:
            file_path = os.path.join(self.workspace_dir, filename)
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            content = f"# Agent {self.agent_id} completed {current_step['name']} at {time.time()}\n"
            if self.llm_provider == "ollama" and is_ollama_running():
                prompt = ""
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
            tombstones = load_json(TOMBSTONES_FILE) or []
            new_tombstone = {
                "file_path": step_files[0] if step_files else "unknown",
                "tool_used": step_tools[0] if step_tools else "unknown",
                "error_message": error_msg,
                "fix_action": fix_msg,
                "timestamp": time.time()
            }
            tombstones.append(new_tombstone)
            save_json(TOMBSTONES_FILE, tombstones)
            print(f"  [TOMBSTONE REGISTERED] Saved failure context to tombstones.json.")
            
            self.state["status"] = "pending_termination"
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
        
        self.state["steps_completed"] += 1
        self.state["progress"] = int((self.state["steps_completed"] / len(steps)) * 100)
        
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
            self.state["status"] = "completed"
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
        
        print("\n" + "="*50)
        print("          NEGOTIATION CONVERSE PROTOCOL")
        print("="*50)
        print(f"Agent A (ID: {agent_a['id']}): Goal: {agent_a['goal']}")
        print(f"  Progress: {agent_a['progress']}% | Current: {agent_a['current_step']['name']}")
        print(f"Agent B (ID: {agent_b['id']}): Goal: {agent_b['goal']}")
        print(f"  Progress: {agent_b['progress']}% | Current: {agent_b['current_step']['name']}")
        print("-"*50)
        
        action = None
        reason = ""
        
        if self.interactive:
            print("[INTERACTIVE MODE] Select resolution outcome:")
            print(f"  1. Redundant: Propose terminating Agent A ({agent_a['id']}) - Agent B is ahead.")
            print(f"  2. Redundant: Propose terminating Agent B ({agent_b['id']}) - Agent A is ahead.")
            print("  3. Complementary: Keep both alive, share state information and resume.")
            
            while True:
                choice = input("Enter choice (1, 2, or 3): ").strip()
                if choice == "1":
                    action = "kill_a"
                    reason = "User manually proposed Agent A termination."
                    break
                elif choice == "2":
                    action = "kill_b"
                    reason = "User manually proposed Agent B termination."
                    break
                elif choice == "3":
                    action = "keep_both"
                    reason = "User manually marked goals as complementary. Resuming both."
                    break
                else:
                    print("Invalid input. Select 1, 2, or 3.")
        else:
            # Determine LLM provider (Ollama or Gemini or rules)
            provider = self.llm_provider
            
            # Auto-detect defaults if not explicitly set
            if not provider:
                if os.environ.get("GEMINI_API_KEY"):
                    provider = "gemini"
                elif is_ollama_running():
                    provider = "ollama"
                else:
                    provider = "rules"
            
            prompt = (
                f"You are the Swarm Supervisor coordinating two autonomous coding agents:\n"
                f"Agent A: ID={agent_a['id']}, Role={agent_a.get('personality', 'Generalist')}, Goal={agent_a['goal']}, Progress={agent_a['progress']}%, CurrentStep={agent_a['current_step']['description']}\n"
                f"Agent B: ID={agent_b['id']}, Role={agent_b.get('personality', 'Generalist')}, Goal={agent_b['goal']}, Progress={agent_b['progress']}%, CurrentStep={agent_b['current_step']['description']}\n\n"
                f"Evaluate if their goals are redundant (overlapping work on same file/subtask) or complementary.\n"
                f"If redundant, propose terminating the one with less progress. If complementary, keep both.\n"
                f"Respond strictly in JSON with keys 'action' (must be one of 'kill_a', 'kill_b', 'keep_both') and 'reason' (text explanation)."
            )
            
            res = None
            if provider == "gemini":
                print("Invoking Gemini LLM Negotiation engine...")
                res = call_gemini_api(prompt)
            elif provider == "ollama":
                print(f"Invoking Ollama LLM Negotiation engine (Model: {self.ollama_model})...")
                res = call_ollama_api(prompt, model=self.ollama_model)
                
            if res and "action" in res:
                action = res["action"]
                reason = res.get("reason", "LLM determined resolution.")
                print(f"LLM ({provider.upper()}) Decision: {action.upper()}")
                print(f"Reason: {reason}")
            
            # Rule-based fallback if rules were selected or API calls failed
            if not action:
                print("Running local deterministic deconfliction rules...")
                is_redundant = collision["similarity_metrics"]["goal_cosine"] > 0.6
                if is_redundant:
                    if agent_a["progress"] >= agent_b["progress"]:
                        action = "kill_b"
                        reason = f"Redundancy detected. Propose Agent B ({agent_b['id']}) termination."
                    else:
                        action = "kill_a"
                        reason = f"Redundancy detected. Propose Agent A ({agent_a['id']}) termination."
                else:
                    action = "keep_both"
                    reason = "Goals deemed complementary. Resuming both."
                    
        # Apply resolution
        if action == "kill_a":
            agent_a["status"] = "pending_termination"
            agent_b["status"] = "exploring"
            self.share_knowledge_files(agent_a["id"], agent_b["id"])
            
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
        
        print(f"Negotiation Complete. Outcome: {action.upper()}")
        print(f"Reason: {reason}")
        print("="*50 + "\n")
        
        self.state = load_json(self.state_file)

    def share_knowledge_files(self, loser_id, survivor_id):
        """Copies any files created by the losing agent to the survivor's workspace."""
        loser_ws = os.path.join(WORKSPACES_DIR, f"agent_{loser_id}")
        survivor_ws = os.path.join(WORKSPACES_DIR, f"agent_{survivor_id}")
        
        if os.path.exists(loser_ws):
            print(f"  [State Transfer] Migrating partial files from Agent {loser_id} to Agent {survivor_id}...")
            for root, dirs, files in os.walk(loser_ws):
                for file in files:
                    src = os.path.join(root, file)
                    rel = os.path.relpath(src, loser_ws)
                    dest = os.path.join(survivor_ws, rel)
                    os.makedirs(os.path.dirname(dest), exist_ok=True)
                    try:
                        with open(src, 'r') as f_in:
                            content = f_in.read()
                        with open(dest, 'w') as f_out:
                            f_out.write(content)
                            f_out.write(f"# Inherited from Agent {loser_id} during collision resolution.\n")
                    except Exception as e:
                        print(f"    Failed to copy {file}: {e}")


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
        sub_swarm_id=args.sub_swarm_id
    )
    
    print(f"Starting Agent {args.agent_id} runner...")
    for _ in range(args.steps):
        runner.execute_step()
        if runner.state["status"] in ["completed", "dead"]:
            break


if __name__ == "__main__":
    main()
