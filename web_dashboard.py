#!/usr/bin/env python3
"""
Proximity Swarm V3 — Web Dashboard Server
A lightweight Python HTTP server providing REST API + SSE for the web UI.
Uses only Python stdlib — zero external dependencies.

Usage:
    python3 web_dashboard.py [--port 8080] [--llm-provider ollama] [--ollama-model gemma4:latest]
"""

import os
import sys
import socket
socket.getfqdn = lambda x=None: "localhost" if x is None else x
import json
time_import = None # Keep layout intact
import time
import threading
import subprocess
import argparse
import urllib.parse
import hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_DIR = os.path.join(BASE_DIR, ".proximity_swarm")
AGENTS_DIR = os.path.join(STATE_DIR, "agents")
COLLISIONS_DIR = os.path.join(STATE_DIR, "collisions")
WORKSPACES_DIR = os.path.join(STATE_DIR, "workspaces")
TOMBSTONES_FILE = os.path.join(STATE_DIR, "tombstones.json")
LOG_FILE = os.path.join(STATE_DIR, "monitor.log")
ORCHESTRATOR_FILE = os.path.join(STATE_DIR, "orchestrator.json")
MOCK_TASKS_FILE = os.path.join(BASE_DIR, "mock_tasks.json")
STATIC_DIR = os.path.join(BASE_DIR, "static")

# ---------------------------------------------------------------------------
# Global server state
# ---------------------------------------------------------------------------
server_state = {
    "supervisor_proc": None,
    "llm_provider": "ollama",
    "ollama_model": "gemma4:latest",
    "session_budget": 20000,
    "predefined_agents": [],
    "swarm_running": False,
    "macro_goal": "",
    "auto_approve_spawns": False,
}

# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def load_json(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, "r") as f:
            return json.load(f)
    except Exception:
        return None


def save_json(filepath, data):
    try:
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        with open(filepath, "w") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


def write_to_monitor_log(message, level="INFO"):
    os.makedirs(STATE_DIR, exist_ok=True)
    try:
        timestamp = time.strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a") as f:
            f.write(f"{timestamp} [{level}] {message}\n")
    except Exception:
        pass

# ---------------------------------------------------------------------------
# State readers
# ---------------------------------------------------------------------------

def get_all_agents():
    agents = []
    if not os.path.exists(AGENTS_DIR):
        return agents
    try:
        for filename in sorted(os.listdir(AGENTS_DIR)):
            if filename.startswith("agent_") and filename.endswith(".json"):
                data = load_json(os.path.join(AGENTS_DIR, filename))
                if data:
                    agents.append(data)
    except Exception:
        pass
    return agents


def get_agent(agent_id):
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    return load_json(filepath)


def get_collisions():
    collisions = []
    if not os.path.exists(COLLISIONS_DIR):
        return collisions
    try:
        for filename in sorted(os.listdir(COLLISIONS_DIR)):
            if filename.endswith(".json"):
                data = load_json(os.path.join(COLLISIONS_DIR, filename))
                if data:
                    collisions.append(data)
    except Exception:
        pass
    return collisions


def get_tombstones():
    data = load_json(TOMBSTONES_FILE)
    return data if isinstance(data, list) else []


def get_log_tail(n=100):
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
        return [l.rstrip() for l in lines[-n:]]
    except Exception:
        return []


def get_orchestrator():
    return load_json(ORCHESTRATOR_FILE) or {}


def get_budget_alert():
    alert_file = os.path.join(STATE_DIR, "budget_alert.json")
    return load_json(alert_file) or {}


def get_workspace_files(agent_id):
    ws_dir = os.path.join(WORKSPACES_DIR, f"agent_{agent_id}")
    if not os.path.exists(ws_dir):
        return {"files": [], "contents": {}}
    files = []
    contents = {}
    try:
        for root, dirs, filenames in os.walk(ws_dir):
            for fname in filenames:
                if fname.endswith((".pyc", ".pyo")) or "__pycache__" in root:
                    continue
                full_path = os.path.join(root, fname)
                rel_path = os.path.relpath(full_path, ws_dir)
                files.append(rel_path)
                try:
                    with open(full_path, "r", errors="replace") as f:
                        contents[rel_path] = f.read()
                except Exception:
                    contents[rel_path] = "[Binary or unreadable file]"
    except Exception:
        pass
    return {"files": files, "contents": contents}


def _agent_workspace_text(agent_id):
    """Concatenate an agent's workspace files into a markdown block."""
    data = get_workspace_files(agent_id)
    files = sorted(data.get("files", []))
    contents = data.get("contents", {})
    if not files:
        return ""
    blocks = []
    for f in files:
        body = contents.get(f, "")
        blocks.append(f"**`{f}`**\n\n```\n{body}\n```")
    return "\n\n".join(blocks)


def _synthesize_node(node_id, tree, seen=None):
    """Recursively merge an agent's deliverables with its sub-agents' (design_doc §7)."""
    if seen is None:
        seen = set()
    if node_id in seen:
        return ""
    seen.add(node_id)
    node = tree[node_id]
    state = node["state"]
    role = state.get("personality", "Generalist")
    goal = state.get("goal", "")
    content = _agent_workspace_text(node_id)
    children = sorted(node["children"])
    if not children:
        return content if content.strip() else f"*(No output from Agent {node_id} yet)*"
    child_blocks = []
    for cid in children:
        csyn = _synthesize_node(cid, tree, seen)
        cstate = tree[cid]["state"]
        child_blocks.append(
            f"#### Agent {cid} ({cstate.get('personality', 'Generalist')}): {cstate.get('goal', '')}\n\n{csyn}"
        )
    parts = [f"## Agent {node_id} ({role}): {goal}"]
    parts.append(content if content.strip() else f"*(Agent {node_id} is coordinating sub-agents)*")
    parts.append(f"### Sub-agent contributions to Agent {node_id}")
    parts.append("\n\n---\n\n".join(child_blocks))
    return "\n\n".join(parts)


def build_synthesis():
    """Deterministic hierarchical artifact synthesis (design_doc §7), no LLM required.

    Walks the agent state tree and merges each agent's workspace deliverables with its
    sub-agents' contributions bottom-up into a single combined markdown report.
    """
    tree = {}
    for data in get_all_agents():
        if not data or "id" not in data:
            continue
        aid = data["id"]
        pid = data.get("parent_id")
        if pid == "None" or not pid:
            pid = None
        tree[aid] = {"id": aid, "parent_id": pid, "children": [], "state": data}
    for aid, node in tree.items():
        pid = node["parent_id"]
        if pid and pid in tree and aid not in tree[pid]["children"]:
            tree[pid]["children"].append(aid)

    if not tree:
        return {"markdown": "No agent states found. Launch a swarm to generate a synthesis."}

    roots = sorted([aid for aid, n in tree.items() if n["parent_id"] is None]) or sorted(tree.keys())
    if len(roots) == 1:
        markdown = _synthesize_node(roots[0], tree)
    else:
        markdown = "# Combined swarm artifact\n\n" + "\n\n---\n\n".join(
            _synthesize_node(r, tree) for r in roots
        )
    return {"markdown": markdown}


def get_memory_episodes():
    try:
        sys.path.insert(0, BASE_DIR)
        import memory_store
        memory_store.init_db()
        conn = memory_store.get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, goal, role, status, reflection, created_at FROM episodic_memories ORDER BY created_at DESC"
        )
        rows = cursor.fetchall()
        conn.close()
        return [dict(r) for r in rows]
    except Exception:
        return []


def get_trace_data(agent_id):
    try:
        sys.path.insert(0, BASE_DIR)
        import causal_tracer
        mermaid = causal_tracer.generate_mermaid_graph(agent_id=agent_id)
        
        # Get event timeline
        conn = causal_tracer.get_db_connection()
        edges = conn.execute(
            "SELECT source, target, type, timestamp, details FROM trace_edges ORDER BY timestamp ASC"
        ).fetchall()
        conn.close()
        
        timeline = []
        for e in edges:
            source, target = e["source"], e["target"]
            if f"agent_{agent_id}" in source or f"agent_{agent_id}" in target:
                details = {}
                try:
                    details = json.loads(e["details"]) if e["details"] else {}
                except Exception:
                    pass
                timeline.append({
                    "source": source,
                    "target": target,
                    "type": e["type"],
                    "timestamp": e["timestamp"],
                    "details": details,
                })
        
        return {"mermaid": mermaid, "timeline": timeline}
    except Exception as ex:
        return {"mermaid": "graph TD\n    empty[\"No trace data\"]", "timeline": [], "error": str(ex)}


def compute_state_hash():
    """Compute a hash of the current swarm state for change detection."""
    parts = []
    if os.path.exists(AGENTS_DIR):
        try:
            for f in sorted(os.listdir(AGENTS_DIR)):
                fp = os.path.join(AGENTS_DIR, f)
                parts.append(f"{f}:{os.path.getmtime(fp):.3f}")
        except Exception:
            pass
    if os.path.exists(COLLISIONS_DIR):
        try:
            for f in sorted(os.listdir(COLLISIONS_DIR)):
                fp = os.path.join(COLLISIONS_DIR, f)
                parts.append(f"c_{f}:{os.path.getmtime(fp):.3f}")
        except Exception:
            pass
    for extra in [TOMBSTONES_FILE, LOG_FILE, ORCHESTRATOR_FILE]:
        if os.path.exists(extra):
            try:
                parts.append(f"{os.path.basename(extra)}:{os.path.getmtime(extra):.3f}")
            except Exception:
                pass
    parts.append(f"running:{server_state['swarm_running']}")
    raw = "|".join(parts)
    return hashlib.md5(raw.encode()).hexdigest()


def get_full_state():
    agents = get_all_agents()
    
    # Determine pending decisions
    pending_spawns = []
    pending_blockers = []
    for a in agents:
        aid = a.get("id", "")
        sr = a.get("spawn_request") or {}
        if sr.get("status") == "pending":
            pending_spawns.append({
                "agent_id": aid,
                "goal": sr.get("goal", ""),
                "reason": sr.get("reason", "Accelerate sub-task execution."),
            })
        if a.get("status") == "pending_termination" and a.get("blocker_details"):
            pending_blockers.append({
                "agent_id": aid,
                "blocker": a["blocker_details"],
            })
    
    return {
        "agents": agents,
        "collisions": get_collisions(),
        "tombstones": get_tombstones(),
        "orchestrator": get_orchestrator(),
        "budget_alert": get_budget_alert(),
        "logs": get_log_tail(80),
        "pending_spawns": pending_spawns,
        "pending_blockers": pending_blockers,
        "swarm_running": server_state["swarm_running"],
        "macro_goal": server_state["macro_goal"],
        "session_budget": server_state["session_budget"],
        "predefined_agents": server_state["predefined_agents"],
        "auto_approve_spawns": server_state.get("auto_approve_spawns", False),
        "state_hash": compute_state_hash(),
    }

# ---------------------------------------------------------------------------
# Swarm launch helpers (reuses supervisor.py logic)
# ---------------------------------------------------------------------------

def generate_task_steps_via_llm(goal):
    """Use Ollama to decompose a goal into task steps."""
    try:
        import urllib.request
        prompt = f"""You are a task decomposition engine. Break the following goal into 2-5 concrete execution steps.

Goal: {goal}

Return ONLY a valid JSON array of step objects. Each step has:
- "step_id": integer starting at 1
- "name": short step name
- "description": what this step does
- "touched_files": list of file paths this step will create/edit
- "tools": list of tools used (e.g. "edit_file", "pytest", "gcc")

Example:
[{{"step_id": 1, "name": "Write auth module", "description": "Create authentication logic", "touched_files": ["src/auth.py"], "tools": ["edit_file"]}}]

JSON:"""
        body = json.dumps({
            "model": server_state["ollama_model"],
            "prompt": prompt,
            "stream": False,
        }).encode()
        req = urllib.request.Request(
            "http://localhost:11434/api/generate",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode())
        text = result.get("response", "")
        # Extract JSON from response
        start = text.find("[")
        end = text.rfind("]") + 1
        if start >= 0 and end > start:
            return json.loads(text[start:end])
    except Exception as ex:
        write_to_monitor_log(f"LLM step decomposition failed: {ex}", "WARN")
    return None


def register_dynamic_task(task_id, goal, steps):
    """Register a dynamically generated task into mock_tasks.json."""
    tasks_data = load_json(MOCK_TASKS_FILE)
    if not tasks_data:
        tasks_data = {"tasks": {}}
    tasks_data["tasks"][task_id] = {
        "id": task_id,
        "goal": goal,
        "steps": steps,
        "is_dynamic": True,
    }
    save_json(MOCK_TASKS_FILE, tasks_data)


def launch_swarm(goal, agents_config, budget):
    """Launch the supervisor subprocess with the given agent configs."""
    global server_state

    if server_state["swarm_running"]:
        return False, "Swarm is already running"

    server_state["macro_goal"] = goal
    server_state["session_budget"] = budget
    server_state["swarm_running"] = True

    write_to_monitor_log(f"Launching swarm for goal: '{goal}' with {len(agents_config)} agents", "INFO")

    def _bg_launch():
        try:
            # Prepare orchestrator.json
            os.makedirs(STATE_DIR, exist_ok=True)
            sub_swarms = {
                "swarm_001": {
                    "id": "swarm_001",
                    "goal": goal,
                    "role": "Primary Swarm",
                    "dependencies": [],
                    "status": "pending",
                    "agent_ids": [a["agent_id"] for a in agents_config],
                }
            }
            save_json(ORCHESTRATOR_FILE, {"macro_goal": goal, "sub_swarms": sub_swarms})

            # Decompose goals and register tasks
            now_ts = int(time.time())
            final_configs = []
            for idx, agent in enumerate(agents_config):
                agent_id = agent.get("agent_id", f"{idx + 1:03d}")
                agent_role = agent.get("personality", agent.get("role", "Generalist"))
                agent_goal = agent.get("goal", goal)

                write_to_monitor_log(f"Decomposing goal for Agent {agent_id} ({agent_role})...", "INFO")
                steps = generate_task_steps_via_llm(agent_goal)
                if not steps:
                    steps = [
                        {
                            "step_id": 1,
                            "name": "General Execution",
                            "description": f"Perform tasks for: {agent_goal}",
                            "touched_files": [f"src/agent_{agent_id}_output.md"],
                            "tools": ["edit_file"],
                        }
                    ]
                task_id = f"task_dynamic_{now_ts}_{idx}"
                register_dynamic_task(task_id, agent_goal, steps)
                final_configs.append({
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "personality": agent_role,
                    "goal": agent_goal,
                    "sub_swarm_id": "swarm_001",
                })

            # Launch supervisor subprocess
            cmd = [
                sys.executable,
                os.path.join(BASE_DIR, "supervisor.py"),
                "--agents-config", json.dumps(final_configs),
                "--llm-provider", server_state["llm_provider"],
                "--step-delay", "1.5",
                "--budget", str(budget),
            ]
            if server_state.get("auto_approve_spawns"):
                cmd.append("--auto-approve-spawns")

            write_to_monitor_log(f"Launching supervisor: {' '.join(cmd[:6])}...", "INFO")

            proc = subprocess.Popen(
                cmd,
                cwd=BASE_DIR,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )
            server_state["supervisor_proc"] = proc
            server_state["predefined_agents"] = []

            # Monitor supervisor in background
            def monitor_proc():
                proc.wait()
                server_state["swarm_running"] = False
                server_state["supervisor_proc"] = None
                write_to_monitor_log("Supervisor process exited.", "INFO")

            t = threading.Thread(target=monitor_proc, daemon=True)
            t.start()
        except Exception as ex:
            server_state["swarm_running"] = False
            write_to_monitor_log(f"Failed to launch supervisor in background: {ex}", "ERROR")

    threading.Thread(target=_bg_launch, daemon=True).start()
    return True, f"Swarm launched with {len(agents_config)} agents"

# ---------------------------------------------------------------------------
# Action handlers
# ---------------------------------------------------------------------------

def handle_approve(agent_id):
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    data = load_json(filepath)
    if not data:
        return False, "Agent not found"
    sr = data.get("spawn_request", {})
    if sr.get("status") != "pending":
        return False, "No pending spawn request"
    sr["status"] = "approved"
    data["spawn_request"] = sr
    save_json(filepath, data)
    write_to_monitor_log(f"Spawn request for Agent {agent_id} APPROVED via web UI.", "INFO")
    return True, "Spawn approved"


def handle_reject(agent_id):
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    data = load_json(filepath)
    if not data:
        return False, "Agent not found"
    sr = data.get("spawn_request", {})
    if sr.get("status") != "pending":
        return False, "No pending spawn request"
    sr["status"] = "rejected"
    data["spawn_request"] = sr
    save_json(filepath, data)
    write_to_monitor_log(f"Spawn request for Agent {agent_id} REJECTED via web UI.", "INFO")
    return True, "Spawn rejected"


def handle_resolve(agent_id, choice):
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    data = load_json(filepath)
    if not data:
        return False, "Agent not found"

    choices_map = {1: "workaround", 2: "bypass", 3: "kill"}
    resolution = choices_map.get(choice, "workaround")

    if resolution == "kill":
        data["status"] = "dead"
        # Add tombstone
        tombstones = get_tombstones()
        tombstones.append({
            "agent_id": agent_id,
            "goal": data.get("goal", ""),
            "reason": f"Killed via web UI blocker resolution",
            "blocker": data.get("blocker_details", {}),
            "timestamp": time.time(),
        })
        save_json(TOMBSTONES_FILE, tombstones)
    elif resolution == "bypass":
        data["status"] = "exploring"
        if "blocker_details" in data:
            del data["blocker_details"]
        current_step = data.get("current_step", 0)
        data["current_step"] = current_step + 1
    else:  # workaround
        data["status"] = "exploring"
        if "blocker_details" in data:
            del data["blocker_details"]

    save_json(filepath, data)
    write_to_monitor_log(f"Agent {agent_id} blocker resolved: {resolution} via web UI.", "INFO")
    return True, f"Resolved with: {resolution}"


def handle_prune(agent_id):
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    data = load_json(filepath)
    if not data:
        return False, "Agent not found"

    # Check it's a leaf agent
    all_agents = get_all_agents()
    children = [a for a in all_agents if a.get("parent_id") == agent_id and a.get("status") not in ("completed", "dead")]
    if children:
        return False, f"Agent {agent_id} is not a leaf — it has {len(children)} active children"

    data["status"] = "dead"
    save_json(filepath, data)

    tombstones = get_tombstones()
    tombstones.append({
        "agent_id": agent_id,
        "goal": data.get("goal", ""),
        "reason": "Pruned via web UI",
        "is_pruned": True,
        "timestamp": time.time(),
    })
    save_json(TOMBSTONES_FILE, tombstones)
    write_to_monitor_log(f"Agent {agent_id} PRUNED via web UI.", "INFO")
    return True, "Agent pruned"


def handle_clean(target):
    import shutil
    cleaned = []
    if target in ("logs", "all"):
        if os.path.exists(LOG_FILE):
            os.remove(LOG_FILE)
            cleaned.append("logs")
    if target in ("workspaces", "all"):
        if os.path.exists(WORKSPACES_DIR):
            shutil.rmtree(WORKSPACES_DIR, ignore_errors=True)
            os.makedirs(WORKSPACES_DIR, exist_ok=True)
            cleaned.append("workspaces")
    if target in ("collisions", "all"):
        if os.path.exists(COLLISIONS_DIR):
            shutil.rmtree(COLLISIONS_DIR, ignore_errors=True)
            os.makedirs(COLLISIONS_DIR, exist_ok=True)
            cleaned.append("collisions")
    if target in ("tombstones", "all"):
        save_json(TOMBSTONES_FILE, [])
        cleaned.append("tombstones")
    if target in ("memory", "all"):
        try:
            import memory_store
            memory_store.clean_memories()
            cleaned.append("memory")
        except Exception:
            pass
    if target in ("agents", "all"):
        if os.path.exists(AGENTS_DIR):
            shutil.rmtree(AGENTS_DIR, ignore_errors=True)
            os.makedirs(AGENTS_DIR, exist_ok=True)
            cleaned.append("agents")
    if target == "all":
        if os.path.exists(ORCHESTRATOR_FILE):
            os.remove(ORCHESTRATOR_FILE)
        alert_file = os.path.join(STATE_DIR, "budget_alert.json")
        if os.path.exists(alert_file):
            os.remove(alert_file)
        cleaned.append("orchestrator")
    return cleaned


def handle_edit_agent(agent_id, updates):
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    data = load_json(filepath)
    if not data:
        return False, "Agent not found"
    for key in ("goal", "role", "personality", "status", "token_budget", "subtree_token_budget"):
        if key in updates:
            data[key] = updates[key]
    save_json(filepath, data)
    write_to_monitor_log(f"Agent {agent_id} updated via web UI: {updates}", "INFO")
    return True, "Agent updated"


def handle_chat_message(agent_id, message):
    """Append a user chat message to the agent's chat_messages array."""
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    data = load_json(filepath)
    if not data:
        return False, "Agent not found"
    if "chat_messages" not in data:
        data["chat_messages"] = []
    data["chat_messages"].append({
        "role": "user",
        "content": message,
        "timestamp": time.time(),
        "processed": False,
    })
    save_json(filepath, data)
    write_to_monitor_log(f"Chat message sent to Agent {agent_id}: {message[:80]}...", "INFO")
    return True, "Message sent"


def get_chat_messages(agent_id):
    """Return the agent's chat_messages array."""
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    data = load_json(filepath)
    if not data:
        return []
    return data.get("chat_messages", [])


def handle_set_agent_budget(agent_id, token_budget=None, subtree_token_budget=None):
    """Set per-node and/or subtree token budget for a specific agent."""
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent_id}.json")
    data = load_json(filepath)
    if not data:
        return False, "Agent not found"
    if token_budget is not None:
        data["token_budget"] = int(token_budget)
    if subtree_token_budget is not None:
        data["subtree_token_budget"] = int(subtree_token_budget)
    save_json(filepath, data)
    write_to_monitor_log(f"Budget set for Agent {agent_id}: node={token_budget}, subtree={subtree_token_budget}", "INFO")
    return True, "Budget updated"


def handle_redistribute_budget(parent_id, strategy="equal"):
    """Redistribute a parent's subtree budget among its children."""
    all_agents = get_all_agents()
    parent = None
    for a in all_agents:
        if a.get("id") == parent_id:
            parent = a
            break
    if not parent:
        return False, "Parent agent not found"

    children = [a for a in all_agents if a.get("parent_id") == parent_id
                and a.get("status") not in ("completed", "dead")]
    if not children:
        return False, "No active children to redistribute to"

    subtree_budget = parent.get("subtree_token_budget", server_state["session_budget"])
    parent_used = parent.get("output_tokens", 0)
    remaining = max(subtree_budget - parent_used, 0)

    if strategy == "equal":
        per_child = remaining // len(children) if children else remaining
        for child in children:
            filepath = os.path.join(AGENTS_DIR, f"agent_{child['id']}.json")
            cdata = load_json(filepath)
            if cdata:
                cdata["token_budget"] = per_child
                cdata["subtree_token_budget"] = per_child
                save_json(filepath, cdata)
    elif strategy == "weighted":
        # Allocate more to agents closer to completion
        total_progress = sum(a.get("progress", 0) or 0 for a in children)
        if total_progress == 0:
            total_progress = len(children)  # fallback to equal
            weights = [1] * len(children)
        else:
            weights = [(a.get("progress", 0) or 0) for a in children]
        weight_sum = sum(weights) or 1
        for i, child in enumerate(children):
            share = int(remaining * weights[i] / weight_sum)
            filepath = os.path.join(AGENTS_DIR, f"agent_{child['id']}.json")
            cdata = load_json(filepath)
            if cdata:
                cdata["token_budget"] = share
                cdata["subtree_token_budget"] = share
                save_json(filepath, cdata)
    elif strategy == "priority":
        # Use priority_weight field if set, else default to 1
        weights = [a.get("priority_weight", 1) for a in children]
        weight_sum = sum(weights) or 1
        for i, child in enumerate(children):
            share = int(remaining * weights[i] / weight_sum)
            filepath = os.path.join(AGENTS_DIR, f"agent_{child['id']}.json")
            cdata = load_json(filepath)
            if cdata:
                cdata["token_budget"] = share
                cdata["subtree_token_budget"] = share
                save_json(filepath, cdata)

    write_to_monitor_log(f"Budget redistributed for children of Agent {parent_id} using '{strategy}' strategy. Remaining pool: {remaining}", "INFO")
    return True, f"Redistributed {remaining} tokens among {len(children)} children using {strategy} strategy"

# ---------------------------------------------------------------------------
# HTTP Request Handler
# ---------------------------------------------------------------------------

MIME_TYPES = {
    ".html": "text/html",
    ".css": "text/css",
    ".js": "application/javascript",
    ".json": "application/json",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".svg": "image/svg+xml",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
}


class SwarmRequestHandler(BaseHTTPRequestHandler):

    def log_message(self, format, *args):
        """Suppress default access log noise."""
        pass

    def send_json(self, data, status=200):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def send_text(self, text, status=200, content_type="text/plain"):
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        try:
            return json.loads(self.rfile.read(length).decode("utf-8"))
        except Exception:
            return {}

    # -----------------------------------------------------------------------
    # GET routes
    # -----------------------------------------------------------------------
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"

        # --- Static files ---
        if path == "/" or path == "":
            return self.serve_static("index.html")
        if path.startswith("/static/"):
            return self.serve_static(path[len("/static/"):])

        # --- SSE stream ---
        if path == "/api/events":
            return self.handle_sse()

        # --- API routes ---
        if path == "/api/state":
            return self.send_json(get_full_state())
        if path == "/api/agents":
            return self.send_json(get_all_agents())
        if path.startswith("/api/agents/") and path.endswith("/chat"):
            agent_id = path.split("/api/agents/")[1].replace("/chat", "")
            return self.send_json(get_chat_messages(agent_id))
        if path.startswith("/api/agents/"):
            agent_id = path.split("/api/agents/")[1]
            data = get_agent(agent_id)
            if data:
                return self.send_json(data)
            return self.send_json({"error": "Agent not found"}, 404)
        if path == "/api/collisions":
            return self.send_json(get_collisions())
        if path == "/api/tombstones":
            return self.send_json(get_tombstones())
        if path == "/api/logs":
            return self.send_json({"lines": get_log_tail(200)})
        if path == "/api/memory":
            return self.send_json(get_memory_episodes())
        if path.startswith("/api/trace/"):
            agent_id = path.split("/api/trace/")[1]
            return self.send_json(get_trace_data(agent_id))
        if path.startswith("/api/workspaces/"):
            agent_id = path.split("/api/workspaces/")[1]
            return self.send_json(get_workspace_files(agent_id))
        if path == "/api/synthesis":
            return self.send_json(build_synthesis())

        self.send_json({"error": "Not found"}, 404)

    # -----------------------------------------------------------------------
    # POST routes
    # -----------------------------------------------------------------------
    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        body = self.read_body()

        if path == "/api/config":
            provider = body.get("llm_provider")
            if provider in ["ollama", "gemini"]:
                server_state["llm_provider"] = provider
                write_to_monitor_log(f"LLM Provider updated to {provider} via web UI.", "INFO")
            if "auto_approve_spawns" in body:
                server_state["auto_approve_spawns"] = bool(body["auto_approve_spawns"])
                write_to_monitor_log(f"Auto-approve spawns updated to {server_state['auto_approve_spawns']} via web UI.", "INFO")
            return self.send_json({
                "success": True, 
                "llm_provider": server_state["llm_provider"],
                "auto_approve_spawns": server_state.get("auto_approve_spawns", False)
            })

        if path == "/api/run":
            goal = body.get("goal", "")
            agents = body.get("agents", [])
            budget = body.get("budget", server_state["session_budget"])
            if not goal:
                return self.send_json({"error": "Goal is required"}, 400)
            if not agents:
                # Default single agent
                agents = [{"agent_id": "001", "personality": "Generalist", "goal": goal}]
            ok, msg = launch_swarm(goal, agents, budget)
            return self.send_json({"success": ok, "message": msg}, 200 if ok else 500)

        if path.startswith("/api/approve/"):
            agent_id = path.split("/api/approve/")[1]
            ok, msg = handle_approve(agent_id)
            return self.send_json({"success": ok, "message": msg})

        if path.startswith("/api/reject/"):
            agent_id = path.split("/api/reject/")[1]
            ok, msg = handle_reject(agent_id)
            return self.send_json({"success": ok, "message": msg})

        if path.startswith("/api/resolve/"):
            agent_id = path.split("/api/resolve/")[1]
            choice = body.get("choice", 1)
            ok, msg = handle_resolve(agent_id, int(choice))
            return self.send_json({"success": ok, "message": msg})

        if path.startswith("/api/prune/"):
            agent_id = path.split("/api/prune/")[1]
            ok, msg = handle_prune(agent_id)
            return self.send_json({"success": ok, "message": msg})

        if path == "/api/budget":
            new_budget = body.get("budget", server_state["session_budget"])
            server_state["session_budget"] = int(new_budget)
            write_to_monitor_log(f"Budget cap updated to {new_budget} via web UI.", "INFO")
            return self.send_json({"success": True, "budget": int(new_budget)})

        if path == "/api/clean":
            target = body.get("target", "all")
            cleaned = handle_clean(target)
            return self.send_json({"success": True, "cleaned": cleaned})

        if path == "/api/add-agent":
            role = body.get("role", "Generalist")
            goal = body.get("goal", "")
            server_state["predefined_agents"].append({
                "agent_id": f"{len(server_state['predefined_agents']) + 1:03d}",
                "role": role,
                "personality": role,
                "goal": goal,
            })
            return self.send_json({"success": True, "agents": server_state["predefined_agents"]})

        if path.startswith("/api/agents/") and path.endswith("/edit"):
            agent_id = path.split("/api/agents/")[1].replace("/edit", "")
            ok, msg = handle_edit_agent(agent_id, body)
            return self.send_json({"success": ok, "message": msg})

        if path.startswith("/api/agents/") and path.endswith("/chat"):
            agent_id = path.split("/api/agents/")[1].replace("/chat", "")
            message = body.get("message", "")
            if not message:
                return self.send_json({"error": "Message is required"}, 400)
            ok, msg = handle_chat_message(agent_id, message)
            return self.send_json({"success": ok, "message": msg})

        if path.startswith("/api/agents/") and path.endswith("/budget"):
            agent_id = path.split("/api/agents/")[1].replace("/budget", "")
            ok, msg = handle_set_agent_budget(
                agent_id,
                token_budget=body.get("token_budget"),
                subtree_token_budget=body.get("subtree_token_budget"),
            )
            return self.send_json({"success": ok, "message": msg})

        if path == "/api/budget/redistribute":
            parent_id = body.get("parent_id", "")
            strategy = body.get("strategy", "equal")
            if not parent_id:
                return self.send_json({"error": "parent_id is required"}, 400)
            ok, msg = handle_redistribute_budget(parent_id, strategy)
            return self.send_json({"success": ok, "message": msg})

        self.send_json({"error": "Not found"}, 404)

    # -----------------------------------------------------------------------
    # DELETE routes
    # -----------------------------------------------------------------------
    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        if path.startswith("/api/agents/") and path.endswith("/preset"):
            idx_str = path.split("/api/agents/")[1].replace("/preset", "")
            try:
                idx = int(idx_str) - 1
                if 0 <= idx < len(server_state["predefined_agents"]):
                    removed = server_state["predefined_agents"].pop(idx)
                    # Re-index IDs
                    for i, a in enumerate(server_state["predefined_agents"]):
                        a["agent_id"] = f"{i + 1:03d}"
                    return self.send_json({"success": True, "removed": removed})
            except Exception:
                pass
            return self.send_json({"error": "Invalid index"}, 400)

        self.send_json({"error": "Not found"}, 404)

    # -----------------------------------------------------------------------
    # OPTIONS (CORS preflight)
    # -----------------------------------------------------------------------
    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # -----------------------------------------------------------------------
    # Static file server
    # -----------------------------------------------------------------------
    def serve_static(self, filename):
        filepath = os.path.join(STATIC_DIR, filename)
        if not os.path.isfile(filepath):
            self.send_json({"error": f"File not found: {filename}"}, 404)
            return
        ext = os.path.splitext(filename)[1].lower()
        content_type = MIME_TYPES.get(ext, "application/octet-stream")
        try:
            mode = "rb"
            with open(filepath, mode) as f:
                data = f.read()
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            self.wfile.write(data)
        except Exception as ex:
            self.send_json({"error": str(ex)}, 500)

    # -----------------------------------------------------------------------
    # Server-Sent Events stream
    # -----------------------------------------------------------------------
    def handle_sse(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "keep-alive")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

        last_hash = ""
        try:
            while True:
                current_hash = compute_state_hash()
                if current_hash != last_hash:
                    state = get_full_state()
                    payload = json.dumps(state)
                    self.wfile.write(f"data: {payload}\n\n".encode("utf-8"))
                    self.wfile.flush()
                    last_hash = current_hash
                else:
                    # Send heartbeat to keep connection alive
                    self.wfile.write(": heartbeat\n\n".encode("utf-8"))
                    self.wfile.flush()
                time.sleep(1.0)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass


# ---------------------------------------------------------------------------
# Threaded HTTP Server
# ---------------------------------------------------------------------------

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    allow_reuse_address = True


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Proximity Swarm V3 — Web Dashboard")
    parser.add_argument("--port", type=int, default=8080, help="HTTP server port (default: 8080)")
    parser.add_argument("--llm-provider", choices=["gemini", "ollama", "rules"], default="ollama",
                        help="LLM provider for task decomposition")
    parser.add_argument("--ollama-model", default="gemma4:latest", help="Ollama model to use")
    args = parser.parse_args()

    server_state["llm_provider"] = args.llm_provider
    server_state["ollama_model"] = args.ollama_model

    # Ensure static directory exists
    os.makedirs(STATIC_DIR, exist_ok=True)
    os.makedirs(STATE_DIR, exist_ok=True)

    server = ThreadedHTTPServer(("0.0.0.0", args.port), SwarmRequestHandler)

    print(f"""
╔══════════════════════════════════════════════════════════╗
║          🐝  PROXIMITY SWARM V3 — WEB DASHBOARD         ║
╠══════════════════════════════════════════════════════════╣
║                                                          ║
║   Server running at:  http://localhost:{args.port:<5}             ║
║   LLM Provider:       {args.llm_provider:<33} ║
║   Ollama Model:       {args.ollama_model:<33} ║
║                                                          ║
║   Press Ctrl+C to stop the server.                       ║
╚══════════════════════════════════════════════════════════╝
""")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[Server] Shutting down...")
        # Kill supervisor if running
        if server_state["supervisor_proc"]:
            try:
                server_state["supervisor_proc"].terminate()
                server_state["supervisor_proc"].wait(timeout=5)
            except Exception:
                pass
        server.shutdown()
        print("[Server] Goodbye.")


if __name__ == "__main__":
    main()
