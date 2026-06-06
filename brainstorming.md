# Proximity Swarm: Game-of-Life Agent Swarm Framework

Proximity Swarm is an agentic framework designed to coordinate a swarm of autonomous agents working on complex tasks. It applies cellular-automata-style rules (inspired by Conway's Game of Life) and semantic spatial proximity to manage resource consumption, accelerate task execution, and share learnings dynamically.

---

## 1. Core Concept & Analogy

In a traditional agent swarm, agents work either completely in parallel (leading to duplicate work) or through a rigid hierarchical structure (rigid manager-worker patterns). 

**Proximity Swarm** treats agents as cells living in a high-dimensional **Trajectory Space**. 
* **The Grid:** The "board" is a shared global semantic space where agents publish their trajectories (goals, thoughts, tool executions, and findings).
* **Proximity:** Two agents are "neighbors" if their goal embeddings, tool usages, or visited directories are semantically or structurally close.
* **Cellular Rules (Game of Life):**
  * **Overpopulation (Redundancy):** If too many agents are working on the same subtask in the same workspace, they "die" (self-terminate) to save compute.
  * **Underpopulation (Isolation):** If an agent is alone and making slow progress, it can "reproduce" (spawn specialized sub-agents) to explore surrounding paths.
  * **Symbiosis (Converse & Learn):** When agents get close, they pause, share memories, and accelerate each other or redirect their trajectories to avoid traps.

---

## 2. Architecture & Components

```mermaid
graph TD
    subgraph Swarm Environment
        A1[Agent 1] <--> |Reads/Writes| Tracker[(Global Trajectory Tracker)]
        A2[Agent 2] <--> |Reads/Writes| Tracker
        A3[Agent 3] <--> |Reads/Writes| Tracker
    end
    
    subgraph Proximity & Life Engine
        Tracker --> PE[Proximity Engine]
        PE --> |Finds Overlap| SC[Sync Coordinator]
        SC --> |Triggers| Converse[Converse & Negotiate]
    end
    
    Converse --> |Outcome 1| Accelerate[Accelerate & Share]
    Converse --> |Outcome 2| TerminateA[Agent A Self-Terminates]
    Converse --> |Outcome 3| DeadEnd[Altruistic Trap Warning]
```

### A. The Trajectory Tracker
Every agent continuously logs its execution state to a shared database or blackboard. A trajectory slice includes:
* **Agent Metadata:** ID, Parent ID, Status (`exploring`, `syncing`, `dead`, `completed`).
* **Semantic Coordinates:** Embeddings of the high-level goal, current sub-task, and recent reasoning steps.
* **Structural Footprint:** Absolute file paths accessed, command prefixes executed, APIs called, and tools used.
* **Knowledge Ledger:** Facts discovered, errors encountered, and successfully generated code snippets.

### B. The Proximity Engine
A background engine (or self-checking routine runs within each agent) that computes distances between agents:
$$\text{Distance}(A_1, A_2) = w_1 \cdot (1 - \cos(\theta_{\text{goal}})) + w_2 \cdot d_{\text{workspace}} + w_3 \cdot d_{\text{tools}}$$
* $\cos(\theta_{\text{goal}})$: Cosine similarity between goal/subtask embeddings.
* $d_{\text{workspace}}$: Overlap ratio of accessed directory trees or files.
* $d_{\text{tools}}$: Jaccard similarity of toolsets and command invocations.

When $\text{Distance}(A_1, A_2) < \text{Collision Threshold}$, a **Sync Event** is triggered.

---

## 3. The Sync & Converse Protocol

When a Sync Event is triggered, the two proximate agents pause execution and initiate a **Negotiation Dialogue** using their LLM contexts.

### The Negotiation Workflow
1. **State Exchange:** Agent A and Agent B exchange compressed summaries of their trajectories and current state.
2. **Path Comparison:** They assess who has progressed further and if their goals are identical or complementary.
3. **Decision Selection:**

| Scenario | Agent A State | Agent B State | Resolution / Action |
| :--- | :--- | :--- | :--- |
| **Identical Goal, B is Ahead** | Active, behind in path | Active, ahead in path | **Agent A Self-Terminates.** Agent A logs its partial learnings for B, then terminates. |
| **Complementary Goals** | Active on subtask 1 | Active on subtask 2 | **Acceleration.** They exchange code snippets/knowledge. Agent A avoids repeating B's work on shared sub-problems. |
| **Trap/Dead-End Encountered** | Active, entering a path | Active, failed/blocked on that path | **Trap Avoidance.** Agent B shares the failure mode (e.g., "Library X has a bug on macOS"). Agent B self-terminates, leaving a "Tombstone". Agent A updates its planning constraints and pivots. |
| **Stagnant Search** | Isolated, low progress | None | **Spawning.** Agent A spawns a helper agent with a different search heuristic to explore adjacent nodes. |

---

## 4. Concrete Examples

### Example 1: Redundancy Prevention (Game of Life: Overpopulation)
* **Scenario:** Agent A and Agent B are both tasked with fixing a bug in `auth.py`. Agent A started 5 minutes later than Agent B.
* **Proximity Check:** Both are editing `/src/auth.py` and running test suite commands. Proximity is high.
* **Negotiation:**
  * Agent A: *"I am at line 45 trying to resolve the JWT signing error."*
  * Agent B: *"I have already fixed that in my local workspace at line 55, and the tests pass. I am now writing unit tests."*
  * **Action:** Agent A states: *"Understood. Terminating duplicate process."* Agent A shuts down. Agent B inherits the CPU/budget allocation.

### Example 2: Altruistic Warning (Game of Life: Dead-end Evolution)
* **Scenario:** Agent A is trying to compile a C extension with GCC. Agent B just spent 10 steps attempting GCC, failed repeatedly due to missing system headers, and realized they must use Clang on macOS.
* **Proximity Check:** Agent A is about to execute `gcc -o build ...`. Agent B's trajectory matches the compilation attempt.
* **Negotiation:**
  * Agent B: *"Stop! Do not run GCC. I spent 8 steps trying; it fails because of macOS SDK header issues. Use `clang` instead. Here is the flags string: `-isysroot ...`."*
  * Agent B: *"I am terminating because my branch was focused on GCC setup, which is invalid."*
  * **Action:** Agent B dies. Agent A modifies its next step to use `clang` with the provided flags and succeeds on the first try.

---

## 5. Implementation Roadmap

### Phase 1: Local Simulation & Mock Agents
* Define the `TrajectoryTracker` using a local SQLite database or simple file system.
* Build a python command-line simulator showing mock agents running mock tasks.
* Implement the semantic and structural proximity calculations.
* Demonstrate the Sync protocol via LLM calls where mock agents chat and decide to terminate or share.

### Phase 2: Live Shell Agents
* Wrap agents with actual shell/editor tool access.
* Write a supervisor process that monitors trajectories.
* Create the "Tombstone" database to persist long-term lessons across different agent lifetimes.

### Phase 3: Web Visualization Dashboard
* A visual dashboard (using a force-directed graph or grid system) that renders agents moving through Trajectory Space.
* Highlight collisions, active negotiations, terminations, and spawned descendants.

---

## 6. Proposed Solutions for Open Questions

### A. How do we keep LLM costs low during sync?
To prevent exponential cost and high latency, we propose a **Tiered Proximity Pipeline**:

1. **Stage 1: Structural Filter ($O(1)$ cost)**
   - Check if agents share active directory paths, touched files, or command prefixes. If there is no overlap, skip checking.
2. **Stage 2: Embedding Similarity Check (Very Cheap)**
   - Generate embeddings for each agent's active sub-task (using a lightweight model like `text-embedding-3-small`). Calculate cosine similarity. Only proceed if similarity $> 0.8$.
3. **Stage 3: Gated LLM Check (Low-cost Model)**
   - Feed a concise summary of both trajectories to a cheap model (e.g., `gemini-1.5-flash`). Ask a binary question: *"Is there redundancy or a direct learning overlap between these two agent paths? Answer YES or NO."*
4. **Stage 4: Full Negotiation (Advanced Model)**
   - Only if Stage 3 returns YES, pause both agents and initiate the LLM negotiation protocol to decide on termination or sharing.

*Additionally, we can **rate-limit** sync checks to only occur at natural milestones (e.g., when a subtask ends, when a command fails, or every 5 steps) rather than on every single tool invocation.*

---

### B. What is the optimal embedding strategy for trajectories?
Instead of embedding raw tool outputs or full source code, we construct a hybrid **State Vector**:

1. **Semantic Layer:** Embedding of the high-level goal concatenated with the current step's planned objective.
2. **Structural Layer:** A set representation of accessed files, modified files, and tools used. Similarity is calculated using the Jaccard index:
   $$J(A, B) = \frac{|A \cap B|}{|A \cup B|}$$
3. **Composite Proximity Metric:**
   $$\text{Proximity} = w_1 \cdot \text{CosineSim}(\text{Semantic}_A, \text{Semantic}_B) + w_2 \cdot J(\text{Files}_A, \text{Files}_B)$$
   This ensures that agents are deemed "proximate" only if they are both thinking about the same concept *and* working in the same structural area.

---

### C. How do agents transfer state?
Since agents are not limited to coding tasks and may be doing research, writing, math, or executing APIs, state transfer must be environment-agnostic. We propose three general mechanisms:

1. **Shared Workspace Directory (The "Blackboard" File System):**
   - The swarm shares a root workspace. Each agent is allocated a subfolder (e.g., `./workspace/agent_A/`).
   - Before Agent A self-terminates, it moves its relevant output files and data artifacts to a shared folder `./workspace/shared/` or directly to Agent B's folder.
   - This allows Agent B to read Agent A's output files without version control systems.

2. **Structured Handover Packet (Context Injection):**
   - The terminating agent compiles a serialized JSON payload containing its local state variables:
     ```json
     {
       "variables": {"retrieved_api_key": "xyz", "target_url": "example.com"},
       "findings": ["Endpoint X returned status 200", "Documentation suggests using v2 API"],
       "traps_avoided": ["v1 API is deprecated, do not use"],
       "pending_actions": ["Fetch data from /v2/analytics"]
     }
     ```
   - The supervisor/coordinator injects this payload directly into Agent B's system prompt or working memory context in the next step.

3. **Key-Value Store / Shared Memory Database:**
   - A central lightweight database (like SQLite or Redis) tracks key-value parameters.
   - Agents read/write to keys namespace-prefixed by task or agent.
   - When Agent A dies, it updates the status of its keys to `released`, enabling Agent B to acquire lock/ownership over those variables and continue the work.


