#!/usr/bin/env python3
import os
import sys
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


def run_redundant_demo(interactive=False, deconflict=False):
    """
    Launches two agents assigned to the same task (redundancy test).
    If deconflict is enabled, applies goal deconfliction offsets to their files.
    """
    clean_state()
    
    print("\n" + "="*60)
    print(f"  STARTING PROXIMITY SWARM V2 DEMO")
    print(f"  Redundant collision check | Deconfliction: {deconflict} | Interactive: {interactive}")
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
    
    # 2. Assign agent configurations (Goal Deconfliction Queue)
    agent_a_id = "007"
    agent_b_id = "008"
    
    # If deconfliction is enabled, assign suffix offsets to the agents' workspaces
    offset_a = "offset_a" if deconflict else None
    offset_b = "offset_b" if deconflict else None
    
    # Run Agent A (Task: task_jwt_auth)
    cmd_a = [
        sys.executable, "agent_runner.py", 
        "--agent-id", agent_a_id, 
        "--task-id", "task_jwt_auth", 
        "--step-delay", "2.0", 
        "--steps", "5"
    ]
    if offset_a:
        cmd_a.extend(["--offset-suffix", offset_a])
    if interactive:
        cmd_a.append("--interactive")
        
    # Run Agent B (Task: task_jwt_auth)
    cmd_b = [
        sys.executable, "agent_runner.py", 
        "--agent-id", agent_b_id, 
        "--task-id", "task_jwt_auth", 
        "--step-delay", "2.0", 
        "--steps", "5"
    ]
    if offset_b:
        cmd_b.extend(["--offset-suffix", offset_b])
    if interactive:
        cmd_b.append("--interactive")
        
    print(f"[Supervisor] Launching Agent {agent_a_id} runner (Process A)...")
    proc_a = subprocess.Popen(cmd_a)
    
    print(f"[Supervisor] Launching Agent {agent_b_id} runner (Process B)...")
    proc_b = subprocess.Popen(cmd_b)
    
    # Watch processes
    try:
        while True:
            status_a = proc_a.poll()
            status_b = proc_b.poll()
            
            if status_a is not None and status_b is not None:
                break
                
            time.sleep(0.5)
            
        print("\n[Supervisor] Simulation runs completed.")
        
    except KeyboardInterrupt:
        print("\n[Supervisor] Simulation interrupted by user. Terminating processes...")
    finally:
        # Graceful cleanup of child processes
        proc_a.terminate()
        proc_b.terminate()
        monitor_proc.terminate()
        
        proc_a.wait()
        proc_b.wait()
        monitor_proc.wait()
        print("[Supervisor] Cleaned up child processes.")


def main():
    parser = argparse.ArgumentParser(description="Proximity Swarm V2 - Orchestrator Entrypoint")
    parser.add_argument("--run-redundant", action="store_true", help="Launch two identical auth agents (collision check)")
    parser.add_argument("--deconflict", action="store_true", help="Enable goal deconfliction file parameter offsets")
    parser.add_argument("--interactive", action="store_true", help="Enable terminal prompts to manually negotiate collisions")
    args = parser.parse_args()
    
    if args.run_redundant:
        run_redundant_demo(interactive=args.interactive, deconflict=args.deconflict)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
