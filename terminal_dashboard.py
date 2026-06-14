#!/usr/bin/env python3
import os
import sys
import json
import time
import subprocess
import argparse
import urllib.request
import shutil
from datetime import datetime
import threading

# Import Rich components
try:
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.live import Live
    from rich.console import Console
    from rich.text import Text
    from rich.align import Align
    from rich.syntax import Syntax
except ImportError:
    print("Error: The 'rich' library is required to run the terminal dashboard.")
    print("Please install it by running: pip install rich")
    sys.exit(1)

STATE_DIR = os.path.join(os.getcwd(), ".proximity_swarm")
AGENTS_DIR = os.path.join(STATE_DIR, "agents")
COLLISIONS_DIR = os.path.join(STATE_DIR, "collisions")
TOMBSTONES_FILE = os.path.join(STATE_DIR, "tombstones.json")
LOG_FILE = os.path.join(STATE_DIR, "monitor.log")
MOCK_TASKS_FILE = os.path.join(os.getcwd(), "mock_tasks.json")
OLLAMA_MODEL = "gemma4:latest"

predefined_personalities = []
current_view = "combined"
synthesis_cache = {"last_hash": None, "content": None, "is_generating": False}
session_budget = 4

# TUI State Machine variables
TUI_STATE = "MENU"  # "MENU", "DECOMPOSING_MACRO", "BUDGET_CONFIRM", "DESIGNER", "DECOMPOSING_AGENTS", "RUNNING"
TUI_MACRO_GOAL = ""
TUI_RECOMMENDED_CAP = 20000
TUI_DESIGNER_AGENTS = []
TUI_DECOMPOSE_PROGRESS = {
    "current": 0,
    "total": 0,
    "agent_role": "",
    "agent_id": ""
}
TUI_SUPERVISOR_CMD = None
TUI_SUPERVISOR_PROC = None
TUI_ARGS = None

def bg_decompose_macro_goal(query):
    global TUI_STATE, TUI_DESIGNER_AGENTS, TUI_RECOMMENDED_CAP
    try:
        orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")
        os.makedirs(STATE_DIR, exist_ok=True)
        
        initial_swarm = []
        if predefined_personalities:
            for idx, entry in enumerate(predefined_personalities):
                initial_swarm.append({
                    "role": entry["role"],
                    "goal": entry["goal"] or query,
                    "sub_swarm_id": "swarm_001"
                })
            orchestrator_state = {
                "macro_goal": query,
                "sub_swarms": {
                    "swarm_001": {
                        "id": "swarm_001",
                        "goal": query,
                        "role": "Custom Swarm",
                        "dependencies": [],
                        "status": "pending",
                        "agent_ids": []
                    }
                }
            }
            save_json(orchestrator_file, orchestrator_state)
        else:
            write_to_monitor_log(f"No custom agents defined. Decomposing task into sub-swarms for: '{query}'...", "INFO")
            decomposition = decompose_macro_goal(query)
            
            sub_swarms_dict = {}
            for s in decomposition.get("sub_swarms", []):
                sub_swarms_dict[s["id"]] = {
                    "id": s["id"],
                    "goal": s["goal"],
                    "role": s["role"],
                    "dependencies": s.get("dependencies", []),
                    "status": "pending",
                    "agent_ids": []
                }
                initial_swarm.append({
                    "role": s["role"],
                    "goal": s["goal"],
                    "sub_swarm_id": s["id"]
                })
                
            orchestrator_state = {
                "macro_goal": query,
                "sub_swarms": sub_swarms_dict
            }
            save_json(orchestrator_file, orchestrator_state)
            
        TUI_DESIGNER_AGENTS = initial_swarm
        TUI_RECOMMENDED_CAP = recommend_budget_cap(query)
        TUI_STATE = "BUDGET_CONFIRM"
    except Exception as e:
        write_to_monitor_log(f"Error in macro decomposition background thread: {e}", "ERROR")
        TUI_STATE = "MENU"

def bg_decompose_agent_goals():
    global TUI_STATE, TUI_DECOMPOSE_PROGRESS, TUI_SUPERVISOR_CMD
    try:
        now_ts = int(time.time())
        agents_config = []
        total = len(TUI_DESIGNER_AGENTS)
        
        TUI_DECOMPOSE_PROGRESS.update({
            "total": total,
            "current": 0,
            "agent_role": "",
            "agent_id": ""
        })
        
        for idx, entry in enumerate(TUI_DESIGNER_AGENTS):
            agent_role = entry.get("role", "Generalist")
            agent_goal = entry.get("goal") or TUI_MACRO_GOAL
            agent_id = f"{idx+1:03d}"
            agent_sub_swarm = entry.get("sub_swarm_id", "swarm_001")
            
            TUI_DECOMPOSE_PROGRESS.update({
                "current": idx + 1,
                "agent_role": agent_role,
                "agent_id": agent_id
            })
            
            write_to_monitor_log(f"Decomposing goal for Agent {agent_id} ({agent_role}): '{agent_goal}'...", "INFO")
            steps = generate_task_steps(agent_goal)
            if not steps:
                steps = [
                    {
                        "step_id": 1,
                        "name": "General Execution",
                        "description": f"Perform tasks for: {agent_goal}",
                        "touched_files": [f"src/agent_{agent_id}_output.md"],
                        "tools": ["edit_file"]
                    }
                ]
            
            task_id = f"task_dynamic_{now_ts}_{idx}"
            register_dynamic_task(task_id, agent_goal, steps)
            
            agents_config.append({
                "agent_id": agent_id,
                "task_id": task_id,
                "personality": agent_role,
                "goal": agent_goal,
                "sub_swarm_id": agent_sub_swarm
            })
            
        # Update orchestrator.json with final assigned agent IDs
        orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")
        orchestrator_state = load_json(orchestrator_file)
        if orchestrator_state:
            for sid in orchestrator_state["sub_swarms"]:
                orchestrator_state["sub_swarms"][sid]["agent_ids"] = []
            for item in agents_config:
                sid = item["sub_swarm_id"]
                if sid in orchestrator_state["sub_swarms"]:
                    orchestrator_state["sub_swarms"][sid]["agent_ids"].append(item["agent_id"])
            save_json(orchestrator_file, orchestrator_state)
            
        predefined_personalities.clear()
        
        write_to_monitor_log(f"Starting swarm with {len(agents_config)} agents. Initializing TUI dashboard visualization...", "INFO")
        
        # Prepare supervisor subprocess command
        supervisor_cmd = [
            sys.executable, "supervisor.py",
            "--agents-config", json.dumps(agents_config),
            "--llm-provider", "ollama",
            "--step-delay", "1.5"
        ]
        if TUI_ARGS and TUI_ARGS.interactive:
            supervisor_cmd.append("--interactive")
        if session_budget:
            supervisor_cmd.extend(["--budget", str(session_budget)])
            
        synthesis_cache.update({"last_hash": None, "content": None, "is_generating": False})
        TUI_SUPERVISOR_CMD = supervisor_cmd
        TUI_STATE = "RUNNING"
    except Exception as e:
        write_to_monitor_log(f"Error in agent decomposition background thread: {e}", "ERROR")
        TUI_STATE = "MENU"


def compute_swarm_state_hash():
    """Computes a unique string hash based on agent states and workspace file modification times."""
    hash_parts = []
    
    # 1. Add agent status/progress from agent state files
    agents_dir = os.path.join(STATE_DIR, "agents")
    if os.path.exists(agents_dir):
        try:
            for filename in sorted(os.listdir(agents_dir)):
                if filename.endswith(".json"):
                    filepath = os.path.join(agents_dir, filename)
                    try:
                        mtime = os.path.getmtime(filepath)
                        hash_parts.append(f"{filename}:{mtime}")
                    except Exception:
                        pass
        except Exception:
            pass
                    
    # 2. Add workspaces file timestamps
    workspaces_dir = os.path.join(STATE_DIR, "workspaces")
    if os.path.exists(workspaces_dir):
        try:
            for root, dirs, files in os.walk(workspaces_dir):
                for file in sorted(files):
                    if file.endswith((".pyc", ".pyo")) or "__pycache__" in root:
                        continue
                    filepath = os.path.join(root, file)
                    try:
                        mtime = os.path.getmtime(filepath)
                        hash_parts.append(f"{file}:{mtime}")
                    except Exception:
                        pass
        except Exception:
            pass
                    
    import hashlib
    h = hashlib.md5()
    h.update(str(hash_parts).encode('utf-8'))
    return h.hexdigest()


def synthesize_node_llm(node_id, tree, model="gemma4:latest"):
    """Recursively synthesizes the agent workspace content bottom-up using LLM."""
    node = tree[node_id]
    state = node["state"]
    role = state.get("personality", "Generalist")
    goal = state.get("goal", "")
    
    parent_content = get_agent_workspace_content(node_id, raw_if_single=True)
    
    children_ids = sorted(node["children"])
    if not children_ids:
        if not parent_content.strip():
            return f"*(No output files generated by Agent {node_id} yet)*"
            
        prompt = (
            f"You are the Swarm Summarizer. Summarize the following workspace files content for Agent {node_id} "
            f"({role}) working on goal: '{goal}'.\n\n"
            f"Files content:\n{parent_content}\n\n"
            f"Provide a concise, high-quality markdown report detailing their deliverables. "
            f"Do not include any chat greeting, intro, or explaining text outside the markdown content."
        )
        summary = call_ollama_raw(prompt, model)
        if summary and summary.strip() and not summary.startswith("Error"):
            return summary.strip()
        return parent_content
        
    children_syntheses = {}
    for cid in children_ids:
        children_syntheses[cid] = synthesize_node_llm(cid, tree, model)
        
    if len(children_syntheses) == 1:
        combined_children = list(children_syntheses.values())[0]
    else:
        prompt = (
            f"You are the Swarm Combiner. Combine the following sibling agent summaries (who worked on the same level) "
            f"into a single, unified, cohesive markdown report.\n\n"
        )
        for cid, syn in children_syntheses.items():
            cstate = tree[cid]["state"]
            crole = cstate.get("personality", "Generalist")
            cgoal = cstate.get("goal", "")
            prompt += f"--- Agent {cid} ({crole}) Goal: '{cgoal}' ---\n{syn}\n\n"
        prompt += "Respond with only the cohesive merged markdown report. Do not include any explanations outside the report."
        combined_children = call_ollama_raw(prompt, model)
        if not combined_children or not combined_children.strip() or combined_children.startswith("Error"):
            sibling_blocks = []
            for cid, csyn in children_syntheses.items():
                cstate = tree[cid]["state"]
                crole = cstate.get("personality", "Generalist")
                cgoal = cstate.get("goal", "")
                sibling_blocks.append(f"#### Agent {cid} ({crole}): {cgoal}\n\n{csyn}")
            combined_children = "\n\n---\n\n".join(sibling_blocks)
            
    prompt = (
        f"You are the Swarm Combiner. Integrate the following sub-agent outputs/summaries upward into their parent agent's workspace output. "
        f"Parent Agent: ID={node_id}, Role={role}, Goal={goal}\n\n"
        f"Parent Agent's own workspace output:\n{parent_content if parent_content.strip() else '*(Agent was coordinating sub-agents)*'}\n\n"
        f"Sub-agent contributions summary:\n{combined_children}\n\n"
        f"Provide a single cohesive, integrated markdown report that combines them. Do not include any explanations or intro text outside the markdown."
    )
    integrated = call_ollama_raw(prompt, model)
    if integrated and integrated.strip() and not integrated.startswith("Error"):
        return integrated.strip()
        
    result_parts = [f"## Agent {node_id} ({role}): {goal}"]
    if parent_content.strip():
        result_parts.append(parent_content)
    else:
        result_parts.append(f"*(Agent {node_id} is coordinating sub-agents)*")
    result_parts.append(f"### Sub-Agent Contributions to Agent {node_id}")
    result_parts.append(combined_children)
    return "\n\n".join(result_parts)


def bg_generate_synthesis(state_hash):
    """Background thread target to compute LLM synthesis or fallback."""
    global synthesis_cache
    try:
        if is_ollama_running():
            tree = build_agent_tree()
            if tree:
                roots = [aid for aid, node in tree.items() if node["parent_id"] is None]
                roots.sort()
                if not roots:
                    roots = sorted(list(tree.keys()))
                
                if roots:
                    if len(roots) == 1:
                        content = synthesize_node_llm(roots[0], tree, OLLAMA_MODEL)
                    else:
                        root_blocks = []
                        for rid in roots:
                            rsyn = synthesize_node_llm(rid, tree, OLLAMA_MODEL)
                            root_blocks.append(rsyn)
                        content = "# Combined Swarm Main Artifact\n\n" + "\n\n---\n\n".join(root_blocks)
                    
                    synthesis_cache["content"] = content
                    synthesis_cache["last_hash"] = state_hash
                    synthesis_cache["is_generating"] = False
                    return
                    
        synthesis_cache["content"] = generate_combined_synthesis_fallback()
        synthesis_cache["last_hash"] = state_hash
    except Exception as e:
        synthesis_cache["content"] = f"Error generating synthesis: {e}"
        synthesis_cache["last_hash"] = None
    finally:
        synthesis_cache["is_generating"] = False


def build_agent_tree():
    agents_dir = os.path.join(STATE_DIR, "agents")
    if not os.path.exists(agents_dir):
        return {}
        
    tree = {}
    for filename in os.listdir(agents_dir):
        if filename.endswith(".json"):
            filepath = os.path.join(agents_dir, filename)
            data = load_json(filepath)
            if data and "id" in data:
                aid = data["id"]
                pid = data.get("parent_id")
                if pid == "None" or not pid:
                    pid = None
                
                if aid not in tree:
                    tree[aid] = {
                        "id": aid,
                        "parent_id": pid,
                        "children": [],
                        "state": data
                    }
                else:
                    tree[aid]["state"] = data
                    tree[aid]["parent_id"] = pid

    for aid, node in tree.items():
        pid = node["parent_id"]
        if pid and pid in tree:
            if aid not in tree[pid]["children"]:
                tree[pid]["children"].append(aid)
                
    return tree


def get_agent_workspace_content(agent_id, raw_if_single=False):
    agent_ws = os.path.join(STATE_DIR, "workspaces", f"agent_{agent_id}")
    if not os.path.exists(agent_ws):
        return ""
        
    found_files = []
    for root, dirs, files in os.walk(agent_ws):
        for file in files:
            if file.endswith((".pyc", ".pyo")) or "__pycache__" in root:
                continue
            path = os.path.join(root, file)
            found_files.append(path)
            
    if not found_files:
        return ""
        
    found_files.sort()
    
    if raw_if_single and len(found_files) == 1:
        try:
            with open(found_files[0], 'r') as f:
                return f.read()
        except Exception as e:
            return f"Error reading file: {e}"
            
    sections = []
    for filepath in found_files:
        rel_path = os.path.relpath(filepath, agent_ws)
        try:
            with open(filepath, 'r') as f:
                content = f.read()
        except Exception as e:
            content = f"Error reading file: {e}"
            
        ext = os.path.splitext(rel_path)[1].lower()
        if ext == '.py':
            formatted_content = f"```python\n{content}\n```"
        elif ext == '.json':
            formatted_content = f"```json\n{content}\n```"
        elif ext in ['.md', '.txt']:
            formatted_content = content
        else:
            formatted_content = f"```\n{content}\n```"
            
        sections.append(f"### File: `{rel_path}`\n\n{formatted_content}\n")
        
    return "\n".join(sections)


def synthesize_node(node_id, tree, level=0):
    node = tree[node_id]
    state = node["state"]
    role = state.get("personality", "Generalist")
    goal = state.get("goal", "")
    
    parent_content = get_agent_workspace_content(node_id, raw_if_single=True)
    
    children_ids = sorted(node["children"])
    if not children_ids:
        if not parent_content.strip():
            return f"*(No output from Agent {node_id} yet)*"
        return parent_content
        
    children_syntheses = []
    for cid in children_ids:
        csyn = synthesize_node(cid, tree, level + 1)
        children_syntheses.append((cid, csyn))
        
    if len(children_syntheses) == 1:
        children_combined = children_syntheses[0][1]
    else:
        sibling_blocks = []
        for cid, csyn in children_syntheses:
            cstate = tree[cid]["state"]
            crole = cstate.get("personality", "Generalist")
            cgoal = cstate.get("goal", "")
            sibling_blocks.append(
                f"#### Agent {cid} ({crole}): {cgoal}\n\n{csyn}"
            )
        children_combined = "\n\n---\n\n".join(sibling_blocks)
        
    result_parts = []
    header = f"## Agent {node_id} ({role}): {goal}"
    result_parts.append(header)
    
    if parent_content.strip():
        result_parts.append(parent_content)
    else:
        result_parts.append(f"*(Agent {node_id} is coordinating sub-agents)*")
        
    result_parts.append(f"### Sub-Agent Contributions to Agent {node_id}")
    result_parts.append(children_combined)
    
    return "\n\n".join(result_parts)


def generate_combined_synthesis_fallback():
    tree = build_agent_tree()
    if not tree:
        return "No agent states found. Execute a task to start."
        
    roots = [aid for aid, node in tree.items() if node["parent_id"] is None]
    roots.sort()
    
    if not roots:
        roots = sorted(list(tree.keys()))
        
    if not roots:
        return "No agents found to synthesize."
        
    if len(roots) == 1:
        return synthesize_node(roots[0], tree, 0)
        
    root_blocks = []
    for rid in roots:
        rsyn = synthesize_node(rid, tree, 0)
        root_blocks.append(rsyn)
        
    return "# Combined Swarm Main Artifact\n\n" + "\n\n---\n\n".join(root_blocks)


def generate_combined_synthesis():
    global synthesis_cache
    
    current_hash = compute_swarm_state_hash()
    
    if current_hash != synthesis_cache["last_hash"]:
        if not synthesis_cache["is_generating"]:
            synthesis_cache["is_generating"] = True
            threading.Thread(target=bg_generate_synthesis, args=(current_hash,), daemon=True).start()
            
    if synthesis_cache["is_generating"] and not synthesis_cache["content"]:
        return "⏳ [bold yellow]Generating LLM hierarchical synthesis...[/bold yellow]\n*(Running bottom-up recursive model calls via Ollama. Please wait...)*"
        
    if synthesis_cache["content"]:
        return synthesis_cache["content"]
        
    return "No agent outputs generated yet."


console = Console()


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



def purge_artifacts(target=None):
    """Wipes the selected/all .proximity_swarm state artifacts and optionally dynamic tasks."""
    if target is None or target.strip().lower() == "all":
        if os.path.exists(STATE_DIR):
            try:
                shutil.rmtree(STATE_DIR)
                os.makedirs(STATE_DIR, exist_ok=True)
            except Exception as e:
                print(f"[-] Error wiping state directory: {e}")
                
        # Reset tombstones.json
        try:
            os.makedirs(os.path.dirname(TOMBSTONES_FILE), exist_ok=True)
            with open(TOMBSTONES_FILE, 'w') as f:
                json.dump([], f, indent=2)
        except Exception as e:
            print(f"[-] Error resetting tombstones: {e}")

        # Purge dynamic tasks from mock_tasks.json to keep it clean
        if os.path.exists(MOCK_TASKS_FILE):
            try:
                with open(MOCK_TASKS_FILE, 'r') as f:
                    data = json.load(f)
                if "tasks" in data:
                    original_tasks = {k: v for k, v in data["tasks"].items() if not k.startswith("task_dynamic_")}
                    data["tasks"] = original_tasks
                with open(MOCK_TASKS_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"[-] Error filtering mock_tasks.json: {e}")
                
        # Clean memory database too
        try:
            import memory_store
            memory_store.clean_memories()
            print("[+] Successfully purged episodic memory database.")
        except Exception as e:
            pass

        # Clean trace database too
        try:
            import causal_tracer
            if os.path.exists(causal_tracer.DB_PATH):
                os.remove(causal_tracer.DB_PATH)
            md_path = os.path.join(STATE_DIR, "causal_graph.md")
            if os.path.exists(md_path):
                os.remove(md_path)
            print("[+] Successfully purged causal trace database.")
        except Exception:
            pass
        return

    # Specific targets
    t_lower = target.strip().lower()
    if t_lower == "logs":
        if os.path.exists(LOG_FILE):
            try:
                os.remove(LOG_FILE)
                print(f"[+] Deleted log file: {LOG_FILE}")
            except Exception as e:
                print(f"[-] Error deleting log file: {e}")
        else:
            print("[-] No log file found to delete.")
            
    elif t_lower == "workspaces":
        workspaces_dir = os.path.join(STATE_DIR, "workspaces")
        if os.path.exists(workspaces_dir):
            try:
                shutil.rmtree(workspaces_dir)
                os.makedirs(workspaces_dir, exist_ok=True)
                print(f"[+] Cleared workspaces directory: {workspaces_dir}")
            except Exception as e:
                print(f"[-] Error clearing workspaces directory: {e}")
        else:
            print("[-] No workspaces directory found to clear.")
            
    elif t_lower == "collisions":
        if os.path.exists(COLLISIONS_DIR):
            try:
                shutil.rmtree(COLLISIONS_DIR)
                os.makedirs(COLLISIONS_DIR, exist_ok=True)
                print(f"[+] Cleared collisions directory: {COLLISIONS_DIR}")
            except Exception as e:
                print(f"[-] Error clearing collisions directory: {e}")
        else:
            print("[-] No collisions directory found to clear.")
            
    elif t_lower == "tombstones":
        try:
            os.makedirs(os.path.dirname(TOMBSTONES_FILE), exist_ok=True)
            with open(TOMBSTONES_FILE, 'w') as f:
                json.dump([], f, indent=2)
            print(f"[+] Reset tombstones database: {TOMBSTONES_FILE}")
        except Exception as e:
            print(f"[-] Error resetting tombstones: {e}")
            
    elif t_lower == "tasks":
        if os.path.exists(MOCK_TASKS_FILE):
            try:
                with open(MOCK_TASKS_FILE, 'r') as f:
                    data = json.load(f)
                if "tasks" in data:
                    original_tasks = {k: v for k, v in data["tasks"].items() if not k.startswith("task_dynamic_")}
                    data["tasks"] = original_tasks
                with open(MOCK_TASKS_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
                print(f"[+] Purged dynamic tasks from mock tasks database.")
            except Exception as e:
                print(f"[-] Error filtering mock_tasks.json: {e}")
        else:
            print("[-] No mock tasks file found to update.")
            
    elif t_lower in ["memory", "history"]:
        try:
            import memory_store
            memory_store.clean_memories()
            print("[+] Successfully purged episodic memory database.")
        except Exception as e:
            print(f"[-] Error purging episodic memory: {e}")
            
    elif t_lower in ["trace", "traces", "causal"]:
        try:
            import causal_tracer
            if os.path.exists(causal_tracer.DB_PATH):
                os.remove(causal_tracer.DB_PATH)
            md_path = os.path.join(STATE_DIR, "causal_graph.md")
            if os.path.exists(md_path):
                os.remove(md_path)
            print("[+] Successfully purged causal trace database.")
        except Exception as e:
            print(f"[-] Error purging causal trace: {e}")
            
    else:
        # Check recursive file matches under workspaces directory
        workspaces_dir = os.path.join(STATE_DIR, "workspaces")
        if not os.path.exists(workspaces_dir):
            print("[-] No workspaces directory found.")
            return
            
        normalized_target = target.replace('/', os.sep).replace('\\', os.sep)
        deleted_files = []
        for root, dirs, files in os.walk(workspaces_dir):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, workspaces_dir)
                
                # Check for matches (relative path, basename, or sub-path)
                if (rel_path == normalized_target or 
                    file == normalized_target or 
                    rel_path.endswith(os.sep + normalized_target)):
                    try:
                        os.remove(file_path)
                        deleted_files.append(rel_path)
                    except Exception as e:
                        print(f"[-] Error deleting file {rel_path}: {e}")
                        
        if deleted_files:
            for df in deleted_files:
                print(f"[+] Deleted file: {df}")
        else:
            print(f"[-] No file matching '{target}' was found in workspaces.")


def get_swarm_summary():
    """Calculates counts of agents in each state."""
    summary = {"total": 0, "exploring": 0, "syncing": 0, "pending_termination": 0, "dead": 0, "completed": 0}
    if not os.path.exists(AGENTS_DIR):
        return summary
        
    for filename in os.listdir(AGENTS_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(AGENTS_DIR, filename)
            data = load_json(filepath)
            if data:
                summary["total"] += 1
                status = data.get("status", "exploring")
                if status in summary:
                    summary[status] += 1
    return summary


def make_header_panel():
    """Renders the dashboard header panel with clock and swarm stats."""
    summary = get_swarm_summary()
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    header_text = Text()
    header_text.append(" PROXIMITY SWARM V2 ", style="bold white on blue")
    header_text.append("  |  ", style="dim white")
    header_text.append(f"Time: {time_str}", style="cyan")
    header_text.append("  |  ", style="dim white")
    header_text.append(f"Total Agents: {summary['total']}  ", style="bold white")
    header_text.append(f"Exploring: {summary['exploring']}  ", style="bold green")
    header_text.append(f"Syncing: {summary['syncing']}  ", style="bold yellow")
    header_text.append(f"Pending Kill: {summary['pending_termination']}  ", style="bold magenta")
    header_text.append(f"Dead: {summary['dead']}  ", style="bold red")
    header_text.append(f"Completed: {summary['completed']}", style="bold blue")
    
    return Panel(Align.center(header_text), border_style="blue")


def make_agents_table():
    """Renders a table showing states and progress of all agents."""
    if TUI_STATE in ["DESIGNER", "DECOMPOSING_AGENTS"]:
        return make_designer_agents_table(TUI_DESIGNER_AGENTS)
    table = Table(title="Agent Swarm Status", expand=True)
    table.add_column("ID", justify="center", style="bold white", width=6)
    table.add_column("Parent", justify="center", style="dim white", width=8)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Goal / Sub-task", justify="left")
    table.add_column("Progress", justify="center", width=12)
    table.add_column("Touched Files", justify="left", style="dim cyan")
    
    has_agents = False
    if os.path.exists(AGENTS_DIR):
        filenames = sorted(os.listdir(AGENTS_DIR))
        for filename in filenames:
            if filename.endswith(".json"):
                data = load_json(os.path.join(AGENTS_DIR, filename))
                if not data:
                    continue
                has_agents = True
                    
                status = data.get("status", "exploring")
                if status == "exploring":
                    status_styled = Text(status.upper(), style="bold green")
                elif status == "syncing":
                    status_styled = Text(status.upper(), style="bold yellow")
                elif status == "pending_termination":
                    status_styled = Text("PENDING KILL", style="bold magenta")
                elif status == "dead":
                    status_styled = Text(status.upper(), style="bold red dim")
                elif status == "completed":
                    status_styled = Text(status.upper(), style="bold blue")
                else:
                    status_styled = Text(status.upper())
                    
                prog = data.get("progress", 0)
                filled = int(prog / 10)
                bar = "█" * filled + "░" * (10 - filled)
                progress_styled = f"{bar} {prog}%"
                
                files = ", ".join(data.get("touched_files", []))
                if len(files) > 30:
                    files = files[:27] + "..."
                
                goal_prefix = f"[{data.get('personality', 'Generalist')}] "
                full_goal = goal_prefix + data.get("goal", "")
                if len(full_goal) > 60:
                    full_goal = full_goal[:57] + "..."
                    
                table.add_row(
                    data.get("id"),
                    str(data.get("parent_id") or "None"),
                    status_styled,
                    full_goal,
                    progress_styled,
                    files
                )
                
    if not has_agents and predefined_personalities:
        # Render the custom predefined roles configuration UI!
        config_table = Table(title="Custom Swarm Configuration (Pending Query)", expand=True)
        config_table.add_column("Agent #", justify="center", style="bold white", width=10)
        config_table.add_column("Role / Personality", justify="left", style="cyan", width=25)
        config_table.add_column("Dedicated Goal / Focus Area", justify="left", style="white")
        config_table.add_column("Status", justify="center", style="green", width=20)
        
        for idx, entry in enumerate(predefined_personalities):
            config_table.add_row(
                f"Agent {idx+1:03d}",
                entry.get("role", "Generalist"),
                entry.get("goal") or "Inherits overall task goal",
                "Ready to Initialize"
            )
        return Panel(config_table, border_style="yellow")

    return Panel(table, border_style="green")


def make_output_panel():
    """Renders either the combined hierarchical synthesis or a specific agent's workspace files."""
    if TUI_STATE == "DECOMPOSING_MACRO":
        return Panel(Align.center(Text(f"\n\n\n⏳ Decomposing macro task into sub-swarms via LLM...\n\nTask: '{TUI_MACRO_GOAL}'\n\nThis may take up to 10-15 seconds. Please wait...", style="bold yellow")), title="Macro Goal Decomposition", border_style="yellow")
    elif TUI_STATE == "BUDGET_CONFIRM":
        return Panel(Text(f"\n🛰️  SWARM BUDGET CAP CONFIGURATION\n\nOverall Task: '{TUI_MACRO_GOAL}'\n\nRecommended Active Agent Budget Cap: {TUI_RECOMMENDED_CAP}\n\nThis cap restricts the number of concurrently active agents exploring options.\nIf active count exceeds the cap, warning and productivity rankings will trigger.\n\nType 'y' or press enter in the console below to confirm the recommended cap,\nor enter a custom integer.", style="white"), title="Swarm Budget Cap Configuration", border_style="yellow")
    elif TUI_STATE == "DESIGNER":
        return make_designer_center_panel(TUI_MACRO_GOAL)
    elif TUI_STATE == "DECOMPOSING_AGENTS":
        return Panel(Align.center(Text(f"\n\n\n⏳ Decomposing agent goals & registering tasks...\n\nDecomposing Agent {TUI_DECOMPOSE_PROGRESS['agent_id']} ({TUI_DECOMPOSE_PROGRESS['agent_role']}): {TUI_DECOMPOSE_PROGRESS['current']}/{TUI_DECOMPOSE_PROGRESS['total']}\n\nPlease wait...", style="bold yellow")), title="Agent Goals Decomposition", border_style="yellow")
        
    if current_view == "help":
        help_table = Table(title="Interactive Swarm Terminal CLI Commands", show_lines=True, expand=True)
        help_table.add_column("Command", style="bold green", width=25)
        help_table.add_column("Description", style="white")
        help_table.add_row("/help", "Show this help view in the main window.")
        help_table.add_row("/add-agent <role> : <goal>", "Predefine custom agent role and sub-goal for the swarm.")
        help_table.add_row("/view <combined/id/memory/help>", "Switch between Combined tree synthesis, a specific Agent's files, episodic memory database, or help menu.")
        help_table.add_row("/clean [target]", "Clean specific files/folders. Target can be: logs, workspaces, collisions, tombstones, tasks, memory, all.")
        help_table.add_row("/memory", "Display the sqlite episodic memory database of past runs.")
        help_table.add_row("/trace <agent_id>", "Display visual Mermaid flowchart and chronological event timeline for the agent.")
        help_table.add_row("/budget <n>", "Set output token budget cap limit dynamically.")
        help_table.add_row("/prune <agent_id>", "Manually terminate a leaf agent unit and register its tombstone.")
        help_table.add_row("/approve <agent_id>", "Approve a pending child agent spawn request.")
        help_table.add_row("/reject <agent_id>", "Reject a pending child agent spawn request.")
        help_table.add_row("/resolve <agent_id> <1|2|3>", "Resolve a pending agent blocker: 1=Workaround, 2=Bypass, 3=Kill.")
        help_table.add_row("/exit", "Exit the TUI Dashboard.")
        return Panel(help_table, title="Help & Commands Reference", border_style="cyan")
    
    elif current_view == "memory":
        rows = []
        try:
            import memory_store
            conn = memory_store.get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT id, goal, role, status, reflection, created_at FROM episodic_memories ORDER BY created_at DESC")
            rows = cursor.fetchall()
            conn.close()
        except Exception:
            pass
            
        mem_table = Table(title="Historical Swarm Episodic Memory Archives", show_lines=True, expand=True)
        mem_table.add_column("ID", justify="center", style="bold white", width=6)
        mem_table.add_column("Goal", style="cyan")
        mem_table.add_column("Role", style="green")
        mem_table.add_column("Status", justify="center")
        mem_table.add_column("Reflection", style="magenta")
        mem_table.add_column("Date", justify="center")
        
        for r in rows:
            status_colored = f"[bold green]{r['status']}[/bold green]" if r['status'] == 'completed' else f"[bold red]{r['status']}[/bold red]"
            mem_table.add_row(
                str(r["id"]),
                r["goal"],
                r["role"] or "",
                status_colored,
                r["reflection"] or "",
                r["created_at"]
            )
        return Panel(mem_table, title="Episodic Memory Database", border_style="cyan")

    elif current_view == "combined":
        content = generate_combined_synthesis()
        # Truncate content to avoid terminal overflow
        lines = content.splitlines()
        if len(lines) > 40:
            content_displayed = "\n".join(lines[:40]) + "\n\n... [Truncated due to length] ..."
        else:
            content_displayed = content
            
        display_element = Syntax(content_displayed, "markdown", theme="monokai")
        return Panel(
            display_element,
            title="Swarm Output / Answer Viewer (View: Combined Hierarchy | Type '/view <id>' to toggle)",
            border_style="cyan"
        )
    elif current_view.startswith("trace_"):
        agent_id = current_view.replace("trace_", "")
        import causal_tracer
        mermaid_text = causal_tracer.generate_mermaid_graph(agent_id)
        
        conn = causal_tracer.get_db_connection()
        try:
            events = conn.execute("""
                SELECT source, target, type, timestamp, details FROM trace_edges 
                WHERE source = ? OR target = ?
                ORDER BY timestamp ASC
            """, (f"agent_{agent_id}", f"agent_{agent_id}")).fetchall()
        except Exception:
            events = []
        finally:
            conn.close()
            
        timeline_lines = []
        for ev in events:
            t_str = time.strftime("%H:%M:%S", time.localtime(ev["timestamp"]))
            details = json.loads(ev["details"]) if ev["details"] else {}
            etype = ev["type"]
            
            if etype == "spawn":
                if ev["target"] == f"agent_{agent_id}":
                    parent_part = ev["source"].replace("agent_", "")
                    timeline_lines.append(f"[{t_str}] 🚀 Spawned by Parent Agent {parent_part}")
                else:
                    child_part = ev["target"].replace("agent_", "")
                    timeline_lines.append(f"[{t_str}] 🚀 Spawned Child Agent {child_part}")
            elif etype == "state_transition":
                timeline_lines.append(f"[{t_str}] 🔄 State Transition: {details.get('old_status')} -> {details.get('new_status')}")
            elif etype == "step_exec":
                timeline_lines.append(f"[{t_str}] 📝 Step: {details.get('step_name')} ({details.get('status')})")
            elif etype == "collision_entry":
                timeline_lines.append(f"[{t_str}] ⚠️ Collision detected with peer")
            elif etype == "takeover_survivor":
                timeline_lines.append(f"[{t_str}] ⚔️ Collision negotiation: SURVIVOR of takeover")
            elif etype == "takeover_loser":
                timeline_lines.append(f"[{t_str}] 💀 Collision negotiation: TERMINATED by takeover")
            else:
                timeline_lines.append(f"[{t_str}] Edge: {etype}")
                
        timeline_text = "\n".join(timeline_lines)
        content = (
            f"# Causal Trace Lineage: Agent {agent_id}\n\n"
            f"### 📊 Flowchart (Mermaid syntax)\n"
            f"```mermaid\n"
            f"{mermaid_text}\n"
            f"```\n\n"
            f"### 🕒 Chronological Timeline of Events\n"
            f"{timeline_text or '*(No events logged for this agent yet)*'}"
        )
        
        display_element = Syntax(content, "markdown", theme="monokai")
        return Panel(
            display_element,
            title=f"Swarm Output / Answer Viewer (View: Trace Agent {agent_id} | Type '/view combined' to return)",
            border_style="cyan"
        )
    else:
        tree = build_agent_tree()
        if current_view not in tree:
            valid_ids = sorted(list(tree.keys()))
            valid_str = f"Valid IDs: {', '.join(valid_ids)}" if valid_ids else "No agents active yet."
            return Panel(
                Align.center(Text(f"Agent '{current_view}' not found in active swarm.\n{valid_str}", style="dim yellow")),
                title="Swarm Output / Answer Viewer (View: Error)",
                border_style="cyan"
            )
            
        content = get_agent_workspace_content(current_view, raw_if_single=False)
        if not content.strip():
            content_displayed = f"*(No output files generated by Agent {current_view} yet)*"
        else:
            lines = content.splitlines()
            if len(lines) > 40:
                content_displayed = "\n".join(lines[:40]) + "\n\n... [Truncated due to length] ..."
            else:
                content_displayed = content
                
        display_element = Syntax(content_displayed, "markdown", theme="monokai")
        return Panel(
            display_element,
            title=f"Swarm Output / Answer Viewer (View: Agent {current_view} | Type '/view combined' to return)",
            border_style="cyan"
        )


def make_collisions_panel():
    """Renders active and resolved collisions/negotiation logs."""
    table = Table(title="Collision & Negotiation Log", expand=True)
    table.add_column("Collision ID", justify="center", style="bold white", width=15)
    table.add_column("Distance", justify="center", width=10)
    table.add_column("Status", justify="center", width=15)
    table.add_column("Action Taken", justify="center")
    table.add_column("Reasoning / Details", justify="left")
    
    if os.path.exists(COLLISIONS_DIR):
        filenames = sorted(os.listdir(COLLISIONS_DIR))
        for filename in filenames:
            if filename.endswith(".json"):
                data = load_json(os.path.join(COLLISIONS_DIR, filename))
                if not data:
                    continue
                    
                status = data.get("status", "pending")
                status_styled = Text(status.upper(), style="bold yellow" if status != "resolved" else "bold blue")
                
                action = data.get("action_taken", "None")
                if action == "kill_b" or action == "kill_a":
                    action_styled = Text(action.upper(), style="bold red")
                elif action == "keep_both":
                    action_styled = Text(action.upper(), style="bold green")
                else:
                    action_styled = Text(action.upper())
                    
                table.add_row(
                    data.get("collision_id"),
                    f"{data.get('distance', 0.0):.3f}",
                    status_styled,
                    action_styled,
                    data.get("reasoning", "")[:50] + ("..." if len(data.get("reasoning", "")) > 50 else "")
                )
    return Panel(table, border_style="magenta")


def make_tombstones_panel():
    """Renders the list of registered compiler and execution blockers (tombstones)."""
    table = Table(title="Tombstones Blocker Database", expand=True)
    table.add_column("File Path", style="cyan", width=20)
    table.add_column("Tool", style="bold white", width=8)
    table.add_column("Error Message Signature", style="red")
    table.add_column("Suggested Workaround / Patch Action", style="bold green")
    
    tombstones = load_json(TOMBSTONES_FILE) or []
    for t in tombstones:
        table.add_row(
            t.get("file_path", "unknown"),
            t.get("tool_used", "unknown"),
            t.get("error_message", "unknown")[:50] + ("..." if len(t.get("error_message", "")) > 50 else ""),
            t.get("fix_action", "unknown")
        )
    return Panel(table, border_style="red")


def recommend_budget_cap(query):
    """Query Ollama to recommend a budget cap based on task complexity."""
    if not is_ollama_running():
        return 20000
        
    prompt = (
        f"You are the Swarm Architect. Analyze the following macro task query:\n"
        f"Query: '{query}'\n\n"
        f"Based on the complexity and scope of this task, recommend an active leaf agent output token budget cap limit (integer limit, recommended range 5000 to 50000 tokens).\n"
        f"Return strictly a JSON object with a single key 'recommended_cap' (integer).\n"
        f"Do not include markdown code fences or explanations outside the JSON."
    )
    res_text = call_ollama(prompt)
    if res_text:
        try:
            cleaned = extract_json(res_text)
            data = json.loads(cleaned)
            if "recommended_cap" in data:
                return int(data["recommended_cap"])
        except Exception:
            pass
    return 20000


def make_budget_alert_panel(prompt_state=None):
    """Renders the swarm budget alert and pending decisions panel."""
    if TUI_STATE in ["DESIGNER", "DECOMPOSING_MACRO", "BUDGET_CONFIRM", "DECOMPOSING_AGENTS"]:
        return Panel(Text("\nAlerts panel inactive during configuration.", style="dim white"), title="Alerts & Pending Decisions (Inactive)", border_style="dim white")

    if prompt_state and prompt_state.get("mode"):
        mode = prompt_state["mode"]
        aid = prompt_state["agent_id"]
        content = Text()
        if mode == "spawn":
            req = prompt_state["spawn_req"]
            content.append("🛰️  PENDING SPAWN APPROVAL\n", style="bold yellow")
            content.append(f"   Agent ID:       {aid}\n", style="bold cyan")
            content.append(f"   Goal/Sub-task:  {req.get('goal')}\n", style="white")
            content.append(f"   Reason:         {req.get('reason', 'No reason specified')}\n", style="white")
            content.append(f"   Initial Files:  {', '.join(req.get('initial_files', []))}\n", style="white")
            content.append("\nType 'y' (approve) or 'n' (reject) in the terminal,", style="italic dim white")
            content.append(f"\nor run: /approve {aid} or /reject {aid}", style="bold green")
            return Panel(content, title="Action Required", border_style="yellow")
        elif mode in ["blocker_choice", "blocker_workaround"]:
            blk = prompt_state["blocker_details"]
            content.append("⚠️  SUPERVISOR BLOCKER REVIEW MODE\n", style="bold red")
            content.append(f"   Agent ID:       {aid}\n", style="bold cyan")
            content.append(f"   Blocked File:   {blk.get('file_path')}\n", style="white")
            content.append(f"   Blocked Tool:   {blk.get('tool_used')}\n", style="white")
            content.append(f"   Error Message:  {blk.get('error_message')}\n", style="yellow")
            if mode == "blocker_choice":
                content.append("\n   Resolution Options:\n", style="bold white")
                content.append("     1. Provide manual workaround\n", style="white")
                content.append("     2. Override and bypass step\n", style="white")
                content.append("     3. Kill the agent\n", style="white")
                content.append("\nEnter 1, 2, or 3 in the terminal at the bottom,", style="italic dim white")
                content.append(f"\nor run: /resolve {aid} <1|2|3>", style="bold green")
            else:
                content.append("\nEnter manual workaround details in the terminal at the bottom.", style="italic dim white")
            return Panel(content, title="Action Required", border_style="red")

    alert_file = os.path.join(STATE_DIR, "budget_alert.json")
    
    pending_spawns = []
    pending_blockers = []
    if os.path.exists(AGENTS_DIR):
        for filename in os.listdir(AGENTS_DIR):
            if filename.endswith(".json"):
                try:
                    with open(os.path.join(AGENTS_DIR, filename), 'r') as f:
                        data = json.load(f)
                    aid = data.get("id")
                    if data.get("spawn_request", {}).get("status") == "pending":
                        pending_spawns.append((aid, data["spawn_request"].get("goal"), data["spawn_request"].get("reason", "Accelerate sub-task execution.")))
                    if data.get("status") == "pending_termination" and data.get("blocker_details"):
                        pending_blockers.append((aid, data["blocker_details"]))
                except Exception:
                    pass

    # Read budget alert details
    budget_exceeded = False
    active_count = 0
    budget_limit = 0
    candidates = []
    if os.path.exists(alert_file):
        try:
            with open(alert_file, 'r') as f:
                alert_data = json.load(f)
            budget_exceeded = alert_data.get("budget_exceeded", False)
            active_count = alert_data.get("active_count", 0)
            budget_limit = alert_data.get("budget_limit", 0)
            candidates = alert_data.get("candidates", [])
        except Exception:
            pass

    content = Text()
    
    # 1. Render Swarm Budget Status
    if budget_exceeded:
        content.append("⚠️  BUDGET ALERT: Output Token Limit Exceeded!\n", style="bold red")
        content.append(f"   Max Leaf Output Tokens: {active_count}  |  Budget Cap: {budget_limit}\n", style="yellow")
        content.append("   Ranked Leaf Pruning Candidates (Least to Most Productive):\n", style="bold white")
        for idx, c in enumerate(candidates):
            content.append(f"     [{idx+1}] Agent {c['id']}: ", style="bold cyan")
            content.append(f"{c.get('reason', 'No explanation')}\n", style="white")
    else:
        # Load actual active leaf max output tokens
        max_leaf_tokens_real = 0
        if os.path.exists(AGENTS_DIR):
            active_agents = []
            for filename in os.listdir(AGENTS_DIR):
                if filename.endswith(".json"):
                    try:
                        with open(os.path.join(AGENTS_DIR, filename), 'r') as f:
                            data = json.load(f)
                        if data.get("status") in ["exploring", "syncing", "pending_termination"]:
                            active_agents.append(data)
                    except Exception:
                        pass
            parent_ids = {a.get("parent_id") for a in active_agents if a.get("parent_id")}
            leaf_agents = [a for a in active_agents if a["id"] not in parent_ids]
            if leaf_agents:
                max_leaf_tokens_real = max(a.get("output_tokens", 0) for a in leaf_agents)
                
        # Try to read session budget limit
        global session_budget
        limit_val = session_budget
        orc_file = os.path.join(STATE_DIR, "orchestrator.json")
        if os.path.exists(orc_file):
            try:
                with open(orc_file, 'r') as f_orc:
                    orc_state = json.load(f_orc)
                    if "budget_limit" in orc_state:
                        limit_val = int(orc_state["budget_limit"])
            except Exception:
                pass
        content.append("✅  BUDGET STATUS: Swarm within bounds.\n", style="bold green")
        content.append(f"   Max Leaf Output Tokens: {max_leaf_tokens_real}  |  Budget Cap: {limit_val}\n", style="dim white")

    # 2. Render Pending Actions
    if pending_spawns or pending_blockers:
        content.append("\n⚡  PENDING INTERACTIVE DECISIONS:\n", style="bold yellow")
        for aid, goal, reason in pending_spawns:
            content.append(f"   • Agent {aid}: ", style="bold cyan")
            content.append(f"Pending Spawn Approval for goal '{goal}'.\n", style="white")
            content.append(f"     Reason: '{reason}'\n", style="dim white")
            content.append(f"     Run Command: ", style="dim green")
            content.append(f"/approve {aid}", style="bold green")
            content.append(" or ")
            content.append(f"/reject {aid}\n", style="bold red")
        for aid, blk in pending_blockers:
            content.append(f"   • Agent {aid}: ", style="bold red")
            content.append(f"Blocked on file '{blk.get('file_path')}' using tool '{blk.get('tool_used')}'\n", style="white")
            content.append(f"     Error: {blk.get('error_message')}\n", style="yellow")
            content.append(f"     Run Command: ", style="dim green")
            content.append(f"/resolve {aid} 1", style="bold green")
            content.append(" (Workaround), ")
            content.append(f"/resolve {aid} 2", style="bold green")
            content.append(" (Bypass), or ")
            content.append(f"/resolve {aid} 3", style="bold red")
            content.append(" (Kill)\n")
    else:
        content.append("\n💤  No interactive decisions pending.", style="dim white")

    return Panel(content, title="Alerts & Pending Decisions", border_style="yellow" if (budget_exceeded or pending_spawns or pending_blockers) else "dim white")


def handle_dashboard_pruning(agent_id):
    """Checks restrictions, kills target leaf agent, and registers a detailed pruned tombstone."""
    agent_file = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    if not os.path.exists(agent_file):
        return False, f"Agent {agent_id} file not found."
    
    try:
        with open(agent_file, 'r') as f:
            agent_state = json.load(f)
    except Exception as e:
        return False, f"Failed to load Agent {agent_id} state: {e}"
        
    status = agent_state.get("status")
    if status in ["completed", "dead"]:
        return False, f"Agent {agent_id} is already in state: {status}."
        
    # Check if leaf agent (no other active agent lists this agent as parent)
    active_child_found = False
    if os.path.exists(AGENTS_DIR):
        for filename in os.listdir(AGENTS_DIR):
            if filename.endswith(".json") and filename != f"agent_{agent_id}.json":
                try:
                    filepath = os.path.join(AGENTS_DIR, filename)
                    with open(filepath, 'r') as f:
                        data = json.load(f)
                    if data.get("status") in ["exploring", "syncing", "pending_termination"]:
                        parents = data.get("parent_ids") or ([data.get("parent_id")] if data.get("parent_id") else [])
                        if agent_id in parents:
                            active_child_found = True
                            break
                except Exception:
                    pass
                    
    if active_child_found:
        return False, f"Agent {agent_id} cannot be pruned: it is not a leaf agent (active child agents depend on it)."
        
    # Prune the agent: set status to dead
    agent_state["status"] = "dead"
    save_json(agent_file, agent_state)
    
    # Write details to tombstones.json
    tombstone_file = os.path.join(STATE_DIR, "tombstones.json")
    tombstones = load_json(tombstone_file) or []
    
    # Get explanation from budget_alert.json if available
    explanation = "Pruned by user due to low productivity."
    alert_file = os.path.join(STATE_DIR, "budget_alert.json")
    if os.path.exists(alert_file):
        try:
            with open(alert_file, 'r') as f:
                alert_data = json.load(f)
            for c in alert_data.get("candidates", []):
                if c.get("id") == agent_id:
                    explanation = c.get("reason", explanation)
                    break
        except Exception:
            pass
            
    current_step = agent_state.get("current_step")
    step_files = agent_state.get("touched_files", [])
    step_tools = agent_state.get("tools_used", [])
    
    def get_iso_timestamp():
        from datetime import datetime, timezone
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
    new_tombstone = {
        "file_path": step_files[0] if step_files else "unknown",
        "tool_used": step_tools[0] if step_tools else "pruned",
        "error_message": explanation,
        "fix_action": "Avoid this approach; prune record indicates low productivity.",
        "is_pruned": True,
        "goal": agent_state.get("goal"),
        "step_name": current_step.get("name") if current_step else "unknown",
        "timestamp": get_iso_timestamp()
    }
    tombstones.append(new_tombstone)
    save_json(tombstone_file, tombstones)
    
    return True, f"Agent {agent_id} successfully pruned. Tombstone registered."


def make_logs_panel():
    """Renders the tail of the background supervisor logs with a commands helper banner."""
    logs_lines = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()
                logs_lines = [line.strip() for line in lines[-6:]]
        except Exception:
            pass
            
    log_text = Text()
    log_text.append("💡 Helpful Commands: /add-agent <role> : <goal> | /view [combined/id] | /clean [target] | /memory | /trace <id> | /exit\n", style="bold yellow")
    log_text.append("-" * 90 + "\n", style="dim white")
    
    if logs_lines:
        for line in logs_lines:
            if "[WARNING]" in line or "COLLISION" in line:
                log_text.append(line + "\n", style="bold yellow")
            elif "[ERROR]" in line:
                log_text.append(line + "\n", style="bold red")
            elif "CONSENSUS APPROVED" in line:
                log_text.append(line + "\n", style="bold red")
            elif "CONSENSUS OVERRIDE" in line or "Extinction" in line:
                log_text.append(line + "\n", style="bold green")
            else:
                log_text.append(line + "\n", style="dim white")
    else:
        log_text.append("Waiting for supervisor logs...\n", style="dim white")
        
    return Panel(log_text, title="Supervisor Console Logs", border_style="cyan")


def make_input_panel(input_buffer, prompt_state):
    """Renders the inline terminal input panel at the bottom of the TUI."""
    msg = prompt_state.get("error_msg")
    if msg:
        return Panel(Text.from_markup(msg), title="Terminal Status", border_style="cyan")
        
    mode = prompt_state.get("mode")
    panel_text = Text()
    
    if TUI_STATE == "DECOMPOSING_MACRO":
        panel_text.append("Decomposing macro task... please wait ┃", style="bold yellow")
        return Panel(panel_text, title="PROCESSING", border_style="yellow")
    elif TUI_STATE == "BUDGET_CONFIRM":
        panel_text.append(f"Confirm recommended budget cap of {TUI_RECOMMENDED_CAP}? [Y/n] or enter custom cap > ", style="bold yellow")
        panel_text.append(input_buffer, style="white")
        panel_text.append("┃", style="bold yellow")
        return Panel(panel_text, title="BUDGET CONFIGURATION", border_style="yellow")
    elif TUI_STATE == "DESIGNER":
        panel_text.append("Swarm Designer (Commands: /run | /add | /remove | /edit | /cancel) > ", style="bold green")
        panel_text.append(input_buffer, style="white")
        panel_text.append("┃", style="bold green")
        return Panel(panel_text, title="SWARM DESIGNER", border_style="green")
    elif TUI_STATE == "DECOMPOSING_AGENTS":
        panel_text.append("Decomposing agent goals... please wait ┃", style="bold yellow")
        return Panel(panel_text, title="PROCESSING", border_style="yellow")
        
    if mode == "spawn":
        aid = prompt_state["agent_id"]
        panel_text.append(f"Approve spawn for Agent {aid}? [y/n] > ", style="bold yellow")
        panel_text.append(input_buffer, style="white")
        panel_text.append("┃", style="bold yellow")
        return Panel(panel_text, title="SPAWN APPROVAL REQUIRED", border_style="yellow")
    elif mode == "blocker_choice":
        aid = prompt_state["agent_id"]
        panel_text.append(f"Select Blocker Resolution (1/2/3) > ", style="bold red")
        panel_text.append(input_buffer, style="white")
        panel_text.append("┃", style="bold red")
        return Panel(panel_text, title="BLOCKER ENCOUNTERED", border_style="red")
    elif mode == "blocker_workaround":
        aid = prompt_state["agent_id"]
        panel_text.append("Enter workaround details > ", style="bold yellow")
        panel_text.append(input_buffer, style="white")
        panel_text.append("┃", style="bold yellow")
        return Panel(panel_text, title="ENTER WORKAROUND", border_style="yellow")
    else:
        panel_text.append("> ", style="bold cyan")
        panel_text.append(input_buffer, style="white")
        panel_text.append("┃", style="bold cyan")
        return Panel(panel_text, title="Interactive Swarm Terminal (Commands: /budget <n> | /prune <id> | /exit)", border_style="cyan")


# Ollama Connection Helper
def is_ollama_running():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


# Call Ollama API
def call_ollama(prompt):
    url = "http://localhost:11434/api/generate"
    headers = {"Content-Type": "application/json"}
    body = {
        "model": OLLAMA_MODEL,
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
        with urllib.request.urlopen(req, timeout=45) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data.get("response", "").strip()
    except Exception as e:
        return None


def call_ollama_raw(prompt, model="gemma4:latest"):
    """Call local Ollama API to generate raw text responses."""
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
        return None


# Clean LLM response to get pure JSON
def extract_json(text):
    content = text.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


# Generate steps dynamically using Ollama
def generate_task_steps(query):
    prompt = (
        f"You are the Swarm Planner. Decompose the following agentic task into a series of 3 to 4 sequential, concrete steps:\n"
        f"Task: '{query}'\n\n"
        f"For each step, provide:\n"
        f"- 'step_id': integer sequential ID\n"
        f"- 'name': short step name\n"
        f"- 'description': detailed description of what should be accomplished\n"
        f"- 'touched_files': list of relative file paths that will be edited or created. IMPORTANT: You MUST specify at least one target output file (e.g., 'src/answer.md' or 'output.md') in the final step so the agents write their findings, answers, or code results to disk for TUI rendering.\n"
        f"- 'tools': list of tools that will be used (e.g. ['edit_file', 'pytest', 'run_python', 'gcc', 'make'])\n\n"
        f"You MUST respond with a valid JSON object only. Do not include markdown formatting or explanations outside the JSON. "
        f"Example output structure:\n"
        f"{{\n"
        f"  \"steps\": [\n"
        f"    {{\n"
        f"      \"step_id\": 1,\n"
        f"      \"name\": \"Write quicksort\",\n"
        f"      \"description\": \"Write sorting implementation in src/quicksort.py\",\n"
        f"      \"touched_files\": [\"src/quicksort.py\"],\n"
        f"      \"tools\": [\"edit_file\"]\n"
        f"    }}\n"
        f"  ]\n"
        f"}}\n"
    )
    
    response_text = call_ollama(prompt)
    if not response_text:
        return None
        
    try:
        cleaned_json = extract_json(response_text)
        data = json.loads(cleaned_json)
        if "steps" in data:
            return data["steps"]
    except Exception:
        pass
        
    return None


def recommend_starting_agents(query):
    """Query Ollama to recommend optimal starting agent roles and goals for the query."""
    past_references = ""
    try:
        import memory_store
        matches = memory_store.query_similar_episodes(query, top_k=2)
        if matches:
            refs = []
            for match in matches:
                if match["score"] >= 0.4:
                    ref_text = (
                        f"- Task Goal: {match['goal']}\n"
                        f"  Role: {match['role']}\n"
                        f"  Execution Status: {match['status']}\n"
                        f"  Reflection: {match['reflection']}"
                    )
                    refs.append(ref_text)
            if refs:
                past_references = "=== SIMILAR PAST SWARM EXECUTIONS (REFERENCE) ===\n" + "\n\n".join(refs) + "\n=================================================\n\n"
    except Exception:
        pass

    prompt = (
        f"You are the Swarm Architect. Analyze the following task request:\n"
        f"Task: '{query}'\n\n"
    )
    if past_references:
        prompt += past_references
        
    prompt += (
        f"Recommend the optimal number of starting agents (minimum 1, maximum 3) to execute this task.\n"
        f"For each agent, provide:\n"
        f"- 'role': A concise role or personality (e.g. 'Software Engineer', 'Pytest QA Specialist', 'Documentation Lead')\n"
        f"- 'goal': A specific, dedicated goal/focus area for this agent (e.g. 'Write core JWT signing library in python', 'Write integration tests to validate token algorithms')\n\n"
        f"You MUST respond with a valid JSON object only. Do not include markdown code fences or explanations outside the JSON.\n"
        f"Example output structure:\n"
        f"{{\n"
        f"  \"recommendations\": [\n"
        f"    {{\n"
        f"      \"role\": \"Software Engineer\",\n"
        f"      \"goal\": \"Write core JWT library\"\n"
        f"    }}\n"
        f"  ]\n"
        f"}}\n"
    )
    
    response_text = call_ollama(prompt)
    if not response_text:
        return []
        
    try:
        cleaned_json = extract_json(response_text)
        data = json.loads(cleaned_json)
        if "recommendations" in data:
            return data["recommendations"]
    except Exception:
        pass
        
    return []


def decompose_macro_goal(query):
    """Query Ollama to decompose a macro task into a dependency tree of 1-3 sub-swarms."""
    if not is_ollama_running():
        return {
            "sub_swarms": [
                {
                    "id": "swarm_001",
                    "goal": query,
                    "role": "Generalist Group",
                    "dependencies": []
                }
            ]
        }
        
    prompt = (
        f"You are the Swarm Architect. Analyze the following macro task query:\n"
        f"Query: '{query}'\n\n"
        f"Decompose this task into a dependency tree of 1 to 3 functional sub-swarms.\n"
        f"For each sub-swarm, specify:\n"
        f"- 'id': A unique identifier (e.g. 'swarm_001', 'swarm_002')\n"
        f"- 'goal': The sub-goal focus of the sub-swarm\n"
        f"- 'role': The role/personality category of the sub-swarm (e.g. 'Security Specialists')\n"
        f"- 'dependencies': A list of sub-swarm IDs that must complete BEFORE this sub-swarm can start (e.g., ['swarm_001']).\n\n"
        f"You MUST respond with a valid JSON object only. Do not include markdown code fences or explanations outside the JSON.\n"
        f"Example output structure:\n"
        f"{{\n"
        f"  \"sub_swarms\": [\n"
        f"    {{\n"
        f"      \"id\": \"swarm_001\",\n"
        f"      \"goal\": \"Implement JWT signature verification\",\n"
        f"      \"role\": \"Security Specialists\",\n"
        f"      \"dependencies\": []\n"
        f"    }},\n"
        f"    {{\n"
        f"      \"id\": \"swarm_002\",\n"
        f"      \"goal\": \"Write unit tests for signature validation\",\n"
        f"      \"role\": \"QA Specialists\",\n"
        f"      \"dependencies\": [\"swarm_001\"]\n"
        f"    }}\n"
        f"  ]\n"
        f"}}\n"
    )
    
    response_text = call_ollama(prompt)
    if not response_text:
        return {
            "sub_swarms": [
                {
                    "id": "swarm_001",
                    "goal": query,
                    "role": "Generalist Group",
                    "dependencies": []
                }
            ]
        }
        
    try:
        cleaned_json = extract_json(response_text)
        data = json.loads(cleaned_json)
        if "sub_swarms" in data:
            return data
    except Exception:
        pass
        
    return {
        "sub_swarms": [
            {
                "id": "swarm_001",
                "goal": query,
                "role": "Generalist Group",
                "dependencies": []
            }
        ]
    }


def register_dynamic_task(task_id, goal, steps):
    if not os.path.exists(MOCK_TASKS_FILE):
        tasks_data = {"tasks": {}}
    else:
        try:
            with open(MOCK_TASKS_FILE, 'r') as f:
                tasks_data = json.load(f)
        except Exception:
            tasks_data = {"tasks": {}}
            
    tasks_data["tasks"][task_id] = {
        "id": task_id,
        "goal": goal,
        "steps": steps
    }
    
    with open(MOCK_TASKS_FILE, 'w') as f:
        json.dump(tasks_data, f, indent=2)


def execute_dashboard_run(layout, supervisor_cmd):

    # Launch supervisor subprocess
    sup_proc = subprocess.Popen(supervisor_cmd)
    is_interactive = "--interactive" in supervisor_cmd
    
    def get_iso_timestamp():
        from datetime import timezone
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        
    input_buffer = ""
    prompt_state = {
        "mode": None,          # 'spawn', 'blocker_choice', 'blocker_workaround', or None
        "agent_id": None,
        "agent_filepath": None,
        "spawn_req": None,
        "blocker_details": None,
        "error_msg": None,
        "msg_timer": 0.0
    }

    # Live loop updating layout components
    try:
        with Live(layout, refresh_per_second=5, screen=True, redirect_stdin=False) as live:
            while sup_proc.poll() is None:
                # 1. Update status/error message timer
                if prompt_state["error_msg"] and time.time() - prompt_state["msg_timer"] > 2.0:
                    prompt_state["error_msg"] = None
                
                # 2. Check for interactive prompts if in interactive mode and no prompt is active
                if is_interactive and prompt_state["mode"] is None:
                    if os.path.exists(AGENTS_DIR):
                        for filename in os.listdir(AGENTS_DIR):
                            if filename.endswith(".json"):
                                filepath = os.path.join(AGENTS_DIR, filename)
                                try:
                                    with open(filepath, 'r') as f:
                                        data = json.load(f)
                                except Exception:
                                    continue
                                    
                                # Check for spawn request
                                spawn_req = data.get("spawn_request")
                                if spawn_req and spawn_req.get("status") == "pending":
                                    prompt_state.update({
                                        "mode": "spawn",
                                        "agent_id": data.get("id"),
                                        "agent_filepath": filepath,
                                        "spawn_req": spawn_req
                                    })
                                    break
                                    
                                # Check for pending_termination due to blocker_details
                                status = data.get("status")
                                blocker = data.get("blocker_details")
                                if status == "pending_termination" and blocker:
                                    prompt_state.update({
                                        "mode": "blocker_choice",
                                        "agent_id": data.get("id"),
                                        "agent_filepath": filepath,
                                        "blocker_details": blocker
                                    })
                                    break

                # Verify prompt state validity (in case file state changes externally)
                if prompt_state["mode"] is not None:
                    filepath = prompt_state["agent_filepath"]
                    if not os.path.exists(filepath):
                        prompt_state["mode"] = None
                    else:
                        try:
                            with open(filepath, 'r') as f:
                                data = json.load(f)
                            if prompt_state["mode"] == "spawn":
                                spawn_req = data.get("spawn_request")
                                if not spawn_req or spawn_req.get("status") != "pending":
                                    prompt_state["mode"] = None
                            elif prompt_state["mode"] in ["blocker_choice", "blocker_workaround"]:
                                status = data.get("status")
                                blocker = data.get("blocker_details")
                                if status != "pending_termination" or not blocker:
                                    prompt_state["mode"] = None
                        except Exception:
                            pass

                # Update panels
                layout["header"].update(make_header_panel())
                layout["left"].update(make_agents_table())
                layout["center"].update(make_output_panel())
                layout["right_top"].update(make_collisions_panel())
                layout["right_middle"].update(make_budget_alert_panel(prompt_state))
                layout["right_bottom"].update(make_tombstones_panel())
                layout["footer_logs"].update(make_logs_panel())
                layout["footer_input"].update(make_input_panel(input_buffer, prompt_state))

                # 3. Read input char-by-char non-blocking
                import select
                import sys
                try:
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if rlist:
                        # Character is ready, read in raw mode
                        import tty
                        import termios
                        fd = sys.stdin.fileno()
                        old_settings = termios.tcgetattr(fd)
                        try:
                            tty.setraw(fd)
                            ch = sys.stdin.read(1)
                        finally:
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                            
                        # Clear error/success message immediately when user types
                        if prompt_state["error_msg"]:
                            prompt_state["error_msg"] = None
                            
                        # Handle character
                        if ch == '\x03':  # Ctrl+C
                            raise KeyboardInterrupt
                        elif ch in ('\r', '\n'):  # Enter
                            cmd_line = input_buffer.strip()
                            input_buffer = ""
                            
                            # Handle active prompts
                            if prompt_state["mode"] == "spawn":
                                filepath = prompt_state["agent_filepath"]
                                spawn_req = prompt_state["spawn_req"]
                                if cmd_line.lower() in ["y", "yes", "approve"]:
                                    spawn_req["status"] = "approved"
                                    try:
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["spawn_request"] = spawn_req
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold green][+] Spawn APPROVED for Agent {prompt_state['agent_id']}[/bold green]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                elif cmd_line.lower() in ["n", "no", "reject"]:
                                    spawn_req["status"] = "rejected"
                                    try:
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["spawn_request"] = spawn_req
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold yellow][-] Spawn REJECTED for Agent {prompt_state['agent_id']}[/bold yellow]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Invalid option. Type y or n.[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    
                            elif prompt_state["mode"] == "blocker_choice":
                                if cmd_line == "1":
                                    prompt_state["mode"] = "blocker_workaround"
                                elif cmd_line == "2":
                                    filepath = prompt_state["agent_filepath"]
                                    try:
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["steps_completed"] += 1
                                        tasks_data = load_json(MOCK_TASKS_FILE)
                                        task_id = agent_data.get("task_id")
                                        if tasks_data and task_id in tasks_data.get("tasks", {}):
                                            steps = tasks_data["tasks"][task_id].get("steps", [])
                                            agent_data["progress"] = int((agent_data["steps_completed"] / len(steps)) * 100)
                                            if agent_data["steps_completed"] < len(steps):
                                                next_step = steps[agent_data["steps_completed"]]
                                                agent_data["current_step"] = {
                                                    "step_id": next_step["step_id"],
                                                    "name": next_step["name"],
                                                    "description": next_step["description"]
                                                }
                                            else:
                                                agent_data["status"] = "completed"
                                                agent_data["current_step"] = None
                                        if agent_data["status"] != "completed":
                                            agent_data["status"] = "exploring"
                                        agent_data["blocker_details"] = None
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold green][+] Blocker bypassed for Agent {prompt_state['agent_id']}[/bold green]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                    
                                elif cmd_line == "3":
                                    filepath = prompt_state["agent_filepath"]
                                    try:
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["status"] = "dead"
                                        agent_data["blocker_details"] = None
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold red][-] Agent {prompt_state['agent_id']} terminated[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Invalid option. Enter 1, 2, or 3.[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    
                            elif prompt_state["mode"] == "blocker_workaround":
                                if cmd_line:
                                    filepath = prompt_state["agent_filepath"]
                                    blocker = prompt_state["blocker_details"]
                                    try:
                                        tombstones = load_json(TOMBSTONES_FILE) or []
                                        tombstones.append({
                                            "file_path": blocker.get("file_path", "unknown"),
                                            "tool_used": blocker.get("tool_used", "unknown"),
                                            "error_message": blocker.get("error_message", "unknown"),
                                            "fix_action": cmd_line,
                                            "timestamp": get_iso_timestamp()
                                        })
                                        save_json(TOMBSTONES_FILE, tombstones)
                                        
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["status"] = "exploring"
                                        agent_data["blocker_details"] = None
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold green][+] Workaround registered for Agent {prompt_state['agent_id']}[/bold green]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Workaround cannot be empty.[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    
                            else:
                                # Normal Command parsing
                                if cmd_line:
                                    parts = cmd_line.split(maxsplit=1)
                                    cmd = parts[0].lower()
                                    arg = parts[1] if len(parts) > 1 else None
                                    
                                    if cmd in ["/exit", "/quit"]:
                                        raise KeyboardInterrupt
                                    elif cmd == "/budget":
                                        if not arg or not arg.isdigit():
                                            prompt_state["error_msg"] = "[bold red][-] Usage: /budget <new_cap>[/bold red]"
                                            prompt_state["msg_timer"] = time.time()
                                        else:
                                            cap = int(arg)
                                            global session_budget
                                            session_budget = cap
                                            orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")
                                            if os.path.exists(orchestrator_file):
                                                try:
                                                    orc_state = load_json(orchestrator_file) or {}
                                                    orc_state["budget_limit"] = cap
                                                    save_json(orchestrator_file, orc_state)
                                                    prompt_state["error_msg"] = f"[bold green][+] Budget updated dynamically to {cap}[/bold green]"
                                                    prompt_state["msg_timer"] = time.time()
                                                except Exception as e:
                                                    prompt_state["error_msg"] = f"[bold red][-] Error updating budget: {e}[/bold red]"
                                                    prompt_state["msg_timer"] = time.time()
                                            else:
                                                prompt_state["error_msg"] = "[bold red][-] Error: orchestrator.json not found[/bold red]"
                                    elif cmd == "/prune":
                                        if not arg:
                                            prompt_state["error_msg"] = "[bold red][-] Usage: /prune <agent_id>[/bold red]"
                                            prompt_state["msg_timer"] = time.time()
                                        else:
                                            agent_id = arg.strip().zfill(3)
                                            success, msg = handle_dashboard_pruning(agent_id)
                                            if success:
                                                prompt_state["error_msg"] = f"[bold green][+] {msg}[/bold green]"
                                                prompt_state["msg_timer"] = time.time()
                                            else:
                                                prompt_state["error_msg"] = f"[bold red][-] {msg}[/bold red]"
                                                prompt_state["msg_timer"] = time.time()
                                    elif cmd == "/approve":
                                        if not arg:
                                            prompt_state["error_msg"] = "[bold red][-] Usage: /approve <agent_id>[/bold red]"
                                            prompt_state["msg_timer"] = time.time()
                                        else:
                                            target_aid = arg.strip().zfill(3)
                                            filepath = os.path.join(AGENTS_DIR, f"agent_{target_aid}.json")
                                            if os.path.exists(filepath):
                                                try:
                                                    with open(filepath, 'r') as f:
                                                        agent_data = json.load(f)
                                                    spawn_req = agent_data.get("spawn_request")
                                                    if spawn_req and spawn_req.get("status") == "pending":
                                                        spawn_req["status"] = "approved"
                                                        agent_data["spawn_request"] = spawn_req
                                                        save_json(filepath, agent_data)
                                                        prompt_state["error_msg"] = f"[bold green][+] Spawn APPROVED for Agent {target_aid}[/bold green]"
                                                    else:
                                                        prompt_state["error_msg"] = f"[bold red][-] No pending spawn request for Agent {target_aid}[/bold red]"
                                                except Exception as e:
                                                    prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                            else:
                                                prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} not found[/bold red]"
                                            prompt_state["msg_timer"] = time.time()
                                    elif cmd == "/reject":
                                        if not arg:
                                            prompt_state["error_msg"] = "[bold red][-] Usage: /reject <agent_id>[/bold red]"
                                            prompt_state["msg_timer"] = time.time()
                                        else:
                                            target_aid = arg.strip().zfill(3)
                                            filepath = os.path.join(AGENTS_DIR, f"agent_{target_aid}.json")
                                            if os.path.exists(filepath):
                                                try:
                                                    with open(filepath, 'r') as f:
                                                        agent_data = json.load(f)
                                                    spawn_req = agent_data.get("spawn_request")
                                                    if spawn_req and spawn_req.get("status") == "pending":
                                                        spawn_req["status"] = "rejected"
                                                        agent_data["spawn_request"] = spawn_req
                                                        save_json(filepath, agent_data)
                                                        prompt_state["error_msg"] = f"[bold yellow][-] Spawn REJECTED for Agent {target_aid}[/bold yellow]"
                                                    else:
                                                        prompt_state["error_msg"] = f"[bold red][-] No pending spawn request for Agent {target_aid}[/bold red]"
                                                except Exception as e:
                                                    prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                            else:
                                                prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} not found[/bold red]"
                                            prompt_state["msg_timer"] = time.time()
                                    elif cmd == "/resolve":
                                        subparts = arg.strip().split() if arg else []
                                        if len(subparts) < 2:
                                            prompt_state["error_msg"] = "[bold red][-] Usage: /resolve <agent_id> <1|2|3>[/bold red]"
                                            prompt_state["msg_timer"] = time.time()
                                        else:
                                            target_aid = subparts[0].zfill(3)
                                            choice = subparts[1]
                                            filepath = os.path.join(AGENTS_DIR, f"agent_{target_aid}.json")
                                            if os.path.exists(filepath):
                                                try:
                                                    with open(filepath, 'r') as f:
                                                        agent_data = json.load(f)
                                                    status = agent_data.get("status")
                                                    blocker = agent_data.get("blocker_details")
                                                    if status == "pending_termination" and blocker:
                                                        if choice == "1":
                                                            prompt_state.update({
                                                                "mode": "blocker_workaround",
                                                                "agent_id": target_aid,
                                                                "agent_filepath": filepath,
                                                                "blocker_details": blocker
                                                            })
                                                            prompt_state["error_msg"] = f"[bold yellow][*] Enter manual workaround for Agent {target_aid} below...[/bold yellow]"
                                                        elif choice == "2":
                                                            tombstones = load_json(TOMBSTONES_FILE) or []
                                                            tombstones.append({
                                                                "file_path": blocker.get("file_path", "unknown"),
                                                                "tool_used": blocker.get("tool_used", "unknown"),
                                                                "error_message": blocker.get("error_message", "unknown"),
                                                                "fix_action": "Bypassed by User command",
                                                                "timestamp": get_iso_timestamp()
                                                            })
                                                            save_json(TOMBSTONES_FILE, tombstones)
                                                            agent_data["status"] = "exploring"
                                                            agent_data["blocker_details"] = None
                                                            save_json(filepath, agent_data)
                                                            prompt_state["error_msg"] = f"[bold green][+] Agent {target_aid} bypass recorded. Resuming...[/bold green]"
                                                        elif choice == "3":
                                                            success, msg = handle_dashboard_pruning(target_aid)
                                                            if success:
                                                                prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} pruned[/bold red]"
                                                            else:
                                                                prompt_state["error_msg"] = f"[bold red][-] {msg}[/bold red]"
                                                        else:
                                                            prompt_state["error_msg"] = "[bold red][-] Invalid choice. Must be 1, 2, or 3.[/bold red]"
                                                    else:
                                                        prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} is not blocked[/bold red]"
                                                except Exception as e:
                                                    prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                            else:
                                                prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} not found[/bold red]"
                                            prompt_state["msg_timer"] = time.time()
                                    else:
                                        prompt_state["error_msg"] = f"[bold red][-] Unknown command: {cmd}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                        
                        elif ch in ('\x7f', '\x08'):  # Backspace
                            input_buffer = input_buffer[:-1]
                        elif ch == '\x1b':  # Escape sequence
                            r, _, _ = select.select([sys.stdin], [], [], 0.001)
                            if r:
                                sys.stdin.read(1)
                                r, _, _ = select.select([sys.stdin], [], [], 0.001)
                                if r:
                                    sys.stdin.read(1)
                        else:
                            # Append printable characters
                            if len(ch) == 1 and (32 <= ord(ch) <= 126):
                                input_buffer += ch
                except Exception:
                    pass

            # Update final state before loop exit check
            layout["header"].update(make_header_panel())
            layout["left"].update(make_agents_table())
            layout["center"].update(make_output_panel())
            layout["right_top"].update(make_collisions_panel())
            layout["right_middle"].update(make_budget_alert_panel(prompt_state))
            layout["right_bottom"].update(make_tombstones_panel())
            layout["footer_logs"].update(make_logs_panel())
            layout["footer_input"].update(make_input_panel(input_buffer, prompt_state))
            
    except KeyboardInterrupt:
        pass
    finally:
        sup_proc.terminate()
        sup_proc.wait()


def write_to_monitor_log(message, level="INFO"):
    """Writes a message directly to monitor.log in the standard format."""
    try:
        os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)
        time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S,%f")[:-3]  # YYYY-MM-DD HH:MM:SS,mmm
        with open(LOG_FILE, 'a') as f:
            f.write(f"{time_str} [{level}] {message}\n")
    except Exception:
        pass


def make_designer_agents_table(current_agents):
    """Renders the designer's agent table."""
    config_table = Table(title="Custom Swarm Configuration", expand=True)
    config_table.add_column("Agent #", justify="center", style="bold white", width=10)
    config_table.add_column("Role / Personality", justify="left", style="cyan", width=25)
    config_table.add_column("Dedicated Goal / Focus Area", justify="left", style="white")
    config_table.add_column("Status", justify="center", style="green", width=20)
    
    for idx, entry in enumerate(current_agents):
        config_table.add_row(
            f"Agent {idx+1:02d}",
            entry.get("role", "Generalist"),
            entry.get("goal") or "Inherits overall task goal",
            "Ready to Initialize"
        )
    return Panel(config_table, border_style="yellow", title="Swarm Designer Agents")


def make_designer_center_panel(overall_query):
    """Renders designer center panel instructions."""
    designer_text = Text()
    designer_text.append("🛰️  SWARM DESIGNER ACTIVE  🛰️\n\n", style="bold yellow")
    designer_text.append("Overall Goal / Query:\n", style="bold white")
    designer_text.append(f"{overall_query}\n\n", style="cyan")
    designer_text.append("Modify the agent swarm before starting execution.\n", style="dim white")
    designer_text.append("You can edit roles, goals, add specialists, or remove agents.\n\n", style="dim white")
    designer_text.append("When ready, type /run to start the swarm execution.", style="bold green")
    
    return Panel(designer_text, border_style="yellow", title="Task Context")


def make_designer_placeholder_panel(title):
    """Placeholder panels for inactive components during designer phase."""
    return Panel(
        Align.center(Text("Inactive during Swarm Design", style="dim white")),
        title=title,
        border_style="dim white"
    )


def make_designer_footer_panel():
    """Footer command helper list for the designer phase."""
    help_text = Text()
    help_text.append("🛰️  Swarm Designer Help & Commands:\n", style="bold yellow")
    help_text.append("  /add <role> : <goal>     ", style="bold green")
    help_text.append("- Add a new agent to the swarm\n", style="white")
    help_text.append("  /edit <num> role=<val>   ", style="bold green")
    help_text.append("- Change agent's role/personality\n", style="white")
    help_text.append("  /edit <num> goal=<val>   ", style="bold green")
    help_text.append("- Change agent's dedicated sub-goal\n", style="white")
    help_text.append("  /remove <num>            ", style="bold green")
    help_text.append("- Remove agent from the swarm\n", style="white")
    help_text.append("  /run                     ", style="bold green")
    help_text.append("- Start the swarm   |   ", style="white")
    help_text.append("/cancel                  ", style="bold red")
    help_text.append("- Abort task execution and return", style="white")
    
    return Panel(help_text, border_style="yellow", title="Helpful Designer Commands")


def run_swarm_designer(initial_list, overall_query, layout=None):
    """Enters an interactive loop to let the user review, add, edit, or remove swarm agents."""
    current_agents = list(initial_list)
    
    # Prompt user for recommended budget cap
    is_testing = "unittest" in sys.modules or "pytest" in sys.modules or any("unittest" in arg for arg in sys.argv)
    if not is_testing:
        recommended_cap = recommend_budget_cap(overall_query)
        os.system("clear")
        print("\n" + "="*70)
        print("                🛰️  SWARM BUDGET CAP CONFIGURATION  🛰️")
        print("="*70 + "\n")
        print(f"Overall Task: '{overall_query}'")
        print(f"Recommended Active Agent Budget Cap: {recommended_cap}")
        print("This cap restricts the number of concurrently active agents exploring options.")
        print("If active count exceeds the cap, warning and productivity rankings will trigger.")
        print("-"*70)
        try:
            import termios
            termios.tcflush(sys.stdin, termios.TCIFLUSH)
        except Exception:
            pass
        global session_budget
        try:
            ans = input(f"Confirm recommended budget cap of {recommended_cap}? [Y/n] or enter custom cap: ").strip()
            if not ans or ans.lower() in ["y", "yes"]:
                session_budget = recommended_cap
            elif ans.isdigit():
                session_budget = int(ans)
                print(f"[+] Custom budget cap set to {session_budget}.")
            else:
                session_budget = recommended_cap
        except (KeyboardInterrupt, EOFError):
            session_budget = recommended_cap

    # Write transient budget cap to orchestrator config
    orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        orc_state = load_json(orchestrator_file) or {}
        orc_state["budget_limit"] = session_budget
        save_json(orchestrator_file, orc_state)
    except Exception:
        pass

    input_buffer = ""
    prompt_state = {
        "mode": None,
        "error_msg": None,
        "msg_timer": 0.0
    }

    if layout:
        with Live(layout, refresh_per_second=5, screen=True, redirect_stdin=False) as live:
            while True:
                if prompt_state["error_msg"] and time.time() - prompt_state["msg_timer"] > 2.0:
                    prompt_state["error_msg"] = None
                    
                layout["header"].update(make_header_panel())
                layout["left"].update(make_designer_agents_table(current_agents))
                layout["center"].update(make_designer_center_panel(overall_query))
                layout["right_top"].update(make_designer_placeholder_panel("Collision Monitor (Inactive)"))
                layout["right_middle"].update(make_designer_placeholder_panel("Alerts / Pending Decisions (Inactive)"))
                layout["right_bottom"].update(make_designer_placeholder_panel("Tombstone Database (Inactive)"))
                layout["footer_logs"].update(make_designer_footer_panel())
                layout["footer_input"].update(make_input_panel(input_buffer, prompt_state))
                
                import select
                try:
                    rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                    if rlist:
                        import tty
                        import termios
                        fd = sys.stdin.fileno()
                        old_settings = termios.tcgetattr(fd)
                        try:
                            tty.setraw(fd)
                            ch = sys.stdin.read(1)
                        finally:
                            termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                            
                        if prompt_state["error_msg"]:
                            prompt_state["error_msg"] = None
                            
                        if ch == '\x03':
                            raise KeyboardInterrupt
                        elif ch in ('\r', '\n'):
                            cmd_input = input_buffer.strip()
                            input_buffer = ""
                            if not cmd_input:
                                continue
                                
                            parts = cmd_input.split(maxsplit=1)
                            cmd = parts[0].lower()
                            arg = parts[1] if len(parts) > 1 else None
                            
                            if cmd == "/run":
                                if not current_agents:
                                    prompt_state["error_msg"] = "[bold red][-] Error: Swarm cannot be empty.[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                return current_agents
                            elif cmd == "/cancel":
                                return None
                            elif cmd == "/add":
                                if not arg:
                                    prompt_state["error_msg"] = "[bold red][-] Usage: /add <role> : <goal>[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                if ":" in arg:
                                    r_part, g_part = arg.split(":", 1)
                                    r = r_part.strip()
                                    g = g_part.strip()
                                else:
                                    r = arg.strip()
                                    g = None
                                if r:
                                    current_agents.append({"role": r, "goal": g})
                                    prompt_state["error_msg"] = f"[bold green][+] Added agent: {r}[/bold green]"
                                    prompt_state["msg_timer"] = time.time()
                            elif cmd == "/remove":
                                if not arg or not arg.isdigit():
                                    prompt_state["error_msg"] = "[bold red][-] Usage: /remove <num>[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                num = int(arg) - 1
                                if 0 <= num < len(current_agents):
                                    removed = current_agents.pop(num)
                                    prompt_state["error_msg"] = f"[bold yellow][-] Removed agent: {removed['role']}[/bold yellow]"
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Error: Invalid agent number.[/bold red]"
                                prompt_state["msg_timer"] = time.time()
                            elif cmd == "/edit":
                                if not arg:
                                    prompt_state["error_msg"] = "[bold red][-] Usage: /edit <num> role=<val> OR goal=<val>[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                subparts = arg.split(maxsplit=1)
                                if len(subparts) < 2 or not subparts[0].isdigit():
                                    prompt_state["error_msg"] = "[bold red][-] Usage: /edit <num> role=<val> OR goal=<val>[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                num = int(subparts[0]) - 1
                                edit_arg = subparts[1]
                                if 0 <= num < len(current_agents):
                                    if "=" in edit_arg:
                                        field, val = edit_arg.split("=", 1)
                                        field = field.strip().lower()
                                        val = val.strip()
                                        if field in ["role", "goal"]:
                                            current_agents[num][field] = val
                                            prompt_state["error_msg"] = f"[bold green][+] Updated Agent {num+1} {field}.[/bold green]"
                                        else:
                                            prompt_state["error_msg"] = "[bold red][-] Field must be role or goal.[/bold red]"
                                    else:
                                        prompt_state["error_msg"] = "[bold red][-] Format: field=value.[/bold red]"
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Invalid agent number.[/bold red]"
                                prompt_state["msg_timer"] = time.time()
                            else:
                                prompt_state["error_msg"] = f"[bold red][-] Unknown designer command: {cmd}[/bold red]"
                                prompt_state["msg_timer"] = time.time()
                        elif ord(ch) in (127, 8):
                            input_buffer = input_buffer[:-1]
                        elif len(ch) == 1 and (32 <= ord(ch) <= 126):
                            input_buffer += ch
                except select.error:
                    pass
                time.sleep(0.05)
    else:
        while True:
            os.system("clear")
            print("\n\033[1;33m" + "="*70)
            print("                🛰️  SWARM DESIGNER MODE  🛰️")
            print("="*70 + "\033[0m\n")
            print(f"\033[1mOverall Goal/Query:\033[0m {overall_query}\n")
            
            if not current_agents:
                print("  (No agents defined yet. The swarm will be empty! Add agents or cancel.)\n")
            else:
                for idx, agent in enumerate(current_agents):
                    role = agent.get("role", "Generalist")
                    goal = agent.get("goal") or "Inherits overall task goal"
                    print(f"  \033[1;36mAgent {idx+1:02d}:\033[0m")
                    print(f"    \033[1mRole/Personality:\033[0m {role}")
                    print(f"    \033[1mDedicated Goal:\033[0m   {goal}\n")
                    
            print("\033[1;33mAvailable Commands:\033[0m")
            print("  \033[1m/run\033[0m                       - Start the swarm with these agents")
            print("  \033[1m/edit <num> role=<val>\033[0m     - Change an agent's role/personality")
            print("  \033[1m/edit <num> goal=<val>\033[0m     - Change an agent's dedicated goal")
            print("  \033[1m/add <role> : <goal>\033[0m       - Add a new agent to the swarm")
            print("  \033[1m/remove <num>\033[0m              - Remove an agent from the swarm")
            print("  \033[1m/cancel\033[0m                    - Abort task and go back to main dashboard\n")
            
            try:
                import termios
                termios.tcflush(sys.stdin, termios.TCIFLUSH)
            except Exception:
                pass
                
            designer_prompt = "\033[1;32mSwarm Designer > \033[0m"
            try:
                cmd_input = input(designer_prompt).strip()
            except (KeyboardInterrupt, EOFError):
                print("\n[*] Swarm design cancelled.")
                return None
                
            if not cmd_input:
                continue
                
            parts = cmd_input.split(maxsplit=1)
            cmd = parts[0].lower()
            arg = parts[1] if len(parts) > 1 else None
            
            if cmd == "/run":
                if not current_agents:
                    print("\n\033[1;31m[-] Error: Cannot start an empty swarm. Please add agents first.\033[0m")
                    time.sleep(1.5)
                    continue
                return current_agents
            elif cmd == "/cancel":
                return None
            elif cmd == "/add":
                if not arg:
                    print("\n\033[1;31m[-] Error: Usage: /add <role> : <goal>\033[0m")
                    time.sleep(1.5)
                    continue
                if ":" in arg:
                    r_part, g_part = arg.split(":", 1)
                    r = r_part.strip()
                    g = g_part.strip()
                else:
                    r = arg.strip()
                    g = None
                if r:
                    current_agents.append({"role": r, "goal": g})
                    print(f"\n\033[1;32m[+] Added agent: {r}\033[0m")
                else:
                    print("\n\033[1;31m[-] Error: Agent role cannot be empty.\033[0m")
                time.sleep(1.0)
            elif cmd == "/remove":
                if not arg or not arg.isdigit():
                    print("\n\033[1;31m[-] Error: Usage: /remove <num>\033[0m")
                    time.sleep(1.5)
                    continue
                num = int(arg) - 1
                if 0 <= num < len(current_agents):
                    removed = current_agents.pop(num)
                    print(f"\n\033[1;32m[+] Removed agent {num+1}: {removed['role']}\033[0m")
                else:
                    print("\n\033[1;31m[-] Error: Invalid agent number.\033[0m")
                time.sleep(1.0)
            elif cmd == "/edit":
                if not arg:
                    print("\n\033[1;31m[-] Error: Usage: /edit <num> role=<val> OR /edit <num> goal=<val>\033[0m")
                    time.sleep(2.0)
                    continue
                subparts = arg.split(maxsplit=1)
                if len(subparts) < 2 or not subparts[0].isdigit():
                    print("\n\033[1;31m[-] Error: Usage: /edit <num> role=<val> OR /edit <num> goal=<val>\033[0m")
                    time.sleep(2.0)
                    continue
                num = int(subparts[0]) - 1
                edit_arg = subparts[1]
                if 0 <= num < len(current_agents):
                    if "=" in edit_arg:
                        field, val = edit_arg.split("=", 1)
                        field = field.strip().lower()
                        val = val.strip()
                        if field == "role":
                            current_agents[num]["role"] = val
                            print(f"\n\033[1;32m[+] Updated Agent {num+1}'s role to: {val}\033[0m")
                        elif field == "goal":
                            current_agents[num]["goal"] = val
                            print(f"\n\033[1;32m[+] Updated Agent {num+1}'s goal to: {val}\033[0m")
                        else:
                            print("\n\033[1;31m[-] Error: Field must be 'role' or 'goal'.\033[0m")
                    else:
                        print("\n\033[1;31m[-] Error: Format must be field=value.\033[0m")
                else:
                    print("\n\033[1;31m[-] Error: Invalid agent number.\033[0m")
                time.sleep(1.5)
            else:
                print("\n\033[1;31m[-] Unknown designer command.\033[0m")
                time.sleep(1.0)


def cleanup_transient_session_state():
    """Wipes the transient session state at TUI startup to ensure a clean boot."""
    if os.path.exists(STATE_DIR):
        try:
            shutil.rmtree(STATE_DIR)
        except Exception:
            pass
            
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        os.makedirs(os.path.dirname(TOMBSTONES_FILE), exist_ok=True)
        with open(TOMBSTONES_FILE, 'w') as f:
            json.dump([], f, indent=2)
    except Exception:
        pass

    if os.path.exists(MOCK_TASKS_FILE):
        try:
            with open(MOCK_TASKS_FILE, 'r') as f:
                data = json.load(f)
            if "tasks" in data:
                data["tasks"] = {k: v for k, v in data["tasks"].items() if not k.startswith("task_dynamic_")}
            with open(MOCK_TASKS_FILE, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass


def main():
    cleanup_transient_session_state()
    parser = argparse.ArgumentParser(description="Proximity Swarm V2 - Terminal Monitor Dashboard")
    parser.add_argument("--run-redundant", action="store_true", help="Launch the identical goal collision demo")
    parser.add_argument("--task-id", help="Launch a custom task ID and monitor it")
    parser.add_argument("--deconflict", action="store_true", help="Enable goal deconfliction file parameter offsets")
    parser.add_argument("--interactive", action="store_true", help="Enable terminal prompts to manually negotiate collisions")
    parser.add_argument("--step-delay", type=float, default=2.0, help="Agent runner step delay in seconds")
    parser.add_argument("--llm-provider", choices=["gemini", "ollama", "rules"], help="LLM API provider for deconfliction negotiation")
    parser.add_argument("--ollama-model", default="gemma4:latest", help="Ollama model string to query if provider is ollama")
    parser.add_argument("--budget", type=int, default=20000, help="Maximum active leaf agent output token budget cap limit")
    args = parser.parse_args()
    
    global session_budget
    session_budget = args.budget
    
    # Build 3-column layout
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=15)
    )
    layout["body"].split_row(
        Layout(name="left", ratio=5),
        Layout(name="center", ratio=6),
        Layout(name="right", ratio=5)
    )
    layout["right"].split(
        Layout(name="right_top", ratio=1),
        Layout(name="right_middle", ratio=1),
        Layout(name="right_bottom", ratio=1)
    )
    layout["footer"].split(
        Layout(name="footer_logs", ratio=2),
        Layout(name="footer_input", size=5)
    )
    
    # Check if we should execute a single direct run (redundant demo or specific task)
    if args.run_redundant or args.task_id:
        supervisor_cmd = [
            sys.executable, "supervisor.py"
        ]
        if args.run_redundant:
            supervisor_cmd.append("--run-redundant")
        elif args.task_id:
            supervisor_cmd.extend(["--task-id", args.task_id])

        if args.deconflict:
            supervisor_cmd.append("--deconflict")
        if args.interactive:
            supervisor_cmd.append("--interactive")
        if args.llm_provider:
            supervisor_cmd.extend(["--llm-provider", args.llm_provider])
        if args.ollama_model:
            supervisor_cmd.extend(["--ollama-model", args.ollama_model])
        if args.step_delay:
            supervisor_cmd.extend(["--step-delay", str(args.step_delay)])
        if session_budget:
            supervisor_cmd.extend(["--budget", str(session_budget)])
            
        global TUI_STATE, TUI_SUPERVISOR_CMD
        TUI_STATE = "RUNNING"
        TUI_SUPERVISOR_CMD = supervisor_cmd
        synthesis_cache.update({"last_hash": None, "content": None, "is_generating": False})
        
    try:
        run_tui_loop(layout, args)
    except (KeyboardInterrupt, EOFError):
        os.system("clear")
        print("\n" + "="*50)
        print("    Terminal Dashboard Session Terminated")
        print("="*50 + "\n")

def run_swarm_workflow(user_input, layout, args):
    # Decompose goal into sub-swarms first
    orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")
    os.makedirs(STATE_DIR, exist_ok=True)
    
    initial_swarm = []
    if predefined_personalities:
        for idx, entry in enumerate(predefined_personalities):
            initial_swarm.append({
                "role": entry["role"],
                "goal": entry["goal"] or user_input,
                "sub_swarm_id": "swarm_001"
            })
        orchestrator_state = {
            "macro_goal": user_input,
            "sub_swarms": {
                "swarm_001": {
                    "id": "swarm_001",
                    "goal": user_input,
                    "role": "Custom Swarm",
                    "dependencies": [],
                    "status": "pending",
                    "agent_ids": []
                }
            }
        }
        save_json(orchestrator_file, orchestrator_state)
    else:
        write_to_monitor_log(f"No custom agents defined. Decomposing task into sub-swarms for: '{user_input}'...", "INFO")
        with console.status("[bold yellow]Decomposing macro task into sub-swarms via Ollama...", spinner="dots"):
            decomposition = decompose_macro_goal(user_input)
        
        sub_swarms_dict = {}
        for s in decomposition["sub_swarms"]:
            sub_swarms_dict[s["id"]] = {
                "id": s["id"],
                "goal": s["goal"],
                "role": s["role"],
                "dependencies": s["dependencies"],
                "status": "pending",
                "agent_ids": []
            }
            initial_swarm.append({
                "role": s["role"],
                "goal": s["goal"],
                "sub_swarm_id": s["id"]
            })
            
        orchestrator_state = {
            "macro_goal": user_input,
            "sub_swarms": sub_swarms_dict
        }
        save_json(orchestrator_file, orchestrator_state)
    
    # Enter Swarm Designer Mode to review/modify roles/goals
    final_swarm = run_swarm_designer(initial_swarm, user_input, layout)
    if final_swarm is None:
        predefined_personalities.clear()
        write_to_monitor_log("Swarm design cancelled by user.", "WARNING")
        return
        
    # Decompose goals and register tasks
    agents_config = []
    now_ts = int(time.time())
    
    from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TimeElapsedColumn
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        console=console
    ) as progress:
        task_id_progress = progress.add_task("[yellow]Decomposing agent goals...", total=len(final_swarm))
        
        for idx, entry in enumerate(final_swarm):
            agent_role = entry.get("role", "Generalist")
            agent_goal = entry.get("goal") or user_input
            agent_id = f"{idx+1:03d}"
            agent_sub_swarm = entry.get("sub_swarm_id", "swarm_001")
            
            progress.update(task_id_progress, description=f"[yellow]Agent {agent_id} ({agent_role}): Decomposing goal...")
            write_to_monitor_log(f"Decomposing goal for Agent {agent_id} ({agent_role}): '{agent_goal}'...", "INFO")
            
            steps = generate_task_steps(agent_goal)
            if not steps:
                steps = [
                    {
                        "step_id": 1,
                        "name": "General Execution",
                        "description": f"Perform tasks for: {agent_goal}",
                        "touched_files": [f"src/agent_{agent_id}_output.md"],
                        "tools": ["edit_file"]
                    }
                ]
            
            task_id = f"task_dynamic_{now_ts}_{idx}"
            register_dynamic_task(task_id, agent_goal, steps)
            
            agents_config.append({
                "agent_id": agent_id,
                "task_id": task_id,
                "personality": agent_role,
                "goal": agent_goal,
                "sub_swarm_id": agent_sub_swarm
            })
            
            progress.advance(task_id_progress)
        
    # Update orchestrator.json with final assigned agent IDs
    orchestrator_state = load_json(orchestrator_file)
    if orchestrator_state:
        for sid in orchestrator_state["sub_swarms"]:
            orchestrator_state["sub_swarms"][sid]["agent_ids"] = []
        for item in agents_config:
            sid = item["sub_swarm_id"]
            if sid in orchestrator_state["sub_swarms"]:
                orchestrator_state["sub_swarms"][sid]["agent_ids"].append(item["agent_id"])
        save_json(orchestrator_file, orchestrator_state)
        
    # Clear predefined personalities for next run
    predefined_personalities.clear()
    
    write_to_monitor_log(f"Starting swarm with {len(agents_config)} agents. Initializing TUI dashboard visualization...", "INFO")
    
    supervisor_cmd = [
        sys.executable, "supervisor.py",
        "--agents-config", json.dumps(agents_config),
        "--llm-provider", "ollama",
        "--step-delay", "1.5"
    ]
    if args.interactive:
        supervisor_cmd.append("--interactive")
    if session_budget:
        supervisor_cmd.extend(["--budget", str(session_budget)])
    
    synthesis_cache.update({"last_hash": None, "content": None, "is_generating": False})
    execute_dashboard_run(layout, supervisor_cmd)


# Persistent Interactive TUI Dashboard Mode
def run_tui_loop(layout, args):
    global TUI_STATE, TUI_MACRO_GOAL, TUI_RECOMMENDED_CAP, TUI_DESIGNER_AGENTS
    global TUI_DECOMPOSE_PROGRESS, TUI_SUPERVISOR_CMD, TUI_SUPERVISOR_PROC
    global TUI_ARGS, session_budget, current_view
    
    TUI_ARGS = args
    input_buffer = ""
    prompt_state = {
        "mode": None,          # 'spawn', 'blocker_choice', 'blocker_workaround', or None
        "agent_id": None,
        "agent_filepath": None,
        "spawn_req": None,
        "blocker_details": None,
        "error_msg": None,
        "msg_timer": 0.0
    }
    
    is_interactive = args.interactive if hasattr(args, "interactive") else True
    
    def get_iso_timestamp():
        from datetime import timezone
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    with Live(layout, refresh_per_second=5, screen=True, redirect_stdin=False) as live:
        while True:
            # 1. Update status/error message timer
            if prompt_state["error_msg"] and time.time() - prompt_state["msg_timer"] > 2.0:
                prompt_state["error_msg"] = None
                
            # 2. State specific updates
            if TUI_STATE == "RUNNING":
                # Ensure supervisor subprocess is running
                if TUI_SUPERVISOR_PROC is None:
                    TUI_SUPERVISOR_PROC = subprocess.Popen(TUI_SUPERVISOR_CMD)
                    
                # Poll supervisor subprocess
                if TUI_SUPERVISOR_PROC.poll() is not None:
                    TUI_SUPERVISOR_PROC = None
                    # If this was a direct task run (non-persistent CLI mode), exit dashboard
                    if args.run_redundant or args.task_id:
                        break
                    TUI_STATE = "MENU"
                    prompt_state["error_msg"] = "[bold green][+] Swarm execution completed successfully.[/bold green]"
                    prompt_state["msg_timer"] = time.time()
                
                # Check for interactive prompts from supervisor
                if is_interactive and prompt_state["mode"] is None:
                    if os.path.exists(AGENTS_DIR):
                        for filename in os.listdir(AGENTS_DIR):
                            if filename.endswith(".json"):
                                filepath = os.path.join(AGENTS_DIR, filename)
                                try:
                                    with open(filepath, 'r') as f:
                                        data = json.load(f)
                                except Exception:
                                    continue
                                    
                                spawn_req = data.get("spawn_request")
                                if spawn_req and spawn_req.get("status") == "pending":
                                    prompt_state.update({
                                        "mode": "spawn",
                                        "agent_id": data.get("id"),
                                        "agent_filepath": filepath,
                                        "spawn_req": spawn_req
                                    })
                                    break
                                    
                                status = data.get("status")
                                blocker = data.get("blocker_details")
                                if status == "pending_termination" and blocker:
                                    prompt_state.update({
                                        "mode": "blocker_choice",
                                        "agent_id": data.get("id"),
                                        "agent_filepath": filepath,
                                        "blocker_details": blocker
                                    })
                                    break

                # Verify prompt state validity (in case file state changes externally)
                if prompt_state["mode"] is not None:
                    filepath = prompt_state["agent_filepath"]
                    if not os.path.exists(filepath):
                        prompt_state["mode"] = None
                    else:
                        try:
                            with open(filepath, 'r') as f:
                                data = json.load(f)
                            if prompt_state["mode"] == "spawn":
                                spawn_req = data.get("spawn_request")
                                if not spawn_req or spawn_req.get("status") != "pending":
                                    prompt_state["mode"] = None
                            elif prompt_state["mode"] in ["blocker_choice", "blocker_workaround"]:
                                status = data.get("status")
                                blocker = data.get("blocker_details")
                                if status != "pending_termination" or not blocker:
                                    prompt_state["mode"] = None
                        except Exception:
                            pass

            # 3. Update layout components
            layout["header"].update(make_header_panel())
            layout["left"].update(make_agents_table())
            layout["center"].update(make_output_panel())
            layout["right_top"].update(make_collisions_panel())
            layout["right_middle"].update(make_budget_alert_panel(prompt_state))
            layout["right_bottom"].update(make_tombstones_panel())
            layout["footer_logs"].update(make_logs_panel())
            layout["footer_input"].update(make_input_panel(input_buffer, prompt_state))
            
            # 4. Read input character non-blockingly
            import select
            try:
                rlist, _, _ = select.select([sys.stdin], [], [], 0.05)
                if rlist:
                    import tty
                    import termios
                    fd = sys.stdin.fileno()
                    old_settings = termios.tcgetattr(fd)
                    try:
                        tty.setraw(fd)
                        ch = sys.stdin.read(1)
                    finally:
                        termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
                        
                    if prompt_state["error_msg"]:
                        prompt_state["error_msg"] = None
                        
                    if ch == '\x03':  # Ctrl+C
                        raise KeyboardInterrupt
                    elif ch in ('\r', '\n'):
                        cmd_line = input_buffer.strip()
                        input_buffer = ""
                        
                        # Process based on TUI_STATE and active mode
                        if TUI_STATE == "RUNNING" and prompt_state["mode"] is not None:
                            # Handle active interactive prompts
                            if prompt_state["mode"] == "spawn":
                                filepath = prompt_state["agent_filepath"]
                                spawn_req = prompt_state["spawn_req"]
                                if cmd_line.lower() in ["y", "yes", "approve"]:
                                    spawn_req["status"] = "approved"
                                    try:
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["spawn_request"] = spawn_req
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold green][+] Spawn APPROVED for Agent {prompt_state['agent_id']}[/bold green]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                elif cmd_line.lower() in ["n", "no", "reject"]:
                                    spawn_req["status"] = "rejected"
                                    try:
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["spawn_request"] = spawn_req
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold yellow][-] Spawn REJECTED for Agent {prompt_state['agent_id']}[/bold yellow]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Invalid option. Type y or n.[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    
                            elif prompt_state["mode"] == "blocker_choice":
                                if cmd_line == "1":
                                    prompt_state["mode"] = "blocker_workaround"
                                elif cmd_line == "2":
                                    filepath = prompt_state["agent_filepath"]
                                    try:
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["steps_completed"] += 1
                                        tasks_data = load_json(MOCK_TASKS_FILE)
                                        task_id = agent_data.get("task_id")
                                        if tasks_data and task_id in tasks_data.get("tasks", {}):
                                            steps = tasks_data["tasks"][task_id].get("steps", [])
                                            agent_data["progress"] = int((agent_data["steps_completed"] / len(steps)) * 100)
                                            if agent_data["steps_completed"] < len(steps):
                                                next_step = steps[agent_data["steps_completed"]]
                                                agent_data["current_step"] = {
                                                    "step_id": next_step["step_id"],
                                                    "name": next_step["name"],
                                                    "description": next_step["description"]
                                                }
                                            else:
                                                agent_data["status"] = "completed"
                                                agent_data["current_step"] = None
                                        if agent_data["status"] != "completed":
                                            agent_data["status"] = "exploring"
                                        agent_data["blocker_details"] = None
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold green][+] Blocker bypassed for Agent {prompt_state['agent_id']}[/bold green]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                    
                                elif cmd_line == "3":
                                    filepath = prompt_state["agent_filepath"]
                                    try:
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["status"] = "dead"
                                        agent_data["blocker_details"] = None
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold red][-] Agent {prompt_state['agent_id']} terminated[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Invalid option. Enter 1, 2, or 3.[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    
                            elif prompt_state["mode"] == "blocker_workaround":
                                if cmd_line:
                                    filepath = prompt_state["agent_filepath"]
                                    blocker = prompt_state["blocker_details"]
                                    try:
                                        tombstones = load_json(TOMBSTONES_FILE) or []
                                        tombstones.append({
                                            "file_path": blocker.get("file_path", "unknown"),
                                            "tool_used": blocker.get("tool_used", "unknown"),
                                            "error_message": blocker.get("error_message", "unknown"),
                                            "fix_action": cmd_line,
                                            "timestamp": get_iso_timestamp()
                                        })
                                        save_json(TOMBSTONES_FILE, tombstones)
                                        
                                        with open(filepath, 'r') as f:
                                            agent_data = json.load(f)
                                        agent_data["status"] = "exploring"
                                        agent_data["blocker_details"] = None
                                        save_json(filepath, agent_data)
                                        prompt_state["error_msg"] = f"[bold green][+] Workaround registered for Agent {prompt_state['agent_id']}[/bold green]"
                                        prompt_state["msg_timer"] = time.time()
                                    except Exception as e:
                                        prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    prompt_state["mode"] = None
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Workaround cannot be empty.[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                        
                        elif TUI_STATE == "BUDGET_CONFIRM":
                            if not cmd_line or cmd_line.lower() in ["y", "yes"]:
                                session_budget = TUI_RECOMMENDED_CAP
                                TUI_STATE = "DESIGNER"
                            elif cmd_line.isdigit():
                                session_budget = int(cmd_line)
                                TUI_STATE = "DESIGNER"
                            else:
                                prompt_state["error_msg"] = "[bold red][-] Invalid cap. Press enter to confirm or type an integer.[/bold red]"
                                prompt_state["msg_timer"] = time.time()
                                
                        elif TUI_STATE == "DESIGNER":
                            if not cmd_line:
                                continue
                            parts = cmd_line.split(maxsplit=1)
                            cmd = parts[0].lower()
                            arg = parts[1] if len(parts) > 1 else None
                            
                            if cmd == "/run":
                                if not TUI_DESIGNER_AGENTS:
                                    prompt_state["error_msg"] = "[bold red][-] Error: Swarm cannot be empty.[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                TUI_STATE = "DECOMPOSING_AGENTS"
                                threading.Thread(target=bg_decompose_agent_goals, daemon=True).start()
                            elif cmd == "/cancel":
                                TUI_STATE = "MENU"
                            elif cmd == "/add":
                                if not arg:
                                    prompt_state["error_msg"] = "[bold red][-] Usage: /add <role> : <goal>[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                if ":" in arg:
                                    r_part, g_part = arg.split(":", 1)
                                    r = r_part.strip()
                                    g = g_part.strip()
                                else:
                                    r = arg.strip()
                                    g = None
                                if r:
                                    TUI_DESIGNER_AGENTS.append({"role": r, "goal": g})
                                    prompt_state["error_msg"] = f"[bold green][+] Added agent: {r}[/bold green]"
                                    prompt_state["msg_timer"] = time.time()
                            elif cmd == "/remove":
                                if not arg or not arg.isdigit():
                                    prompt_state["error_msg"] = "[bold red][-] Usage: /remove <num>[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                num = int(arg) - 1
                                if 0 <= num < len(TUI_DESIGNER_AGENTS):
                                    removed = TUI_DESIGNER_AGENTS.pop(num)
                                    prompt_state["error_msg"] = f"[bold yellow][-] Removed agent: {removed['role']}[/bold yellow]"
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Error: Invalid agent number.[/bold red]"
                                prompt_state["msg_timer"] = time.time()
                            elif cmd == "/edit":
                                if not arg:
                                    prompt_state["error_msg"] = "[bold red][-] Usage: /edit <num> role=<val> OR goal=<val>[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                subparts = arg.split(maxsplit=1)
                                if len(subparts) < 2 or not subparts[0].isdigit():
                                    prompt_state["error_msg"] = "[bold red][-] Usage: /edit <num> role=<val> OR goal=<val>[/bold red]"
                                    prompt_state["msg_timer"] = time.time()
                                    continue
                                num = int(subparts[0]) - 1
                                edit_arg = subparts[1]
                                if 0 <= num < len(TUI_DESIGNER_AGENTS):
                                    if "=" in edit_arg:
                                        field, val = edit_arg.split("=", 1)
                                        field = field.strip().lower()
                                        val = val.strip()
                                        if field in ["role", "goal"]:
                                            TUI_DESIGNER_AGENTS[num][field] = val
                                            prompt_state["error_msg"] = f"[bold green][+] Updated Agent {num+1} {field}.[/bold green]"
                                        else:
                                            prompt_state["error_msg"] = "[bold red][-] Field must be role or goal.[/bold red]"
                                    else:
                                        prompt_state["error_msg"] = "[bold red][-] Format: field=value.[/bold red]"
                                else:
                                    prompt_state["error_msg"] = "[bold red][-] Invalid agent number.[/bold red]"
                                prompt_state["msg_timer"] = time.time()
                            else:
                                prompt_state["error_msg"] = f"[bold red][-] Unknown designer command: {cmd}[/bold red]"
                                prompt_state["msg_timer"] = time.time()
                                
                        elif TUI_STATE in ["DECOMPOSING_MACRO", "DECOMPOSING_AGENTS"]:
                            # Ignore inputs during async operations
                            continue
                            
                        else:
                            # Normal TUI command line mode (STATE_MENU or RUNNING with no active prompt)
                            if cmd_line:
                                parts = cmd_line.split(maxsplit=1)
                                cmd = parts[0].lower()
                                arg = parts[1] if len(parts) > 1 else None
                                
                                if cmd in ["/exit", "/quit"]:
                                    raise KeyboardInterrupt
                                    
                                elif cmd in ["/clean", "/purge"]:
                                    purge_artifacts(arg)
                                    prompt_state["error_msg"] = f"[bold green][+] Cleaned target: {arg or 'all'}[/bold green]"
                                    prompt_state["msg_timer"] = time.time()
                                    
                                elif cmd in ["/add-agent", "/add-personality"]:
                                    if not arg:
                                        prompt_state["error_msg"] = "[bold red][-] Usage: /add-agent <role> : <goal>[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    else:
                                        if ":" in arg:
                                            r_part, g_part = arg.split(":", 1)
                                            role = r_part.strip()
                                            goal = g_part.strip()
                                        else:
                                            role = arg.strip()
                                            goal = None
                                        if role:
                                            predefined_personalities.append({"role": role, "goal": goal})
                                            prompt_state["error_msg"] = f"[bold green][+] Registered agent: '{role}'[/bold green]"
                                        else:
                                            prompt_state["error_msg"] = "[bold red][-] Error: Role name cannot be empty.[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                        
                                elif cmd == "/budget":
                                    if not arg or not arg.isdigit():
                                        prompt_state["error_msg"] = "[bold red][-] Usage: /budget <new_cap>[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    else:
                                        cap = int(arg)
                                        session_budget = cap
                                        orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")
                                        if os.path.exists(orchestrator_file):
                                            try:
                                                orc_state = load_json(orchestrator_file) or {}
                                                orc_state["budget_limit"] = cap
                                                save_json(orchestrator_file, orc_state)
                                                prompt_state["error_msg"] = f"[bold green][+] Budget updated dynamically to {cap}[/bold green]"
                                            except Exception as e:
                                                prompt_state["error_msg"] = f"[bold red][-] Error updating budget: {e}[/bold red]"
                                        else:
                                            prompt_state["error_msg"] = f"[bold green][+] Budget cap updated to {cap}[/bold green]"
                                        prompt_state["msg_timer"] = time.time()
                                        
                                elif cmd == "/view":
                                    if not arg:
                                        current_view = "combined"
                                        prompt_state["error_msg"] = "[bold green][+] View set to: Combined Hierarchy[/bold green]"
                                    else:
                                        target_view = arg.strip().lower()
                                        if target_view in ["combined", "main"]:
                                            current_view = "combined"
                                            prompt_state["error_msg"] = "[bold green][+] View set to: Combined Hierarchy[/bold green]"
                                        else:
                                            if target_view.isdigit():
                                                target_view = f"{int(target_view):03d}"
                                            current_view = target_view
                                            prompt_state["error_msg"] = f"[bold green][+] View set to Agent: {current_view}[/bold green]"
                                    prompt_state["msg_timer"] = time.time()
                                    
                                elif cmd == "/trace":
                                    if not arg:
                                        prompt_state["error_msg"] = "[bold red][-] Usage: /trace <agent_id>[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    else:
                                        target_agent = arg.strip()
                                        if target_agent.isdigit():
                                            target_agent = f"{int(target_agent):03d}"
                                            
                                        import causal_tracer
                                        conn = causal_tracer.get_db_connection()
                                        try:
                                            node = conn.execute("SELECT id FROM trace_nodes WHERE id = ?", (f"agent_{target_agent}",)).fetchone()
                                        except Exception:
                                            node = None
                                        finally:
                                            conn.close()
                                            
                                        if not node:
                                            prompt_state["error_msg"] = f"[bold red][-] Agent {target_agent} not found in causal traces[/bold red]"
                                        else:
                                            current_view = f"trace_{target_agent}"
                                            prompt_state["error_msg"] = f"[bold green][+] View set to trace: Agent {target_agent}[/bold green]"
                                        prompt_state["msg_timer"] = time.time()
                                        
                                elif cmd in ["/memory", "/history"]:
                                    current_view = "memory"
                                    prompt_state["error_msg"] = "[bold green][+] View set to Episodic Memory Archives[/bold green]"
                                    prompt_state["msg_timer"] = time.time()
                                    
                                elif cmd == "/help":
                                    current_view = "help"
                                    prompt_state["error_msg"] = "[bold green][+] View set to Help Menu[/bold green]"
                                    prompt_state["msg_timer"] = time.time()
                                    
                                elif cmd == "/prune" and TUI_STATE == "RUNNING":
                                    if not arg:
                                        prompt_state["error_msg"] = "[bold red][-] Usage: /prune <agent_id>[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    else:
                                        agent_id = arg.strip().zfill(3)
                                        success, msg = handle_dashboard_pruning(agent_id)
                                        if success:
                                            prompt_state["error_msg"] = f"[bold green][+] {msg}[/bold green]"
                                            prompt_state["msg_timer"] = time.time()
                                        else:
                                            prompt_state["error_msg"] = f"[bold red][-] {msg}[/bold red]"
                                            prompt_state["msg_timer"] = time.time()
                                            
                                elif cmd == "/approve" and TUI_STATE == "RUNNING":
                                    if not arg:
                                        prompt_state["error_msg"] = "[bold red][-] Usage: /approve <agent_id>[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    else:
                                        target_aid = arg.strip().zfill(3)
                                        filepath = os.path.join(AGENTS_DIR, f"agent_{target_aid}.json")
                                        if os.path.exists(filepath):
                                            try:
                                                with open(filepath, 'r') as f:
                                                    agent_data = json.load(f)
                                                spawn_req = agent_data.get("spawn_request")
                                                if spawn_req and spawn_req.get("status") == "pending":
                                                    spawn_req["status"] = "approved"
                                                    agent_data["spawn_request"] = spawn_req
                                                    save_json(filepath, agent_data)
                                                    prompt_state["error_msg"] = f"[bold green][+] Spawn APPROVED for Agent {target_aid}[/bold green]"
                                                else:
                                                    prompt_state["error_msg"] = f"[bold red][-] No pending spawn request for Agent {target_aid}[/bold red]"
                                            except Exception as e:
                                                prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        else:
                                            prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} not found[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                        
                                elif cmd == "/reject" and TUI_STATE == "RUNNING":
                                    if not arg:
                                        prompt_state["error_msg"] = "[bold red][-] Usage: /reject <agent_id>[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    else:
                                        target_aid = arg.strip().zfill(3)
                                        filepath = os.path.join(AGENTS_DIR, f"agent_{target_aid}.json")
                                        if os.path.exists(filepath):
                                            try:
                                                with open(filepath, 'r') as f:
                                                    agent_data = json.load(f)
                                                spawn_req = agent_data.get("spawn_request")
                                                if spawn_req and spawn_req.get("status") == "pending":
                                                    spawn_req["status"] = "rejected"
                                                    agent_data["spawn_request"] = spawn_req
                                                    save_json(filepath, agent_data)
                                                    prompt_state["error_msg"] = f"[bold yellow][-] Spawn REJECTED for Agent {target_aid}[/bold yellow]"
                                                else:
                                                    prompt_state["error_msg"] = f"[bold red][-] No pending spawn request for Agent {target_aid}[/bold red]"
                                            except Exception as e:
                                                prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        else:
                                            prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} not found[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                        
                                elif cmd == "/resolve" and TUI_STATE == "RUNNING":
                                    subparts = arg.strip().split() if arg else []
                                    if len(subparts) < 2:
                                        prompt_state["error_msg"] = "[bold red][-] Usage: /resolve <agent_id> <1|2|3>[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                    else:
                                        target_aid = subparts[0].zfill(3)
                                        choice = subparts[1]
                                        filepath = os.path.join(AGENTS_DIR, f"agent_{target_aid}.json")
                                        if os.path.exists(filepath):
                                            try:
                                                with open(filepath, 'r') as f:
                                                    agent_data = json.load(f)
                                                status = agent_data.get("status")
                                                blocker = agent_data.get("blocker_details")
                                                if status == "pending_termination" and blocker:
                                                    if choice == "1":
                                                        prompt_state.update({
                                                            "mode": "blocker_workaround",
                                                            "agent_id": target_aid,
                                                            "agent_filepath": filepath,
                                                            "blocker_details": blocker
                                                        })
                                                        prompt_state["error_msg"] = f"[bold yellow][*] Enter manual workaround for Agent {target_aid} below...[/bold yellow]"
                                                    elif choice == "2":
                                                        tombstones = load_json(TOMBSTONES_FILE) or []
                                                        tombstones.append({
                                                            "file_path": blocker.get("file_path", "unknown"),
                                                            "tool_used": blocker.get("tool_used", "unknown"),
                                                            "error_message": blocker.get("error_message", "unknown"),
                                                            "fix_action": "Bypassed by User command",
                                                            "timestamp": get_iso_timestamp()
                                                        })
                                                        save_json(TOMBSTONES_FILE, tombstones)
                                                        agent_data["status"] = "exploring"
                                                        agent_data["blocker_details"] = None
                                                        save_json(filepath, agent_data)
                                                        prompt_state["error_msg"] = f"[bold green][+] Agent {target_aid} bypass recorded. Resuming...[/bold green]"
                                                    elif choice == "3":
                                                        success, msg = handle_dashboard_pruning(target_aid)
                                                        if success:
                                                            prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} pruned[/bold red]"
                                                        else:
                                                            prompt_state["error_msg"] = f"[bold red][-] {msg}[/bold red]"
                                                    else:
                                                        prompt_state["error_msg"] = "[bold red][-] Invalid choice. Must be 1, 2, or 3.[/bold red]"
                                                else:
                                                    prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} is not blocked[/bold red]"
                                            except Exception as e:
                                                prompt_state["error_msg"] = f"[bold red][-] Error: {e}[/bold red]"
                                        else:
                                            prompt_state["error_msg"] = f"[bold red][-] Agent {target_aid} not found[/bold red]"
                                        prompt_state["msg_timer"] = time.time()
                                        
                                else:
                                    # State is STATE_MENU, input is a new task query!
                                    # Start macro goal decomposition in a background thread!
                                    TUI_MACRO_GOAL = cmd_line
                                    TUI_STATE = "DECOMPOSING_MACRO"
                                    threading.Thread(target=bg_decompose_macro_goal, args=(cmd_line,), daemon=True).start()
                                    
                    elif ord(ch) in (127, 8):
                        input_buffer = input_buffer[:-1]
                    elif len(ch) == 1 and (32 <= ord(ch) <= 126):
                        input_buffer += ch
            except select.error:
                pass
            time.sleep(0.05)


if __name__ == "__main__":
    main()
