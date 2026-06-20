# Proximity Swarm V3 — Resolved & Closed Bugs

This document tracks the problems encountered during the execution and validation of **Journey 1: Cartographer of a Hard Conjecture**, along with their resolutions.

---

## 1. [RESOLVED] Spawn Request Auto-Approval / Interactive Mode Desync
* **Category:** Swarm Coordination & UI Flow
* **Status:** FIXED
* **Resolution:** Plumbed a dedicated `--auto-approve-spawns` CLI flag (via `web_dashboard.py` -> `supervisor.py` -> `proximity_monitor.py`). In the web UI launch modal, a checkbox allows turning this on or off (defaults to off, requiring manual approval). When off, spawns pause in a pending state, showing as timeline decision cards and highlighted with a blue attention ring on the canvas.

---

## 2. [RESOLVED] Sequential Blocking LLM Calls during Swarm Launch
* **Category:** Performance / UX
* **Status:** FIXED
* **Resolution:** Re-architected `launch_swarm` in `web_dashboard.py` to run goal decomposition and supervisor process invocation asynchronously on a daemon thread. The server returns a success response instantly, updating the UI status pill to `RUNNING` immediately. Added a frontend guard in `app.js` to prevent the Init overlay from showing up while the daemon thread initializes the agents.

---

## 3. [RESOLVED] Pending Spawn Requests Orphaned by Completed Agents
* **Category:** Monitor Logic / UI State Desync
* **Status:** FIXED
* **Resolution:** Implemented parent-child join semantics. A parent agent now enters an `awaiting_child` state instead of immediately completing if it has unresolved child spawns. While in this state, it remains tracked as active by `proximity_monitor.py` and periodically checks in on the children, ingests their results when they finish, or makes a timed/capping decision to proceed. Once the child is resolved, the parent ingests its outputs and transitions to `completed`.

---

## 4. [RESOLVED] Inconsistent Dialog Behavior: Command Bar vs. UI Clean Actions
* **Category:** UX Consistency
* **Status:** FIXED
* **Resolution:** Added a confirmation dialog to `/clean all` in the command bar in `app.js`, ensuring consistency with the gear menu dropdown.

---

## 5. [RESOLVED] Lack of Deselect / Clear Agent Selection Gesture
* **Category:** UI / Navigation
* **Status:** FIXED
* **Resolution:** Implemented three deselect gestures in `app.js`: clicking the empty canvas area, pressing the `Escape` key, or clicking the explicit "✕ Show all agents" button next to the stage toggle. This clears the selected agent focus and returns the view to the unscoped global timeline feed.

