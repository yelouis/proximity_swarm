# Technical Design Document: Proximity Swarm (Logic Research Harness)

Proximity Swarm is a research harness that coordinates a swarm of simple, open-source LLMs to collaboratively solve complex multistep logic problems (e.g., mathematical proofs, deep research). It treats individual LLM agents as "logic processors" that work through a problem by processing and validating one logic step at a time. By applying cellular-automata-style rules and semantic spatial proximity, it ensures agents are aware of each other's logical exploration. If they drift into similar logic paths, they share information or merge to avoid redundant compute, while continuously exploring divergent ideas like a highly collaborative research team.

This document is the **backend / system spec** (orchestration, agents, coordination, learning, and the terminal interface). The **visual dashboard** has its own spec in [`harness_design_document.md`](harness_design_document.md), and the **step-by-step build plan** (gap analysis, phases, data model, file map) is in [`implementation_plan.md`](implementation_plan.md).

---

## 0. Core Thesis: Atomic Steps & the Propose/Validate Split

The bet is that you do not need a *stronger* model to carry a hard chain of logic — you need a better *process* around a weak one. A small, open-source model loses the thread over a long proof or a multi-file change, and its errors **compound**: one bad step poisons everything downstream. Three ideas turn a crowd of weak models into a team that doesn't:

1. **Decompose into atomic logic steps.** A weak model is unreliable over twenty steps but usually competent at *one*: "given these premises, derive this single conclusion." Sizing each agent's task to a single logic step keeps every call inside the model's competence, so the long-horizon weakness is never exercised.

2. **Separate *proposing* a step from *validating* it.** Coming up with the right next step is creative, high-variance, and error-prone (a huge search space). *Checking* whether a proposed step is sound is cheap and reliable — apply the inference rule, run the test, re-derive the value numerically, or ask a stronger **Judge** model to evaluate just that one step. So the swarm divides the labor: **Proposer** agents generate candidate steps; **Validator/Judge** agents verify them before they enter the trusted graph. A weak proposer behind a strict validator beats a lone weak model doing both, because invalid steps are caught *before* they corrupt the chain. This propose/validate asymmetry is the core amplification mechanism — and the reason collaboration matters: building the proof and checking the proof are different jobs.

3. **Coordinate like a team, not a crowd.** Running N copies of a model in parallel just re-derives the same things N times. **Proximity** (§5, §11) gives every agent peripheral awareness of what its peers are doing in idea-space and resource-space, so the swarm can *dedupe* (drift too close → stop, share, or merge) and *diverge* (work too isolated/novel → "hire" a subagent to open a new branch, §15). That is what makes it a research team exploring different approaches at once.

**The shared artifact — the logic graph.** Everything above grows one structure: a directed graph of atomic steps. Each node holds a `claim`, its `justification`, the prior nodes it `depends_on`, a `status` (`proposed → under_review → validated` **or** `refuted` → Gravestone), and the `approach`/branch it belongs to. Premises are the roots; the goal (QED, or a passing acceptance test) is the sink; a **solution** is a fully *validated* path from premises to goal; competing **approaches** are live branches the team explores in parallel.

**One mechanism, two personas.** Only the validation oracle changes. For a **researcher**, a node is a lemma and validation is checking the inference (rule application, symbolic/numeric re-derivation, or a stronger Judge). For a **coder**, a node is a code change and validation is running the test/type-check/build (the self-healing loop, §13). The coordination machinery is identical — that is why this is one harness, not two tools.

**What success means.** Solving the problem is the aspiration, not the bar. A successful run produces a **legible map of the idea space**: which approaches were tried, how they branched, where they collided, and which steps were validated vs. refuted. A well-mapped dead end (a Gravestone with a reason) is valuable output even when the conjecture still stands.

---

## Implementation status

Every feature below is implemented and has test coverage. The sections retain their original numbering; the groups are conceptual.

| # | Feature | Primary module(s) | Tests | Status |
|---|---|---|---|---|
| 1 | Architecture (supervisor / monitor / runner / TUI) | `supervisor.py`, `proximity_monitor.py`, `agent_runner.py`, `terminal_dashboard.py` | — | ✅ |
| 2 | Storage layout (`.proximity_swarm/`) | all modules | — | ✅ |
| 3 | Storage clean commands | `terminal_dashboard.py`, `web_dashboard.py` | `test_clean.py` | ✅ |
| 4 | Swarm designer + LLM recommendations | `terminal_dashboard.py`, `supervisor.py` | `test_personalities.py` | ✅ |
| 5 | Deconfliction, Negotiation & The Judge | `proximity_monitor.py`, `agent_runner.py` | `test_proximity.py`, `test_monitor.py` | ✅ |
| 6 | Verification plan & automated tests | `tests/` | — | ✅ |
| 7 | Hierarchical artifact synthesis | `terminal_dashboard.py` | `test_artifact_combination.py` | ✅ |
| 8 | TUI enhancements | `terminal_dashboard.py` | — | ✅ |
| 9 | Episodic memory | `memory_store.py` | `test_memory.py` | ✅ |
| 10 | Three-tier hierarchical scaling | `supervisor.py` | `test_hierarchical_scaling.py` | ✅ |
| 11 | Dynamic proximity weighting | `proximity_monitor.py` | `test_proximity_weighting.py` | ✅ |
| 12 | Causal graph tracing | `causal_tracer.py` | `test_causal_tracer.py` | ✅ |
| 13 | Self-healing verification loop (Logic Check) | `agent_runner.py` | `test_self_healing.py` | ✅ |
| 14 | Interactive budget & leaf pruning | `supervisor.py`, `proximity_monitor.py`, `terminal_dashboard.py` | `test_v2.py` | ✅ |
| 15 | Proximity & novelty-driven spawning | `agent_runner.py` | `test_collatz_research.py` | ✅ |

---

## 1. System Architecture & Components

The system uses a decoupled, file-based architecture where the logic graph and state are tracked on the local filesystem.

### A. Supervisor Orchestrator (`supervisor.py`)
Manages the process lifecycle of the swarm's logic tree:
- Initializes the background **Proximity Monitor** daemon.
- Provisions child agent processes sequentially or concurrently to explore logic branches.
- Implements process control policies such as **Cascading Kill Switches** (killing child subagents if a parent logic branch is terminated) and **Consensus-Gated Termination** (forcing at least one hypothesis branch to survive).

### B. Proximity Monitor (`proximity_monitor.py`)
Calculates spatial proximity between agents exploring the logic space:
- Computes distances using a weighted combination of:
  - **TF-IDF Goal/Logic Similarity**: Vectorizes the high-level logic steps being evaluated.
  - **Workspace Overlap**: Overlap of accessed resources/files.
  - **Tool Overlap**: Jaccard similarity of executed tools.
- When distance falls below the collision threshold (agents exploring the same proof step), it pauses them and triggers deconfliction protocols.

### C. Agent Runner (`agent_runner.py`)
The worker representing a single logic processor in the swarm:
- An agent can perform multi-step logic but strictly processes and validates **one logic step at a time**.
- Dynamically decomposes tasks and spawns ("hires") subagents to parallelize exploration of subsequent steps.
- Integrates local LLMs to formulate logic, write code, and evaluate outputs.

### D. Unified Persistent TUI REPL Dashboard (`terminal_dashboard.py`)
A comprehensive, terminal-based research harness:
- **Left Panel**: Logic tree and agent status board.
- **Center Panel**: Live output viewer displaying the formulated steps.
- **Right Panel**: Active deconfliction collisions log and the registered gravestones (Tombstones).
- **Persistent REPL Input**: For injecting human intuition or managing the swarm.

---

## 2. Storage & Directory Layout

The workspace state encapsulates the logic graph under `.proximity_swarm/`:

- **`agents/*.json`**: State files containing agent ID, parent ID, current logic step, progress, and spawn requests.
- **`collisions/*.json`**: Active negotiations when agents step on each other's logic paths.
- **`workspaces/agent_<id>/`**: Isolated workspace for an agent's hypotheses.
- **`tombstones.json`**: An index of "Gravestones"—failed steps and invalid logic branches so active agents steer clear of known dead ends.
- **`monitor.log`**: Centralized log stream.

---

## 3. Storage Management & TUI Commands

The TUI implements `/clean` to manage the massive state generated by logical exploration:
- `/clean logs`, `/clean workspaces`, `/clean collisions`, `/clean tombstones`, `/clean tasks`, `/clean all`, `/clean <filename>`.

---

## 4. Pre-Query Swarm Configuration & Recommendations

Users can define custom roles and dedicated goals for starting agents:
- **Manual Configuration**: `/add-agent <role> : <goal>`.
- **Dynamic Recommendation**: The TUI uses the local LLM to analyze the initial problem and recommend 1-3 starting agents to tackle divergent approaches.
- **TUI Swarm Designer**: A CLI Swarm Designer editor to review and edit agents.

---

## 5. Deconfliction, Collision Negotiation & The Judge

When the Proximity Engine detects two agents drifting too close (duplicating logic):
1. **Rule-Based fallback**: Evaluates which agent has formulated a more complete step.
2. **Interactive mode**: Prompts the user to manually resolve the collision.
3. **The Judge**: A dedicated evaluation mechanism. The Judge evaluates the validity of the colliding logic steps and resolves the deadlock. The Judge utilizes the strongest available local reasoning model (e.g., `gemma-2-27b` running on the 64GB Mac Studio) for high-fidelity evaluation.

---

## 6. Verification Plan & Automated Tests

A dedicated test suite (`/tests`) validates the supervisor logic and distance calculations: `test_proximity.py`, `test_monitor.py`, `test_v2.py`, `test_clean.py`, `test_personalities.py`, `test_artifact_combination.py`.

---

## 7. Hierarchical Artifact Synthesis (Proof Combination)

Aggregates individual logic steps into a coherent final proof/report:
- **Process Tree Mapping**: Scans the agent state files to build parent-child logical links.
- **Asynchronous LLM Bottom-Up Synthesis**: Generates a synthesized report via the local LLM in a background thread. Summarizes leaf nodes first, merges sibling logic, and integrates upward into the final conclusion.

---

## 8. User Interface Enhancements

- **Embedded Swarm Designer TUI**: Integrates the designer directly within the dashboard.
- **Context-Aware Command Help Banners**: Shows permanent commands.

---

## 9. Episodic Memory System

Facilitates long-term institutional learning:
- **Local Vector Database**: Persists completed/failed logic runs via SQLite (`memory.db`).
- **Ollama Embeddings with TF-IDF Fallback**: Generates semantic embeddings for tasks.
- **Hybrid Lifecycle Integration**: On start, an agent queries for highly similar past episodes and injects their errors and reflections to avoid repeating past mistakes. On completion, it records a self-reflection summary.

---

## 10. Three-Tiered Hierarchical Swarm Scaling

Scales complex logic decomposition:
- **Orchestrator Coordination**: Decomposes the macro problem into a dependency tree of sub-goals.
- **Global Workspace & Cross-Swarm Takeovers**: Sub-swarms share context. If agents in different sub-swarms duplicate logic, they negotiate, and one takes over.
- **Dependency-Gated Lifecycle**: A sub-swarm is complete only when all active leaf agents finish and the consensus-gating framework (Judge) approves the synthesis.

---

## 11. Dynamic Proximity Weighting (Adaptive Focus)

Adjusts spatial sensitivity based on the current logic phase:
- **LLM-Based Phase Classification**: Classifies steps into `Planning`, `Exploring`, `Validating`, or `Synthesizing`.
- **Predefined Weights**: Planning heavily weighs goal alignment; Validating heavily weighs resource collisions.

---

## 12. Causal Graph Tracing (Observability Layer)

Observes the non-deterministic trajectories of the logic search:
- **Local SQLite Adjacency List**: Stores all nodes (Logic Steps) and edges (Spawns, Merges).
- **Mermaid Markdown Flowcharts**: Translates the search tree into a Markdown diagram.
- **TUI Integration**: `/trace [agent_id]` dynamically renders the causal lineage.

---

## 13. Self-Healing Verification Loop (Logic Check)

High-reliability verification of logic steps:
- **Self-Healing Inner Loop**: After a step is formulated, the agent executes its verification command. On failure, it enters a self-healing loop—feeding the raw failure back to the LLM to patch the logic.
- **Gravestones (Tombstones)**: If it fails after `MAX_HEAL_ATTEMPTS`, the branch is declared a logical dead end. A Gravestone is registered, and the agent terminates. Future agents avoid this exact path.
- **Test-Driven Progress**: A logic step is only considered complete if it passes verification.

---

## 14. Interactive Swarm Budget & Pruning System (Quotas)

Manages computational overhead and prevents runaway branching in open-ended research:
- **Active Swarm Quota Enforcer**: A CLI argument (`--budget`) sets the active branch cap.
- **The Judge's Ranking**: If the swarm exceeds the quota, the Judge evaluates active leaf agents, ranking their logic branches from least to most promising.
- **Safe Leaf-Only Pruning**: The least promising branches are paused or pruned (`/prune <agent_id>`). Pruned branches write a Gravestone so the swarm doesn't immediately re-explore them.

---

## 15. Proximity & Novelty-Driven Spawning (Hiring)

Accelerates logic exploration through divergent subagents:
- **Semantic Isolation Check**: If an agent's logic approach is highly dissimilar to peers, it is semantically isolated.
- **Episodic Novelty Check**: If the approach has never been tried in memory, it is novel.
- **Hiring**: If isolated or novel, the agent dynamically spawns ("hires") a subagent to parallelize investigation into that specific branch.

---

## 16. Real-Time Thought Traces & Interactive Goal Pivoting

Supports human-in-the-loop logic steering:
- **Chronological Timeline**: Merges agent logic thoughts into a thread.
- **Operator Instruction Interception**: An agent checks for human intuition messages before starting its next step. It can either ingest it as context or pivot its logic entirely.
