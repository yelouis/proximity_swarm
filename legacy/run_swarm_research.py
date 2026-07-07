#!/usr/bin/env python3
import os
import sys
import json
import time
import urllib.request
import urllib.error

OLLAMA_MODEL = "gemma4:latest"
OUTPUT_REPORT_PATH = "/Users/louisye/Desktop/Louis/proximity_swarm/research_report.md"

def call_ollama(prompt):
    """Query the local Ollama instance with a prompt."""
    url = "http://localhost:11434/api/generate"
    headers = {"Content-Type": "application/json"}
    body = {
        "model": OLLAMA_MODEL,
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
        # 90-second timeout to allow the model to fully process long-form responses
        with urllib.request.urlopen(req, timeout=90) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data.get("response", "").strip()
    except Exception as e:
        print(f"[Ollama Error] Query failed: {e}")
        return None

def main():
    print("="*60)
    print("    LAUNCHING SWARM RESEARCH & IMPROVEMENT INVESTIGATION")
    print(f"    Target LLM: {OLLAMA_MODEL} | Output: {OUTPUT_REPORT_PATH}")
    print("="*60 + "\n")

    # Step 1: Agent 009 - AutoGen & LangGraph
    print("[Agent 009] Starting Research Phase: Industry Parallels (Part 1)...")
    prompt_009_s1 = (
        "Research and analyze the orchestration, state management, routing, and deconfliction mechanisms "
        "in Microsoft AutoGen and LangGraph. Detail how they manage agent communications, graphs, cycles, "
        "and how they prevent duplicate work or infinite loop conditions. Focus on technical primitives "
        "(e.g., LangGraph state channels, AutoGen GroupChatManager). Format the response in highly detailed Markdown."
    )
    print("  Querying Ollama for AutoGen & LangGraph analysis...")
    time.sleep(1)
    res_009_s1 = call_ollama(prompt_009_s1)
    if not res_009_s1:
        print("  [Error] Failed to gather data for AutoGen & LangGraph. Exiting.")
        sys.exit(1)
    print("  [Agent 009] Completed AutoGen & LangGraph research step.")
    
    # Step 2: Agent 010 - Proximity Swarm V2 Current Primitives
    print("\n[Agent 010] Starting Evaluation Phase: Current Primitives...")
    prompt_010_s1 = (
        "Evaluate the current architecture of Proximity Swarm V2. Its features include:\n"
        "1. Trajectory State logging via local JSON files.\n"
        "2. Proximity calculation using TF-IDF Cosine Similarity for goals, Jaccard index for touched files, and Jaccard for tools.\n"
        "3. Collision pausing and negotiation converse skills using LLMs or fallback rules.\n"
        "4. Consensus-gated termination (extinction prevention) ensuring task coverage is kept.\n"
        "5. Cascading kill switch (runaway prevention) killing descendants of dead parents.\n"
        "6. Deconfliction goal parameters offsets.\n\n"
        "Analyze the strengths and limitations of this architecture. Compare it to traditional architectures. Format in detailed Markdown."
    )
    print("  Querying Ollama for Proximity Swarm V2 evaluation...")
    time.sleep(1)
    res_010_s1 = call_ollama(prompt_010_s1)
    if not res_010_s1:
        print("  [Error] Failed to evaluate Proximity Swarm V2. Exiting.")
        sys.exit(1)
    print("  [Agent 010] Completed Proximity Swarm V2 architecture evaluation.")

    # Step 3: Agent 009 - CrewAI & OpenAI Swarm
    print("\n[Agent 009] Starting Research Phase: Industry Parallels (Part 2)...")
    prompt_009_s2 = (
        "Research and analyze the orchestration, state management, routing, and deconfliction mechanisms "
        "in CrewAI and OpenAI Swarm. Detail how they handle role delegation, task routing, handoffs, "
        "and light-weight coordination. Compare them. Format the response in highly detailed Markdown."
    )
    print("  Querying Ollama for CrewAI & OpenAI Swarm analysis...")
    time.sleep(1)
    res_009_s2 = call_ollama(prompt_009_s2)
    if not res_009_s2:
        print("  [Error] Failed to gather data for CrewAI & OpenAI Swarm. Exiting.")
        sys.exit(1)
    print("  [Agent 009] Completed CrewAI & OpenAI Swarm research step.")

    # Step 4: Agent 010 - Improvements & Enhancements
    print("\n[Agent 010] Starting Innovation Phase: Architectural Enhancements...")
    prompt_010_s2 = (
        "Formulate detailed architectural improvement ideas for Proximity Swarm. "
        "Draw inspiration from AutoGen, LangGraph, CrewAI, and OpenAI Swarm. Suggest improvements such as:\n"
        "- Episodic experience logs & semantic vector lookup for past tombstones.\n"
        "- Dynamic weighting of proximity (e.g. goal vs files vs tools based on task phase).\n"
        "- Hierarchical swarm scaling (routing tasks to sub-swarms).\n"
        "- Visual graph routing & trace logs.\n"
        "Explain how these features could be implemented technically. Format in detailed Markdown."
    )
    print("  Querying Ollama for architectural improvement ideas...")
    time.sleep(1)
    res_010_s2 = call_ollama(prompt_010_s2)
    if not res_010_s2:
        print("  [Error] Failed to generate architectural improvement ideas. Exiting.")
        sys.exit(1)
    print("  [Agent 010] Completed architectural improvement ideas.")

    # Step 5: Merge / Negotiation Protocol
    print("\n[Swarm Orchestrator] Starting Negotiation & Consensus Protocol...")
    print("  Blending research drafts into a single cohesive, premium report...")
    time.sleep(1)
    
    merge_prompt = (
        "You are the Swarm Lead merging the research reports from Agent 009 (Industry Parallels Researcher) "
        "and Agent 010 (Framework Architect).\n\n"
        f"--- Agent 009 Draft Part 1 (AutoGen & LangGraph):\n{res_009_s1}\n\n"
        f"--- Agent 009 Draft Part 2 (CrewAI & OpenAI Swarm):\n{res_009_s2}\n\n"
        f"--- Agent 010 Draft Part 1 (Proximity Swarm V2 Assessment):\n{res_010_s1}\n\n"
        f"--- Agent 010 Draft Part 2 (Enhancement Proposals):\n{res_010_s2}\n\n"
        "Combine all of the above drafts into a single, cohesive, comprehensive, highly professional Markdown report. "
        "Organize it into the following sections:\n"
        "1. Executive Summary\n"
        "2. Industry Parallels (Microsoft AutoGen, LangGraph, CrewAI, OpenAI Swarm)\n"
        "3. Proximity Swarm V2 Architectural Assessment\n"
        "4. Recommended Enhancements & Architectural Improvements (highly technical, explaining implementation details)\n\n"
        "Format it using clean, beautiful Markdown headers, bullet points, tables, and bold highlights."
    )
    
    final_report = call_ollama(merge_prompt)
    if not final_report:
        print("  [Error] Failed to merge research reports. Exiting.")
        sys.exit(1)
        
    # Write to final file
    try:
        with open(OUTPUT_REPORT_PATH, 'w') as f:
            f.write(final_report)
        print(f"\n[Success] Final research report written to: {OUTPUT_REPORT_PATH}")
    except Exception as e:
        print(f"  [Error] Failed to write report to disk: {e}")
        sys.exit(1)
        
    print("\n" + "="*60)
    print("    SWARM RESEARCH INVESTIGATION COMPLETED SUCCESSFULLY")
    print("="*60 + "\n")

if __name__ == "__main__":
    main()
