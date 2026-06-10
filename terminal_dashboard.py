#!/usr/bin/env python3
import os
import sys
import json
import time
import subprocess
import argparse
import urllib.request
import shutil
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
    from rich.syntax import Syntax
except ImportError:
    print("Error: The 'rich' library is required to run the terminal dashboard.")
    print("Please install it by running: pip install rich")
    sys.exit(1)

STATE_DIR = os.path.join(os.getcwd(), ".proximity_swarm")
AGENTS_DIR = os.path.join(STATE_DIR, "agents")
COLLISIONS_DIR = os.path.join(STATE_DIR, "collisions")
TOMBSTONES_FILE = os.path.join(STATE_DIR, "tombstones.json")
LOG_FILE = os.path.join(STATE_DIR, "monitor.log")
MOCK_TASKS_FILE = os.path.join(os.getcwd(), "mock_tasks.json")
OLLAMA_MODEL = "gemma4:latest"

predefined_personalities = []

console = Console()


def load_json(filepath):
    if not os.path.exists(filepath):
        return None
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception:
        return None


def purge_artifacts(target=None):
    """Wipes the selected/all .proximity_swarm state artifacts and optionally dynamic tasks."""
    if target is None or target.strip().lower() == "all":
        if os.path.exists(STATE_DIR):
            try:
                shutil.rmtree(STATE_DIR)
                os.makedirs(STATE_DIR, exist_ok=True)
            except Exception as e:
                print(f"[-] Error wiping state directory: {e}")
                
        # Reset tombstones.json
        try:
            os.makedirs(os.path.dirname(TOMBSTONES_FILE), exist_ok=True)
            with open(TOMBSTONES_FILE, 'w') as f:
                json.dump([], f, indent=2)
        except Exception as e:
            print(f"[-] Error resetting tombstones: {e}")

        # Purge dynamic tasks from mock_tasks.json to keep it clean
        if os.path.exists(MOCK_TASKS_FILE):
            try:
                with open(MOCK_TASKS_FILE, 'r') as f:
                    data = json.load(f)
                if "tasks" in data:
                    original_tasks = {k: v for k, v in data["tasks"].items() if not k.startswith("task_dynamic_")}
                    data["tasks"] = original_tasks
                with open(MOCK_TASKS_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
            except Exception as e:
                print(f"[-] Error filtering mock_tasks.json: {e}")
        return

    # Specific targets
    t_lower = target.strip().lower()
    if t_lower == "logs":
        if os.path.exists(LOG_FILE):
            try:
                os.remove(LOG_FILE)
                print(f"[+] Deleted log file: {LOG_FILE}")
            except Exception as e:
                print(f"[-] Error deleting log file: {e}")
        else:
            print("[-] No log file found to delete.")
            
    elif t_lower == "workspaces":
        workspaces_dir = os.path.join(STATE_DIR, "workspaces")
        if os.path.exists(workspaces_dir):
            try:
                shutil.rmtree(workspaces_dir)
                os.makedirs(workspaces_dir, exist_ok=True)
                print(f"[+] Cleared workspaces directory: {workspaces_dir}")
            except Exception as e:
                print(f"[-] Error clearing workspaces directory: {e}")
        else:
            print("[-] No workspaces directory found to clear.")
            
    elif t_lower == "collisions":
        if os.path.exists(COLLISIONS_DIR):
            try:
                shutil.rmtree(COLLISIONS_DIR)
                os.makedirs(COLLISIONS_DIR, exist_ok=True)
                print(f"[+] Cleared collisions directory: {COLLISIONS_DIR}")
            except Exception as e:
                print(f"[-] Error clearing collisions directory: {e}")
        else:
            print("[-] No collisions directory found to clear.")
            
    elif t_lower == "tombstones":
        try:
            os.makedirs(os.path.dirname(TOMBSTONES_FILE), exist_ok=True)
            with open(TOMBSTONES_FILE, 'w') as f:
                json.dump([], f, indent=2)
            print(f"[+] Reset tombstones database: {TOMBSTONES_FILE}")
        except Exception as e:
            print(f"[-] Error resetting tombstones: {e}")
            
    elif t_lower == "tasks":
        if os.path.exists(MOCK_TASKS_FILE):
            try:
                with open(MOCK_TASKS_FILE, 'r') as f:
                    data = json.load(f)
                if "tasks" in data:
                    original_tasks = {k: v for k, v in data["tasks"].items() if not k.startswith("task_dynamic_")}
                    data["tasks"] = original_tasks
                with open(MOCK_TASKS_FILE, 'w') as f:
                    json.dump(data, f, indent=2)
                print(f"[+] Purged dynamic tasks from mock tasks database.")
            except Exception as e:
                print(f"[-] Error filtering mock_tasks.json: {e}")
        else:
            print("[-] No mock tasks file found to update.")
            
    else:
        # Check recursive file matches under workspaces directory
        workspaces_dir = os.path.join(STATE_DIR, "workspaces")
        if not os.path.exists(workspaces_dir):
            print("[-] No workspaces directory found.")
            return
            
        normalized_target = target.replace('/', os.sep).replace('\\', os.sep)
        deleted_files = []
        for root, dirs, files in os.walk(workspaces_dir):
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, workspaces_dir)
                
                # Check for matches (relative path, basename, or sub-path)
                if (rel_path == normalized_target or 
                    file == normalized_target or 
                    rel_path.endswith(os.sep + normalized_target)):
                    try:
                        os.remove(file_path)
                        deleted_files.append(rel_path)
                    except Exception as e:
                        print(f"[-] Error deleting file {rel_path}: {e}")
                        
        if deleted_files:
            for df in deleted_files:
                print(f"[+] Deleted file: {df}")
        else:
            print(f"[-] No file matching '{target}' was found in workspaces.")


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
    
    has_agents = False
    if os.path.exists(AGENTS_DIR):
        filenames = sorted(os.listdir(AGENTS_DIR))
        for filename in filenames:
            if filename.endswith(".json"):
                data = load_json(os.path.join(AGENTS_DIR, filename))
                if not data:
                    continue
                has_agents = True
                    
                status = data.get("status", "exploring")
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
                    
                prog = data.get("progress", 0)
                filled = int(prog / 10)
                bar = "█" * filled + "░" * (10 - filled)
                progress_styled = f"{bar} {prog}%"
                
                files = ", ".join(data.get("touched_files", []))
                if len(files) > 30:
                    files = files[:27] + "..."
                
                goal_prefix = f"[{data.get('personality', 'Generalist')}] "
                full_goal = goal_prefix + data.get("goal", "")
                if len(full_goal) > 60:
                    full_goal = full_goal[:57] + "..."
                    
                table.add_row(
                    data.get("id"),
                    str(data.get("parent_id") or "None"),
                    status_styled,
                    full_goal,
                    progress_styled,
                    files
                )
                
    if not has_agents and predefined_personalities:
        # Render the custom predefined roles configuration UI!
        config_table = Table(title="Custom Swarm Configuration (Pending Query)", expand=True)
        config_table.add_column("Agent #", justify="center", style="bold white", width=10)
        config_table.add_column("Role / Personality", justify="left", style="cyan", width=25)
        config_table.add_column("Dedicated Goal / Focus Area", justify="left", style="white")
        config_table.add_column("Status", justify="center", style="green", width=20)
        
        for idx, entry in enumerate(predefined_personalities):
            config_table.add_row(
                f"Agent {idx+1:03d}",
                entry.get("role", "Generalist"),
                entry.get("goal") or "Inherits overall task goal",
                "Ready to Initialize"
            )
        return Panel(config_table, border_style="yellow")

    return Panel(table, border_style="green")


def make_output_panel():
    """Renders the contents of the generated workspace files."""
    workspaces_dir = os.path.join(STATE_DIR, "workspaces")
    if not os.path.exists(workspaces_dir):
        return Panel(
            Align.center(Text("Waiting for agent output...", style="dim yellow")),
            title="Swarm Output / Answer Viewer",
            border_style="cyan"
        )
        
    found_files = []
    for root, dirs, files in os.walk(workspaces_dir):
        for file in files:
            if file.endswith((".pyc", ".pyo")) or "__pycache__" in root:
                continue
            path = os.path.join(root, file)
            found_files.append((path, os.path.getmtime(path)))
            
    if not found_files:
        return Panel(
            Align.center(Text("No files generated yet...", style="dim yellow")),
            title="Swarm Output / Answer Viewer",
            border_style="cyan"
        )
        
    # Sort files by modification time (most recent first)
    found_files.sort(key=lambda x: x[1], reverse=True)
    latest_file_path = found_files[0][0]
    
    # Read the file contents
    try:
        with open(latest_file_path, 'r') as f:
            content = f.read()
    except Exception as e:
        content = f"Error reading file: {e}"
        
    filename = os.path.basename(latest_file_path)
    rel_path = os.path.relpath(latest_file_path, workspaces_dir)
    
    # Truncate content to avoid terminal overflow
    lines = content.splitlines()
    if len(lines) > 40:
        content_displayed = "\n".join(lines[:40]) + "\n\n... [Truncated due to length] ..."
    else:
        content_displayed = content
        
    if filename.endswith(".py"):
        display_element = Syntax(content_displayed, "python", theme="monokai", line_numbers=True)
    elif filename.endswith(".md"):
        display_element = Syntax(content_displayed, "markdown", theme="monokai")
    else:
        display_element = Text(content_displayed, style="green")
        
    return Panel(
        display_element,
        title=f"Swarm Output / Answer Viewer (File: {rel_path})",
        border_style="cyan"
    )


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
    table = Table(title="Tombstones Blocker Database", expand=True)
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


# Ollama Connection Helper
def is_ollama_running():
    try:
        with urllib.request.urlopen("http://localhost:11434/api/tags", timeout=1.5) as response:
            return response.status == 200
    except Exception:
        return False


# Call Ollama API
def call_ollama(prompt):
    url = "http://localhost:11434/api/generate"
    headers = {"Content-Type": "application/json"}
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
        with urllib.request.urlopen(req, timeout=45) as response:
            res_data = json.loads(response.read().decode("utf-8"))
            return res_data.get("response", "").strip()
    except Exception as e:
        return None


# Clean LLM response to get pure JSON
def extract_json(text):
    content = text.strip()
    if content.startswith("```json"):
        content = content[7:]
    elif content.startswith("```"):
        content = content[3:]
    if content.endswith("```"):
        content = content[:-3]
    return content.strip()


# Generate steps dynamically using Ollama
def generate_task_steps(query):
    prompt = (
        f"You are the Swarm Planner. Decompose the following agentic task into a series of 3 to 4 sequential, concrete steps:\n"
        f"Task: '{query}'\n\n"
        f"For each step, provide:\n"
        f"- 'step_id': integer sequential ID\n"
        f"- 'name': short step name\n"
        f"- 'description': detailed description of what should be accomplished\n"
        f"- 'touched_files': list of relative file paths that will be edited or created. IMPORTANT: You MUST specify at least one target output file (e.g., 'src/answer.md' or 'output.md') in the final step so the agents write their findings, answers, or code results to disk for TUI rendering.\n"
        f"- 'tools': list of tools that will be used (e.g. ['edit_file', 'pytest', 'run_python', 'gcc', 'make'])\n\n"
        f"You MUST respond with a valid JSON object only. Do not include markdown formatting or explanations outside the JSON. "
        f"Example output structure:\n"
        f"{{\n"
        f"  \"steps\": [\n"
        f"    {{\n"
        f"      \"step_id\": 1,\n"
        f"      \"name\": \"Write quicksort\",\n"
        f"      \"description\": \"Write sorting implementation in src/quicksort.py\",\n"
        f"      \"touched_files\": [\"src/quicksort.py\"],\n"
        f"      \"tools\": [\"edit_file\"]\n"
        f"    }}\n"
        f"  ]\n"
        f"}}\n"
    )
    
    response_text = call_ollama(prompt)
    if not response_text:
        return None
        
    try:
        cleaned_json = extract_json(response_text)
        data = json.loads(cleaned_json)
        if "steps" in data:
            return data["steps"]
    except Exception:
        pass
        
    return None


def recommend_starting_agents(query):
    """Query Ollama to recommend optimal starting agent roles and goals for the query."""
    prompt = (
        f"You are the Swarm Architect. Analyze the following task request:\n"
        f"Task: '{query}'\n\n"
        f"Recommend the optimal number of starting agents (minimum 1, maximum 3) to execute this task.\n"
        f"For each agent, provide:\n"
        f"- 'role': A concise role or personality (e.g. 'Software Engineer', 'Pytest QA Specialist', 'Documentation Lead')\n"
        f"- 'goal': A specific, dedicated goal/focus area for this agent (e.g. 'Write core JWT signing library in python', 'Write integration tests to validate token algorithms')\n\n"
        f"You MUST respond with a valid JSON object only. Do not include markdown code fences or explanations outside the JSON.\n"
        f"Example output structure:\n"
        f"{{\n"
        f"  \"recommendations\": [\n"
        f"    {{\n"
        f"      \"role\": \"Software Engineer\",\n"
        f"      \"goal\": \"Write core JWT library\"\n"
        f"    }}\n"
        f"  ]\n"
        f"}}\n"
    )
    
    response_text = call_ollama(prompt)
    if not response_text:
        return []
        
    try:
        cleaned_json = extract_json(response_text)
        data = json.loads(cleaned_json)
        if "recommendations" in data:
            return data["recommendations"]
    except Exception:
        pass
        
    return []


def register_dynamic_task(task_id, goal, steps):
    if not os.path.exists(MOCK_TASKS_FILE):
        tasks_data = {"tasks": {}}
    else:
        try:
            with open(MOCK_TASKS_FILE, 'r') as f:
                tasks_data = json.load(f)
        except Exception:
            tasks_data = {"tasks": {}}
            
    tasks_data["tasks"][task_id] = {
        "id": task_id,
        "goal": goal,
        "steps": steps
    }
    
    with open(MOCK_TASKS_FILE, 'w') as f:
        json.dump(tasks_data, f, indent=2)


def execute_dashboard_run(layout, supervisor_cmd):
    # Launch supervisor subprocess
    sup_proc = subprocess.Popen(supervisor_cmd)
    
    # Live loop updating layout components
    try:
        with Live(layout, refresh_per_second=5, screen=True) as live:
            while sup_proc.poll() is None:
                layout["header"].update(make_header_panel())
                layout["left"].update(make_agents_table())
                layout["center"].update(make_output_panel())
                layout["right_top"].update(make_collisions_panel())
                layout["right_bottom"].update(make_tombstones_panel())
                layout["footer"].update(make_logs_panel())
                time.sleep(0.2)
                
            layout["header"].update(make_header_panel())
            layout["left"].update(make_agents_table())
            layout["center"].update(make_output_panel())
            layout["right_top"].update(make_collisions_panel())
            layout["right_bottom"].update(make_tombstones_panel())
            layout["footer"].update(make_logs_panel())
            
    except KeyboardInterrupt:
        pass
    finally:
        sup_proc.terminate()
        sup_proc.wait()


def main():
    parser = argparse.ArgumentParser(description="Proximity Swarm V2 - Terminal Monitor Dashboard")
    parser.add_argument("--run-redundant", action="store_true", help="Launch the identical goal collision demo")
    parser.add_argument("--task-id", help="Launch a custom task ID and monitor it")
    parser.add_argument("--deconflict", action="store_true", help="Enable goal deconfliction file parameter offsets")
    parser.add_argument("--interactive", action="store_true", help="Enable terminal prompts to manually negotiate collisions")
    parser.add_argument("--step-delay", type=float, default=2.0, help="Agent runner step delay in seconds")
    parser.add_argument("--llm-provider", choices=["gemini", "ollama", "rules"], help="LLM API provider for deconfliction negotiation")
    parser.add_argument("--ollama-model", default="gemma4:latest", help="Ollama model string to query if provider is ollama")
    args = parser.parse_args()
    
    # Build 3-column layout
    layout = Layout()
    layout.split(
        Layout(name="header", size=3),
        Layout(name="body"),
        Layout(name="footer", size=10)
    )
    layout["body"].split_row(
        Layout(name="left", ratio=5),
        Layout(name="center", ratio=6),
        Layout(name="right", ratio=5)
    )
    layout["right"].split(
        Layout(name="right_top", ratio=1),
        Layout(name="right_bottom", ratio=1)
    )
    
    # Check if we should execute a single direct run (redundant demo or specific task)
    if args.run_redundant or args.task_id:
        supervisor_cmd = [
            sys.executable, "supervisor.py"
        ]
        if args.run_redundant:
            supervisor_cmd.append("--run-redundant")
        elif args.task_id:
            supervisor_cmd.extend(["--task-id", args.task_id])

        if args.deconflict:
            supervisor_cmd.append("--deconflict")
        if args.interactive:
            supervisor_cmd.append("--interactive")
        if args.llm_provider:
            supervisor_cmd.extend(["--llm-provider", args.llm_provider])
        if args.ollama_model:
            supervisor_cmd.extend(["--ollama-model", args.ollama_model])
        if args.step_delay:
            supervisor_cmd.extend(["--step-delay", str(args.step_delay)])
            
        print(f"[Dashboard] Initializing simulation: {' '.join(supervisor_cmd)}...")
        time.sleep(1.0)
        execute_dashboard_run(layout, supervisor_cmd)
        
        console.clear()
        print("\n" + "="*50)
        print("    Terminal Dashboard Session Terminated")
        print("="*50 + "\n")
        sys.exit(0)
        
    # Persistent Interactive TUI Dashboard Mode
    while True:
        try:
            # 1. Redraw/render current state statically to terminal screen
            os.system("clear")
            layout["header"].update(make_header_panel())
            layout["left"].update(make_agents_table())
            layout["center"].update(make_output_panel())
            layout["right_top"].update(make_collisions_panel())
            layout["right_bottom"].update(make_tombstones_panel())
            layout["footer"].update(make_logs_panel())
            console.print(layout)
            
            # 2. Get prompt input at the bottom of the dashboard screen
            prompt_str = "\n\033[1;36mSwarm Command (Type '/exit' to quit) > \033[0m"
            user_input = input(prompt_str).strip()
            if not user_input:
                continue
                
            parts = user_input.strip().split(maxsplit=1)
            cmd = parts[0].lower() if parts else ""
            arg = parts[1] if len(parts) > 1 else None
            
            if cmd in ["/exit", "/quit", "exit", "quit"]:
                os.system("clear")
                print("\n" + "="*50)
                print("    Terminal Dashboard Session Terminated")
                print("="*50 + "\n")
                break
                
            if cmd in ["/clean", "/purge", "/delete-artifacts"]:
                purge_artifacts(arg)
                time.sleep(1.5)
                continue
                
            if cmd in ["/add-agent", "/add-personality"]:
                if not arg:
                    print("\n\033[1;31m[-] Error: Usage: /add-agent <role> : <goal> (goal is optional)\033[0m")
                    time.sleep(2.0)
                    continue
                
                if ":" in arg:
                    r_part, g_part = arg.split(":", 1)
                    role = r_part.strip()
                    goal = g_part.strip()
                else:
                    role = arg.strip()
                    goal = None
                
                if role:
                    predefined_personalities.append({"role": role, "goal": goal})
                    print(f"\n\033[1;32m[+] Registered agent: '{role}'\033[0m")
                    if goal:
                        print(f"    Dedicated Goal: '{goal}'")
                else:
                    print("\n\033[1;31m[-] Error: Role name cannot be empty.\033[0m")
                time.sleep(1.5)
                continue

            if cmd == "/help":
                print("\n\033[1;33mAvailable Dashboard CLI Commands:\033[0m")
                print("  /help                     - Show this help dialogue")
                print("  /add-agent <role> : <goal> - Predefine custom agent role and dedicated goal")
                print("                              (e.g., '/add-agent Tester : Write tests')")
                print("  /clean [target]           - Clean specific storage/files rather than everything.")
                print("                              Supported targets: 'logs', 'workspaces', 'collisions',")
                print("                              'tombstones', 'tasks', 'all', or a specific filename")
                print("  /delete-artifacts         - Synonym for /clean")
                print("  /exit                     - Exit the TUI Dashboard\n")
                print("Press Enter to return to dashboard...")
                input()
                continue

            # Check if personalities should be recommended
            if not predefined_personalities:
                recs = recommend_starting_agents(user_input)
                if recs:
                    print("\n\033[1;33m[Swarm Recommendation Engine]\033[0m")
                    print(f"No custom agents defined. Based on your task: '{user_input}', I recommend starting with {len(recs)} agents:")
                    for i, r in enumerate(recs):
                        print(f"  {i+1}. Role: {r.get('role')} | Goal: {r.get('goal')}")
                    print("\nInitialize the swarm with these recommended agents? (Y/n) > ", end="")
                    ans = input().strip().lower()
                    if not ans or ans in ["y", "yes"]:
                        predefined_personalities.extend(recs)
                        print("\033[1;32m[+] Initialized swarm with recommended agents.\033[0m")
                        time.sleep(1.5)
                    else:
                        print("[*] Initializing default single-agent swarm.")
                        time.sleep(1.0)
                        
            # Decompose goals and register tasks
            agents_config = []
            now_ts = int(time.time())
            
            if predefined_personalities:
                for idx, entry in enumerate(predefined_personalities):
                    agent_role = entry.get("role", "Generalist")
                    agent_goal = entry.get("goal") or user_input
                    agent_id = f"{idx+1:03d}"
                    
                    print(f"\n[*] Decomposing goal for Agent {agent_id} ({agent_role})...")
                    steps = generate_task_steps(agent_goal)
                    if not steps:
                        steps = [
                            {
                                "step_id": 1,
                                "name": "General Execution",
                                "description": f"Perform tasks for: {agent_goal}",
                                "touched_files": [f"src/agent_{agent_id}_output.md"],
                                "tools": ["edit_file"]
                            }
                        ]
                    
                    task_id = f"task_dynamic_{now_ts}_{idx}"
                    register_dynamic_task(task_id, agent_goal, steps)
                    
                    agents_config.append({
                        "agent_id": agent_id,
                        "task_id": task_id,
                        "personality": agent_role,
                        "goal": agent_goal
                    })
            else:
                agent_goal = user_input
                print("\n[*] Decomposing task using Ollama...")
                steps = generate_task_steps(agent_goal)
                if not steps:
                    steps = [
                        {
                            "step_id": 1,
                            "name": "General Execution",
                            "description": f"Perform research and coordinate: {agent_goal}",
                            "touched_files": ["src/dynamic_task_output.md"],
                            "tools": ["edit_file"]
                        }
                    ]
                task_id = f"task_dynamic_{now_ts}_0"
                register_dynamic_task(task_id, agent_goal, steps)
                agents_config.append({
                    "agent_id": "001",
                    "task_id": task_id,
                    "personality": "Generalist",
                    "goal": agent_goal
                })
                
            # Clear predefined personalities for next run
            predefined_personalities.clear()
            
            # Launch dynamic execution loop in dashboard
            supervisor_cmd = [
                sys.executable, "supervisor.py",
                "--agents-config", json.dumps(agents_config),
                "--llm-provider", "ollama",
                "--step-delay", "1.5"
            ]
            
            print("[*] Starting swarm. Initializing visualization...")
            time.sleep(1.0)
            
            execute_dashboard_run(layout, supervisor_cmd)
            
        except (KeyboardInterrupt, EOFError):
            os.system("clear")
            print("\n" + "="*50)
            print("    Terminal Dashboard Session Terminated")
            print("="*50 + "\n")
            break


if __name__ == "__main__":
    main()
