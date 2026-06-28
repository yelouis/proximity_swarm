# Proximity Swarm

Proximity Swarm is a **research harness** that takes *any* small, open-source LLM and amplifies its ability to carry a long chain of logic — proofs, deep research, multi-step engineering — by running it not as one model but as a coordinated **team** of single-step agents. Each agent works one atomic **logic step** at a time, and the swarm separates the hard, creative job of *proposing* a step from the cheap, reliable job of *validating* it. Agents sense each other in idea- and resource-space (**proximity**) so they dedupe overlapping work and deliberately diverge onto different approaches, like a research team. The combined, validated steps assemble into a shared **logic graph** — the answer, and a legible map of every idea that was explored.

For the concept, architecture, and the propose/validate thesis, see the [Technical Design Document](designs/design_doc.md). The harness is headless and scriptable; the optional observability dashboard is specified in [designs/harness_design_document.md](designs/harness_design_document.md).

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
- **Novelty Spawning Gating:** Every 5 steps, agents evaluate semantic isolation (TF-IDF similarity < 0.35) and historical run novelty (SQLite query similarity < 0.50) to trigger specialized child helper spawns.
- **Active Swarm Budget & Leaf Pruning:** Limits concurrent active agents (default `--budget 4`). If exceeded, the TUI displays LLM-ranked (or heuristic-sorted fallback) leaf agents for manual pruning.
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
    *   `/budget <cap>` - Dynamically adjust the active swarm budget cap (transient).
    *   `/prune <agent_id>` - Terminate an active leaf agent (safety restricted) and register a pruned tombstone blocker explanation.
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

## 🌀 Ralph Wiggum Loop Integration (Concept)

The system supports architectural patterns inspired by the **Ralph Wiggum Loop** ("persistence over perfection") to enable resilient local agent execution:

* **Self-Healing Retries**: Agents wrapped in an inner evaluation loop. If a step's verification tool (e.g. `pytest`, `gcc`) fails, the runner queries the LLM again with the compiler traceback to self-correct the code.
* **Context Resetting**: Wipes conversational memory on retry iterations, presenting the LLM only with the target code and compiler error to prevent context dilution/confusion.
* **Test-Driven Progress**: Ties agent progress bar increments strictly to passing compilation/verification tests.

---

## Roadmap

1. **Phase 1: Local Simulation & Mock Agents:** Simulate agent collisions, negotiations, and status transitions in a local database sandbox.
2. **Phase 2: Live Shell Agents:** Wrap agents with file/terminal tools and add tombstone lessons persistence.
3. **Phase 3: Web Visualization Dashboard:** Build a dynamic visual grid/network visualization of agents interacting in trajectory space.
4. **Phase 4: Ralph Wiggum Loop Integration:** Implement the self-healing retry loop, context resetting, and test-driven progress gates across the swarm.


