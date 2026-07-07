# Proximity Swarm — Harness Implementation Plan

> **Audience.** A developer or an autonomous coding agent building the Proximity Swarm *logic
> research harness*. This document is **self-contained**: it carries the architecture facts, data
> shapes, file map, and step-by-step build instructions you need, so you should rarely have to
> reverse-engineer the codebase from scratch.
>
> **Read first, in order:** [`design_doc.md`](design_doc.md) — especially **§0 Core Thesis**
> (atomic steps + the propose/validate split + the logic graph) — then
> [`harness_design_document.md`](harness_design_document.md) (the observability UI spec), then this
> file. Test journeys live in [`user_journeys.md`](user_journeys.md) and
> [`user_journeys_collatz.md`](user_journeys_collatz.md).
>
> ✅ **The LLM is now really in the loop.** Defects A–H, regressions R1–R4, and the stubbed
> propose/validate loop (O1/O2) are all fixed and **verified 2026-07-06** (commits `0507ee7`,
> `417b845`, `efc8177`; 101/101 unit tests pass). A real `gemma4` run produces genuine
> model-generated lemmas and can refute steps. Closed items: **[§11 Resolution log](#11-resolution-log)**.
>
> 🛑 **But real-model runs still cannot succeed, and "Success" doesn't mean what it should.** Two
> blockers verified 2026-07-06: (1) the hardcoded **120s wall-clock kill-switch** terminates any
> `ollama` run after ~2–3 LLM cycles (token budgets never bind because token accounting is lost to a
> write race); (2) the supervisor **promotes the goal to "proven" as soon as ONE child node
> validates** — a validated "2+2=4" lemma marks "Prove the Collatz Conjecture" as solved. Current
> blockers: **[§12 Open problems](#12-open-problems-blocking)** (N1–N7).

---

## Table of contents

1. [What we are building (one page)](#1-what-we-are-building-one-page)
2. [The current codebase, grounded](#2-the-current-codebase-grounded)
3. [Gap analysis: today → target](#3-gap-analysis-today--target)
4. [Core data model: the logic graph](#4-core-data-model-the-logic-graph)
5. [Ground rules: how to run, test, and not break things](#5-ground-rules-how-to-run-test-and-not-break-things)
6. [Phased build plan](#6-phased-build-plan)
   - [Phase 1 — Logic graph runtime artifact](#phase-1--logic-graph-runtime-artifact)
   - [Phase 2 — The propose/validate loop](#phase-2--the-proposevalidate-loop)
   - [Phase 3 — The Judge as a first-class role](#phase-3--the-judge-as-a-first-class-role)
   - [Phase 4 — Pluggable validation oracle](#phase-4--pluggable-validation-oracle)
   - [Phase 5 — Proximity over logic steps](#phase-5--proximity-over-logic-steps)
   - [Phase 6 — Divergence, gravestones, quotas](#phase-6--divergence-gravestones-quotas)
   - [Phase 7 — Hierarchy, consensus, cascading kills](#phase-7--hierarchy-consensus-cascading-kills)
   - [Phase 8 — Observability artifacts](#phase-8--observability-artifacts)
   - [Phase 9 — The Logic Exploration Harness UI](#phase-9--the-logic-exploration-harness-ui)
   - [Phase 10 — Headless harness surface & benchmarking](#phase-10--headless-harness-surface--benchmarking)
7. [Frontend architecture reference](#7-frontend-architecture-reference)
8. [Testing strategy](#8-testing-strategy)
9. [Smallest-safe-commit discipline](#9-smallest-safe-commit-discipline)
10. [Glossary](#10-glossary)
11. [Resolution log (defects A–H, regressions R1–R4)](#11-resolution-log)
12. [Open problems (BLOCKING)](#12-open-problems-blocking)

---

## 1. What we are building (one page)

The goal (from `design_doc.md` §0): take a **small, local, open-source LLM** and amplify its ability
to carry a long chain of logic by running it as a **team of single-step agents** that grow and
validate a shared **logic graph** toward a hard goal (a proof, or a piece of engineering).

Three mechanisms make the team work, and they are the spine of this plan:

1. **Atomic steps.** Each agent's unit of work is *one logic step* — small enough that a weak model
   is reliable at it.
2. **Propose ≠ validate.** *Proposing* the next step is creative and error-prone; *validating* it is
   cheap and reliable. The swarm splits these jobs: **Proposer** agents generate candidate steps;
   **Validator/Judge** agents verify each one against an oracle *before* it joins the trusted graph.
   This filtering is the amplification.
3. **Proximity = team awareness.** Agents sense peers in idea- and resource-space, so they **dedupe**
   (drift too close → stop / share / merge) and **diverge** (too isolated/novel → "hire" a child to
   open a new branch).

The product is a **harness**: a headless engine + CLI/API that runs these experiments and emits
structured artifacts (the logic graph, validated paths, gravestones, the causal trace, cost). The
web dashboard is an **optional observability lens** over those artifacts.

**The single most important change in this plan:** today the system *decomposes a goal into 2–5
fixed steps once, then executes them*. We are turning that into an **iterative
propose → validate → commit loop that grows a graph**, with proposing and validating as separate
roles. Everything else (Judge, gravestones, hiring, quotas, memory, trace, UI) already exists in
some form and gets re-pointed at the graph.

---

## 2. The current codebase, grounded

A decoupled, **file-based** system: state lives under `.proximity_swarm/` and loosely couples a
background supervisor, independent agent processes, and any reader (CLI, TUI, or web).

### 2.1 Modules and the functions that matter

| Module | Role | Key functions (verified) |
|---|---|---|
| `supervisor.py` | Process lifecycle / orchestration | `run_swarm`, `launch_agent`, `evaluate_sub_swarm_completion`, `is_agent_sub_swarm_active`, `clean_state`, `run_redundant_demo` |
| `proximity_monitor.py` | Background daemon: proximity, collisions, phase weighting, consensus, pruning | `monitor_loop`, `calculate_proximity`, `calculate_tfidf_cosine_similarity`, `calculate_jaccard_similarity`, `classify_phase`/`fallback_classify_phase`, `handle_spawn_requests`, `evaluate_consensus_gate`, `run_cascading_kills`, `get_active_leaf_agents`, `rank_leaf_agents_llm` |
| `agent_runner.py` | The worker "cell" | `AgentRunner.execute_step` (the core loop, ~L1031), `perform_negotiation` (~L1505, today's Judge), `evaluate_isolation_spawn` (~L495, hiring), `run_verification`/`heal_file`/`run_verification_loop` (~L773, validation), `check_tombstones`/`check_pruned_tombstones`, `save_memory_episode`, `load_historical_context`, `request_spawn_agent`, `check_in_on_children`, `ingest_child_outputs`, `finalize_or_await` |
| `memory_store.py` | Episodic memory (SQLite) | `init_db`, `save_episode`, `query_similar_episodes`, `get_embedding`, `compute_tfidf_similarities`, `cosine_similarity`, `clean_memories` |
| `causal_tracer.py` | Causal trace (SQLite → Mermaid) | `add_node`, `add_edge`, `log_agent_spawn`, `log_step_execution`, `log_collision`, `log_takeover`, `log_state_transition`, `get_connected_component`, `generate_mermaid_graph`, `save_mermaid_markdown` |
| `web_dashboard.py` | HTTP/SSE server + one-shot goal decomposition | `decompose_goal` (~L374), REST routes (see §7.4), SSE `/api/events` |
| `terminal_dashboard.py` | TUI REPL + swarm designer | `bg_decompose_macro_goal`, `decompose_macro_goal`, `recommend_budget_cap`, render loop |
| `static/` | SPA | `index.html`, `app.js`, `styles.css` (see §7) |
| `cli.py`, `run_swarm_research.py` | Entry points | piped forwarder; research compiler |

### 2.2 LLM providers (verified)

`--llm-provider` accepts **`ollama`** (default model `gemma4:latest`), **`gemini`** (needs
`GEMINI_API_KEY`), or **`rules`** (deterministic, no LLM — used by tests and offline). Embeddings:
`nomic-embed-text` (`memory_store.DEFAULT_EMBED_MODEL`), with a TF-IDF fallback. Tool-calling exists
(`call_ollama_chat_with_tools`); a small skill set lives in `.gemini/skills/` (`spawn`, `tombstone`,
`negotiate`, `explore`).

### 2.3 How work flows today (the loop we are changing)

1. A goal is **decomposed once** into 2–5 steps: `web_dashboard.decompose_goal` (or
   `terminal_dashboard.decompose_macro_goal`) prompts the LLM and writes a **task** into
   `mock_tasks.json`. Task shape: `{ id, goal, steps:[{ step_id, name, description, touched_files,
   tools }] }`. **Note:** steps do *not* currently carry a `verification` command, so the §13
   self-healing oracle is wired but never triggered by real tasks.
2. `supervisor.run_swarm` launches `proximity_monitor.py` and N `agent_runner.py` processes.
3. Each `AgentRunner.execute_step` reads the **next predefined step** (`steps[steps_completed]`),
   writes file content into its workspace via the LLM, optionally runs the verification loop, and
   increments `steps_completed` / `progress`. It also: processes operator chat (pivot/add-context),
   checks tombstones, and every step calls `evaluate_isolation_spawn`.
4. The monitor computes pairwise `calculate_proximity`; below threshold it flips both agents to
   `syncing` and writes a collision file; the agent's `perform_negotiation` resolves it
   (`kill_a` / `kill_b` / `keep_both`).
5. Spawns, consensus gate, cascading kills, pruning run in `monitor_loop`.

**The key insight for this plan:** steps are *consumed*, not *proposed*; proposing is a one-shot
upfront act, and validation is code-only and unused. We make proposing iterative and per-agent, and
make validation a first-class, pluggable gate.

---

## 3. Gap analysis: today → target

| Concept (`design_doc.md`) | Today | Target | Phase |
|---|---|---|---|
| **Logic graph** (§0, §2) | Linear `steps[]` in `mock_tasks.json` + per-agent state JSON | A real DAG of step nodes with status/deps/approach, persisted under `.proximity_swarm/graph/` | 1 |
| **Propose a step** (§0) | One-shot decomposition into 2–5 fixed steps | Iterative per-agent **Proposer**: propose next step from the graph frontier | 2 |
| **Validate a step** (§0, §13) | `run_verification_loop`, code-only, opt-in, unused by tasks | First-class validate gate every step passes before commit; status `proposed→validated/refuted` | 2, 4 |
| **The Judge** (§5, §10, §14) | `perform_negotiation`: redundancy only (kill/keep), "coding agents" prompt, picks gemini-if-key-else-ollama | One role that (a) validates/adjudicates steps, (b) resolves collisions, (c) ranks branches — **strongest *local* model first** | 3 |
| **Validation oracle** (§13) | Shell command + Ollama heal | Pluggable: `shell` (code), `numeric`/`symbolic` (math), `checker_model` (LLM-as-judge) | 4 |
| **Proximity** (§5, §11) | Over goal text + files + tools | Also over the **current step claim**; outcomes = stop / **share** / **merge** (not just kill/keep) | 5 |
| **Hiring** (§15) | `evaluate_isolation_spawn` every 5 steps | Same, but seeds a **distinct approach branch** in the graph | 6 |
| **Gravestones** (§4.4/§13/§14) | `tombstones.json` for dead files/tools + pruned | Also tombstone **refuted steps / dead branches** with reasons; surfaced on the tree | 6 |
| **Quotas** (§14) | `--budget`, leaf ranking + prune | Unchanged mechanism; ranks **leaf branches** of the graph | 6 |
| **Hierarchy/consensus** (§10) | sub-swarms, `evaluate_consensus_gate`, `run_cascading_kills` | Adapt completeness gate to "validated path exists" | 7 |
| **Observability** (§12) | Causal trace + tabbed IDE UI | Emit logic-graph artifact (JSON + Mermaid); **Logic Exploration Harness** UI | 8, 9 |
| **Harness surface** (§5 of design) | CLI args scattered; UI-centric | Declarative **run spec** file + headless CLI + cross-model benchmark | 10 |

---

## 4. Core data model: the logic graph

This is the new central artifact. **Storage decision (locked): one JSON file per node** under
`.proximity_swarm/graph/node_<id>.json`, **plus a single derived snapshot**
`.proximity_swarm/graph/snapshot.json`. Rationale and the concurrency rules are in **§4.4** — read
it before building anything here. (In short: the codebase has *no* file locking and `save_json` is
not atomic, so a single hot `graph.json` written by many processes would suffer torn reads and lost
updates — the exact latent failure mode `tombstones.json` already has. Per-node files give
contention-free writes; the snapshot gives cheap whole-graph reads/export.)

### 4.1 Step node schema

```jsonc
// .proximity_swarm/graph/node_<node_id>.json
{
  "node_id": "n0007",                // stable, zero-padded
  "claim": "For n even, T(n)=n/2 strictly decreases n.",  // what this step asserts/accomplishes
  "justification": "…reasoning or code…",                  // how it is supported
  "depends_on": ["n0001", "n0004"],  // parent nodes / premises (the DAG edges)
  "approach": "A",                   // which line of attack / branch this belongs to
  "status": "proposed",              // proposed | under_review | validated | refuted
  "kind": "lemma",                   // lemma | inference | subgoal | code_change | premise | goal
  "oracle": {                        // how this step is/was validated (see Phase 4)
    "type": "numeric",               // shell | numeric | symbolic | checker_model | none
    "spec": "python3 check_even.py", // command, expression, or checker prompt ref
    "result": null,                  // {passed:bool, detail:str, attempts:int} once validated
    "judge_model": null              // model used by the Judge for this evaluation
  },
  "provenance": {
    "proposed_by": "003",            // agent id
    "validated_by": "002",           // agent id (Validator/Judge)
    "created_at": "2026-06-27T22:40:00Z",
    "cost_tokens": 412
  }
}
```

- **Roots** are `kind:"premise"` nodes (problem statement, axioms, existing code+spec).
- The **goal** is a single `kind:"goal"` node; a **solution** is a fully `validated` path of
  `depends_on` edges from premises to the goal.
- **Approaches** are values of `approach` ("A", "B", …); the team explores several live branches at
  once. A refuted branch's nodes go `status:"refuted"` and emit a gravestone (Phase 6).

### 4.2 Graph access API (new module: `logic_graph.py`)

Create one module so every process touches the graph the same way (mirror `memory_store.py` style —
plain functions; **atomic writes via `save_json`, no cross-process locks** — see §4.4):

```
init_graph(run_dir)                       -> ensure .proximity_swarm/graph/ exists, write premises+goal
add_node(node) / get_node(node_id) / update_node(node_id, **fields)   # node-local writes only
frontier()                                -> [open nodes worth attacking]: validated nodes whose
                                             successors are unproposed, or the goal's unmet deps
nodes_by_status(status) / nodes_by_approach(approach)
validated_path_to_goal()                  -> [node_ids] or None (the completeness check, Phase 7)
similar_open_nodes(claim, k)              -> TF-IDF/embedding match for dedup (Phase 5)
merge_nodes(survivor_id, loser_ids)       -> MONITOR-ONLY structural mutation (§4.4); reparents deps
reparent(node_id, new_deps) / prune_branch(approach)  -> MONITOR-ONLY structural mutations
validate_graph()                          -> [violations]: invariant checker (§4.5); [] == healthy
rebuild_snapshot()                        -> MONITOR-ONLY: atomically rewrite snapshot.json from nodes
to_mermaid() / to_artifact_json()         -> observability exports (Phase 8), read from snapshot
```

`add_node`/`update_node` are **node-local** (each touches exactly one file) and may be called by any
process. The `merge_nodes`/`reparent`/`prune_branch`/`rebuild_snapshot` calls are **structural**
(they touch multiple files / referential integrity) and must run **only in the monitor process**
(§4.4) so they are serialized without cross-process locking.

Keep the existing `mock_tasks.json` path working as a **fallback / demo mode** (flag
`--graph-mode {linear|graph}`, default `graph`). This lets all current tests keep passing while the
graph path is built and tested in parallel.

### 4.3 Agent state JSON (existing — keep, extend)

Each `.proximity_swarm/agents/agent_<id>.json` already has (verified via the frontend contract):
`id`, `parent_id`, `parent_ids?`, `personality` (role), `goal`, `status`
(`exploring|syncing|pending_termination|completed|dead`, plus the runner-only `awaiting_child`),
`progress`, `steps_completed`, `current_step`, `touched_files`, `tools_used`, `thought_traces[]`,
`output_tokens`, `token_budget`, `subtree_token_budget`, `sub_swarm_id`, `spawn_request`,
`blocker_details`, `chat_messages[]`.

**Extend with:** `role_mode: "proposer" | "validator" | "judge" | "lead"` (default `"proposer"`),
`active_node_id` (the graph node this agent is currently proposing/validating), and `approach` (the
branch it is exploring). Default everything defensively — agents mid-spawn may lack fields.

### 4.4 Storage layout & concurrency model (decision + hardening)

The system is **multi-process** (supervisor + monitor + N agents) communicating **only through
files**, with **no lock manager**. Two verified facts about the current code drive this design:

- `save_json` (`agent_runner.py:56`) is **not atomic** — a plain `open(path,'w')` + `json.dump`, so
  a concurrent reader can read a half-written file.
- There is **no locking anywhere** (`fcntl`/`flock`/`filelock`/threading) — isolation is achieved by
  giving each writer its own file (`agents/<id>.json`, `collisions/*.json`). The one shared-file
  read-modify-write (`tombstones.json`, `agent_runner.py:1360-1369`) has a **latent lost-update
  bug**.

**Layout (locked):**

```
.proximity_swarm/graph/
├── node_n0001.json      # one file per node — the source of truth (concurrent, node-local writes)
├── node_n0002.json
├── …
└── snapshot.json        # derived, monitor-owned: full graph in one file for fast reads/export
```

**Concurrency rules (all three are invariants — see §5):**

1. **Node ownership.** A given node's *status* is written by exactly one role at a time: the
   **proposer** owns it while `proposed`/`under_review`; on hand-off the **validator/Judge** owns it
   through `validated`/`refuted`. Encode the owner in `provenance` and refuse a write from a
   non-owner. This removes same-node write races (different agents only ever write different nodes).
2. **Structural mutations are monitor-only.** `merge_nodes`, `reparent`, `prune_branch`, and
   `rebuild_snapshot` touch multiple files / referential integrity. Route them through the single
   monitor process (where `run_cascading_kills` / pruning already live) so they are serialized
   within one process — transaction-like safety without cross-process locks. Agents *request* a
   merge/prune by writing a flag on their node; the monitor performs it.
3. **Snapshot is derived, never authoritative.** `rebuild_snapshot()` (monitor, each tick or on
   change) writes `snapshot.json` atomically. Readers (UI `/api/graph`, exports, fast traversals)
   read the snapshot; a *stale* snapshot is acceptable, a *corrupt* one is not. The per-node files
   are always the source of truth.

**Hardening step (do this in Phase 1, benefits the whole codebase):** make `save_json` atomic —
write to `path + ".tmp"` then `os.replace(tmp, path)` (atomic on POSIX). This eliminates torn reads
everywhere (agents, collisions, graph nodes, snapshot) in ~3 lines and is a prerequisite for the
snapshot guarantee above. Note it does **not** fix `tombstones.json` *lost updates* (that needs
append-only files or a monitor-owned writer) — track that as a separate, pre-existing fix.

### 4.5 Graph invariant checker — `validate_graph()` (validation to implement)

Implement `logic_graph.validate_graph()` returning a list of violations (`[]` = healthy). It is the
runtime guard for the storage model above and the backbone of the test suite (§8). Run it: as an
assertion in tests, as a monitor self-check each tick (log + attempt repair), and before writing the
final artifact (Phase 8). It must check:

- **Referential integrity** — every id in any `depends_on` resolves to an existing node file; no
  edge points at a missing/loser node after a merge.
- **Acyclicity** — `depends_on` forms a DAG (no cycle); topological sort succeeds.
- **Single goal** — exactly one `kind:"goal"` node; ≥1 `kind:"premise"` root.
- **Status legality** — every `status` ∈ {proposed, under_review, validated, refuted}; every
  `oracle.type` ∈ {shell, numeric, symbolic, checker_model, none}.
- **Validated-path soundness** — no `validated` node `depends_on` a `refuted` node (a proof can't
  rest on a disproven step); `none`-oracle nodes never appear on a path counted as complete (§ Phase 4).
- **Ownership** — each node's last writer matches its owner per rule §4.4(1).
- **No orphaned in-flight nodes** — every `proposed`/`under_review` node is either owned by a live
  agent or back on the frontier (catches the cascading-kill release bug, Phase 7).
- **Snapshot freshness** — `snapshot.json` parses and its node set is a subset of (ideally equal to)
  the per-node files (stale-but-valid is OK; corrupt is a violation).

A `repair_graph()` companion (monitor-only) should fix the auto-fixable violations (release orphaned
nodes to the frontier, drop dangling edges from a half-finished merge, rebuild a corrupt snapshot)
and log the rest.

---

## 5. Ground rules: how to run, test, and not break things

```bash
# Headless engine (no UI), deterministic provider — best for building/testing the engine:
python3 supervisor.py --llm-provider rules --budget 4
# Local LLM run (needs Ollama running with gemma4:latest pulled):
python3 supervisor.py --llm-provider ollama --ollama-model gemma4:latest --budget 4
# Web dashboard (serves static/ from disk each request → edit-reload, no build step):
python3 web_dashboard.py --port 8080 --llm-provider rules     # open http://localhost:8080
# TUI:
python3 terminal_dashboard.py
# Tests (unittest — NOT pytest; pytest is not installed):
python3 -m unittest discover -s tests
```

**Non-negotiable invariants:**

1. **`rules` provider must always work offline.** Every new LLM call site needs a deterministic
   `rules` fallback (look at how `perform_negotiation` and `evaluate_isolation_spawn` branch on
   `provider`). Tests run under `rules`.
2. **Backward compatibility via `--graph-mode`.** The linear `mock_tasks.json` path must keep
   working until Phase 9; do not delete it. All 15 existing test files must stay green at every
   commit.
3. **File-based state is the contract.** Processes communicate only through `.proximity_swarm/`.
   Never add an in-memory cross-process channel.
4. **Writes must be atomic.** `save_json` is currently *not* atomic (`agent_runner.py:56`) and there
   is no locking. Phase 1 makes it atomic (temp + `os.replace`, §4.4). After that, all state writes
   — agents, collisions, graph nodes, snapshot — go through atomic `save_json`. Do not add a raw
   `open(...,'w')` + `dump` on shared state.
5. **Node ownership & monitor-only structural mutations.** A node's status is written only by its
   current owner (proposer → validator/Judge, §4.4(1)); `merge_nodes`/`reparent`/`prune_branch`/
   `rebuild_snapshot` run only in the monitor process. `validate_graph()` (§4.5) must pass at the end
   of every test.
6. **Local-model-first for the Judge.** Per the design owner's decision, the Judge uses the
   strongest available **local** model (e.g. `gemma-2-27b` on a 64 GB Mac Studio). Do **not** add a
   path that routes the Judge to a remote API for "higher fidelity." (Agents may still use any
   provider; the *Judge* is local-first.)
7. **Frontend:** plain DOM + template strings, no framework/npm/CDN; reuse `escapeHtml`/`escapeAttr`,
   the `:root` CSS custom properties, and the single delegated click dispatcher (see §7).

---

## 6. Phased build plan

Each phase is independently shippable, leaves the app working, and ends with explicit acceptance
criteria. Build the **engine** (Phases 1–8, 10) before the **UI** (Phase 9) — the UI only visualizes
artifacts the engine emits.

### Phase 1 — Logic graph runtime artifact

**Goal:** introduce the graph as data, with the storage/concurrency model and its validation in
place, but no agent behavior change yet.

1. **Harden `save_json` first (§4.4).** Change `agent_runner.py:56` to write `path + ".tmp"` then
   `os.replace(tmp, path)`. Keep the signature/return identical. This is a prerequisite for the
   snapshot guarantee and removes torn reads system-wide. Run the full suite — it must stay green.
2. Create `logic_graph.py` implementing §4.2 over `.proximity_swarm/graph/node_*.json`, using the
   atomic `save_json`. Node-local writes (`add_node`/`update_node`) callable by any process;
   structural ops (`merge_nodes`/`reparent`/`prune_branch`/`rebuild_snapshot`) callable but guarded
   so they no-op with a logged error if invoked outside the monitor (enforce §4.4(2)).
3. Implement `validate_graph()` and `repair_graph()` per **§4.5**.
4. Implement `rebuild_snapshot()` → atomic `snapshot.json`; point `to_artifact_json()`/`to_mermaid()`
   at the snapshot. Have the monitor call `rebuild_snapshot()` each tick when the graph changed.
5. Add `--graph-mode {linear|graph}` to `supervisor.py` and `agent_runner.py` (`argparse` already
   present; see `supervisor.py:328`, `agent_runner.py:1927`). Thread it through `launch_agent`.
6. On run start, when `graph-mode=graph`, seed the graph: write `kind:"premise"` node(s) from the
   macro goal and a single `kind:"goal"` node. Reuse the existing decomposition
   (`web_dashboard.decompose_goal` / `terminal_dashboard.decompose_macro_goal`) **only to seed an
   initial frontier of subgoals**, not to fix the whole plan.

**Validation to implement (`tests/test_logic_graph.py`, under `rules`):**
- **Round-trip & API:** `add_node`/`get_node`/`update_node`/`frontier`/`nodes_by_*` correctness;
  `to_mermaid()` smoke.
- **Atomic write / no torn reads:** a writer thread rewrites a node ~1000× with growing content while
  a reader loops `load_json`; assert the reader **never** gets `None`/parse error and always a valid
  dict (proves temp+`os.replace`).
- **Concurrent node creation (no lost creates):** spawn K threads/processes each `add_node` distinct
  nodes; assert all K files exist and parse afterward.
- **No lost updates across nodes:** K writers each `update_node` a *different* node concurrently;
  assert every update persisted.
- **Monitor-only guard:** calling `merge_nodes`/`prune_branch` outside the monitor no-ops + logs;
  inside, a merge reparents dependents and leaves **no dangling edge** (assert via `validate_graph()`).
- **Merge interrupt recovery:** simulate a crash partway through `merge_nodes` (e.g. survivor written,
  losers not yet marked); assert `validate_graph()` flags it and `repair_graph()` restores integrity.
- **`validate_graph()` catches:** an injected cycle, a dangling `depends_on`, two goal nodes, an
  illegal status, a `validated`→`refuted` dependency, an orphaned in-flight node, and a corrupt
  snapshot — each must appear as a violation; a clean graph returns `[]`.

**Acceptance:** `--graph-mode graph` seeds premises+goal+initial frontier; `frontier()` returns the
open subgoals; `validate_graph()` returns `[]` on a healthy graph and flags each injected violation;
the snapshot is atomic and never corrupt under concurrent writers; linear mode and all 15 existing
test files unaffected.

### Phase 2 — The propose/validate loop

**Goal:** replace "consume the next predefined step" with "propose a step, then validate it before
committing." This is the heart of the harness.

Refactor `AgentRunner.execute_step` (~`agent_runner.py:1031`). Keep the linear branch intact; add a
graph branch gated on `--graph-mode graph`:

1. **Pick a target.** If the agent has no `active_node_id`, choose an open node from
   `logic_graph.frontier()` (prefer nodes in the agent's `approach`; if none, the lead assigns one).
2. **Propose** (Proposer role). Build a fresh, tight prompt — *only* the goal, the chosen frontier
   node's `claim`, and its validated ancestors (NOT the whole history; mirror the reset-context
   discipline in `heal_file`, `agent_runner.py:791`). Ask the model for the **single next atomic
   step**: a new `claim`, `justification`, `depends_on`, and a proposed `oracle.spec`. Write it as a
   `status:"proposed"` node via `logic_graph.add_node`.
3. **Validate** (Validator gate). Run the node's oracle (Phase 4). On pass → `status:"validated"`,
   advance `steps_completed`/`progress` (progress counts **validated** nodes only — preserve the
   §13 rule). On fail → enter the self-healing loop (reuse `run_verification_loop`); if still
   failing after `MAX_HEAL_ATTEMPTS`, mark `status:"refuted"`, emit a gravestone (Phase 6), release
   the node, and let the agent pick a different frontier node.
4. **Role split.** Add `role_mode`. A `proposer` does steps 1–2 and leaves nodes `proposed`; a
   `validator` polls for `proposed` nodes in its approach and runs step 3. In small swarms one agent
   can do both (set `role_mode` per agent at design time / via the lead). The split is what lets a
   strict validator filter a weak proposer.
5. **Rules fallback.** Under `rules`, "propose" = take the next seeded subgoal; "validate" = run the
   shell oracle if present else pass. This keeps tests deterministic.

**Acceptance:** in graph mode, an agent proposes a node, the validator transitions it to
`validated`/`refuted`, progress advances only on validation, refuted nodes are released, and a
multi-node validated path can form. New `tests/test_propose_validate.py` covers propose→validate→
commit and propose→refute→gravestone under `rules`.

### Phase 3 — The Judge as a first-class role

**Goal:** unify the three adjudication jobs into one **local-first** Judge, replacing the
"coding agents" framing of `perform_negotiation`.

1. Create `judge.py` (or an `AgentRunner` mixin) exposing:
   - `validate_step(node) -> {valid: bool, reason}` — LLM-as-judge for steps with
     `oracle.type == "checker_model"` (Phase 4), and the final say when a shell/numeric oracle is
     ambiguous.
   - `resolve_collision(collision) -> {action, reason}` — generalize `perform_negotiation`
     (`agent_runner.py:1505`). Replace the prompt's "two autonomous coding agents" with the
     logic-step framing, and **add `share` and `merge`** to the action set (today only
     `kill_a|kill_b|keep_both`; see Phase 5).
   - `rank_branches(leaves) -> ordered` — move/relabel `proximity_monitor.rank_leaf_agents_llm`
     so the Judge ranks branches for pruning (Phase 6) by *promise of the logic*, not just
     steps-completed.
2. **Model selection:** add `--judge-model` / `--judge-provider` (default: detect the largest local
   Ollama model; fall back to the swarm's `--ollama-model`). Centralize this in one
   `select_judge_model()` helper. **No remote-API escalation path** (invariant #4).
3. Wire `execute_step`'s validate gate (Phase 2) and `monitor_loop`'s collision/prune steps to call
   the Judge.
4. Log every Judge decision to the causal trace (`causal_tracer.log_*`) and as a `thought_trace` of
   type `decision` so it surfaces in the UI's Judge's Feed.

**Acceptance:** collisions resolve via the Judge with logic-step prompts and can return `share`/
`merge`; step validation can defer to the Judge; branch ranking uses the Judge; `select_judge_model`
picks a local model and never a remote one. Extend `tests/test_v2.py`/add `tests/test_judge.py`
(under `rules`, the Judge uses the existing deterministic rules).

### Phase 4 — Pluggable validation oracle

**Goal:** make validation work for proofs, not just code. Generalize `run_verification`
(`agent_runner.py:773`).

1. Define an oracle dispatch keyed on `node.oracle.type`:
   - `shell` — existing behavior: run `oracle.spec` in the workspace (code/tests/compilers).
   - `numeric` — evaluate a Python expression / script that returns truthy (e.g. verify a Collatz
     identity over a range). Sandbox with the existing `subprocess` pattern + timeout.
   - `symbolic` — optional: shell out to `sympy` if available; otherwise downgrade to
     `checker_model`.
   - `checker_model` — ask the Judge (Phase 3) to verify the single inference, with a strict rubric
     and a fresh context. Reserve for steps no executable oracle can check.
   - `none` — unverifiable; node stays `under_review` and never counts toward a validated path
     (and is flagged in the UI).
2. Keep the self-healing loop (`run_verification_loop`) as the retry wrapper for `shell`/`numeric`.
   For `checker_model`, "healing" = re-propose (back to Phase 2 step 2), not patch-in-place.
3. Make tasks/nodes actually *carry* an oracle. (Reminder: no current `mock_tasks.json` step has a
   `verification` field — seed oracles when proposing nodes, and add at least one demo task with a
   shell oracle for tests.)

**Acceptance:** a node with a `numeric` oracle validates by execution; a `checker_model` node
validates via the local Judge; a `none` node is correctly excluded from completeness.
`tests/test_oracles.py` covers each type under `rules`/offline (numeric runs; checker_model uses the
rules stub).

### Phase 5 — Proximity over logic steps

**Goal:** make the team's peripheral vision operate on what agents are *currently reasoning about*,
and add **share/merge** outcomes.

1. In `proximity_monitor.calculate_proximity` (~L191), include the agents' `active_node_id` **claim
   text** in the goal-similarity term (today it uses goal text + files + tools). The phase weighting
   (`classify_phase`, L136) already shifts weights — extend the phase set to the design's
   `Planning | Exploring | Validating | Synthesizing`.
2. When a collision fires, the Judge (Phase 3) may now return:
   - `stop` — the behind agent yields (existing kill semantics, but reframed: free its budget).
   - `share` — call the existing `share_knowledge_files` (`agent_runner.py:1879`) and resume both.
   - `merge` — fold two `proposed` nodes on the same claim into one (graph op in `logic_graph.py`),
     reparent dependents, and continue with the survivor.
3. Add `similar_open_nodes()` as a **pre-proposal dedup**: before proposing, an agent checks whether
   a near-identical open node already exists; if so it joins/validates that node instead of creating
   a duplicate.

**Acceptance:** two agents converging on the same claim trigger a collision that can resolve to
`share` or `merge` (not only kill); a duplicate proposal is suppressed by `similar_open_nodes`.
Extend `tests/test_proximity.py` / `tests/test_monitor.py`.

### Phase 6 — Divergence, gravestones, quotas

**Goal:** make the swarm explore *different* approaches, record dead ends, and stay bounded. These
mostly exist — re-point them at the graph.

1. **Hiring (divergence).** `evaluate_isolation_spawn` (`agent_runner.py:495`) already fires on
   semantic isolation (TF-IDF < 0.35) or novelty (episodic < 0.5). Change the spawn so the child is
   seeded with a **new `approach` id** and a frontier node in a different region — i.e. it opens a
   *distinct branch*, not a parallel copy. Keep spawn approval gating (`handle_spawn_requests`).
2. **Gravestones.** Today tombstones cover dead files/tools and pruned agents
   (`check_tombstones`/`check_pruned_tombstones`, `tombstones.json`). Add: when a node is `refuted`
   or a branch is abandoned, write a gravestone with `{approach, claim, reason}` so other agents
   skip that line (consult it in the Proposer prompt, Phase 2). Surface as the skull state on the
   tree (Phase 9).
3. **Quotas.** `--budget` + `get_active_leaf_agents` + Judge `rank_branches` (Phase 3) already gate
   concurrency. Confirm the two invariants from `design_doc.md` §14: **leaf-only** pruning (never an
   internal node others depend on) and **never extinct** (consensus gate forces one survivor,
   `evaluate_consensus_gate`).

**Acceptance:** isolation/novelty spawns open a new `approach` branch; refuted nodes and dead
branches produce gravestones that later proposers avoid; pruning stays leaf-only and never kills the
last branch. Extend `tests/test_collatz_research.py`, `tests/test_spawn_lifecycle.py`.

### Phase 7 — Hierarchy, consensus, cascading kills

**Goal:** scale to big problems and define "done" for the graph. Mostly exists; adapt.

1. Keep three-tier scaling (`supervisor.py` sub-swarms, `evaluate_sub_swarm_completion`). Map a
   sub-swarm to an `approach`/sub-DAG.
2. Redefine the consensus/completeness gate (`proximity_monitor.evaluate_consensus_gate`, L348) in
   graph mode as: **a sub-goal is complete iff `logic_graph.validated_path_to_goal()` exists for its
   region AND the Judge approves the synthesis.** Preserve "never extinct."
3. Keep `run_cascading_kills` (L416): terminating a parent terminates running children; ensure it
   also releases their `active_node_id`s back to the frontier (don't orphan in-flight nodes).

**Acceptance:** a (sub-)goal flips to complete only when a validated path exists and the Judge signs
off; cascading kills release nodes; extinction is impossible. Extend
`tests/test_hierarchical_scaling.py`.

### Phase 8 — Observability artifacts

**Goal:** emit the run's results as standalone, readable artifacts (the real deliverable), beyond
the live UI.

1. `logic_graph.to_artifact_json()` → `.proximity_swarm/graph/run_<ts>.json` (full graph + validated
   path + cost). `to_mermaid()` → a Markdown file with the proof/plan DAG (reuse
   `causal_tracer.save_mermaid_markdown` conventions).
2. Extend `causal_tracer` edges to include `propose`, `validate`, `refute`, `share`, `merge` (it
   already has spawn/step/collision/takeover/state-transition).
3. Episodic memory (`memory_store.save_episode`): on run end, store the validated subgraph summary,
   gravestones, and a reflection so future runs recall them (`query_similar_episodes` already feeds
   `load_historical_context` and the novelty check).

**Acceptance:** a finished run writes a graph JSON + Mermaid file readable without the server; the
causal trace contains propose/validate/refute edges; the episode is queryable next run.

### Phase 9 — The Logic Exploration Harness UI

**Goal:** build the dashboard specified in `harness_design_document.md` — **Branches rail ·
Exploration Tree ⇄ Timeline · Judge's Feed**, *no file editor*. This visualizes Phase 8 artifacts.
Follow the frontend architecture in §7 and the locked decisions in `harness_design_document.md` §5.1.

The shell (activity bar, blue status bar, command bar, 3-zone grid, on-demand Inspector and
Activity/Logs drawer) is **already built and merged**. Remaining work, in order — each is a small,
browser-verifiable commit:

1. **Center stage: Exploration Tree ⇄ Timeline toggle.** Add `UIState.stageView`
   (`tree|timeline`, default `tree` when `agents.length>1` else `timeline`) and a `toggle-stage`
   dispatcher case. Render the **search graph** from the logic graph (nodes = steps, solid edges =
   `depends_on`/spawn, dashed amber + ring = collision). Node fill: green=validating, amber=syncing,
   gray=idle, ✓=validated, **skull=gravestone**. Attention rings: blue=needs input,
   orange=prune candidate. Reuse/relabel the existing `renderClustersTab` map machinery
   (boundary hulls `drawBoundaries`, `calculateAgentDistance`); add parent→child arrowheads and the
   rings. Add a legend.
2. **Right panel: the Judge's Feed.** Replace the code editor. On node select, stream the Judge's
   evaluation of that step (valid/invalid + reason), collision resolutions, and prune
   recommendations — sourced from the node's `oracle.result` + the agent's `decision` thought
   traces. Remove the Workspace/Editor activity-bar entries and the multiplayer-cursor code.
3. **Inspector (slide-over):** sub-tabs **Overview** (hypothesis + similarity), **Quotas**,
   **Trace** (`/api/trace/<id>`), **Memory (Gravestones)** (`/api/memory`). Single-click focuses;
   double-click / details icon opens it (decision in `harness_design_document.md` §5.1).
4. **Activity/Logs drawer:** pending spawn approvals (hiring), blocker/collision resolutions, prune
   candidates, new gravestones, `monitor.log`. Opened from the status-bar `K decisions` / `Logs`.
5. **Init modal:** one "Initialize Swarm Task" modal — goal, provider (swarm + Judge), segmented
   quota presets (Small/Medium/Large = 5k/20k/50k) with an Advanced exact-tokens reveal, and the
   agent designer as an expandable section.
6. **New backend route** (only one likely needed): `GET /api/graph` returning
   `logic_graph.to_artifact_json()` for the tree; everything else reuses existing routes (§7.4).
   Backend route changes require a server restart (static edits do not).

**Acceptance:** the dashboard matches `harness_design_document.md` §3 with `--llm-provider rules`,
zero console errors, SSE re-render intact, and the coverage map in `harness_design_document.md` §7
all reachable. Verify against `user_journeys.md` and `user_journeys_collatz.md`.

### Phase 10 — Headless harness surface & benchmarking

**Goal:** make it a *research tool* you can script and compare models with.

1. **Run spec file.** A declarative `run.json` / `run.yaml`: `{ goal, premises, oracle defaults,
   budget, swarm_provider+model, judge_provider+model, seed_roles[], graph_mode }`. Add
   `supervisor.py --run-spec run.json` that loads it instead of CLI flags. Makes experiments
   reproducible and diffable.
2. **Headless CLI.** Ensure a full run works with no UI and prints/streams progress + writes the
   Phase 8 artifacts. (`cli.py` / `run_swarm_research.py` are the entry points to extend.)
3. **Cross-model benchmark.** A thin driver that runs the same run spec across several local models
   (e.g. `gemma4`, `llama3`, `qwen2`) and reports **amplification**: validated steps, dead ends
   mapped, validated-path reached?, and cost — the core research output.

**Acceptance:** `supervisor.py --run-spec run.json` reproduces a run headlessly and emits artifacts;
the benchmark driver produces a comparison table across ≥2 local models.

### Phase 12 — Garbage Collection and Memory Bounding

**Goal:** implement automatic cleanup systems for the logic graph, physical workspace, and episodic
memory so the agentic framework can execute long-running headless benchmarks without storage bloat.
Every deletion surface has explicit safeguards — the swarm must never destroy user data.

#### 12.1 Episodic Memory Database (auto, low risk)

Add `enforce_memory_limit(max_episodes=500)` to `memory_store.py`. Call it at the end of
`save_episode` so the SQLite DB self-prunes with FIFO eviction (oldest rows deleted first). The cap
is configurable via `--memory-limit N` on `supervisor.py` so the operator can raise or lower it.

**Safeguards:**
- Only internal vector embeddings / reflections are deleted — no user files involved.
- Configurable cap avoids one-size-fits-all surprises.

#### 12.2 Logic Graph Disk State (auto on teardown, low-medium risk)

The `.proximity_swarm/graph/` directory produces one JSON file per node. Add
`logic_graph.garbage_collect_post_run()` which:

1. Reads all `node_*.json` files and compiles them into `snapshot.json`.
2. **Archives** the individual node files into a timestamped `.tar.gz`
   (e.g. `graph_archive_2026-06-28T12-00.tar.gz`) inside `.proximity_swarm/graph/archives/`.
3. **Integrity-verifies** the snapshot by reading it back and confirming the node count matches.
4. Only *then* deletes the individual `node_*.json` files.

Call this during the engine teardown phase in `supervisor.py`.

**Safeguards:**
- **Archive-before-delete:** node data is always recoverable from the `.tar.gz`.
- **Path containment:** the GC function is hardcoded to only touch files matching the glob
  `node_*.json` inside `GRAPH_DIR`. It never touches `snapshot.json`, archives, or anything else.
- **Integrity check:** if the round-trip verification fails, the GC aborts and logs an error
  without deleting anything.

#### 12.3 Workspace Files and Tombstones (opt-in only, HIGH risk)

The tombstone system records `file_path` strings that originated from agent-generated code. A naive
`os.remove(tombstone["file_path"])` could delete files outside the workspace if an agent
hallucinated or produced a path-traversal string (e.g. `../../../important_file.py`). Therefore
workspace file cleanup is **opt-in only** and heavily guarded.

Build `cleanup_workspace()` (in a new `gc.py` module or `causal_tracer.py`) that:

1. Reads `tombstones.json` and iterates through tombstones of type `file`.
2. Resolves each path with `os.path.realpath()` and asserts it `.startswith(WORKSPACES_DIR)`.
   If it resolves outside `.proximity_swarm/workspaces/`, **refuse to delete and log a warning**.
3. Writes a `gc_manifest_<timestamp>.json` listing every file that will be deleted — a permanent
   audit trail that survives even after the files are gone.
4. Deletes the files.

**Safeguards:**
- **Opt-in only:** workspace cleanup requires an explicit `--gc-workspace` CLI flag or a manual
  `POST /api/clean` call. It never runs automatically at the end of a benchmark.
- **Path jail:** every resolved path must fall inside `WORKSPACES_DIR`. Paths that escape are
  logged and skipped.
- **Dry-run mode:** `--gc-dry-run` logs what *would* be deleted without calling `os.remove`, so
  the operator can audit before committing.
- **Deletion manifest:** the `gc_manifest_<timestamp>.json` file is written *before* any
  deletions begin, providing a permanent record.

#### Safeguard summary

| Surface | Auto? | Key safeguards |
|---|---|---|
| Memory DB rows | ✅ Auto after `save_episode` | Configurable cap (`--memory-limit`), FIFO eviction, internal data only |
| Graph node files | ✅ Auto on run teardown | Archive to `.tar.gz` first, glob-locked to `node_*.json`, integrity verify |
| Workspace tombstone files | ❌ **Opt-in** (`--gc-workspace`) | Jail to `WORKSPACES_DIR`, dry-run mode, deletion manifest log |

**Acceptance:** episodic memory stays within the configured cap. After a headless benchmark, the
`graph` directory contains only `snapshot.json` + an archive `.tar.gz` (no loose `node_*.json`).
Workspace cleanup only fires with `--gc-workspace`, respects the path jail, and writes a manifest.
Tests in `test_gc.py` cover: memory rotation, graph archive+delete, path-jail rejection, dry-run
mode, and manifest creation.

---

## 7. Frontend architecture reference

*(Carried over from the now-removed UI implementation brief — still accurate for the shell. Use this
when building Phase 9.)* The SPA is framework-free: the Python server serves `static/index.html`,
`static/app.js`, `static/styles.css` **from disk every request**, so the loop is **edit → reload**.
Backend (`web_dashboard.py`) route changes need a restart; static edits do not.

### 7.1 Client state (top of `app.js`)

- `SwarmState` mirrors the server (merged by SSE + `/api/state`): `agents[]`, `collisions[]`,
  `tombstones[]`, `orchestrator{}`, `budget_alert{}`, `logs[]`, `pending_spawns[]`,
  `pending_blockers[]`, `swarm_running`, `macro_goal`, `session_budget`, `predefined_agents[]`,
  `state_hash`. **Add for Phase 9:** `graph` (from `GET /api/graph`).
- `UIState` is client-only view state that must **survive a re-render** (store here, never only in
  the DOM): `activeTab`, `selectedAgentId` (the selection that drives everything), `inspectorOpen`,
  `inspectorTab`, `drawerOpen`, `drawerTab`, `stageView`, cached `traceData`/`memoryData`,
  `designerAgents`.

### 7.2 Render pipeline & dispatcher

- `connectSSE()` merges pushed state and calls `render()` when `state_hash` changes. `render()`
  fans out to per-region render functions; **add new regions to `render()`**, never create a
  parallel update path.
- **All clicks go through one delegated listener** that switches on
  `e.target.closest('[data-action]').dataset.action`. Add behavior by (a) putting
  `data-action="…"` (+ `data-*`) in HTML and (b) adding a `case`. No inline `onclick`.
- `render()` rebuilds DOM via `innerHTML`; **escape dynamic text** with `escapeHtml`/`escapeAttr`;
  reuse `:root` CSS custom properties (`--bg-*`, `--accent-*`, `--text-*`, `--border-*`); the map
  SVG uses `viewBox="0 0 1000 600"` around `cx=500,cy=300`.

### 7.3 Reusable functions (don't rewrite — relocate)

`renderClustersTab` (map: tree, orbital layout, boundary hulls, proximity/collision links, node
colors → the Exploration Tree), `calculateAgentDistance` (similarity), `renderAgentChatTab`
(Timeline), `renderTraceTab`, `renderMemoryTab`, `renderAlertsPanel` (spawn/blocker cards → drawer),
slide-panel pattern (`#agent-edit-panel` + `#slide-backdrop` → Inspector). Helpers: `apiGet`,
`apiPost`, `showToast`, `getMaxLeafTokens`.

### 7.4 REST + SSE endpoints (implemented in `web_dashboard.py`)

GET `/api/state`, `/api/agents`, `/api/agents/<id>`, `/api/workspaces/<id>`, `/api/trace/<id>`,
`/api/memory`, `/api/collisions`, `/api/tombstones`, `/api/logs`, `/api/synthesis`,
`/api/events` (SSE). POST `/api/config`, `/api/run`, `/api/add-agent`, `/api/agents/<id>/preset`,
`/api/agents/<id>/edit`, `/api/agents/<id>/chat`, `/api/approve/<id>`, `/api/reject/<id>`,
`/api/resolve/<id>` (`{choice:1|2|3}`), `/api/prune/<id>`, `/api/budget`, `/api/agents/<id>/budget`,
`/api/budget/redistribute`, `/api/clean` (`{target}`). **Add in Phase 9:** `GET /api/graph`.

---

## 8. Testing strategy

- **Runner:** `python3 -m unittest discover -s tests` (and target one file, e.g.
  `python3 -m unittest tests.test_propose_validate -v`). **No pytest.**
- **Provider:** all engine tests run under `--llm-provider rules` so they are deterministic and need
  no Ollama/network. Every LLM call site you add must have a `rules` branch.
- **Keep green:** the 15 existing files must pass at every commit
  (`test_proximity`, `test_monitor`, `test_v2`, `test_clean`, `test_personalities`,
  `test_artifact_combination`, `test_memory`, `test_hierarchical_scaling`, `test_proximity_weighting`,
  `test_causal_tracer`, `test_self_healing`, `test_collatz_research`, `test_skills_integration`,
  `test_spawn_lifecycle`, `test_tool_calling`).
- **New files by phase:** `test_logic_graph` (1), `test_propose_validate` (2), `test_judge` (3),
  `test_oracles` (4); extend `test_proximity`/`test_monitor` (5), `test_collatz_research`/
  `test_spawn_lifecycle` (6), `test_hierarchical_scaling` (7).
- **Concurrency & storage validation (Phase 1, in `test_logic_graph`):** atomic-write/no-torn-read,
  concurrent node creation (no lost creates), no lost updates across nodes, monitor-only mutation
  guard, merge interrupt → `repair_graph()`, and the `validate_graph()` violation catalogue — full
  list in **Phase 1 → "Validation to implement"**. Because there is no locking, these are the tests
  that prove the storage model is safe; treat them as release-blocking.
- **`validate_graph()` is a universal assertion.** Any test that runs the engine in `graph-mode`
  must assert `logic_graph.validate_graph() == []` at the end (healthy graph). Add it to a shared
  test helper so every graph test enforces it.
- **Frontend** has no unit tests — verify in a browser (zero console errors; SSE re-render intact)
  and against the user-journey docs.

---

## 9. Smallest-safe-commit discipline

- Do phases **in order**; each leaves the app working and tests green. Commit per phase:
  `feat(engine): phase N — <summary>` / `feat(ui): phase 9.x — <summary>`.
- Within a phase: data model → `rules` path → LLM path → tests → wire into monitor/UI.
- Never break the **file-state contract** or the **`rules` offline path**. Keep `--graph-mode
  linear` working until Phase 9 so you always have a known-good fallback.
- The design owner edits these docs directly and prefers **local-only** models for the Judge — when
  in doubt about model routing, choose local and ask before adding any remote escalation.

---

## 10. Glossary

- **Logic step / node** — one atomic claim+justification with dependencies; the unit of agent work.
- **Logic graph** — the DAG of nodes; the shared artifact and the deliverable.
- **Approach / branch** — a distinct line of attack on the goal; the team runs several at once.
- **Proposer** — agent that generates candidate next steps (creative, error-prone).
- **Validator** — agent/gate that checks a proposed step against an oracle (cheap, reliable).
- **The Judge** — the local-first adjudicator: validates ambiguous steps, resolves collisions
  (stop/share/merge), and ranks branches for pruning.
- **Oracle** — how a step is validated: `shell` (code), `numeric`/`symbolic` (math),
  `checker_model` (LLM-as-judge), or `none`.
- **Gravestone / tombstone** — a recorded dead end (refuted step, dead branch, pruned agent) other
  agents avoid.
- **Hiring** — spawning a child to open a new approach when isolated or novel.
- **Quota / budget** — the active-agent / token cap that bounds combinatorial exploration.
- **Consensus / completeness gate** — a (sub-)goal is done only when a validated path exists and the
  Judge approves; also guarantees the swarm never goes extinct.
- **Harness** — the headless engine + CLI/API + artifacts (the product); the dashboard is an
  optional observability lens.

---

## 11. Resolution log

Closed items, kept as a short record only — full detail is in git history and the prior revisions of
this section. **Do not re-fix these.**

- **Defects A–H** — instant false-completion (A), post-run GC eating the graph (B), goal/roles never
  reaching the swarm (C), `WORKSPACE_DIR` NameError (D), benchmark status-string mismatch (E),
  inverted propose edges (F), leftover debug print (G), unconditional GC (H).
  **Fixed in commit `0507ee7`; verified 2026-06-29** (101/101 unit tests pass; original symptoms
  absent from a live run).

- **Regressions R1–R4** — infinite relaunch hang (R1), isolation-spawn storm (R2), no validator ever
  assigned (R3), duplicate node ids (R4).
  **Fixed in commit `417b845`; verified 2026-06-29** by a headless `rules` end-to-end run:
  terminates cleanly in ~2.2 s ("Goal proven", safety caps **not** triggered), Agent 001 launched 2×
  (was 29), 1 active agent / 0 isolation-spawns, artifacts written (no `WORKSPACE_DIR` error), 17
  **unique** node ids, `validate_graph()` returns `[]`, `validated_path` length 17. The benchmark
  (`python3 benchmark_driver.py --spec example_run.json --models rules`) reports
  `Success=Yes, Nodes=17, Valid=17, Dead=0`.

How the fixes landed (for reference): graph agents now reach a terminal `completed` status + the
supervisor has a goal-proven global stop and `MAX_RELAUNCHES`/`MAX_TOTAL_DURATION` safety caps (R1);
`evaluate_isolation_spawn` is gated to linear mode only, plus monitor budget enforcement/pruning
(R2); default `role_mode` is `"both"` so a solo agent proposes *then* validates (R3);
`logic_graph.next_node_id()` allocates uuid-based ids (R4).

- **Open problems O1–O2** — the propose/validate/judge/oracle steps were stubs (`"LLM Proposed
  claim"`, `echo ok` oracles, judge always `valid:True`), so no reasoning happened and nothing could
  be refuted. **Fixed in commit `efc8177`; verified 2026-07-06** by a live `gemma4:latest` run:
  proposed nodes carry genuine model-generated Collatz claims with model-chosen oracles, the Judge
  issues real LLM verdicts, and one node was **refuted** in the wild (`Dead > 0` is reachable).
  `resolve_collision` and `rank_branches` are also LLM-backed now; graph-mode self-healing exists
  (but see N3 — it heals the wrong thing).

---

## 12. Open problems (BLOCKING)

> **Status (2026-07-06).** O1/O2 are fixed — the model genuinely proposes and judges. But the swarm
> **still cannot complete a meaningful real-model run**: an `ollama` run of `example_run.json` is
> killed by a hardcoded 120s safety cap after ~2 propose cycles (`Success=No`, 4 nodes), while the
> completion criterion is so weak that any run that *does* validate a single child instantly
> "proves" the goal. Every item below was **reproduced and verified** against the code and live
> runs on 2026-07-06 (line numbers approximate; grep the quoted snippet if drifted). Fix order:
> **N2 → N1 → N7 → N3 → N5 → N4 → N6** (N2 first — otherwise fixing N1 just makes false success
> faster).

### Reproduction (the ground truth)

```bash
rm -rf .proximity_swarm
python3 supervisor.py --run-spec example_run.json          # real gemma4 run
```

Observed (121 s wall): `[Supervisor] Safety Guard: Swarm execution exceeded max duration of 120s.
Terminating.` — final graph has **4 nodes** (goal `proposed`, premise, 1 lemma `proposed`,
1 lemma `refuted`), `validated_path: None` → `Success=No`. The lemma claims are genuine
model-generated Collatz statements (O1 works). Agent state after the run shows **no
`output_tokens` key** despite ≥3 LLM calls (N7). Separately, an isolated check of the supervisor's
promotion logic: seed `goal_0 ← lemma_1("2+2=4", validated)` → `evaluate_sub_swarm_completion()`
promotes the goal to `validated` and reports "completed via graph validation" (N2).

---

### N1 — hardcoded 120s wall-clock cap kills every real-model run [BLOCKER]

**Symptom.** Any `ollama` run dies at exactly ~120 s with the Safety Guard message, mid-validation,
regardless of progress or budget. With gemma4 a single simple call measures ~4.7 s, and a full
propose→judge cycle (long prompts + cold model load + `step_delay=2.0` sleeps + agent relaunch
overhead) lands at ~40–60 s — so the cap allows **~2–3 graph events total**, never enough to
validate even one lemma chain.

**Where.** `supervisor.py:275-276` — `MAX_RELAUNCHES_PER_AGENT = 10`, `MAX_TOTAL_DURATION = 120`
(hardcoded, introduced as the R1 safety cap; correct as a guard, wrong as the *only* effective
bound).

**Root cause.** The R1 fix assumed `rules`-speed agents. The intended resource bound — the run
spec's `budget: 20000` tokens — never binds because token accounting is broken (N7), leaving the
wall clock as the sole limiter.

**Fix.** Make the cap configurable: read `max_duration_seconds` (and `max_relaunches`) from the run
spec / CLI, defaulting to something provider-aware (e.g. 120 s for `rules`, 30–60 min for `ollama`),
and treat the **token budget as the primary bound** once N7 lands. On cap expiry, still emit
artifacts (already the case) but exit with a distinct "budget/time exhausted" status rather than
"completed successfully".

**Verify.** An `ollama` run with `max_duration_seconds: 1800` runs past 120 s and completes ≥5
propose/validate cycles; a `rules` run still terminates in seconds; the exhausted-cap exit is
distinguishable from genuine completion in the output and artifacts.

### N2 — one validated child "proves" the goal (completion criterion is fake) [BLOCKER]

**Symptom.** The moment the goal node's `depends_on` list is non-empty and all entries are
`validated`, the supervisor promotes the goal itself to `validated` and declares victory. Since the
first proposal becomes the goal's only dep, **one validated lemma of any content completes the
run**. Verified in isolation: a goal "Prove the Collatz Conjecture for n <= 10" with a single
validated child claiming **"2+2=4"** is promoted to `validated`, and
`validated_path_to_goal()` returns `['premise_0','lemma_1','goal_0']`. This is also why the `rules`
benchmark's `Success=Yes` is meaningless.

**Where.** `supervisor.py:60-65` (`evaluate_sub_swarm_completion`) — the auto-promotion loop
(`if deps and all(... == "validated") → update_node(goal, status="validated")`). `grep -n
"consensus\|judge" supervisor.py` shows **no** judge/consensus involvement anywhere in the
supervisor: the plan's completeness gate (§4.9, Phase 7 — "validated path exists **AND** the Judge
approves the synthesis") was never wired in.

**Root cause.** Promotion conflates "the goal has some validated support" with "the validated
support *entails* the goal". Nothing ever checks the goal's own claim.

**Fix.**
1. Before promoting, require a **Judge sign-off on entailment**: call `judge.validate_step` on the
   goal node with a rubric of the form "Given these validated claims (list children + their
   justifications), do they jointly establish: <goal claim>? Answer valid=true only if the chain is
   complete." Seed the goal with `oracle: {type: "checker_model", spec: <entailment rubric>}` so
   this flows through the normal validator machinery.
2. Additionally require a minimum structure before consulting the Judge (e.g. the frontier under
   the goal is empty — no open sub-claims remain) so a lone first lemma can't trigger the check.
3. Keep the `rules` path deterministic: under `rules`, promotion may stay as-is so existing tests
   pass, but gate that behind `provider == "rules"`.

**Verify.** The isolated "2+2=4" seed **no longer** promotes the Collatz goal; a `rules` run still
completes; an `ollama` run only reports Success when the Judge explicitly approves the entailment
(visible as a `judge_validate` decision on `goal_0` in the causal trace).

### N7 — token accounting is lost to a write race → budgets never bind [HIGH]

**Symptom.** After a 121 s `ollama` run with at least 3 LLM calls, the agent's state JSON contains
**no `output_tokens` key at all**. The monitor's budget/pruning logic therefore sees 0 tokens
forever, and the run spec's `budget: 20000` can never terminate or prune anything (which is why
N1's wall clock is the only limiter).

**Where.** `agent_runner.py:31-43` (`_accumulate_tokens`) vs. the agent's own state saves.
`_accumulate_tokens` does a read-modify-write of the state **file** (`load_json → +tokens →
save_json`), but the agent holds `self.state` **in memory** and calls
`save_json(self.state_file, self.state)` at the start of every step and after every graph action
(the "start-of-step state save" in `execute_step`, and the `active_node_id`/`role_mode_active`
saves in `execute_step_graph`). Any in-memory save after an LLM call **clobbers** the token
increment — the exact lost-update pattern §4.4 documents for `tombstones.json`, now on the budget
path.

**Fix.** Accumulate tokens **in the runner's memory** instead of the file: record token counts into
the `AgentRunner` instance immediately after each LLM call (`self.state["output_tokens"] =
self.state.get("output_tokens", 0) + n`, before any save) and delete the disk-side
read-modify-write. The agent is the only writer of its own state file, so this is race-free and
~10 lines.

**Verify.** After an `ollama` run, `agent_001.json` shows a non-zero, plausibly-sized
`output_tokens`; setting a tiny budget (e.g. `budget: 500`) causes the monitor to prune/terminate
on token exhaustion — without the wall-clock cap firing.

### N3 — self-healing rewrites the oracle until it passes (validator edits the test) [HIGH]

**Symptom / risk.** When a `numeric` oracle fails, the "self-healing" loop writes the oracle spec
into `check_<node>.py`, asks the LLM to **fix that file** until the check exits 0, then **persists
the rewritten spec back into the node** (`update_node(active_node_id, oracle=node_oracle)`). The
artifact being healed *is the validation check itself* — the model can (and eventually will) weaken
`assert`s until they pass, then the node validates against a check it wrote to satisfy itself.
Validation loses all teeth. (It may also explain verdicts that don't track truth: the live run
refuted a Collatz statement that is *actually true* for n ≤ 10.)

**Where.** `agent_runner.py:1461-1510` — the `if not passed and ... node_oracle_type in ["shell",
"numeric"]` heal block; the spec-persist at ~1496-1510.

**Root cause.** §13's self-healing was designed to heal the **artifact under test** (code) with the
verification command held fixed. In graph mode the numeric oracle has no separate artifact, so the
heal loop was pointed at the check itself.

**Fix.** Never heal the oracle. For `numeric`/`symbolic` failures: refute the node (or send it back
to `proposed` for one re-propose with the failure as context — re-proposal, not in-place edit), and
keep the original spec immutable on the node. Reserve healing for `shell` oracles **only when** the
failing artifact is a workspace file distinct from the oracle command (the coder persona). Drop the
spec-persist entirely.

**Verify.** A node whose numeric oracle is genuinely false (e.g. `assert 2+2==5`) ends `refuted`
with its **original** spec intact in the node file; a regression test asserts the oracle spec is
byte-identical before/after a failed validation.

### N5 — shell oracles are unsatisfiable in graph mode (no artifact step) [MEDIUM]

**Symptom.** In graph mode no step ever writes a solution artifact to the workspace, but the
proposer prompt offers `shell` oracles like `pytest tests/test_math.py`. Such a command references
files that don't exist → the oracle always fails; the heal fallback then guesses a target file as
`existing_files[0]` or a hardcoded `solution.py` (`agent_runner.py:1470-1485`) while the command
still references the missing path — unwinnable, so every `shell` proposal burns heal attempts and
refutes.

**Fix.** Either (a) for research/proof runs, steer the proposer prompt to
`numeric`/`symbolic`/`checker_model` only (drop `shell` from the offered list when the goal is a
proof), or (b) implement the coder-persona artifact step: the proposer also returns file contents
to write into the workspace before the shell oracle runs. (a) is a one-line prompt change and the
right scope for now.

**Verify.** An `ollama` proof run generates no `shell` oracles; no heal loop fires against
nonexistent files.

### N4 — Judge configuration is dead; Judge silently = swarm model [MEDIUM]

**Symptom.** `example_run.json` sets `judge_provider: "ollama"`, but nothing reads it. The runner
calls `select_judge_model(getattr(self, "judge_provider", None), ...)` — and **no code ever sets**
`self.judge_provider` / `self.judge_model` (not `AgentRunner.__init__`, not
`supervisor.launch_agent`, no CLI flag). The Judge therefore always falls back to the swarm's own
provider/model (`gemma4`), and `select_judge_model`'s "largest local model detection" is
unimplemented. This defeats the design decision that the Judge runs the **strongest available
local model** (e.g. `gemma-2-27b` on the 64 GB Mac Studio) — currently the weak proposer and its
judge are the same model.

**Fix.** Plumb it through: run spec `judge_provider`/`judge_model` → `supervisor.py`
(`--judge-provider`, `--judge-model` args → `launch_agent` cmd) → `agent_runner.py` argparse →
`AgentRunner.__init__` attributes. Optionally implement largest-local detection in
`select_judge_model` by querying Ollama `/api/tags` and picking the biggest installed model. Keep
the no-remote-escalation invariant.

**Verify.** With `judge_model` set to a second installed model in the spec, causal-trace
`judge_validate` entries show that model; removing the field falls back to the swarm model with a
logged notice.

### N6 — agent output is invisible in supervised runs [LOW]

**Symptom.** A 121 s real run yields ~924 chars of supervisor output and **zero** agent lines
(`PROPOSED`/`VALIDATED`/`REFUTED` never appear) even though the graph proves they happened. Child
runners inherit a pipe with block-buffered stdout and are `terminate()`d (buffer lost); the monitor
is spawned with `stdout=DEVNULL` (`supervisor.py:197-201`). Diagnosing every bug above required
reconstructing events from state files.

**Fix.** Launch runners with `sys.executable, "-u"` and/or redirect each child's stdout/stderr to
`.proximity_swarm/logs/agent_<id>.log` (and the monitor to `monitor_stdout.log`). Cheap, and makes
every future bug report self-evident.

**Verify.** After any supervised run, per-agent logs exist and contain the
PROPOSED/VALIDATED/REFUTED lines matching the graph.

---

### Definition of done for §12

With N1–N7 fixed, on this machine (Ollama + `gemma4:latest`):

- `python3 supervisor.py --run-spec example_run.json` (with a generous `max_duration_seconds`) runs
  **well past 120 s**, completes multiple propose→validate cycles, and terminates on its own — by
  Judge-approved goal entailment, token-budget exhaustion, or the configured cap (each
  distinguishable in output);
- the trivial-entailment hole is closed: a single "2+2=4"-grade lemma **cannot** complete a run;
- `output_tokens` accumulates in agent state and a small budget demonstrably ends a run;
- no oracle spec is ever modified by validation; `shell` oracles don't appear in proof runs;
- the Judge runs the configured (stronger) local model, visible in the causal trace;
- per-agent logs capture the full propose/validate narrative;
- `python3 -m unittest discover -s tests` stays green and `rules` runs remain fast and
  deterministic.
