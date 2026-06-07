#!/usr/bin/env python3
import os
import sys
import json
import time
import math
import string
import logging

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
        # Avoid division by zero
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


def calculate_proximity(agent1, agent2, corpus):
    """
    Computes composite distance metric between two agents.
    Returns (distance, cosine_sim, file_jaccard, tool_jaccard)
    """
    # Goals Cosine Similarity
    goal1 = agent1.get("goal", "") + " " + agent1.get("current_step", {}).get("description", "")
    goal2 = agent2.get("goal", "") + " " + agent2.get("current_step", {}).get("description", "")
    cosine_sim = calculate_tfidf_cosine_similarity(goal1, goal2, corpus)
    
    # Touched Files Jaccard Similarity
    files1 = agent1.get("touched_files", [])
    files2 = agent2.get("touched_files", [])
    file_jaccard = calculate_jaccard_similarity(files1, files2)
    
    # Tools Jaccard Similarity
    tools1 = agent1.get("tools_used", [])
    tools2 = agent2.get("tools_used", [])
    tool_jaccard = calculate_jaccard_similarity(tools1, tools2)
    
    # Distance components (distance = 1 - similarity)
    d_goal = 1.0 - cosine_sim
    d_workspace = 1.0 - file_jaccard
    d_tools = 1.0 - tool_jaccard
    
    # Weights: w1=0.5 (goal), w2=0.3 (workspace), w3=0.2 (tools)
    w1, w2, w3 = 0.5, 0.3, 0.2
    distance = w1 * d_goal + w2 * d_workspace + w3 * d_tools
    
    return distance, cosine_sim, file_jaccard, tool_jaccard


def load_active_agents():
    """Load states of all active agents."""
    agents = []
    if not os.path.exists(AGENTS_DIR):
        return agents
        
    for filename in os.listdir(AGENTS_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(AGENTS_DIR, filename)
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                    if data.get("status") in ["exploring", "syncing"]:
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
            
            # Find next agent ID
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
            
            # Create child state
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
            
            # Provision child workspace
            child_ws = os.path.join(WORKSPACES_DIR, f"agent_{child_id}")
            os.makedirs(child_ws, exist_ok=True)
            
            # Write child state
            save_agent_state(child_agent)
            
            # Update parent state to clear spawn request
            agent["spawn_request"] = None
            if "children" not in agent:
                agent["children"] = []
            agent["children"].append(child_id)
            save_agent_state(agent)
            
            logging.info(f"Spawned Child Agent {child_id} for Parent Agent {agent['id']}.")


def monitor_loop(poll_interval=1.5, collision_threshold=0.5):
    """Main polling loop to calculate proximity and detect collisions."""
    logging.info("Proximity Monitor started. Monitoring trajectory space...")
    logging.info(f"Settings: Poll Interval = {poll_interval}s, Collision Threshold = {collision_threshold}")
    
    while True:
        try:
            os.makedirs(AGENTS_DIR, exist_ok=True)
            os.makedirs(COLLISIONS_DIR, exist_ok=True)
            os.makedirs(WORKSPACES_DIR, exist_ok=True)
            
            agents = load_active_agents()
            
            # Handle any pending spawn requests first
            handle_spawn_requests(agents)
            
            # Re-load agents to include newly spawned ones
            agents = load_active_agents()
            
            # Build corpus of goals/steps for TF-IDF
            corpus = []
            for a in agents:
                goal_str = a.get("goal", "") + " " + a.get("current_step", {}).get("description", "")
                corpus.append(goal_str)
                
            # Check for collisions pairwise
            n = len(agents)
            collided_pairs = set()
            
            for i in range(n):
                for j in range(i + 1, n):
                    a1 = agents[i]
                    a2 = agents[j]
                    
                    # Compute distance
                    distance, cosine_sim, file_jaccard, tool_jaccard = calculate_proximity(a1, a2, corpus)
                    
                    logging.debug(
                        f"Pair ({a1['id']}, {a2['id']}): Distance={distance:.3f} | GoalSim={cosine_sim:.3f} | FileSim={file_jaccard:.3f}"
                    )
                    
                    if distance < collision_threshold:
                        # Collision detected!
                        collided_pairs.add((a1['id'], a2['id']))
                        
                        # Only trigger sync if both are actively exploring
                        if a1['status'] == "exploring" and a2['status'] == "exploring":
                            logging.warning(
                                f"COLLISION DETECTED between Agent {a1['id']} and Agent {a2['id']}! "
                                f"Distance: {distance:.3f} (GoalSim: {cosine_sim:.2f}, FileSim: {file_jaccard:.2f})"
                            )
                            
                            # Update statuses to syncing
                            a1['status'] = "syncing"
                            a2['status'] = "syncing"
                            
                            # Create collision JSON file
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
            logging.error(f"Error in monitor loop: {e}", exc_info=True)
            
        time.sleep(poll_interval)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Proximity Swarm - Background Monitor")
    parser.add_argument("--interval", type=float, default=1.5, help="Polling interval in seconds")
    parser.add_argument("--threshold", type=float, default=0.5, help="Collision distance threshold (lower = closer)")
    args = parser.parse_args()
    
    try:
        monitor_loop(poll_interval=args.interval, collision_threshold=args.threshold)
    except KeyboardInterrupt:
        logging.info("Proximity Monitor stopped by user.")
        sys.exit(0)
