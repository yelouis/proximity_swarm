# Proximity Swarm

Proximity Swarm is an agentic framework designed to coordinate a swarm of autonomous agents working on complex tasks. It applies cellular-automata-style rules (inspired by Conway's Game of Life) and semantic spatial proximity to manage resource consumption, accelerate task execution, and share learnings dynamically.

For a detailed breakdown of the concept, architecture, and roadmap, please see the [Brainstorming Document](brainstorming.md).

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
