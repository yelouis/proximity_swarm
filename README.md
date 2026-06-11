# Proximity Swarm

Proximity Swarm is an agentic framework designed to coordinate a swarm of autonomous agents working on complex tasks. It applies cellular-automata-style rules (inspired by Conway's Game of Life) and semantic spatial proximity to manage resource consumption, accelerate task execution, and share learnings dynamically.

For a detailed breakdown of the concept, architecture, and implementation details, please see the [Technical Design Document](design_doc.md).

## The Analogy: Git for LLM Trajectories

In addition to Conway's Game of Life dynamics, Proximity Swarm acts as a **Git-like Version Control System for Agent Reasoning Trees**:
*   **Branching (Spawning / Underpopulation):** When an agent needs help or has parallel paths, it forks a new branch (spawns a child agent) to explore a sub-task in an isolated workspace.
*   **Merge Conflicts (Collisions / Overpopulation):** When two agents drift too close in goal and file space, it triggers a merge conflict. The agents hold a negotiation dialogue to resolve the conflict (exchanging knowledge, or deleting/terminating the redundant branch).
*   **Tombstones (Bug tags / Reverts):** When an agent hits a dead-end (compiler error, dependency bug), it commits a "Tombstone" record to the shared repository. Other agents check this index before running tools to steer their trajectories away from the failure.

## Core Concepts

- **Trajectory Space:** The shared grid/space where agents register their paths, goals, and thoughts.
- **Proximity Engine:** Checks if agents are working on semantically or structurally overlapping tasks.
- **Game-of-Life Rules:**
  - **Overpopulation (Redundancy):** Slower duplicate agents self-terminate.
  - **Underpopulation (Isolation):** Isolated agents spawn sub-agents to explore parallel paths.
  - **Symbiosis (Converse & Learn):** Proximate agents share findings to accelerate tasks or warn of dead-ends.

- **Episodic Memory (Institutional Learning):** Completed or failed agent runs are stored as episodes in a local SQLite database (`.proximity_swarm/memory.db`). Active agents query these episodes semantically at startup to preload past files and avoid repeating errors.

## Getting Started & How to Run

### 📋 Prerequisites
1. **Python 3.10+**
2. **Rich Library**: Install standard terminal visualization components:
   ```bash
   pip install rich
   ```
3. **Ollama**: Install [Ollama](https://ollama.com/) locally and make sure it is running. Pull the default LLM and embedding models:
   ```bash
   ollama pull gemma4:latest
   ollama pull nomic-embed-text
   ```

### 🚀 Running the System

You can run the framework in three different modes:

#### 1. Interactive TUI REPL Dashboard (Recommended)
This launches a persistent, 3-column glowing terminal dashboard that keeps you in the interface to continuously decompose tasks and track swarm outcomes:
```bash
python3 terminal_dashboard.py
```
*Alternatively, you can use the piped CLI forwarder wrapper:*
```bash
python3 cli.py
```
*   **In-TUI Commands**:
    *   `/help` - Show all dashboard CLI commands and targets.
    *   `/memory` - Display past recorded run episodes, including goal, role, status, and agent self-reflections.
    *   `/clean [target]` - Granularly purge storage artifacts (e.g., `/clean logs`, `/clean workspaces`, `/clean tombstones`, `/clean memory`, or specific filenames like `/clean quicksort.py`).
    *   `/exit` - Exit the dashboard.

#### 2. Run the Redundant Goal Collision Demo
Launch the preconfigured simulation demonstrating goal collisions, TF-IDF semantic overlaps, and active deconfliction/negotiation:
```bash
python3 terminal_dashboard.py --run-redundant --llm-provider ollama
```

#### 3. Run the Research Swarm Coordinator
Execute the multi-agent framework research compiler to query Ollama and produce a comparative synthesis report:
```bash
python3 run_swarm_research.py
```

---

## 🧪 Running Unit Tests

To run the complete automated test suite (including proximity math, agent spawning, cascading kills, consensus gates, and selective clean command targets):
```bash
python3 -m unittest discover -s tests
```

---

## Roadmap

1. **Phase 1: Local Simulation & Mock Agents:** Simulate agent collisions, negotiations, and status transitions in a local database sandbox.
2. **Phase 2: Live Shell Agents:** Wrap agents with file/terminal tools and add tombstone lessons persistence.
3. **Phase 3: Web Visualization Dashboard:** Build a dynamic visual grid/network visualization of agents interacting in trajectory space.

