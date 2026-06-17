# Technical Design Document: Proximity Swarm

Proximity Swarm is an agentic framework that coordinates a swarm of autonomous agents working on
complex tasks. It applies cellular-automata-style rules (inspired by Conway's Game of Life) and
semantic spatial proximity to manage resource consumption, accelerate task execution, and share
learnings dynamically.

This document is the **backend / system spec** (orchestration, agents, coordination, learning,
and the terminal interface). The **web dashboard** has its own spec in
[`ui_design_document.md`](ui_design_document.md); the simplification rationale is in
[`simplified_ui_design.md`](simplified_ui_design.md).

## Implementation status

Every feature below is implemented and has test coverage. The sections retain their original
numbering; the groups are conceptual.

| # | Feature | Primary module(s) | Tests | Status |
|---|---|---|---|---|
| 1 | Architecture (supervisor / monitor / runner / TUI) | `supervisor.py`, `proximity_monitor.py`, `agent_runner.py`, `terminal_dashboard.py` | — | ✅ |
| 2 | Storage layout (`.proximity_swarm/`) | all modules | — | ✅ |
| 3 | Storage clean commands | `terminal_dashboard.py`, `web_dashboard.py` | `test_clean.py` | ✅ |
| 4 | Swarm designer + LLM recommendations | `terminal_dashboard.py`, `supervisor.py` | `test_personalities.py` | ✅ |
| 5 | Deconfliction & collision negotiation | `proximity_monitor.py`, `agent_runner.py` | `test_proximity.py`, `test_monitor.py` | ✅ |
| 6 | Verification plan & automated tests | `tests/` | — | ✅ |
| 7 | Hierarchical artifact synthesis | `terminal_dashboard.py` | `test_artifact_combination.py` | ✅ |
| 8 | TUI enhancements | `terminal_dashboard.py` | — | ✅ |
| 9 | Episodic memory | `memory_store.py` | `test_memory.py` | ✅ |
| 10 | Three-tier hierarchical scaling | `supervisor.py` | `test_hierarchical_scaling.py` | ✅ |
| 11 | Dynamic proximity weighting | `proximity_monitor.py` | `test_proximity_weighting.py` | ✅ |
| 12 | Causal graph tracing | `causal_tracer.py` | `test_causal_tracer.py` | ✅ |
| 13 | Self-healing verification loop | `agent_runner.py` | `test_self_healing.py` | ✅ |
| 14 | Interactive budget & leaf pruning | `supervisor.py`, `proximity_monitor.py`, `terminal_dashboard.py` | `test_v2.py` | ✅ |
| 15 | Proximity & novelty-driven spawning | `agent_runner.py` | `test_collatz_research.py` | ✅ |

**Conceptual groups:** *Architecture & storage* (§1–2) · *Coordination & lifecycle* (§5, §10,
§14, §15) · *Execution & reliability* (§11, §13) · *Learning & observability* (§7, §9, §12) ·
*Interfaces & operations* (§3, §4, §6, §8).

---

## 1. System Architecture & Components

The system is designed around a decoupled, file-based architecture where state is tracked on the local filesystem. This permits loose coupling between the background supervisor, the individual agent execution processes, and the front-end visualization terminal.

```mermaid
graph TD
    subgraph Frontend / CLI
        TUI[TUI REPL Dashboard / terminal_dashboard.py]
    end

    subgraph Orchestration Layer
        SV[Supervisor Daemon / supervisor.py]
        PM[Proximity Monitor / proximity_monitor.py]
    end

    subgraph Agent Execution Layer
        AR1[Agent Runner / agent_runner.py - Agent 001]
        AR2[Agent Runner / agent_runner.py - Agent 002]
    end

    subgraph State Store (.proximity_swarm/)
        StateAgents[agents/ - State JSON files]
        StateCol[collisions/ - Negotiation files]
        StateWork[workspaces/ - Agent scratch directories]
        StateTomb[tombstones.json - Failure signatures]
        StateLog[monitor.log - Supervisor log feed]
    end

    TUI -->|Launches & Pipes| SV
    SV -->|Spawns| PM
    SV -->|Spawns / Scales| AR1
    SV -->|Spawns / Scales| AR2
    
    PM <-->|Polls & Updates| StateAgents
    PM <-->|Writes| StateCol
    
    AR1 <-->|Reads/Writes| StateAgents
    AR1 <-->|Reads/Writes| StateWork
    AR2 <-->|Reads/Writes| StateAgents
    AR2 <-->|Reads/Writes| StateWork
```

### A. Supervisor Orchestrator (`supervisor.py`)
Manages the process lifecycle of the swarm:
- Initializes the background **Proximity Monitor** daemon.
- Provisions child agent processes sequentially or concurrently based on active tasks.
- Implements process control policies such as **Cascading Kill Switches** (killing child subprocesses if a parent is terminated) and **Consensus-Gated Termination** (forcing at least one branch to survive to avoid swarm extinction).

### B. Proximity Monitor (`proximity_monitor.py`)
Runs continuously in the background to calculate spatial proximity between agents:
- Computes distances using a weighted combination of:
  - **TF-IDF Goal Similarity**: Vectorizes high-level agent goals and computes Cosine similarity.
  - **Workspace Overlap**: Jaccard similarity coefficient of accessed/touched files.
  - **Tool Overlap**: Jaccard similarity coefficient of executed command/tool utilities.
- When distance falls below the collision threshold, it changes agent statuses to `"syncing"` and triggers deconfliction/negotiation protocols.

### C. Agent Runner (`agent_runner.py`)
The worker process representing a single cell/agent in the swarm:
- Decomposes tasks dynamically or executes pre-defined plans.
- Polls its own state JSON file between execution steps to detect status overrides (`"syncing"`, `"pending_termination"`, or `"dead"`).
- Integrates local LLM execution via **Ollama** (`gemma4:latest`) to write code/text outputs into files dynamically instead of using static mock comments.

### D. Unified Persistent TUI REPL Dashboard (`terminal_dashboard.py`)
A comprehensive, terminal-based user interface using `rich` rendering:
- **3-Column Workspace Grid**:
  1. **Left Panel**: Agent status board showing active goals, progress bars, and touched files.
  2. **Center Panel**: Live output viewer displaying the contents of generated files as they are updated by agents in real-time.
  3. **Right Panel**: Active deconfliction collisions log (top) and the registered blocker tombstones database (bottom).
- **Persistent REPL Input**: Features a command prompt at the bottom of the screen allowing users to execute agentic tasks or storage maintenance commands continuously without exiting.

---

## 2. Storage & Directory Layout

The entire local workspace state is encapsulated under the `.proximity_swarm` folder:

```
.proximity_swarm/
├── agents/
│   ├── agent_001.json
│   └── agent_002.json
├── collisions/
│   └── collision_001_002.json
├── workspaces/
│   ├── agent_001/
│   │   └── src/
│   │       └── auth.py
│   └── agent_002/
├── tombstones.json
└── monitor.log
```

- **`agents/*.json`**: Contains agent ID, parent ID, current goal, step-by-step progress metrics, status, and active spawn requests.
- **`collisions/*.json`**: Tracks active negotiations, relative distances, and resolution choices.
- **`workspaces/agent_<id>/`**: Isolated workspace directory for each agent to write code and perform executions.
- **`tombstones.json`**: An index of failed steps and bug signatures so active agents can steer clear of known traps.
- **`monitor.log`**: Centralized log stream.

---

## 3. Storage Management & TUI Commands

To manage storage overhead and clear out dynamic artifacts, the TUI REPL implements `/clean` (or synonyms `/purge`, `/delete-artifacts`) which supports target-specific cleanup arguments:

- **`/clean logs`**: Deletes the supervisor monitor log file (`.proximity_swarm/monitor.log`).
- **`/clean workspaces`**: Cleans the agent workspace output directories.
- **`/clean collisions`**: Cleans deconfliction collision records.
- **`/clean tombstones`**: Resets the tombstones blocker index.
- **`/clean tasks`**: Filters dynamically generated task entries from `mock_tasks.json`.
- **`/clean all`**: Performs a full wipe of the state directory and filters tasks.
- **`/clean <filename>`**: Recursively scans agent workspaces and deletes files matching the name or relative path (e.g. `/clean quicksort.py` or `/clean agent_001/src/quicksort.py`).

---

## 4. Pre-Query Agent Swarm Configuration & Recommendations

Users can define custom roles and dedicated goals for starting agents in the swarm before submitting queries. If none are specified, the system recommends optimal roles and goals based on the query:

- **Manual Configuration**: Users type `/add-agent <role> : <goal>` to register custom agents. The goals determine what focus areas each agent has and shape the dynamic step decomposition for their specific task.
- **Dynamic Recommendation**: Upon receiving a query, if the list of predefined agents is empty, the TUI uses the local Ollama instance to analyze the query. It recommends the optimal number of starting agents (1-3), specific specialist roles, and dedicated goals.
- **TUI Swarm Designer**: Before launching a task, the TUI opens a dedicated CLI Swarm Designer editor to review, edit (change roles/goals), add, or remove agents. It handles unread input streams robustly.
- **Logging Redirects**: To prevent terminal screen shifting/breakage, all task analysis, decomposition logs, and supervisor setup details bypass standard output and are written directly to `monitor.log`, displaying cleanly inside the bottom console log panel.
- **Supervisor Routing**: Predefined agent configurations (IDs, tasks, roles, goals) are serialized into a JSON string and passed to `supervisor.py` via the `--agents-config` CLI argument.

---

## 5. Deconfliction & Collision Negotiation

When the Proximity Engine detects that two agents are drifting too close, they are paused, and a negotiation workflow begins:

1. **Rule-Based fallback**: Evaluates progress metrics to decide which agent has completed more work on a shared task branch.
2. **Interactive mode**: Prompts the user via the command interface to manually specify how the collision should be resolved.
3. **LLM/Ollama negotiation**: Uses the local Ollama instance (`gemma4:latest`) or the Gemini API to have the agents converse and dynamically transfer learnings or merge branches.

---

## 6. Verification Plan & Automated Tests

A dedicated test suite is built under `/tests` to verify both supervisor logic, mathematical distance calculations, and the TUI storage cleanups:

- **`tests/test_proximity.py`**: Validates TF-IDF vectorization, Cosine similarity, and Jaccard overlaps.
- **`tests/test_monitor.py`**: Validates agent spawning, state loading, and workspace provisioning.
- **`tests/test_v2.py`**: Validates consensus-gate approvals/rejections, cascading process terminations, and deconfliction offsets.
- **`tests/test_clean.py`**: Validates granular command inputs and recursive workspace file deletions.
- **`tests/test_personalities.py`**: Validates custom agent role/goal command registration and persistence in the runner.
- **`tests/test_artifact_combination.py`**: Validates tree topology mappings, sibling merges, and recursive upward hierarchical syntheses.

---

## 7. Hierarchical Artifact Combination & Swarm Viewer

Proximity Swarm V2 provides a hierarchical combination engine to aggregate and display agent deliverables in structured Markdown formats:

- **Process Tree Mapping**: Scans active agent JSON state files recursively to build parent-child links.
- **Asynchronous LLM Bottom-Up Synthesis**: Generates a fully LLM-synthesized report via local Ollama (`gemma4:latest`) executing in a background worker thread (`bg_generate_synthesis`). While running, the TUI renders a loading message and prevents execution loop freezes.
- **State Hash Caching**: Computes MD5 signatures over agent JSON states and workspace files. The background LLM task is skipped if the current signature matches the cached value.
- **Prompt Architecture**: Summarizes leaf workspace files first, merges sibling agent outcomes on the same depth, and integrates child reports upward into parent contexts recursively.
- **Fallback**: Automatically falls back to clean deterministic Markdown tree merges if Ollama is disabled or unreachable.
- **TUI Viewer Command (`/view`)**: Toggles the center column output viewer between the combined synthesis and individual agent files.

---

## 8. User Interface Enhancements

- **Embedded Swarm Designer TUI**: Integrates the designer CLI prompt directly within the main dashboard layout. Left, Center, and Footer panels dynamically shift to show custom configurations, task instructions, and designer help documentation without screen clearance or shifting.
- **Context-Aware Command Help Banners**: Shows a permanent commands banner (`/add-agent`, `/view`, `/clean`) in the TUI logs footer during idle phases, shifting to a designer reference helper during agent layout setup.

---

## 9. Episodic Memory System

Proximity Swarm V2 integrates an Episodic Memory System for agent runs to facilitate long-term institutional learning:

- **Local Vector Database**: Persists completed/failed runs under `.proximity_swarm/memory.db` using SQLite. Schema includes goal, role/personality, status, step metadata, errors, deliverable summaries, and self-reflection text.
- **Ollama Embeddings with TF-IDF Fallback**: Generates semantic embeddings for query tasks using Ollama's embeddings API. If Ollama is offline or vector generation fails, it builds a TF-IDF vocabulary on all stored goals and computes Cosine similarity over term-frequency vectors.
- **Hybrid Lifecycle Integration**:
  1. **Swarm Designer Setup**: Retrieves similar past runs to provide reference context to the Ollama recommendations prompt.
  2. **Agent Runner Startup**: Queries the database for the agent's specific goal. If a highly similar past episode is found, its reflection, steps, and error signatures are injected into the agent runner's prompt as historical guidance.
  3. **Agent Completion**: On run completion (success/failure), the runner calls local Ollama (or a rule-based generator if offline) to construct a 2-3 sentence self-reflection summary, then writes the full episode context to memory.
- **TUI Management**: Exposes `/memory` command to display a summary table of past runs, and `/clean memory` to purge SQLite logs.

---

## 10. Three-Tiered Hierarchical Swarm Scaling

To scale complex task decomposition and coordinate functional groups, the architecture supports a three-tiered hierarchical model (Orchestrator -> Sub-Swarms -> Agents):

- **Orchestrator Coordination**: A top-level dynamic planner decomposes overall macro goals into a dependency tree of sub-goals. Sub-swarms are spawned dynamically as their macro-dependencies are resolved.
- **Global Workspace & Cross-Swarm Takeovers**: Sub-swarms share a unified workspace directory structure to facilitate maximum information sharing. The Proximity Monitor runs globally across all active agents. If two agents in different sub-swarms duplicate goals/resources, they undergo deconfliction negotiation where one agent takes over.
- **Dynamic Multi-Parent Links**: When a cross-swarm takeover occurs, the surviving agent is dynamically linked as a child to the parents of both sub-swarms. The supervisor updates the dependency tree so that both parent branches await the surviving agent's completion.
- **Dependency-Gated Lifecycle**: Sub-swarms are initialized dynamically and are marked complete only when all of their active leaf agents finish execution and the consensus-gating framework approves the unified hierarchical synthesis of their deliverables.

---

## 11. Dynamic Proximity Weighting (Adaptive Focus)

To optimize resources and adjust spatial sensitivity based on the state of execution, the framework utilizes an adaptive weighting system:

- **LLM-Based Phase Classification**: At the start of each execution step, the Proximity Monitor queries local Ollama to classify the active step into one of four task phases: `Planning`, `Coding`, `Debugging`, or `Documentation`.
- **Predefined Weights Mapping**: The classified phase dynamically updates the factor weights ($W_{goal}$, $W_{files}$, $W_{tools}$) used in the proximity distance function:
  - **Planning**: Boosts intent alignment ($W_{goal} = 0.8$, $W_{files} = 0.1$, $W_{tools} = 0.1$).
  - **Coding**: Balances semantics and resource changes ($W_{goal} = 0.4$, $W_{files} = 0.4$, $W_{tools} = 0.2$).
  - **Debugging**: Focuses heavily on resource collisions ($W_{goal} = 0.1$, $W_{files} = 0.6$, $W_{tools} = 0.3$).
  - **Documentation**: Prioritizes goals and outputs ($W_{goal} = 0.6$, $W_{files} = 0.3$, $W_{tools} = 0.1$).

---

## 12. Causal Graph Tracing (Observability Layer)

To debug and trace the non-deterministic trajectories of agents, the framework implements a structured causal logging layer:

- **Local SQLite Adjacency List**: Stores all nodes (Agent IDs, Steps, Collisions) and edges (Spawns, State Transitions, Takeovers) locally in SQLite tables. Each edge logs timestamp, command inputs, errors, and LLM reasoning prompts.
- **Mermaid Markdown Flowcharts**: Translates the active database timeline into a structured Markdown file containing a Mermaid syntax diagram.
- **TUI Integration**: Introduces the `/trace [agent_id]` command which dynamically generates and displays the agent's causal lineage flow directly inside the TUI center panel. Allows developers to trace decision histories and find root-cause errors visually.

---

## 13. Self-Healing Verification Loop (Ralph Wiggum Loop)

High-reliability, step-level self-healing built on the **Ralph Wiggum Loop** principle
("persistence over perfection"). Implemented in `agent_runner.py`
(`run_verification`, `heal_file`, `run_verification_loop`, and the gate inside `execute_step`);
covered by `tests/test_self_healing.py`. A step opts in by declaring a `"verification"` shell
command in its task definition (e.g. `"pytest test_cache.py"`); steps without one behave exactly
as before, so the feature is fully backward-compatible.

- **Self-Healing Inner Loop**: After a step writes its file(s), if the step declares a
  verification command the runner executes it in the agent's workspace. On a non-zero exit code it
  enters a self-healing loop — feeding the raw failure back to the LLM to patch the file and
  re-running verification — up to `MAX_HEAL_ATTEMPTS` (default 3, env-overridable via
  `PROXIMITY_MAX_HEAL_ATTEMPTS`). If it still fails, the step is declared a blocker, a tombstone is
  registered, and the agent moves to `pending_termination`.
- **Context Window Resetting**: Each heal attempt builds a **fresh** prompt containing only the
  goal, the current file contents, and the raw verification error — prior failed attempts are
  intentionally not accumulated, which keeps a local model's instruction-following sharp. If no LLM
  patcher is available (offline), the loop stops gracefully rather than spinning.
- **Test-Driven Progress Gates**: `steps_completed` / `progress` advance **only** after
  verification returns exit code 0. A step that cannot pass is never counted as complete, so
  progress indicators reflect concrete, verified milestones rather than mere execution.

---

## 14. Interactive Swarm Budget & Pruning System

To manage computational overhead and prevent runaway subagent spawning when tackling open-ended research problems, the framework implements an interactive swarm budgeting and safe pruning subsystem:

- **Active Swarm Budget Enforcer**: A CLI argument (`--budget`, default 4) sets the active agent cap limit. The supervisor and monitor daemon continuously evaluate active/exploring agents; completed, dead, or paused agents do not consume budget slots.
- **LLM-Based Leaf Agent Productivity Ranking**: If the active count exceeds the cap, the monitor daemon identifies active **leaf agents** (active agents with no active children/descendants). It queries local Ollama or the Gemini API to evaluate each leaf agent's goal and progress log, ranking them from least to most productive.
- **Heuristic Fallback Ranking**: If the LLM is offline or slow, the system automatically falls back to sorting leaf agents based on steps completed percentage (ascending) and inactivity duration (descending, prioritizing older/idle agents).
- **TUI Alerts and Pending Decisions Layout**: The right column of the terminal dashboard is statically divided into three sections: Collisions (top), Alerts/Pending Decisions (middle), and Tombstones (bottom). Budget cap violations, leaf pruning candidates with explanations, pending spawn approvals, and blocker reviews are rendered dynamically here.
- **Safe Leaf-Only Pruning Commands**: Users can dynamically execute `/budget <new_cap>` to adjust limits, or `/prune <agent_id>` to terminate execution. Pruning is strictly restricted to leaf agents to prevent cascading shutdowns of downstream active branches.
- **Administrative Tombstone Records**: Pruned agents set their status to `"dead"` and write their goals, explanations, and metadata to `tombstones.json` with an `is_pruned: true` flag. Future agents do not block on these tombstones, but they ingest the prune warnings during step execution to avoid taking too long or to guide task decomposition.

---

## 15. Proximity & Novelty-Driven Spawning

To solve complex, open-ended tasks like unsolved mathematical theorems (e.g. Collatz Conjecture), the isolation spawning check is refined to measure semantic similarity and historical novelty:

- **Semantic Isolation Check**: Every 5 steps, the agent runner computes TF-IDF similarity against active peer agents. If no peer goal similarity exceeds 0.35, the agent is considered semantically isolated.
- **Episodic Novelty Check**: The agent queries its SQLite vector episodic database. If the best-match similarity of past runs is under 0.50, the task approach is marked as novel.
- **Novelty Spawning Gating**: If the agent is semantically isolated OR the approach is memory-novel, spawning is triggered to launch a specialized subagent (e.g. searching for computational counterexamples), accelerating execution via parallel investigation loops.

## 16. Real-Time Thought Traces & Interactive Goal Pivoting

To support human-in-the-loop coordination, selecting any active agent exposes a messaging timeline and decision intercept loop:

- **Chronological Timeline**: Merges agent chat messages and inner-logic thoughts into a single chronological message thread. Thoughts are rendered as styled blocks with specific border-colors and icons depending on type (`evaluating`, `decision`, `executing`, `completed`, `failed`, `syncing`, `resolved`).
- **Operator Instruction Interception**: At the start of every task execution step, the runner pauses to check for unprocessed operator chat messages. If messages are found, the runner queries the LLM (Ollama or Gemini) with details of the current goal and user directions to choose between:
  1. `ADD_CONTEXT`: Ingest user messages as supplementary instructions while maintaining current goals.
  2. `PIVOT`: Pivot the agent's goal directly in its state database, continuing execution in the new direction.
- **Assistant Reflections**: Writes a thought trace explaining the reasoning behind the context or pivot decision, logging the result back to the chat timeline.




