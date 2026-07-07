#!/usr/bin/env python3
import os
import sys
import json
import time
import math
import string
import logging
import urllib.request

# Define state directory
STATE_DIR = os.path.join(os.getcwd(), ".proximity_swarm")
AGENTS_DIR = os.path.join(STATE_DIR, "agents")
COLLISIONS_DIR = os.path.join(STATE_DIR, "collisions")
WORKSPACES_DIR = os.path.join(STATE_DIR, "workspaces")
TOMBSTONES_FILE = os.path.join(STATE_DIR, "tombstones.json")
LOG_FILE = os.path.join(STATE_DIR, "monitor.log")

# Setup logging
os.makedirs(STATE_DIR, exist_ok=True)
os.makedirs(AGENTS_DIR, exist_ok=True)
os.makedirs(COLLISIONS_DIR, exist_ok=True)
os.makedirs(WORKSPACES_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout)
    ]
)

if not os.path.exists(TOMBSTONES_FILE):
    with open(TOMBSTONES_FILE, 'w') as f:
        json.dump([], f, indent=2)


def tokenize(text):
    """Tokenize and preprocess text into a bag of lowercase words."""
    if not text:
        return []
    # Remove punctuation
    translator = str.maketrans('', '', string.punctuation)
    clean_text = text.translate(translator).lower()
    return [word for word in clean_text.split() if len(word) > 2]


def calculate_tfidf_cosine_similarity(doc1, doc2, corpus):
    """Calculates TF-IDF Cosine Similarity of two documents within a background corpus."""
    tokens1 = tokenize(doc1)
    tokens2 = tokenize(doc2)
    
    if not tokens1 or not tokens2:
        return 0.0
        
    # Build vocabulary from corpus
    all_tokens_corpus = [tokenize(doc) for doc in corpus]
    vocab = set()
    for tokens in all_tokens_corpus:
        vocab.update(tokens)
    vocab.update(tokens1)
    vocab.update(tokens2)
    
    vocab = list(vocab)
    if not vocab:
        return 0.0
        
    # Calculate IDF
    N = len(all_tokens_corpus) if all_tokens_corpus else 1
    idf = {}
    for term in vocab:
        df = sum(1 for tokens in all_tokens_corpus if term in tokens)
        idf[term] = math.log((1 + N) / (1 + df)) + 1
        
    def get_tfidf_vector(tokens):
        vec = []
        for term in vocab:
            tf = tokens.count(term)
            vec.append(tf * idf[term])
        return vec
        
    vec1 = get_tfidf_vector(tokens1)
    vec2 = get_tfidf_vector(tokens2)
    
    dot_product = sum(a * b for a, b in zip(vec1, vec2))
    magnitude1 = math.sqrt(sum(a * a for a in vec1))
    magnitude2 = math.sqrt(sum(b * b for b in vec2))
    
    if magnitude1 == 0 or magnitude2 == 0:
        return 0.0
    return dot_product / (magnitude1 * magnitude2)


def calculate_jaccard_similarity(set1, set2):
    """Calculate Jaccard similarity of two iterables."""
    s1 = set(set1)
    s2 = set(set2)
    if not s1 and not s2:
        return 0.0
    union = s1.union(s2)
    if not union:
        return 0.0
    return len(s1.intersection(s2)) / len(union)


OLLAMA_MODEL = "gemma4:latest"

PHASE_WEIGHTS = {
    "Planning": (0.8, 0.1, 0.1),
    "Exploring": (0.4, 0.4, 0.2),
    "Validating": (0.1, 0.6, 0.3),
    "Synthesizing": (0.6, 0.3, 0.1),
    # Legacy fallbacks
    "Coding": (0.4, 0.4, 0.2),
    "Debugging": (0.1, 0.6, 0.3),
    "Documentation": (0.6, 0.3, 0.1)
}


def is_ollama_running():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.0) as response:
            return response.status == 200
    except Exception:
        return False


def fallback_classify_phase(step_name, step_description):
    text = (step_name + " " + step_description).lower()
    if any(k in text for k in ["bug", "fix", "debug", "error", "fail", "issue", "crash", "compile", "test", "resolve", "validate", "check", "verify", "oracle"]):
        return "Validating"
    if any(k in text for k in ["doc", "read", "writeup", "report", "comment", "markdown", "synthesize", "explain", "conclusion", "summary"]):
        return "Synthesizing"
    if any(k in text for k in ["init", "plan", "setup", "initialize", "design", "requirements", "prepare", "analysis", "architect"]):
        return "Planning"
    return "Exploring"


def classify_phase(agent):
    current_step = agent.get("current_step")
    if not current_step:
        return "Planning"
        
    if "phase" in current_step:
        return current_step["phase"]
        
    step_name = current_step.get("name", "")
    step_description = current_step.get("description", "")
    
    phase = None
    if is_ollama_running():
        url = "http://localhost:11434/api/generate"
        headers = {"Content-Type": "application/json"}
        prompt = (
            f"Classify the following agent task step into exactly one of these four phases: "
            f"Planning, Exploring, Validating, Synthesizing.\n"
            f"Step Name: {step_name}\n"
            f"Step Description: {step_description}\n\n"
            f"Respond with a JSON object containing a single key 'phase' whose value is exactly one of the four strings: "
            f"'Planning', 'Exploring', 'Validating', 'Synthesizing'."
        )
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
            with urllib.request.urlopen(req, timeout=10) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                resp_text = res_data.get("response", "").strip()
                parsed = json.loads(resp_text)
                phase_candidate = parsed.get("phase", "").strip()
                if phase_candidate in PHASE_WEIGHTS:
                    phase = phase_candidate
        except Exception:
            pass
            
    if not phase:
        phase = fallback_classify_phase(step_name, step_description)
        
    current_step["phase"] = phase
    if "id" in agent:
        save_agent_state(agent)
    return phase


def calculate_proximity(agent1, agent2, corpus):
    """
    Computes composite distance metric between two agents.
    Returns (distance, cosine_sim, file_jaccard, tool_jaccard)
    """
    def _get_claim(agent):
        node_id = agent.get("active_node_id")
        if node_id:
            try:
                import logic_graph
                node = logic_graph.get_node(node_id)
                if node:
                    return node.get("claim", "")
            except Exception:
                pass
        return ""

    goal1 = agent1.get("goal", "") + " " + agent1.get("current_step", {}).get("description", "") if agent1.get("current_step") else agent1.get("goal", "")
    goal1 += " " + _get_claim(agent1)
    
    goal2 = agent2.get("goal", "") + " " + agent2.get("current_step", {}).get("description", "") if agent2.get("current_step") else agent2.get("goal", "")
    goal2 += " " + _get_claim(agent2)
    
    cosine_sim = calculate_tfidf_cosine_similarity(goal1, goal2, corpus)
    
    files1 = agent1.get("touched_files", [])
    files2 = agent2.get("touched_files", [])
    file_jaccard = calculate_jaccard_similarity(files1, files2)
    
    tools1 = agent1.get("tools_used", [])
    tools2 = agent2.get("tools_used", [])
    tool_jaccard = calculate_jaccard_similarity(tools1, tools2)
    
    d_goal = 1.0 - cosine_sim
    d_workspace = 1.0 - file_jaccard
    d_tools = 1.0 - tool_jaccard
    
    # Dynamic weighting based on phase classification
    phase1 = classify_phase(agent1)
    phase2 = classify_phase(agent2)
    
    w1_1, w2_1, w3_1 = PHASE_WEIGHTS.get(phase1, (0.5, 0.3, 0.2))
    w1_2, w2_2, w3_2 = PHASE_WEIGHTS.get(phase2, (0.5, 0.3, 0.2))
    
    w1 = (w1_1 + w1_2) / 2.0
    w2 = (w2_1 + w2_2) / 2.0
    w3 = (w3_1 + w3_2) / 2.0
    
    distance = w1 * d_goal + w2 * d_workspace + w3 * d_tools
    
    return distance, cosine_sim, file_jaccard, tool_jaccard


def load_active_agents():
    """Load states of all active agents (including syncing and pending termination)."""
    agents = []
    if not os.path.exists(AGENTS_DIR):
        return agents
        
    for filename in os.listdir(AGENTS_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(AGENTS_DIR, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    if data.get("status") in ["exploring", "syncing", "pending_termination", "awaiting_child"]:
                        agents.append(data)
            except Exception as e:
                logging.error(f"Error loading agent file {filename}: {e}")
    return agents


def save_agent_state(agent):
    """Save an agent's state file."""
    agent["last_updated"] = time.time()
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent['id']}.json")
    try:
        with open(filepath, 'w') as f:
            json.dump(agent, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving state for agent {agent['id']}: {e}")


INTERACTIVE = False
AUTO_APPROVE_SPAWNS = True


def handle_spawn_requests(agents):
    """Process any active spawn requests from agents."""
    active_agents = [a for a in agents if a.get("status") in ["exploring", "syncing", "pending_termination", "awaiting_child"]]
    
    # Dynamically read budget limit
    current_budget = BUDGET
    orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")
    if os.path.exists(orchestrator_file):
        try:
            with open(orchestrator_file, 'r') as f_orc:
                orc_state = json.load(f_orc)
                if "budget_limit" in orc_state:
                    current_budget = int(orc_state["budget_limit"])
        except Exception:
            pass
            
    total_tokens = sum(a.get("output_tokens", 0) for a in active_agents)

    for agent in agents:
        spawn_req = agent.get("spawn_request")
        if spawn_req:
            status = spawn_req.get("status", "pending")
            
            # Quota check
            if status == "pending":
                is_exceeded = False
                if current_budget < 20 and len(active_agents) >= current_budget:
                    is_exceeded = True
                elif total_tokens >= current_budget:
                    is_exceeded = True
                    
                if is_exceeded:
                    logging.info(f"Denying spawn request for Agent {agent['id']} due to budget limit ({current_budget}).")
                    agent["spawn_request"]["status"] = "rejected"
                    save_agent_state(agent)
                    continue

            if not AUTO_APPROVE_SPAWNS or INTERACTIVE:
                if status == "pending":
                    # Wait for interactive approval in dashboard
                    continue
                elif status == "rejected":
                    logging.info(f"Agent {agent['id']} spawn request REJECTED. Clearing request.")
                    agent["spawn_request"] = None
                    save_agent_state(agent)
                    continue
            
            logging.info(f"Agent {agent['id']} requested to spawn a sub-agent with goal: {spawn_req.get('goal')}")
            
            existing_ids = []
            for filename in os.listdir(AGENTS_DIR):
                if filename.startswith("agent_") and filename.endswith(".json"):
                    try:
                        part = filename.replace("agent_", "").replace(".json", "")
                        existing_ids.append(int(part))
                    except ValueError:
                        pass
            next_id = max(existing_ids) + 1 if existing_ids else 1
            child_id = f"{next_id:03d}"
            
            child_agent = {
                "id": child_id,
                "parent_id": agent["id"],
                "goal": spawn_req["goal"],
                "status": "exploring",
                "current_step": {
                    "step_id": 1,
                    "name": "Initialization",
                    "description": "Initialize child sub-task workspace and review parent context."
                },
                "touched_files": spawn_req.get("initial_files", []),
                "tools_used": [],
                "progress": 0,
                "steps_completed": 0
            }
            
            # Inherit offset suffix if present
            if agent.get("offset_suffix"):
                child_agent["offset_suffix"] = agent["offset_suffix"]
                
            # Seed with a distinct approach for graph exploration
            child_agent["approach"] = f"Approach_{child_id}"
                
            # Inherit sub_swarm_id and register in orchestrator
            if agent.get("sub_swarm_id"):
                child_agent["sub_swarm_id"] = agent["sub_swarm_id"]
                try:
                    orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")
                    if os.path.exists(orchestrator_file):
                        with open(orchestrator_file, 'r') as f_orc:
                            state = json.load(f_orc)
                        sid = agent["sub_swarm_id"]
                        if sid in state.get("sub_swarms", {}):
                            if child_id not in state["sub_swarms"][sid]["agent_ids"]:
                                state["sub_swarms"][sid]["agent_ids"].append(child_id)
                                with open(orchestrator_file, 'w') as f_orc:
                                    json.dump(state, f_orc, indent=2)
                except Exception:
                    pass
            
            child_ws = os.path.join(WORKSPACES_DIR, f"agent_{child_id}")
            os.makedirs(child_ws, exist_ok=True)
            
            save_agent_state(child_agent)
            
            agent["spawn_request"] = None
            if "children" not in agent:
                agent["children"] = []
            agent["children"].append(child_id)
            save_agent_state(agent)
            
            logging.info(f"Spawned Child Agent {child_id} for Parent Agent {agent['id']}.")
            try:
                import causal_tracer
                causal_tracer.log_agent_spawn(agent["id"], child_id, spawn_req.get("goal"))
                causal_tracer.log_state_transition(child_id, "none", "exploring")
            except Exception:
                pass


def evaluate_consensus_gate(agents):
    """
    Consensus-Gate Evaluation (Extinction Prevention)
    Verify if termination requests can be approved safely without losing the target task coverage.
    """
    # Gather corpus of goals for similarity checks
    corpus = []
    for a in agents:
        goal_str = a.get("goal", "") + " " + a.get("current_step", {}).get("description", "")
        corpus.append(goal_str)

    for agent in agents:
        if agent["status"] == "pending_termination":
            logging.info(f"Supervisor evaluating termination request for Agent {agent['id']}...")
            
            # Look for other active agents covering the same/similar goals
            task_id = agent.get("task_id")
            covered = False
            covering_agent_id = None
            
            for other in agents:
                if other["id"] == agent["id"]:
                    continue
                if other["status"] not in ["exploring", "syncing", "awaiting_child"]:
                    continue
                    
                # Coverage criteria: same task_id, or high cosine similarity
                same_task = task_id and (other.get("task_id") == task_id)
                
                goal1 = agent.get("goal", "") + " " + agent.get("current_step", {}).get("description", "")
                goal2 = other.get("goal", "") + " " + other.get("current_step", {}).get("description", "")
                goal_similarity = calculate_tfidf_cosine_similarity(goal1, goal2, corpus)
                
                similar_goal = goal_similarity > 0.6
                
                if same_task or similar_goal:
                    covered = True
                    covering_agent_id = other["id"]
                    break
            
            if covered:
                # Safe to terminate: another active agent is covering this branch
                agent["status"] = "dead"
                save_agent_state(agent)
                
                # Write gravestone for branch abandoned
                try:
                    import agent_runner
                    tombstones_file = agent_runner.TOMBSTONES_FILE
                    tombstones = agent_runner.load_json(tombstones_file) or {"pruned_agents": [], "dead_ends": [], "refuted_nodes": []}
                    if "pruned_agents" not in tombstones:
                        tombstones["pruned_agents"] = []
                    tombstones["pruned_agents"].append({
                        "agent_id": agent["id"],
                        "approach": agent.get("approach"),
                        "reason": f"Consensus approved termination, covered by {covering_agent_id}"
                    })
                    agent_runner.save_json(tombstones_file, tombstones)
                except Exception:
                    pass
                logging.info(
                    f"[CONSENSUS APPROVED] Agent {agent['id']} termination approved. "
                    f"Branch covered by active Agent {covering_agent_id}."
                )
                try:
                    import causal_tracer
                    causal_tracer.log_state_transition(agent["id"], "pending_termination", "dead", {"reason": f"consensus approved, covered by {covering_agent_id}"})
                except Exception:
                    pass
            else:
                # Extinction danger! Block termination and force agent to resume exploring
                agent["status"] = "exploring"
                save_agent_state(agent)
                logging.warning(
                    f"[CONSENSUS OVERRIDE] Extinction Prevention triggered! Rejected termination for Agent {agent['id']} "
                    f"as it is the last active agent covering its goal/task."
                )
                try:
                    import causal_tracer
                    causal_tracer.log_state_transition(agent["id"], "pending_termination", "exploring", {"reason": "extinction override"})
                except Exception:
                    pass


def run_cascading_kills():
    """
    Cascading Kill Switch (Runaway Prevention)
    Recursively kills all descendants of dead parents.
    """
    if not os.path.exists(AGENTS_DIR):
        return
        
    # Load all agent states in workspace
    all_agents = {}
    for filename in os.listdir(AGENTS_DIR):
        if filename.endswith(".json"):
            try:
                filepath = os.path.join(AGENTS_DIR, filename)
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    all_agents[data["id"]] = data
            except Exception:
                pass
                
    def cascade(parent_id):
        parent = all_agents.get(parent_id)
        if not parent:
            return
            
        children = parent.get("children", [])
        for child_id in children:
            child = all_agents.get(child_id)
            if child and child["status"] != "dead":
                # Check if all parents of this child are dead
                child_parents = child.get("parent_ids") or ([child.get("parent_id")] if child.get("parent_id") else [])
                all_parents_dead = True
                for pid in child_parents:
                    p_state = all_agents.get(pid)
                    if p_state and p_state.get("status") != "dead":
                        all_parents_dead = False
                        break
                if all_parents_dead:
                    child["status"] = "dead"
                    child["active_node_id"] = None
                    save_agent_state(child)
                    try:
                        import causal_tracer
                        causal_tracer.log_state_transition(child_id, child.get("status", "exploring"), "dead", {"reason": "cascading kill from dead parents"})
                    except Exception:
                        pass
                    logging.warning(
                        f"[CASCADING KILL] Supervisor killed child Agent {child_id} "
                        f"recursively because all of its parents are dead."
                    )
                    cascade(child_id)  # recurse
                
    # Run cascade check starting from all dead agents
    for agent_id, agent in list(all_agents.items()):
        if agent["status"] == "dead":
            cascade(agent_id)


BUDGET = 20000
JUDGE_PROVIDER = None
JUDGE_MODEL = None


def call_ollama_api_local(prompt, model):
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
        with urllib.request.urlopen(req, timeout=30) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            text = res_data["response"]
            return json.loads(text.strip())
    except Exception:
        return None


def call_gemini_api_local(prompt, api_key):
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
    except Exception:
        return None


def get_active_leaf_agents(active_agents):
    active_parent_ids = set()
    for agent in active_agents:
        p_ids = agent.get("parent_ids") or ([agent.get("parent_id")] if agent.get("parent_id") else [])
        for pid in p_ids:
            if pid:
                active_parent_ids.add(pid)
    leaf_agents = [a for a in active_agents if a["id"] not in active_parent_ids]
    return leaf_agents

def rank_leaf_agents_llm(leaf_agents, macro_goal):
    """
    Rank leaf agents based on their progress and activity.
    Fallback heuristic: sort by progress (ascending), then by inactivity (ascending last_updated).
    """
    def heuristic_sort(a):
        progress = a.get("progress", 0)
        last_updated = a.get("last_updated", 0)
        return (progress, last_updated)
        
    return sorted(leaf_agents, key=heuristic_sort)


def monitor_loop(poll_interval=1.5, collision_threshold=0.5, graph_mode="graph"):
    """Main polling loop to calculate proximity and supervise swarm execution."""
    logging.info("V2 Proximity Supervisor started. Coordinating swarm coordinates...")
    logging.info(f"Settings: Poll Interval = {poll_interval}s, Collision Threshold = {collision_threshold}, Graph Mode = {graph_mode}")
    
    if graph_mode == "graph":
        try:
            import logic_graph
            logic_graph.set_monitor(True)
            logic_graph.init_graph()
        except ImportError as e:
            logging.error(f"Failed to load logic_graph: {e}")
    
    while True:
        try:
            # Defensive directory creation
            os.makedirs(AGENTS_DIR, exist_ok=True)
            os.makedirs(COLLISIONS_DIR, exist_ok=True)
            os.makedirs(WORKSPACES_DIR, exist_ok=True)
            
            # Load active agents
            agents = load_active_agents()
            
            # 1. Handle consensus-gate evaluations (extinction prevention)
            evaluate_consensus_gate(agents)
            
            # 2. Run cascading kills switch (runaway prevention)
            run_cascading_kills()
            
            # Reload agents to include adjustments and spawns
            agents = load_active_agents()
            handle_spawn_requests(agents)
            
            agents = load_active_agents()
            active_agents = [a for a in agents if a["status"] in ["exploring", "syncing", "pending_termination", "awaiting_child"]]
            
            # Dynamically read budget limit from orchestrator.json if present
            orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")
            macro_goal = "Solve task"
            current_budget = BUDGET
            if os.path.exists(orchestrator_file):
                try:
                    with open(orchestrator_file, 'r') as f_orc:
                        orc_state = json.load(f_orc)
                        macro_goal = orc_state.get("macro_goal", "Solve task")
                        if "budget_limit" in orc_state:
                            current_budget = int(orc_state["budget_limit"])
                except Exception:
                    pass
                    
            # Check if any active leaf agent's accumulated output tokens exceed the budget cap
            # Supports per-node (token_budget) and subtree (subtree_token_budget) limits
            leafs = get_active_leaf_agents(active_agents)
            budget_exceeded = False
            max_leaf_tokens = 0
            per_agent_status = []

            # Build parent->children map for subtree calculations
            agent_map = {a.get("id"): a for a in agents}
            children_map = {}
            for a in agents:
                pid = a.get("parent_id")
                if pid:
                    children_map.setdefault(pid, []).append(a)

            def get_subtree_tokens(agent_id):
                """Recursively sum output_tokens for an agent and all descendants."""
                total = agent_map.get(agent_id, {}).get("output_tokens", 0)
                for child in children_map.get(agent_id, []):
                    total += get_subtree_tokens(child.get("id"))
                return total

            for leaf in leafs:
                leaf_tokens = leaf.get("output_tokens", 0)
                max_leaf_tokens = max(max_leaf_tokens, leaf_tokens)

                # Per-node budget check (falls back to global budget)
                node_budget = leaf.get("token_budget", current_budget)
                if leaf_tokens > node_budget:
                    budget_exceeded = True

                per_agent_status.append({
                    "id": leaf.get("id"),
                    "output_tokens": leaf_tokens,
                    "token_budget": node_budget,
                    "pct": round((leaf_tokens / max(node_budget, 1)) * 100, 1),
                })

            # Subtree budget checks for parent agents
            subtree_alerts = []
            for a in active_agents:
                stb = a.get("subtree_token_budget")
                if stb is not None and stb > 0:
                    subtree_used = get_subtree_tokens(a.get("id"))
                    if subtree_used > stb:
                        budget_exceeded = True
                        subtree_alerts.append({
                            "parent_id": a.get("id"),
                            "subtree_used": subtree_used,
                            "subtree_budget": stb,
                            "pct": round((subtree_used / max(stb, 1)) * 100, 1),
                        })
                    
            if budget_exceeded or (current_budget < 20 and len(leafs) > current_budget):
                import judge
                judge_provider, judge_model = judge.select_judge_model(
                    JUDGE_PROVIDER, JUDGE_MODEL,
                    "ollama" if is_ollama_running() else "gemini" if os.environ.get("GEMINI_API_KEY") else "rules",
                    OLLAMA_MODEL
                )
                ranked = judge.rank_branches(leafs, judge_provider, judge_model)
                
                # Enforce hard pruning
                to_prune = []
                if current_budget < 20 and len(leafs) > current_budget:
                    # Keep only top current_budget agents, kill the rest
                    to_prune = [l for l in ranked[current_budget:]]
                else:
                    # Kill any leaf agent whose token count exceeds its node budget
                    for leaf in leafs:
                        leaf_tokens = leaf.get("output_tokens", 0)
                        node_budget = leaf.get("token_budget", current_budget)
                        if leaf_tokens > node_budget:
                            to_prune.append(leaf)
                            
                for leaf in to_prune:
                    logging.info(f"Pruning/Killing Agent {leaf['id']} due to budget/quota limit.")
                    leaf["status"] = "dead"
                    save_agent_state(leaf)
                    try:
                        import causal_tracer
                        causal_tracer.log_state_transition(leaf["id"], "exploring", "dead", {"reason": "budget/quota exceeded"})
                    except Exception:
                        pass
                
                alert_data = {
                    "budget_exceeded": True,
                    "active_count": max_leaf_tokens,  # Holds max leaf output tokens for display
                    "budget_limit": current_budget,
                    "candidates": ranked,
                    "per_agent_status": per_agent_status,
                    "subtree_alerts": subtree_alerts,
                }
                alert_file = os.path.join(STATE_DIR, "budget_alert.json")
                with open(alert_file, 'w') as f_alert:
                    json.dump(alert_data, f_alert, indent=2)
            else:
                # Even when not exceeded, write per-agent status for UI display
                alert_data = {
                    "budget_exceeded": False,
                    "active_count": max_leaf_tokens,
                    "budget_limit": current_budget,
                    "per_agent_status": per_agent_status,
                    "subtree_alerts": subtree_alerts,
                }
                alert_file = os.path.join(STATE_DIR, "budget_alert.json")
                with open(alert_file, 'w') as f_alert:
                    json.dump(alert_data, f_alert, indent=2)
            
            # Build corpus of goals/steps for TF-IDF
            corpus = []
            for a in agents:
                goal_str = a.get("goal", "") + " " + a.get("current_step", {}).get("description", "")
                corpus.append(goal_str)
                
            # Check for collisions pairwise
            n = len(agents)
            for i in range(n):
                for j in range(i + 1, n):
                    a1 = agents[i]
                    a2 = agents[j]
                    
                    if a1['status'] == "pending_termination" or a2['status'] == "pending_termination":
                        continue
                        
                    distance, cosine_sim, file_jaccard, tool_jaccard = calculate_proximity(a1, a2, corpus)
                    
                    if distance < collision_threshold:
                        if a1['status'] == "exploring" and a2['status'] == "exploring":
                            logging.warning(
                                f"COLLISION DETECTED between Agent {a1['id']} and Agent {a2['id']}! "
                                f"Distance: {distance:.3f} (GoalSim: {cosine_sim:.2f}, FileSim: {file_jaccard:.2f})"
                            )
                            
                            a1['status'] = "syncing"
                            a2['status'] = "syncing"
                            
                            collision_id = f"{a1['id']}_{a2['id']}"
                            try:
                                import causal_tracer
                                causal_tracer.log_collision(collision_id, a1["id"], a2["id"], {"distance": distance})
                                causal_tracer.log_state_transition(a1["id"], "exploring", "syncing")
                                causal_tracer.log_state_transition(a2["id"], "exploring", "syncing")
                            except Exception:
                                pass
                            collision_file = os.path.join(COLLISIONS_DIR, f"collision_{collision_id}.json")
                            
                            collision_data = {
                                "collision_id": collision_id,
                                "timestamp": time.time(),
                                "distance": distance,
                                "similarity_metrics": {
                                    "goal_cosine": cosine_sim,
                                    "file_jaccard": file_jaccard,
                                    "tool_jaccard": tool_jaccard
                                },
                                "agent_a": a1,
                                "agent_b": a2,
                                "status": "pending_negotiation",
                                "negotiation_log": []
                            }
                            
                            with open(collision_file, 'w') as f:
                                json.dump(collision_data, f, indent=2)
                                
                            save_agent_state(a1)
                            save_agent_state(a2)
                            logging.info(f"Created collision file: collision_{collision_id}.json. Paused both agents.")
            
        except Exception as e:
            logging.error(f"Error in supervisor loop: {e}", exc_info=True)
            
        time.sleep(poll_interval)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Proximity Swarm - V2 Supervisor Monitor")
    parser.add_argument("--interval", type=float, default=1.5, help="Polling interval in seconds")
    parser.add_argument("--threshold", type=float, default=0.5, help="Collision distance threshold (lower = closer)")
    parser.add_argument("--ollama-model", default="gemma4:latest", help="Ollama model to use for phase classification")
    parser.add_argument("--interactive", action="store_true", help="Enable terminal prompts to manually negotiate collisions")
    parser.add_argument("--budget", type=int, default=20000, help="Maximum active leaf agent output token budget cap limit")
    parser.add_argument("--auto-approve-spawns", action="store_true", help="Bypass manual operator approval for spawn requests")
    parser.add_argument("--graph-mode", choices=["linear", "graph"], default="graph", help="Execution mode")
    parser.add_argument("--judge-provider", help="LLM API provider for the Judge")
    parser.add_argument("--judge-model", help="LLM model string to query for the Judge")
    args = parser.parse_args()
    
    OLLAMA_MODEL = args.ollama_model
    INTERACTIVE = args.interactive
    BUDGET = args.budget
    AUTO_APPROVE_SPAWNS = args.auto_approve_spawns
    JUDGE_PROVIDER = args.judge_provider
    JUDGE_MODEL = args.judge_model
    
    try:
        monitor_loop(poll_interval=args.interval, collision_threshold=args.threshold, graph_mode=args.graph_mode)
    except KeyboardInterrupt:
        logging.info("Supervisor stopped by user.")
        sys.exit(0)
