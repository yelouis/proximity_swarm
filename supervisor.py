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
orchestrator_file = os.path.join(STATE_DIR, "orchestrator.json")


def clean_state():
    """Reset the local state directory to ensure clean runs."""
    print("[Supervisor] Cleaning up previous state directories...")
    if os.path.exists(STATE_DIR):
        try:
            shutil.rmtree(STATE_DIR)
        except Exception as e:
            print(f"  Warning: failed to clear state dir: {e}")
    os.makedirs(STATE_DIR, exist_ok=True)


def is_agent_sub_swarm_active(agent_id):
    if not os.path.exists(orchestrator_file):
        return True
    try:
        with open(orchestrator_file, 'r') as f:
            state = json.load(f)
        for sid, s in state.get("sub_swarms", {}).items():
            if agent_id in s.get("agent_ids", []):
                return s.get("status") == "active"
    except Exception:
        pass
    return True


def evaluate_sub_swarm_completion():
    if not os.path.exists(orchestrator_file):
        return
    try:
        with open(orchestrator_file, 'r') as f:
            state = json.load(f)
        agents_dir = os.path.join(STATE_DIR, "agents")
        all_agents = {}
        if os.path.exists(agents_dir):
            for filename in os.listdir(agents_dir):
                if filename.startswith("agent_") and filename.endswith(".json"):
                    aid = filename.replace("agent_", "").replace(".json", "")
                    try:
                        with open(os.path.join(agents_dir, filename), 'r') as f_ag:
                            all_agents[aid] = json.load(f_ag)
                    except Exception:
                        pass
        is_graph_complete = False
        try:
            import logic_graph
            nodes = logic_graph._get_all_nodes()
            for n in nodes.values():
                if n.get("kind") == "goal" and n.get("status") != "validated":
                    deps = n.get("depends_on", [])
                    if deps and all(nodes.get(d, {}).get("status") == "validated" for d in deps):
                        logic_graph.update_node(n["node_id"], status="validated")
            
            nodes = logic_graph._get_all_nodes()
            path = logic_graph.validated_path_to_goal()
            if path is not None:
                goal_node = None
                for n in nodes.values():
                    if n.get("kind") == "goal":
                        goal_node = n
                        break
                if goal_node and goal_node.get("status") == "validated":
                    is_graph_complete = True
        except Exception:
            pass
            
        updated = False
        for sid, s in state.get("sub_swarms", {}).items():
            if s.get("status") == "active":
                agent_ids = s.get("agent_ids", [])
                
                if is_graph_complete:
                    s["status"] = "completed"
                    updated = True
                    print(f"[Supervisor] Sub-Swarm {sid} completed via graph validation.")
                    continue
                    
                if not agent_ids:
                    s["status"] = "completed"
                    updated = True
                    print(f"[Supervisor] Sub-Swarm {sid} has no agents. Marking as completed.")
                    continue
                all_finished = True
                for aid in agent_ids:
                    agent_state = all_agents.get(aid)
                    if agent_state:
                        if agent_state.get("status") not in ["completed", "dead"]:
                            all_finished = False
                            break
                    else:
                        all_finished = False
                        break
                if all_finished:
                    s["status"] = "completed"
                    updated = True
                    print(f"[Supervisor] Sub-Swarm {sid} agents have completed. Marking Sub-Swarm as completed.")
        if updated:
            for sid, s in state.get("sub_swarms", {}).items():
                if s.get("status") == "pending":
                    deps = s.get("dependencies", [])
                    all_deps_met = True
                    for d in deps:
                        dep_swarm = state["sub_swarms"].get(d)
                        if not dep_swarm or dep_swarm.get("status") != "completed":
                            all_deps_met = False
                            break
                    if all_deps_met:
                        s["status"] = "active"
                        print(f"[Supervisor] Sub-Swarm {sid} dependencies resolved. Activating Sub-Swarm.")
            with open(orchestrator_file, 'w') as f:
                json.dump(state, f, indent=2)
    except Exception as e:
        print(f"[Supervisor Error] Failed to evaluate sub-swarms: {e}")


def run_swarm(initial_agents, deconflict=False, interactive=False, llm_provider=None, ollama_model="gemma4:latest", step_delay=2.0, budget=20000, auto_approve_spawns=False, graph_mode="graph", macro_goal="Run task"):
    """
    Launches a swarm dynamically, starting with initial_agents (list of dicts containing agent_id and task_id).
    Dynamically spawns runners for any children created during execution.
    """
    clean_state()
    
    print("\n" + "="*60)
    print(f"  STARTING PROXIMITY SWARM RUN")
    print(f"  Initial Agents: {len(initial_agents)} | Deconfliction: {deconflict} | Interactive: {interactive}")
    print(f"  LLM Provider: {llm_provider or 'Auto-Detect'} | Ollama Model: {ollama_model} | Step Delay: {step_delay}s | Budget: {budget} | Auto-approve Spawns: {auto_approve_spawns}")
    print("="*60 + "\n")
    
    if not os.path.exists(orchestrator_file):
        sub_swarms = {
            "swarm_001": {
                "id": "swarm_001",
                "goal": "Run swarm",
                "role": "Generalist Group",
                "dependencies": [],
                "status": "active",
                "agent_ids": [a["agent_id"] for a in initial_agents]
            }
        }
        state = {
            "macro_goal": macro_goal,
            "sub_swarms": sub_swarms
        }
        os.makedirs(STATE_DIR, exist_ok=True)
        with open(orchestrator_file, 'w') as f:
            json.dump(state, f, indent=2)
    else:
        try:
            with open(orchestrator_file, 'r') as f:
                state = json.load(f)
            updated = False
            for sid, s in state.get("sub_swarms", {}).items():
                if not s.get("dependencies") and s.get("status") == "pending":
                    s["status"] = "active"
                    updated = True
            if updated:
                with open(orchestrator_file, 'w') as f:
                    json.dump(state, f, indent=2)
        except Exception:
            pass
    
    if graph_mode == "graph":
        try:
            import logic_graph
            logic_graph.init_graph()
            nodes = logic_graph._get_all_nodes()
            if not nodes:
                macro_goal = state.get("macro_goal", "Run task")
                logic_graph.add_node({
                    "node_id": "goal_0",
                    "kind": "goal",
                    "claim": macro_goal,
                    "status": "proposed",
                    "depends_on": []
                })
                logic_graph.add_node({
                    "node_id": "premise_0",
                    "kind": "premise",
                    "claim": "Initial state and context",
                    "status": "validated",
                    "depends_on": []
                })
        except Exception as e:
            print(f"Error seeding logic graph: {e}")

    # 1. Start the background Supervisor Monitor process
    print("[Supervisor] Launching Supervisor Monitor daemon...")
    monitor_cmd = [sys.executable, "proximity_monitor.py", "--interval", "0.5"]
    if ollama_model:
        monitor_cmd.extend(["--ollama-model", ollama_model])
    if interactive:
        monitor_cmd.append("--interactive")
    if budget:
        monitor_cmd.extend(["--budget", str(budget)])
    if auto_approve_spawns:
        monitor_cmd.append("--auto-approve-spawns")
    monitor_cmd.extend(["--graph-mode", graph_mode])
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
        cmd.extend(["--graph-mode", graph_mode])
            
        print(f"[Supervisor] Launching Agent {agent_id} runner subprocess...")
        running_processes[agent_id] = subprocess.Popen(cmd)


    # Initialize trace nodes for initial agents
    try:
        import causal_tracer
        for a in initial_agents:
            aid = a["agent_id"]
            causal_tracer.add_node(
                f"agent_{aid}",
                "agent",
                f"Agent {aid} ({a.get('personality', 'Generalist')})",
                {"goal": a.get("goal")}
            )
            causal_tracer.log_state_transition(aid, "none", "exploring")
    except Exception:
        pass

    # Launch initial agents (only if their sub-swarm is active!)
    for idx, agent_info in enumerate(initial_agents):
        agent_id = agent_info["agent_id"]
        task_id = agent_info["task_id"]
        personality = agent_info.get("personality")
        goal = agent_info.get("goal")
        offset = f"offset_{idx}" if (deconflict or len(initial_agents) > 1) else None
        if is_agent_sub_swarm_active(agent_id):
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
                
            # Evaluate sub-swarm completions and transitions
            evaluate_sub_swarm_completion()
            
            # Check if any initial agents should be launched now that their sub-swarm is active
            for idx, agent_info in enumerate(initial_agents):
                agent_id = agent_info["agent_id"]
                if agent_id not in running_processes:
                    if is_agent_sub_swarm_active(agent_id):
                        state_path = os.path.join(STATE_DIR, "agents", f"agent_{agent_id}.json")
                        already_finished = False
                        if os.path.exists(state_path):
                            try:
                                with open(state_path, 'r') as f:
                                    ag_data = json.load(f)
                                if ag_data.get("status") in ["completed", "dead"]:
                                    already_finished = True
                            except Exception:
                                pass
                        if not already_finished:
                            task_id = agent_info["task_id"]
                            personality = agent_info.get("personality")
                            goal = agent_info.get("goal")
                            offset = f"offset_{idx}" if (deconflict or len(initial_agents) > 1) else None
                            launch_agent(agent_id, task_id, offset, personality, goal)
            
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
                                        if is_agent_sub_swarm_active(agent_id):
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
        
        # Phase 8: Emit observability artifacts
        try:
            import logic_graph
            import causal_tracer
            import memory_store
            
            ts = int(time.time())
            
            # 1. Graph JSON and Mermaid
            graph_json = logic_graph.to_artifact_json()
            mermaid_str = logic_graph.to_mermaid()
            
            graph_dir = logic_graph.GRAPH_DIR
            os.makedirs(graph_dir, exist_ok=True)
            
            json_path = os.path.join(graph_dir, f"run_{ts}.json")
            with open(json_path, 'w') as f:
                json.dump(graph_json, f, indent=2)
                
            md_path = os.path.join(graph_dir, f"run_{ts}.md")
            with open(md_path, 'w') as f:
                f.write(f"# Logic Graph Run {ts}\n\n```mermaid\n{mermaid_str}\n```\n")
                
            print(f"[Supervisor] Artifacts saved to {json_path} and {md_path}")
            
            # 2. Episodic memory
            macro_goal = "Unknown Goal"
            try:
                if os.path.exists(orchestrator_file):
                    with open(orchestrator_file, 'r') as f:
                        macro_goal = json.load(f).get("macro_goal", "Unknown Goal")
                elif initial_agents and initial_agents[0].get("goal"):
                    macro_goal = initial_agents[0].get("goal")
            except Exception:
                pass
                
            memory_store.save_episode(
                goal=macro_goal,
                role="Orchestrator",
                status="completed",
                steps=[{"name": "Graph swarm run", "description": "Swarm run finished with graph validation."}],
                errors="",
                deliverable_summary=f"Graph size: {len(graph_json.get('nodes', {}))} nodes.",
                reflection=""
            )
            print("[Supervisor] Episodic memory saved.")
            
        except Exception as e:
            print(f"[Supervisor] Failed to save observability artifacts: {e}")

        
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


def run_redundant_demo(interactive=False, deconflict=False, llm_provider=None, ollama_model="gemma4:latest", step_delay=2.0, budget=20000, graph_mode="graph"):
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
        step_delay=step_delay,
        budget=budget,
        graph_mode=graph_mode
    )


def main():
    parser = argparse.ArgumentParser(description="Proximity Swarm V2 - Orchestrator Entrypoint")
    parser.add_argument("--run-spec", help="Path to declarative JSON/YAML run spec file")
    parser.add_argument("--run-redundant", action="store_true", help="Launch two identical auth agents (collision check)")
    parser.add_argument("--task-id", help="Launch a custom task from mock_tasks.json and manage the swarm dynamically")
    parser.add_argument("--deconflict", action="store_true", help="Enable goal deconfliction file parameter offsets")
    parser.add_argument("--interactive", action="store_true", help="Enable terminal prompts to manually negotiate collisions")
    parser.add_argument("--llm-provider", choices=["gemini", "ollama", "rules"], help="LLM API provider for deconfliction negotiation")
    parser.add_argument("--ollama-model", default="gemma4:latest", help="Ollama model string to query if provider is ollama")
    parser.add_argument("--step-delay", type=float, default=2.0, help="Simulation step delay in seconds")
    parser.add_argument("--personalities", help="Comma-separated list of agent personalities/roles to initialize")
    parser.add_argument("--agents-config", help="JSON string representing starting agent configurations")
    parser.add_argument("--budget", type=int, default=20000, help="Maximum active leaf agent output token budget cap limit")
    parser.add_argument("--auto-approve-spawns", action="store_true", default=None, help="Bypass manual operator approval for spawn requests")
    parser.add_argument("--graph-mode", choices=["linear", "graph"], default="graph", help="Execution mode (linear steps or graph)")
    parser.add_argument("--memory-limit", type=int, default=500, help="Maximum number of episodic memories to keep in DB")
    parser.add_argument("--gc-workspace", action="store_true", help="Garbage collect workspace tombstones at the end of the run")
    parser.add_argument("--gc-graph", action="store_true", help="Garbage collect graph node files at the end of the run")
    parser.add_argument("--gc-dry-run", action="store_true", help="Dry-run mode for workspace and graph garbage collection")
    args = parser.parse_args()
    
    spec_goal = None
    if args.run_spec:
        with open(args.run_spec, 'r') as f:
            if args.run_spec.endswith('.yaml') or args.run_spec.endswith('.yml'):
                import yaml
                spec = yaml.safe_load(f)
            else:
                spec = json.load(f)
        
        spec_goal = spec.get("goal")
        # For a full headless driver, we'd override other args
        args.budget = spec.get("budget", args.budget)
        args.llm_provider = spec.get("swarm_provider", args.llm_provider)
        args.graph_mode = spec.get("graph_mode", args.graph_mode)
        if "seed_roles" in spec:
            args.agents_config = json.dumps([
                {
                    "agent_id": f"{i+1:03d}",
                    "personality": r["role"],
                    "goal": spec_goal,
                    "task_id": None
                }
                for i, r in enumerate(spec["seed_roles"])
            ])

    auto_approve_spawns = args.auto_approve_spawns
    if auto_approve_spawns is None:
        if args.agents_config and not args.run_spec:
            auto_approve_spawns = False
        else:
            auto_approve_spawns = True

    try:
        if args.run_redundant:
            run_redundant_demo(
                interactive=args.interactive, 
                deconflict=args.deconflict,
                llm_provider=args.llm_provider,
                ollama_model=args.ollama_model,
                step_delay=args.step_delay,
                budget=args.budget,
                graph_mode=args.graph_mode
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
                step_delay=args.step_delay,
                budget=args.budget,
                auto_approve_spawns=auto_approve_spawns,
                graph_mode=args.graph_mode,
                macro_goal=spec_goal if spec_goal else "Run task"
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
                step_delay=args.step_delay,
                budget=args.budget,
                auto_approve_spawns=auto_approve_spawns,
                graph_mode=args.graph_mode
            )
        else:
            parser.print_help()
    finally:
        # Engine Teardown GC
        if getattr(args, "gc_graph", False):
            try:
                import logic_graph
                logic_graph.set_monitor(True)
                logic_graph.garbage_collect_post_run(dry_run=getattr(args, "gc_dry_run", False))
            except Exception as e:
                print(f"Graph GC Error: {e}")
            
        if args.gc_workspace:
            try:
                import workspace_gc
                workspace_gc.cleanup_workspace(dry_run=args.gc_dry_run)
            except Exception as e:
                print(f"Workspace GC Error: {e}")


if __name__ == "__main__":
    main()
