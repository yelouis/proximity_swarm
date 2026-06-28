import os
import sqlite3
import json
import time

DB_PATH = os.path.join(os.getcwd(), ".proximity_swarm", "causal_graph.db")


def get_db_connection():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    # Initialize schema
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trace_nodes (
            id TEXT PRIMARY KEY,
            type TEXT NOT NULL,
            label TEXT NOT NULL,
            metadata TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS trace_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source TEXT NOT NULL,
            target TEXT NOT NULL,
            type TEXT NOT NULL,
            timestamp REAL NOT NULL,
            details TEXT
        )
    """)
    conn.commit()
    return conn


def add_node(node_id, node_type, label, metadata=None):
    meta_str = json.dumps(metadata) if metadata else "{}"
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT OR REPLACE INTO trace_nodes (id, type, label, metadata) VALUES (?, ?, ?, ?)",
            (node_id, node_type, label, meta_str)
        )
        conn.commit()
    except Exception as e:
        print(f"[CausalTracer Error] add_node failed: {e}")
    finally:
        conn.close()


def add_edge(source, target, edge_type, details=None):
    details_str = json.dumps(details) if details else "{}"
    conn = get_db_connection()
    try:
        conn.execute(
            "INSERT INTO trace_edges (source, target, type, timestamp, details) VALUES (?, ?, ?, ?, ?)",
            (source, target, edge_type, time.time(), details_str)
        )
        conn.commit()
    except Exception as e:
        print(f"[CausalTracer Error] add_edge failed: {e}")
    finally:
        conn.close()
    
    # Generate flowchart markdown automatically on every new event edge
    save_mermaid_markdown()


def log_agent_spawn(parent_id, child_id, goal=None):
    # Register parent node if it doesn't exist
    add_node(f"agent_{parent_id}", "agent", f"Agent {parent_id}")
    # Register child node
    add_node(
        f"agent_{child_id}", 
        "agent", 
        f"Agent {child_id}", 
        {"goal": goal, "parent": parent_id}
    )
    # Register edge
    add_edge(f"agent_{parent_id}", f"agent_{child_id}", "spawn", {"goal": goal})


def log_step_execution(agent_id, step_id, step_name, description, status, details=None):
    step_node_id = f"agent_{agent_id}_step_{step_id}"
    add_node(
        step_node_id, 
        "step", 
        f"Step {step_id}: {step_name} ({status})", 
        {"description": description, "status": status}
    )
    # Link agent to this step
    add_edge(f"agent_{agent_id}", step_node_id, "step_exec", {
        "step_name": step_name,
        "status": status,
        **(details or {})
    })
    
    # If step_id > 1, link previous step to this step
    if step_id > 1:
        prev_step_node_id = f"agent_{agent_id}_step_{step_id - 1}"
        add_edge(prev_step_node_id, step_node_id, "step_progression")


def log_collision(collision_id, agent_a_id, agent_b_id, details=None):
    collision_node_id = f"collision_{collision_id}"
    add_node(
        collision_node_id, 
        "collision", 
        f"Collision {agent_a_id} & {agent_b_id}", 
        details
    )
    # Link entering agents
    add_edge(f"agent_{agent_a_id}", collision_node_id, "collision_entry", details)
    add_edge(f"agent_{agent_b_id}", collision_node_id, "collision_entry", details)


def log_takeover(collision_id, survivor_id, loser_id, reasoning=None):
    collision_node_id = f"collision_{collision_id}"
    # Link resolution output edges
    add_edge(collision_node_id, f"agent_{survivor_id}", "takeover_survivor", {"reasoning": reasoning})
    add_edge(collision_node_id, f"agent_{loser_id}", "takeover_loser", {"reasoning": reasoning})

def log_decision(agent_id, decision_type, metadata, result, reason):
    decision_id = f"decision_{agent_id}_{int(time.time()*1000)}"
    add_node(
        decision_id,
        "decision",
        f"Judge {decision_type} ({result})",
        {"metadata": metadata, "result": result, "reason": reason}
    )
    add_edge(f"agent_{agent_id}", decision_id, decision_type, {"result": result, "reason": reason})


def log_state_transition(agent_id, old_status, new_status, details=None):
    add_edge(f"agent_{agent_id}", f"agent_{agent_id}", "state_transition", {
        "old_status": old_status,
        "new_status": new_status,
        "details": details
    })


def log_propose(agent_id, node_id, claim):
    add_node(f"node_{node_id}", "logic_node", claim[:30] + "...")
    add_edge(f"agent_{agent_id}", f"node_{node_id}", "propose", {"claim": claim})


def log_validate(agent_id, node_id):
    add_edge(f"agent_{agent_id}", f"node_{node_id}", "validate")


def log_refute(agent_id, node_id):
    add_edge(f"agent_{agent_id}", f"node_{node_id}", "refute")


def log_share(agent_a_id, agent_b_id):
    add_edge(f"agent_{agent_a_id}", f"agent_{agent_b_id}", "share")
    add_edge(f"agent_{agent_b_id}", f"agent_{agent_a_id}", "share")


def log_merge(loser_node_id, survivor_node_id):
    add_edge(f"node_{loser_node_id}", f"node_{survivor_node_id}", "merge")



def get_connected_component(start_node_id):
    conn = get_db_connection()
    try:
        edges = conn.execute("SELECT source, target FROM trace_edges").fetchall()
    except Exception:
        edges = []
    finally:
        conn.close()
        
    adj = {}
    for edge in edges:
        s, t = edge["source"], edge["target"]
        if s not in adj:
            adj[s] = []
        if t not in adj:
            adj[t] = []
        adj[s].append(t)
        adj[t].append(s)
        
    if start_node_id not in adj:
        return {start_node_id}
        
    visited = set()
    queue = [start_node_id]
    visited.add(start_node_id)
    
    while queue:
        curr = queue.pop(0)
        for neighbor in adj.get(curr, []):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append(neighbor)
    return visited


def generate_mermaid_graph(agent_id=None):
    conn = get_db_connection()
    try:
        nodes = conn.execute("SELECT id, type, label FROM trace_nodes").fetchall()
        edges = conn.execute("SELECT source, target, type FROM trace_edges").fetchall()
    except Exception:
        nodes, edges = [], []
    finally:
        conn.close()
        
    filter_nodes = None
    if agent_id:
        target_node = f"agent_{agent_id}"
        filter_nodes = get_connected_component(target_node)
        
    lines = ["graph TD"]
    
    # Render nodes
    for node in nodes:
        nid = node["id"]
        if filter_nodes is not None and nid not in filter_nodes:
            continue
            
        label = node["label"]
        if node["type"] == "agent":
            lines.append(f'    {nid}["👤 {label}"]')
        elif node["type"] == "step":
            lines.append(f'    {nid}["📝 {label}"]')
        elif node["type"] == "collision":
            lines.append(f'    {nid}{{"⚠️ {label}"}}')
        else:
            lines.append(f'    {nid}["{label}"]')
            
    # Render edges
    for edge in edges:
        s, t = edge["source"], edge["target"]
        if filter_nodes is not None and (s not in filter_nodes or t not in filter_nodes):
            continue
            
        # Skip self-loops in visual graph to avoid cluttering flowchart
        if s == t:
            continue
            
        etype = edge["type"]
        lines.append(f'    {s} -->|{etype}| {t}')
        
    return "\n".join(lines)


def save_mermaid_markdown():
    graph_text = generate_mermaid_graph()
    markdown_content = (
        f"# Causal Swarm Timeline Flowchart\n\n"
        f"This flowchart traces the dynamic trajectories, spawns, and collisions of all active agents.\n\n"
        f"```mermaid\n"
        f"{graph_text}\n"
        f"```\n"
    )
    # Locate output directory (.proximity_swarm)
    db_dir = os.path.dirname(DB_PATH)
    md_path = os.path.join(db_dir, "causal_graph.md")
    try:
        with open(md_path, 'w') as f:
            f.write(markdown_content)
    except Exception as e:
        print(f"[CausalTracer Error] Failed to save flowchart markdown: {e}")
