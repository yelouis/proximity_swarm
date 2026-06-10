#!/usr/bin/env python3
import os
import sys
import json
import subprocess
import time
import shutil
import argparse

STATE_DIR = os.path.join(os.getcwd(), ".proximity_swarm")
LOG_FILE = os.path.join(STATE_DIR, "monitor.log")


def clean_state():
    """Reset the local state directory to ensure clean runs."""
    print("[Supervisor] Cleaning up previous state directories...")
    if os.path.exists(STATE_DIR):
        try:
            shutil.rmtree(STATE_DIR)
        except Exception as e:
            print(f"  Warning: failed to clear state dir: {e}")
    os.makedirs(STATE_DIR, exist_ok=True)


def run_swarm(initial_agents, deconflict=False, interactive=False, llm_provider=None, ollama_model="gemma4:latest", step_delay=2.0):
    """
    Launches a swarm dynamically, starting with initial_agents (list of dicts containing agent_id and task_id).
    Dynamically spawns runners for any children created during execution.
    """
    clean_state()
    
    print("\n" + "="*60)
    print(f"  STARTING PROXIMITY SWARM RUN")
    print(f"  Initial Agents: {len(initial_agents)} | Deconfliction: {deconflict} | Interactive: {interactive}")
    print(f"  LLM Provider: {llm_provider or 'Auto-Detect'} | Ollama Model: {ollama_model} | Step Delay: {step_delay}s")
    print("="*60 + "\n")
    
    # 1. Start the background Supervisor Monitor process
    print("[Supervisor] Launching Supervisor Monitor daemon...")
    monitor_cmd = [sys.executable, "proximity_monitor.py", "--interval", "0.5"]
    monitor_proc = subprocess.Popen(
        monitor_cmd, 
        stdout=subprocess.DEVNULL, 
        stderr=subprocess.DEVNULL
    )
    time.sleep(1.0)  # wait for supervisor startup
    
    running_processes = {}
    
    # Helper to launch an agent runner
    def launch_agent(agent_id, task_id=None, offset_suffix=None, personality=None, goal=None):
        cmd = [
            sys.executable, "agent_runner.py",
            "--agent-id", agent_id,
            "--step-delay", str(step_delay),
            "--steps", "15"
        ]
        if task_id:
            cmd.extend(["--task-id", task_id])
        if offset_suffix:
            cmd.extend(["--offset-suffix", offset_suffix])
        if interactive:
            cmd.append("--interactive")
        if llm_provider:
            cmd.extend(["--llm-provider", llm_provider])
        if ollama_model:
            cmd.extend(["--ollama-model", ollama_model])
        if personality:
            cmd.extend(["--personality", personality])
        if goal:
            cmd.extend(["--goal", goal])
            
        print(f"[Supervisor] Launching Agent {agent_id} runner subprocess...")
        running_processes[agent_id] = subprocess.Popen(cmd)

    # Launch initial agents
    for idx, agent_info in enumerate(initial_agents):
        agent_id = agent_info["agent_id"]
        task_id = agent_info["task_id"]
        personality = agent_info.get("personality")
        goal = agent_info.get("goal")
        offset = f"offset_{idx}" if (deconflict or len(initial_agents) > 1) else None
        launch_agent(agent_id, task_id, offset, personality, goal)

    try:
        # Dynamic monitoring loop
        while True:
            # 1. Poll existing processes and clean up finished ones
            finished_ids = []
            for agent_id, proc in list(running_processes.items()):
                if proc.poll() is not None:
                    finished_ids.append(agent_id)
            
            for agent_id in finished_ids:
                del running_processes[agent_id]
                print(f"[Supervisor] Agent {agent_id} runner subprocess exited.")
                
            # 2. Check `.proximity_swarm/agents` to find active agents that aren't running
            agents_dir = os.path.join(STATE_DIR, "agents")
            if os.path.exists(agents_dir):
                try:
                    for filename in os.listdir(agents_dir):
                        if filename.startswith("agent_") and filename.endswith(".json"):
                            agent_id = filename.replace("agent_", "").replace(".json", "")
                            if agent_id not in running_processes:
                                # Read JSON state to verify if active
                                filepath = os.path.join(agents_dir, filename)
                                try:
                                    with open(filepath, 'r') as f:
                                        data = json.load(f)
                                    if data.get("status") in ["exploring", "syncing", "pending_termination"]:
                                        # Launch runner for this agent
                                        launch_agent(agent_id)
                                except Exception:
                                    pass
                except Exception:
                    pass
            
            # 3. Exit condition: monitor daemon and all agent runners have stopped
            if not running_processes:
                break
                
            time.sleep(0.5)
            
        print("\n[Supervisor] Swarm execution completed successfully.")
        
    except KeyboardInterrupt:
        print("\n[Supervisor] Swarm execution interrupted by user. Terminating processes...")
    finally:
        # Graceful cleanup of child processes
        for agent_id, proc in list(running_processes.items()):
            try:
                proc.terminate()
                proc.wait()
            except Exception:
                pass
        try:
            monitor_proc.terminate()
            monitor_proc.wait()
        except Exception:
            pass
        print("[Supervisor] Cleaned up child processes.")


def run_redundant_demo(interactive=False, deconflict=False, llm_provider=None, ollama_model="gemma4:latest", step_delay=2.0):
    """
    Launches two agents assigned to the same task (redundancy test).
    If deconflict is enabled, applies goal deconfliction offsets to their files.
    """
    initial_agents = [
        {"agent_id": "007", "task_id": "task_jwt_auth"},
        {"agent_id": "008", "task_id": "task_jwt_auth"}
    ]
    run_swarm(
        initial_agents=initial_agents,
        deconflict=deconflict,
        interactive=interactive,
        llm_provider=llm_provider,
        ollama_model=ollama_model,
        step_delay=step_delay
    )


def main():
    parser = argparse.ArgumentParser(description="Proximity Swarm V2 - Orchestrator Entrypoint")
    parser.add_argument("--run-redundant", action="store_true", help="Launch two identical auth agents (collision check)")
    parser.add_argument("--task-id", help="Launch a custom task from mock_tasks.json and manage the swarm dynamically")
    parser.add_argument("--deconflict", action="store_true", help="Enable goal deconfliction file parameter offsets")
    parser.add_argument("--interactive", action="store_true", help="Enable terminal prompts to manually negotiate collisions")
    parser.add_argument("--llm-provider", choices=["gemini", "ollama", "rules"], help="LLM API provider for deconfliction negotiation")
    parser.add_argument("--ollama-model", default="gemma4:latest", help="Ollama model string to query if provider is ollama")
    parser.add_argument("--step-delay", type=float, default=2.0, help="Simulation step delay in seconds")
    parser.add_argument("--personalities", help="Comma-separated list of agent personalities/roles to initialize")
    parser.add_argument("--agents-config", help="JSON string representing starting agent configurations")
    args = parser.parse_args()
    
    if args.run_redundant:
        run_redundant_demo(
            interactive=args.interactive, 
            deconflict=args.deconflict,
            llm_provider=args.llm_provider,
            ollama_model=args.ollama_model,
            step_delay=args.step_delay
        )
    elif args.agents_config:
        try:
            initial_agents = json.loads(args.agents_config)
        except Exception as e:
            print(f"Error parsing --agents-config: {e}")
            sys.exit(1)
            
        run_swarm(
            initial_agents=initial_agents,
            deconflict=args.deconflict,
            interactive=args.interactive,
            llm_provider=args.llm_provider,
            ollama_model=args.ollama_model,
            step_delay=args.step_delay
        )
    elif args.task_id:
        personalities = []
        if args.personalities:
            personalities = [p.strip() for p in args.personalities.split(",") if p.strip()]
            
        if personalities:
            initial_agents = [
                {"agent_id": f"{idx+1:03d}", "task_id": args.task_id, "personality": role}
                for idx, role in enumerate(personalities)
            ]
        else:
            initial_agents = [{"agent_id": "001", "task_id": args.task_id}]
            
        run_swarm(
            initial_agents=initial_agents,
            deconflict=args.deconflict,
            interactive=args.interactive,
            llm_provider=args.llm_provider,
            ollama_model=args.ollama_model,
            step_delay=args.step_delay
        )
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
