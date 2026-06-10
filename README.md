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

## Roadmap

1. **Phase 1: Local Simulation & Mock Agents:** Simulate agent collisions, negotiations, and status transitions in a local database sandbox.
2. **Phase 2: Live Shell Agents:** Wrap agents with file/terminal tools and add tombstone lessons persistence.
3. **Phase 3: Web Visualization Dashboard:** Build a dynamic visual grid/network visualization of agents interacting in trajectory space.
