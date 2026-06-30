import os
import json
from causal_tracer import log_decision
import logic_graph

def select_judge_model(provider=None, model=None, fallback_provider=None, fallback_model=None):
    """
    Selects the judge model. Ensures invariant #4: No remote-API escalation path.
    """
    if provider == "rules":
        return "rules", "rules"
        
    if provider == "ollama":
        if not model:
            return "ollama", fallback_model or "llama3"
        return "ollama", model
        
    if provider == "gemini":
        return "gemini", model or fallback_model or "gemini-1.5-pro"
        
    if fallback_provider:
        return fallback_provider, fallback_model
        
    return "ollama", "llama3"

def validate_step(node, provider, model, agent_id=None):
    """
    LLM-as-judge for steps with oracle.type == "checker_model".
    """
    result = {"valid": True, "reason": "Rule-based mock validation."}
    
    if provider == "rules":
        pass
    else:
        prompt = (
            f"You are the Judge Agent evaluating a logic step proposed in the swarm.\n"
            f"Target Node ID: {node.get('node_id')}\n"
            f"Claim: '{node.get('claim', '')}'\n"
            f"Justification: '{node.get('justification', '')}'\n"
            f"Oracle Spec/Rubric: '{node.get('oracle', {}).get('spec', '')}'\n\n"
            f"Please evaluate if the claim is valid, logical, and supported by the justification under the oracle rubric.\n"
            f"You must return a JSON object with the following fields:\n"
            f"1. 'valid' (boolean: true if valid and logical, false if invalid or refuted).\n"
            f"2. 'reason' (string: clear explanation of your judgment).\n"
        )
        try:
            if provider == "gemini":
                from agent_runner import call_gemini_api
                res = call_gemini_api(prompt)
            elif provider == "ollama":
                from agent_runner import call_ollama_api
                res = call_ollama_api(prompt, model=model)
            else:
                res = None
                
            if res and isinstance(res, dict) and "valid" in res:
                result["valid"] = bool(res["valid"])
                result["reason"] = res.get("reason", "No reason provided by LLM Judge.")
            else:
                result["valid"] = False
                result["reason"] = "Failed to parse LLM Judge response or invalid response schema."
        except Exception as e:
            result["valid"] = False
            result["reason"] = f"Judge exception: {e}"

    if agent_id:
        log_decision(agent_id, "judge_validate", {"node": node["node_id"]}, result["valid"], result["reason"])
    
    return result

def resolve_collision(collision, provider, model, agent_id=None):
    """
    Replaces perform_negotiation.
    Returns {action: "share"|"merge"|"kill_a"|"kill_b"|"keep_both", reason: str}
    """
    result = {"action": "keep_both", "reason": "Default rule-based resolution."}
    
    if provider == "rules":
        pass
    else:
        agent_a = collision.get("agent_a", {})
        agent_b = collision.get("agent_b", {})
        
        prompt = (
            f"You are the Judge Agent resolving a collision between two agents in the swarm.\n"
            f"Agent A ID: {agent_a.get('id')}\n"
            f"Agent A Goal: '{agent_a.get('goal', '')}'\n"
            f"Agent A Active Node ID: {agent_a.get('active_node_id')}\n\n"
            f"Agent B ID: {agent_b.get('id')}\n"
            f"Agent B Goal: '{agent_b.get('goal', '')}'\n"
            f"Agent B Active Node ID: {agent_b.get('active_node_id')}\n\n"
            f"Similarity Distance between them: {collision.get('distance', 0.0):.3f}\n\n"
            f"Evaluate how to resolve the overlap/collision between their current paths. Choose one of the following actions:\n"
            f"1. 'kill_a': Terminate Agent A (e.g. if Agent A's work is redundant or Agent B is further ahead).\n"
            f"2. 'kill_b': Terminate Agent B (e.g. if Agent B's work is redundant or Agent A is further ahead).\n"
            f"3. 'share': Keep both agents running, but mutually share all completed files and intermediate state.\n"
            f"4. 'merge': Fold two proposed nodes into one, reparenting dependencies, and continue with the survivor agent.\n"
            f"5. 'keep_both': Allow both to proceed independently with no changes.\n\n"
            f"You must return a JSON object with the following fields:\n"
            f"1. 'action' (string): one of 'kill_a', 'kill_b', 'share', 'merge', 'keep_both'.\n"
            f"2. 'reason' (string): clear justification for this action.\n"
        )
        try:
            if provider == "gemini":
                from agent_runner import call_gemini_api
                res = call_gemini_api(prompt)
            elif provider == "ollama":
                from agent_runner import call_ollama_api
                res = call_ollama_api(prompt, model=model)
            else:
                res = None
                
            if res and isinstance(res, dict) and "action" in res:
                act = res["action"].strip().lower()
                if act in ["kill_a", "kill_b", "share", "merge", "keep_both"]:
                    result["action"] = act
                    result["reason"] = res.get("reason", "No reason provided by LLM collision resolver.")
                else:
                    result["reason"] = f"LLM returned invalid action: {act}. Defaulting to keep_both."
            else:
                result["reason"] = "Failed to parse LLM collision resolver response or invalid response schema."
        except Exception as e:
            result["reason"] = f"Collision resolver exception: {e}"
        
    if agent_id:
        log_decision(agent_id, "judge_collision", {"collision": collision.get("id", collision.get("collision_id"))}, result["action"], result["reason"])
        
    return result

def rank_branches(leaves, provider, model):
    """
    Ranks branches for pruning by promise of the logic.
    """
    if not leaves:
        return []
        
    if provider == "rules":
        return sorted(leaves, key=lambda x: x.get("last_updated", 0), reverse=True)
        
    leaves_info = []
    for leaf in leaves:
        node_id = leaf.get("active_node_id")
        claim = ""
        if node_id:
            try:
                node = logic_graph.get_node(node_id)
                if node:
                    claim = node.get("claim", "")
            except Exception:
                pass
        leaves_info.append({
            "agent_id": leaf.get("id"),
            "goal": leaf.get("goal"),
            "active_node_id": node_id,
            "claim": claim,
            "progress": leaf.get("progress", 0),
            "steps_completed": leaf.get("steps_completed", 0)
        })
        
    prompt = (
        f"You are the Judge Agent ranking the search branches (agents) in the swarm based on their potential promise of resolving the global goal.\n"
        f"Here are the active branches/leaf agents:\n"
        f"{json.dumps(leaves_info, indent=2)}\n\n"
        f"Please rank these agents from most promising to least promising based on their goals and active claims/progress.\n"
        f"You must return a JSON object with a single key 'ranked_agent_ids' whose value is a list of the agent IDs in ranked order (from most promising to least promising).\n"
    )
    try:
        if provider == "gemini":
            from agent_runner import call_gemini_api
            res = call_gemini_api(prompt)
        elif provider == "ollama":
            from agent_runner import call_ollama_api
            res = call_ollama_api(prompt, model=model)
        else:
            res = None
            
        if res and isinstance(res, dict) and "ranked_agent_ids" in res:
            ranked_ids = res["ranked_agent_ids"]
            ranked_leaves = []
            for aid in ranked_ids:
                matching = [l for l in leaves if l.get("id") == str(aid)]
                if matching:
                    ranked_leaves.append(matching[0])
            for leaf in leaves:
                if leaf not in ranked_leaves:
                    ranked_leaves.append(leaf)
            return ranked_leaves
    except Exception as e:
        print(f"  [Judge rank_branches exception]: {e}")
        
    return sorted(leaves, key=lambda x: (x.get("progress", 0), x.get("last_updated", 0)), reverse=True)
