#!/usr/bin/env python3
import os
import sys
import json
import time
import subprocess
import argparse
from datetime import datetime

# Import Rich components
try:
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.table import Table
    from rich.live import Live
    from rich.console import Console
    from rich.text import Text
    from rich.align import Align
except ImportError:
    print("Error: The 'rich' library is required to run the terminal dashboard.")
    print("Please install it by running: pip install rich")
    sys.exit(1)

STATE_DIR = os.path.join(os.getcwd(), ".proximity_swarm")
AGENTS_DIR = os.path.join(STATE_DIR, "agents")
COLLISIONS_DIR = os.path.join(STATE_DIR, "collisions")
TOMBSTONES_FILE = os.path.join(STATE_DIR, "tombstones.json")
LOG_FILE = os.path.join(STATE_DIR, "monitor.log")

console = Console()


def load_json(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def get_swarm_summary():
    """Calculates counts of agents in each state."""
    summary = {"total": 0, "exploring": 0, "syncing": 0, "pending_termination": 0, "dead": 0, "completed": 0}
    if not os.path.exists(AGENTS_DIR):
        return summary
        
    for filename in os.listdir(AGENTS_DIR):
        if filename.endswith(".json"):
            filepath = os.path.join(AGENTS_DIR, filename)
            data = load_json(filepath)
            if data:
                summary["total"] += 1
                status = data.get("status", "exploring")
                if status in summary:
                    summary[status] += 1
    return summary


def make_header_panel():
    """Renders the dashboard header panel with clock and swarm stats."""
    summary = get_swarm_summary()
    time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    header_text = Text()
    header_text.append(" PROXIMITY SWARM V2 ", style="bold white on blue")
    header_text.append("  |  ", style="dim white")
    header_text.append(f"Time: {time_str}", style="cyan")
    header_text.append("  |  ", style="dim white")
    header_text.append(f"Total Agents: {summary['total']}  ", style="bold white")
    header_text.append(f"Exploring: {summary['exploring']}  ", style="bold green")
    header_text.append(f"Syncing: {summary['syncing']}  ", style="bold yellow")
    header_text.append(f"Pending Kill: {summary['pending_termination']}  ", style="bold magenta")
    header_text.append(f"Dead: {summary['dead']}  ", style="bold red")
    header_text.append(f"Completed: {summary['completed']}", style="bold blue")
    
    return Panel(Align.center(header_text), border_style="blue")


def make_agents_table():
    """Renders a table showing states and progress of all agents."""
    table = Table(title="Agent Swarm Status", expand=True)
    table.add_column("ID", justify="center", style="bold white", width=6)
    table.add_column("Parent", justify="center", style="dim white", width=8)
    table.add_column("Status", justify="center", width=12)
    table.add_column("Goal / Sub-task", justify="left")
    table.add_column("Progress", justify="center", width=12)
    table.add_column("Touched Files", justify="left", style="dim cyan")
    
    if os.path.exists(AGENTS_DIR):
        filenames = sorted(os.listdir(AGENTS_DIR))
        for filename in filenames:
            if filename.endswith(".json"):
                data = load_json(os.path.join(AGENTS_DIR, filename))
                if not data:
                    continue
                    
                status = data.get("status", "exploring")
                # Style states
                if status == "exploring":
                    status_styled = Text(status.upper(), style="bold green")
                elif status == "syncing":
                    status_styled = Text(status.upper(), style="bold yellow")
                elif status == "pending_termination":
                    status_styled = Text("PENDING KILL", style="bold magenta")
                elif status == "dead":
                    status_styled = Text(status.upper(), style="bold red dim")
                elif status == "completed":
                    status_styled = Text(status.upper(), style="bold blue")
                else:
                    status_styled = Text(status.upper())
                    
                # Renders mini ASCII progress bar
                prog = data.get("progress", 0)
                filled = int(prog / 10)
                bar = "█" * filled + "░" * (10 - filled)
                progress_styled = f"{bar} {prog}%"
                
                # Format files
                files = ", ".join(data.get("touched_files", []))
                if len(files) > 30:
                    files = files[:27] + "..."
                    
                table.add_row(
                    data.get("id"),
                    str(data.get("parent_id") or "None"),
                    status_styled,
                    data.get("goal")[:60] + ("..." if len(data.get("goal", "")) > 60 else ""),
                    progress_styled,
                    files
                )
    return Panel(table, border_style="green")


def make_collisions_panel():
    """Renders active and resolved collisions/negotiation logs."""
    table = Table(title="Collision & Negotiation Log", expand=True)
    table.add_column("Collision ID", justify="center", style="bold white", width=15)
    table.add_column("Distance", justify="center", width=10)
    table.add_column("Status", justify="center", width=15)
    table.add_column("Action Taken", justify="center")
    table.add_column("Reasoning / Details", justify="left")
    
    if os.path.exists(COLLISIONS_DIR):
        filenames = sorted(os.listdir(COLLISIONS_DIR))
        for filename in filenames:
            if filename.endswith(".json"):
                data = load_json(os.path.join(COLLISIONS_DIR, filename))
                if not data:
                    continue
                    
                status = data.get("status", "pending")
                status_styled = Text(status.upper(), style="bold yellow" if status != "resolved" else "bold blue")
                
                action = data.get("action_taken", "None")
                if action == "kill_b" or action == "kill_a":
                    action_styled = Text(action.upper(), style="bold red")
                elif action == "keep_both":
                    action_styled = Text(action.upper(), style="bold green")
                else:
                    action_styled = Text(action.upper())
                    
                table.add_row(
                    data.get("collision_id"),
                    f"{data.get('distance', 0.0):.3f}",
                    status_styled,
                    action_styled,
                    data.get("reasoning", "")[:50] + ("..." if len(data.get("reasoning", "")) > 50 else "")
                )
    return Panel(table, border_style="magenta")


def make_tombstones_panel():
    """Renders the list of registered compiler and execution blockers (tombstones)."""
    table = Table(title="Tombstones Blocker Database (Dynamic Belief Map)", expand=True)
    table.add_column("File Path", style="cyan", width=20)
    table.add_column("Tool", style="bold white", width=8)
    table.add_column("Error Message Signature", style="red")
    table.add_column("Suggested Workaround / Patch Action", style="bold green")
    
    tombstones = load_json(TOMBSTONES_FILE) or []
    for t in tombstones:
        table.add_row(
            t.get("file_path", "unknown"),
            t.get("tool_used", "unknown"),
            t.get("error_message", "unknown")[:50] + ("..." if len(t.get("error_message", "")) > 50 else ""),
            t.get("fix_action", "unknown")
        )
    return Panel(table, border_style="red")


def make_logs_panel():
    """Renders the tail of the background supervisor logs."""
    logs_lines = []
    if os.path.exists(LOG_FILE):
        try:
            with open(LOG_FILE, 'r') as f:
                lines = f.readlines()
                # Grab the last 8 lines
                logs_lines = [line.strip() for line in lines[-8:]]
        except Exception:
            pass
            
    log_text = Text()
    if logs_lines:
        for line in logs_lines:
            if "[WARNING]" in line or "COLLISION" in line:
                log_text.append(line + "\n", style="bold yellow")
            elif "[ERROR]" in line:
                log_text.append(line + "\n", style="bold red")
            elif "CONSENSUS APPROVED" in line:
                log_text.append(line + "\n", style="bold red")
            elif "CONSENSUS OVERRIDE" in line or "Extinction" in line:
                log_text.append(line + "\n", style="bold green")
            else:
                log_text.append(line + "\n", style="dim white")
    else:
        log_text.append("Waiting for supervisor logs...")
        
    return Panel(log_text, title="Supervisor Console Logs", border_style="cyan")


def main():
    parser = argparse.ArgumentParser(description="Proximity Swarm V2 - Terminal Monitor Dashboard")
    parser.add_argument("--run-redundant", action="store_true", help="Launch the identical goal collision demo")
    parser.add_argument("--deconflict", action="store_true", help="Enable goal deconfliction file parameter offsets")
    parser.add_argument("--interactive", action="store_true", help="Enable terminal prompts to manually negotiate collisions")
    parser.add_argument("--step-delay", type=float, default=2.0, help="Agent runner step delay in seconds")
    args = parser.parse_args()
    
    if not args.run_redundant:
        parser.print_help()
        sys.exit(0)
        
    # Build layout
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=10)
    )
    layout["body"].split_row(
        Layout(name="left", ratio=1),
        Layout(name="right", ratio=1)
    )
    layout["right"].split(
        Layout(name="right_top"),
        Layout(name="right_bottom")
    )
    
    # Launch supervisor subprocess
    supervisor_cmd = [
        sys.executable, "supervisor.py", 
        "--run-redundant"
    ]
    if args.deconflict:
        supervisor_cmd.append("--deconflict")
    if args.interactive:
        supervisor_cmd.append("--interactive")
        
    print(f"[Dashboard] Initializing simulation: {' '.join(supervisor_cmd)}...")
    time.sleep(1.0)
    
    # Run supervisor
    sup_proc = subprocess.Popen(supervisor_cmd)
    
    # Live loop updating layout components
    try:
        with Live(layout, refresh_per_second=5, screen=True) as live:
            while sup_proc.poll() is None:
                # Update layout parts
                layout["header"].update(make_header_panel())
                layout["left"].update(make_agents_table())
                layout["right_top"].update(make_collisions_panel())
                layout["right_bottom"].update(make_tombstones_panel())
                layout["footer"].update(make_logs_panel())
                time.sleep(0.2)
                
            # One final render cycle after exit
            layout["header"].update(make_header_panel())
            layout["left"].update(make_agents_table())
            layout["right_top"].update(make_collisions_panel())
            layout["right_bottom"].update(make_tombstones_panel())
            layout["footer"].update(make_logs_panel())
            
    except KeyboardInterrupt:
        pass
    finally:
        # Graceful cleanup
        sup_proc.terminate()
        sup_proc.wait()
        
        # Restore terminal screen
        console.clear()
        print("\n" + "="*50)
        print("    Terminal Dashboard Session Terminated")
        print("="*50 + "\n")


if __name__ == "__main__":
    main()
