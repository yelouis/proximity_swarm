# Proximity Swarm V3 — Ongoing Bugs & Issues

This document labels and describes the problems encountered during the execution and validation of **Journey 1: Cartographer of a Hard Conjecture**.

---

## 1. Spawn Request Auto-Approval / Interactive Mode Desync
* **Category:** Swarm Coordination & UI Flow
* **Description:** Spawn requests are automatically approved and executed by the backend supervisor/monitor without waiting for operator input from the web dashboard.
* **Expected Behavior:** When an agent decides to spawn a child, the request should remain in a `pending` status, surfacing as a decision card in the Timeline/Activity drawer and putting a blue ring around the agent node on the map. The swarm should wait for the user to approve or reject the request.
* **Actual Behavior:** The monitor automatically and instantly spawns the child agent (e.g. Agent 005 was spawned by Agent 002 automatically).
* **Root Cause:** 
  - `web_dashboard.py` launches `supervisor.py` without the `--interactive` flag.
  - In `supervisor.py`, this sets `interactive = False` and omits passing `--interactive` to `proximity_monitor.py`.
  - In `proximity_monitor.py`, `INTERACTIVE` is a global boolean defaulting to `False`. When `False`, the `handle_spawn_requests()` function bypasses the pending check and immediately invokes the spawn logic.
  - `web_dashboard.py` lacks a command-line interface argument or config option to run the supervisor monitor in interactive mode.

---

## 2. Sequential Blocking LLM Calls during Swarm Launch
* **Category:** Performance / UX
* **Description:** Launching a swarm task blocks the HTTP server thread for an extended period, keeping the UI stuck in `IDLE` state for over 30 seconds before any visual feedback or agent cards appear.
* **Expected Behavior:** Clicking **🐝 Launch Swarm Task** should immediately close the overlay, transition the UI status to `RUNNING` (or a loading/initializing state), and register the agents in the sidebar. Goal decomposition should run asynchronously in the background.
* **Actual Behavior:** The POST request to `/api/run` blocks for 34 seconds while Ollama processes goal decompositions sequentially. The status pill remains `IDLE` because the frontend has not received the POST response yet, and no agents are loaded.
* **Root Cause:**
  - In `web_dashboard.py`'s `/api/run` POST handler, the server calls `launch_swarm(goal, agents, budget)`.
  - `launch_swarm()` iterates through all configured agents and calls `generate_task_steps_via_llm(agent_goal)` sequentially *before* spawning the supervisor process and returning the HTTP response.
  - Doing multiple sequential LLM calls synchronously inside an HTTP request handler blocks the client and creates a poor UX.

---

## 3. Pending Spawn Requests Orphaned by Completed Agents
* **Category:** Monitor Logic / UI State Desync
* **Description:** If an agent submits a spawn request and immediately completes its execution step, its spawn request remains in `"pending"` state forever. This leaves a permanent `🔔 decisions` warning in the status bar that cannot be cleared.
* **Expected Behavior:** A completed agent should either have its pending spawn requests cleaned up/cancelled, or the supervisor monitor should still process and resolve them.
* **Actual Behavior:** The pending spawn request stays in the state forever.
* **Root Cause:**
  - In `agent_runner.py`, `evaluate_isolation_spawn()` is called at the beginning of `execute_step()`. It registers a pending spawn request.
  - Later in `execute_step()`, the agent completes all step tasks (since it is a 1-step dynamic task) and sets its status to `"completed"`.
  - In `proximity_monitor.py`, `load_active_agents()` only selects agents whose status is `["exploring", "syncing", "pending_termination"]`.
  - Because the completed agent's status is `"completed"`, it is omitted from the active agents list. Therefore, `handle_spawn_requests()` never runs on it, leaving the spawn request stuck as `"pending"`.

---

## 4. Inconsistent Dialog Behavior: Command Bar vs. UI Clean Actions
* **Category:** UX Consistency
* **Description:** The slash command `/clean all` in the bottom command bar performs a destructive action immediately, while the gear dropdown dropdown item `🔥 Clean Everything` triggers a confirmation dialog.
* **Expected Behavior:** Destructive actions like cleaning all workspaces, logs, and database files should consistently ask for operator confirmation, regardless of the input method.
* **Actual Behavior:** `/clean all` runs instantly without a confirmation prompt, whereas clicking the button requires confirming.
* **Root Cause:**
  - In `app.js`'s click handler for `data-action="clean"`, it explicitly checks `if (target.dataset.target === 'all') { if (!confirm(...)) return; }`.
  - However, in the command bar keydown listener for `/clean`, it immediately calls `apiPost('/api/clean', { target })` without any dialog check.

---

## 5. Lack of Deselect / Clear Agent Selection Gesture
* **Category:** UI / Navigation
* **Description:** There is no way to deselect a selected agent to return to the global interleaved timeline view without reloading the entire page.
* **Expected Behavior:** Clicking outside agent nodes on the map canvas, clicking a "Deselect" button, or pressing `Esc` should reset `UIState.selectedAgentId` to `null` to view the unscoped global timeline.
* **Actual Behavior:** Once an agent node is clicked, `selectedAgentId` is locked to that agent or other clicked agents. The page must be reloaded to view the global timeline again.
