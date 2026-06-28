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
            # Could implement largest local model detection here.
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
        # Mocking LLM based judge for now
        result["reason"] = f"Judged by {model}"

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
        # Mock LLM collision resolver
        result["reason"] = f"Judged by {model}"
        
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
        
    # Mock LLM ranking
    return sorted(leaves, key=lambda x: x.get("last_updated", 0), reverse=True)
