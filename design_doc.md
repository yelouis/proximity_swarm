# Technical Design Document: Proximity Swarm V2

Proximity Swarm V2 is an agentic framework designed to coordinate a swarm of autonomous agents working on complex tasks. It applies cellular-automata-style rules (inspired by Conway's Game of Life) and semantic spatial proximity to manage resource consumption, accelerate task execution, and share learnings dynamically.

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


