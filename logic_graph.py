import os
import json
import logging
import tarfile
import datetime
import glob
from agent_runner import save_json, load_json

GRAPH_DIR = os.path.join(os.getcwd(), ".proximity_swarm", "graph")
SNAPSHOT_FILE = os.path.join(GRAPH_DIR, "snapshot.json")

_IS_MONITOR = False

def set_monitor(is_monitor: bool):
    global _IS_MONITOR
    _IS_MONITOR = is_monitor

def _guard_monitor(op_name):
    if not _IS_MONITOR:
        logging.error(f"[{op_name}] Structural operation called outside of monitor process.")
        return False
    return True

def init_graph(run_dir=None):
    os.makedirs(GRAPH_DIR, exist_ok=True)

def _node_path(node_id):
    return os.path.join(GRAPH_DIR, f"node_{node_id}.json")

def add_node(node):
    node_id = node.get("node_id")
    if not node_id:
        raise ValueError("node_id required")
    save_json(_node_path(node_id), node)
    return True

def get_node(node_id):
    return load_json(_node_path(node_id))

def update_node(node_id, **fields):
    node = get_node(node_id)
    if not node:
        return False
    for k, v in fields.items():
        node[k] = v
    save_json(_node_path(node_id), node)
    return True

def _get_all_nodes():
    nodes = {}
    if not os.path.exists(GRAPH_DIR):
        return nodes
    has_node_files = False
    for f in os.listdir(GRAPH_DIR):
        if f.startswith("node_") and f.endswith(".json"):
            has_node_files = True
            data = load_json(os.path.join(GRAPH_DIR, f))
            if data and "node_id" in data:
                nodes[data["node_id"]] = data
    if not has_node_files and os.path.exists(SNAPSHOT_FILE):
        snap = load_json(SNAPSHOT_FILE)
        if snap and "nodes" in snap:
            nodes = snap["nodes"]
    return nodes

def frontier():
    nodes = _get_all_nodes()
    goal_node = None
    for n in nodes.values():
        if n.get("kind") == "goal":
            goal_node = n
            break
    if not goal_node:
        return []
    frontier_nodes = []
    visited = set()
    def _traverse(nid):
        if nid in visited:
            return
        visited.add(nid)
        node = nodes.get(nid)
        if not node:
            return
        if node.get("status") in ["validated", "refuted"]:
            return
        unvalidated_deps = []
        for dep_id in node.get("depends_on", []):
            dep_node = nodes.get(dep_id)
            if not dep_node or dep_node.get("status") not in ["validated", "refuted"]:
                unvalidated_deps.append(dep_id)
        if not unvalidated_deps:
            frontier_nodes.append(node)
        else:
            for dep_id in unvalidated_deps:
                _traverse(dep_id)
    _traverse(goal_node["node_id"])
    return frontier_nodes

def nodes_by_status(status):
    nodes = _get_all_nodes()
    return [n for n in nodes.values() if n.get("status") == status]

def nodes_by_approach(approach):
    nodes = _get_all_nodes()
    return [n for n in nodes.values() if n.get("approach") == approach]

def validated_path_to_goal():
    nodes = _get_all_nodes()
    goal_node = None
    for n in nodes.values():
        if n.get("kind") == "goal":
            goal_node = n
            break
    if not goal_node:
        return None
        
    def _is_validated(nid, visited):
        if nid in visited:
            return False
        visited.add(nid)
        node = nodes.get(nid)
        if not node:
            return False
        if node.get("kind") == "premise":
            return node.get("status") == "validated"
        if node.get("status") != "validated":
            return False
        deps = node.get("depends_on", [])
        if not deps:
            return False
        if node.get("kind") != "goal":
            oracle = node.get("oracle", {})
            if oracle.get("type") == "none":
                return False
        for dep in deps:
            if not _is_validated(dep, visited.copy()):
                return False
        return True
        
    if _is_validated(goal_node["node_id"], set()):
        path = set()
        def _collect(nid):
            if nid in path:
                return
            path.add(nid)
            for d in nodes.get(nid, {}).get("depends_on", []):
                _collect(d)
        _collect(goal_node["node_id"])
        return list(path)
    return None



def merge_nodes(survivor_id, loser_ids):
    if not _guard_monitor("merge_nodes"):
        return False
    nodes = _get_all_nodes()
    if survivor_id not in nodes:
        return False
        
    try:
        import causal_tracer
        for lid in loser_ids:
            causal_tracer.log_merge(lid, survivor_id)
    except Exception:
        pass
        
    for n in nodes.values():
        new_deps = []
        changed = False
        for d in n.get("depends_on", []):
            if d in loser_ids:
                new_deps.append(survivor_id)
                changed = True
            else:
                new_deps.append(d)
        if changed:
            update_node(n["node_id"], depends_on=list(set(new_deps)))
            
    for lid in loser_ids:
        if lid in nodes:
            update_node(lid, status="refuted", kind="merged_loser")
            
    return True
def reparent(node_id, new_deps):
    if not _guard_monitor("reparent"):
        return False
    update_node(node_id, depends_on=new_deps)
    return True

def prune_branch(approach):
    if not _guard_monitor("prune_branch"):
        return False
    nodes = _get_all_nodes()
    for n in nodes.values():
        if n.get("approach") == approach:
            update_node(n["node_id"], status="refuted")
    return True

def validate_graph():
    nodes = _get_all_nodes()
    violations = []
    goals = [n for n in nodes.values() if n.get("kind") == "goal"]
    if len(goals) != 1:
        violations.append(f"Expected 1 goal node, found {len(goals)}")
    roots = [n for n in nodes.values() if n.get("kind") == "premise"]
    if len(roots) < 1:
        violations.append("Expected at least 1 premise node")
        
    for nid, n in nodes.items():
        for dep in n.get("depends_on", []):
            if dep not in nodes:
                violations.append(f"Node {nid} has dangling dependency {dep}")
        if n.get("status") not in ["proposed", "under_review", "validated", "refuted", None]:
            violations.append(f"Node {nid} has illegal status {n.get('status')}")
        oracle_type = n.get("oracle", {}).get("type")
        if oracle_type not in ["shell", "numeric", "symbolic", "checker_model", "none", None]:
            violations.append(f"Node {nid} has illegal oracle type {oracle_type}")
        if n.get("status") == "validated":
            for dep in n.get("depends_on", []):
                dep_node = nodes.get(dep)
                if dep_node and dep_node.get("status") == "refuted":
                    violations.append(f"Validated node {nid} depends on refuted node {dep}")
                    
    has_lemmas = any(n.get("kind") == "lemma" for n in nodes.values())
    for nid, n in nodes.items():
        if n.get("kind") != "premise" and (n.get("kind") == "lemma" or has_lemmas):
            if not n.get("depends_on"):
                violations.append(f"Non-premise node {nid} has empty depends_on")
                    
    def has_cycle(start_id, visited, stack):
        visited.add(start_id)
        stack.add(start_id)
        for dep in nodes.get(start_id, {}).get("depends_on", []):
            if dep not in visited:
                if has_cycle(dep, visited, stack):
                    return True
            elif dep in stack:
                return True
        stack.remove(start_id)
        return False
        
    visited_nodes = set()
    for nid in nodes:
        if nid not in visited_nodes:
            if has_cycle(nid, visited_nodes, set()):
                violations.append(f"Cycle detected involving node {nid}")
                
    try:
        if os.path.exists(SNAPSHOT_FILE):
            snap = load_json(SNAPSHOT_FILE)
            if snap is None:
                violations.append("Snapshot is corrupt")
            else:
                snap_nodes = snap.get("nodes", {})
                for snid in snap_nodes:
                    if snid not in nodes:
                        violations.append(f"Snapshot contains node {snid} not in per-node files")
    except Exception:
        violations.append("Snapshot parsing failed")
        
    return violations

def repair_graph():
    if not _guard_monitor("repair_graph"):
        return False
    nodes = _get_all_nodes()
    for nid, n in nodes.items():
        deps = n.get("depends_on", [])
        new_deps = [d for d in deps if d in nodes]
        if len(new_deps) != len(deps):
            update_node(nid, depends_on=new_deps)
    try:
        if os.path.exists(SNAPSHOT_FILE):
            snap = load_json(SNAPSHOT_FILE)
            if snap is None:
                rebuild_snapshot()
    except Exception:
        rebuild_snapshot()
    return True

def rebuild_snapshot():
    if not _guard_monitor("rebuild_snapshot"):
        return False
    nodes = _get_all_nodes()
    snap = {"nodes": nodes}
    save_json(SNAPSHOT_FILE, snap)
    return True

def to_mermaid():
    nodes = _get_all_nodes()
    lines = ["graph TD"]
    for nid, n in nodes.items():
        status = n.get("status", "unknown")
        label = f"{nid}[{nid}: {str(n.get('claim', ''))[:20]}]"
        lines.append(f"  {label}")
        if status == "validated":
            lines.append(f"  style {nid} fill:#a3e4d7")
        elif status == "refuted":
            lines.append(f"  style {nid} fill:#f5b7b1")
        for dep in n.get("depends_on", []):
            lines.append(f"  {dep} --> {nid}")
    return "\n".join(lines)

def to_artifact_json():
    nodes = _get_all_nodes()
    return {"nodes": nodes, "validated_path": validated_path_to_goal()}



def similar_open_nodes(claim_text, threshold=0.8):
    from memory_store import tokenize
    nodes = _get_all_nodes()
    similar = []
    tokens1 = set(tokenize(claim_text))
    if not tokens1:
        return similar
    for n in nodes.values():
        if n.get("status") in ["proposed", "under_review"]:
            c = n.get("claim", "")
            tokens2 = set(tokenize(c))
            if not tokens2:
                continue
            intersection = tokens1.intersection(tokens2)
            union = tokens1.union(tokens2)
            similarity = len(intersection) / len(union) if union else 0.0
            if similarity >= threshold:
                similar.append(n["node_id"])
    return similar


def garbage_collect_post_run(dry_run=False):
    """Compiles nodes into a snapshot, archives individual files, verifies integrity, and deletes node files unless dry_run."""
    if not _guard_monitor("garbage_collect_post_run"):
        return False
        
    nodes = _get_all_nodes()
    if not nodes:
        return True # Nothing to collect
        
    # 1. Rebuild snapshot
    rebuild_snapshot()
    
    # 2. Archive files
    archives_dir = os.path.join(GRAPH_DIR, "archives")
    os.makedirs(archives_dir, exist_ok=True)
    
    timestamp = datetime.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
    archive_path = os.path.join(archives_dir, f"graph_archive_{timestamp}.tar.gz")
    
    node_files = glob.glob(os.path.join(GRAPH_DIR, "node_*.json"))
    
    try:
        with tarfile.open(archive_path, "w:gz") as tar:
            for f in node_files:
                tar.add(f, arcname=os.path.basename(f))
    except Exception as e:
        logging.error(f"Failed to create graph archive: {e}")
        return False
        
    # 3. Integrity verification
    try:
        snap_data = load_json(SNAPSHOT_FILE)
        snap_nodes = snap_data.get("nodes", {})
        if len(snap_nodes) != len(nodes):
            logging.error(f"GC Aborted: Snapshot integrity verification failed. Expected {len(nodes)} nodes, got {len(snap_nodes)}.")
            return False
    except Exception as e:
        logging.error(f"GC Aborted: Could not read snapshot for verification: {e}")
        return False
        
    # 4. Safe deletion
    if dry_run:
        logging.info(f"Dry-run active. Skipping deletion of {len(node_files)} node files.")
        return True

    for f in node_files:
        try:
            os.remove(f)
        except OSError as e:
            logging.error(f"Failed to remove {f}: {e}")
            
    logging.info(f"Successfully garbage collected {len(node_files)} nodes into {archive_path}")
    return True
