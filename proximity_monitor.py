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
    if any(k in text for k in ["bug", "fix", "debug", "error", "fail", "issue", "crash", "compile", "test", "resolve"]):
        return "Debugging"
    if any(k in text for k in ["doc", "read", "writeup", "report", "comment", "markdown", "synthesize", "explain"]):
        return "Documentation"
    if any(k in text for k in ["init", "plan", "setup", "initialize", "design", "requirements", "prepare", "analysis", "architect"]):
        return "Planning"
    return "Coding"


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
            f"Planning, Coding, Debugging, Documentation.\n"
            f"Step Name: {step_name}\n"
            f"Step Description: {step_description}\n\n"
            f"Respond with a JSON object containing a single key 'phase' whose value is exactly one of the four strings: "
            f"'Planning', 'Coding', 'Debugging', 'Documentation'."
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
    goal1 = agent1.get("goal", "") + " " + agent1.get("current_step", {}).get("description", "") if agent1.get("current_step") else agent1.get("goal", "")
    goal2 = agent2.get("goal", "") + " " + agent2.get("current_step", {}).get("description", "") if agent2.get("current_step") else agent2.get("goal", "")
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
                    if data.get("status") in ["exploring", "syncing", "pending_termination"]:
                        agents.append(data)
            except Exception as e:
                logging.error(f"Error loading agent file {filename}: {e}")
    return agents


def save_agent_state(agent):
    """Save an agent's state file."""
    filepath = os.path.join(AGENTS_DIR, f"agent_{agent['id']}.json")
    try:
        with open(filepath, 'w') as f:
            json.dump(agent, f, indent=2)
    except Exception as e:
        logging.error(f"Error saving state for agent {agent['id']}: {e}")


def handle_spawn_requests(agents):
    """Process any active spawn requests from agents."""
    for agent in agents:
        spawn_req = agent.get("spawn_request")
        if spawn_req:
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
                if other["status"] not in ["exploring", "syncing"]:
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
                logging.info(
                    f"[CONSENSUS APPROVED] Agent {agent['id']} termination approved. "
                    f"Branch covered by active Agent {covering_agent_id}."
                )
            else:
                # Extinction danger! Block termination and force agent to resume exploring
                agent["status"] = "exploring"
                save_agent_state(agent)
                logging.warning(
                    f"[CONSENSUS OVERRIDE] Extinction Prevention triggered! Rejected termination for Agent {agent['id']} "
                    f"as it is the last active agent covering its goal/task."
                )


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
                    save_agent_state(child)
                    logging.warning(
                        f"[CASCADING KILL] Supervisor killed child Agent {child_id} "
                        f"recursively because all of its parents are dead."
                    )
                    cascade(child_id)  # recurse
                
    # Run cascade check starting from all dead agents
    for agent_id, agent in list(all_agents.items()):
        if agent["status"] == "dead":
            cascade(agent_id)


def monitor_loop(poll_interval=1.5, collision_threshold=0.5):
    """Main polling loop to calculate proximity and supervise swarm execution."""
    logging.info("V2 Proximity Supervisor started. Coordinating swarm coordinates...")
    logging.info(f"Settings: Poll Interval = {poll_interval}s, Collision Threshold = {collision_threshold}")
    
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
    args = parser.parse_args()
    
    OLLAMA_MODEL = args.ollama_model
    
    try:
        monitor_loop(poll_interval=args.interval, collision_threshold=args.threshold)
    except KeyboardInterrupt:
        logging.info("Supervisor stopped by user.")
        sys.exit(0)
