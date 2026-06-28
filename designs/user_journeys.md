# Proximity Swarm V3 — User Journey Test Specifications

> **Audience:** an autonomous LLM test executor (browser-automation capable) that will
> drive the web dashboard and validate it.
> **Companion docs:** [`harness_design_document.md`](harness_design_document.md) (authoritative UI
> spec; IA rationale in its §5.1), [`design_doc.md`](design_doc.md) (backend/feature spec),
> [`implementation_plan.md`](implementation_plan.md) (how to build the harness).

---

## 0. What these journeys are for

Proximity Swarm coordinates a *swarm* of autonomous LLM agents that fan out across a hard
problem, each pursuing a different line of attack, spawning helpers when they hit a novel
sub-idea, colliding (and negotiating) when two of them converge on the same idea, and dying off
when they hit dead-ends. The **cluster map** is the centerpiece: it is meant to be read as a
**live map of the idea space** — *which approaches are being explored, how they branch, where
they overlap, and which are starved or stuck.*

These journeys exercise the dashboard against two personas:

- **The Researcher** — points the swarm at an open/hard question (e.g. an unproved math
  conjecture) and uses the UI to **watch and steer which ideas get explored.** The objective of a
  test run is **never to solve the problem.** It is to prove the UI faithfully surfaces *what the
  models are thinking and trying*, lets the operator redirect that exploration, and lets them
  read the resulting idea map.
- **The Coder** — points the swarm at a multi-part build task and uses the UI to watch agents
  divide the work, deconflict overlapping files, self-heal failing tests, and assemble a combined
  deliverable.

Every journey states (a) the persona + scenario, (b) **what UI behavior it validates**, (c)
exact actions, (d) expected observations, and (e) an explicit **PASS/FAIL checklist** plus the
**likely cause** when a check fails (so the journey doubles as a debugging aid).

> **Meaning of "validate the UI is working":** a check passes when the **UI surface** reflects
> backend state correctly and reacts to operator input — *not* when the agents produce a correct
> proof or bug-free code. A swarm that explores three wrong ideas but renders them legibly on the
> map is a **PASS** for the UI.

---

## Table of contents

- [1. Test harness setup (shared preamble — read first)](#1-test-harness-setup-shared-preamble--read-first)
- [2. Selector & action reference](#2-selector--action-reference)
- [3. Visual-encoding glossary (how to read the map & timeline)](#3-visual-encoding-glossary-how-to-read-the-map--timeline)
- [4. Timing & liveness model](#4-timing--liveness-model)
- [Journey 1 — Cartographer of a Hard Conjecture (flagship research)](#journey-1--cartographer-of-a-hard-conjecture-flagship-research)
- [Journey 2 — Steering the Search (operator-in-the-loop pivoting)](#journey-2--steering-the-search-operator-in-the-loop-pivoting)
- [Journey 3 — Convergent Minds (redundancy collision & negotiation)](#journey-3--convergent-minds-redundancy-collision--negotiation)
- [Journey 4 — Compute Triage (budget pressure, redistribution & pruning)](#journey-4--compute-triage-budget-pressure-redistribution--pruning)
- [Journey 5 — From Sprawl to Synthesis (coding build + deliverable)](#journey-5--from-sprawl-to-synthesis-coding-build--deliverable)
- [Journey 6 — Institutional Memory (learning across runs)](#journey-6--institutional-memory-learning-across-runs)
- [Appendix A — Cross-cutting validation (run on every journey)](#appendix-a--cross-cutting-validation-run-on-every-journey)
- [Appendix B — Fast deterministic smoke variant](#appendix-b--fast-deterministic-smoke-variant)

---

## 1. Test harness setup (shared preamble — read first)

### 1.1 Do not disturb the operator's instance
The developer keeps a dashboard running on **port 8080** — **do not kill it.** Start a
**throwaway instance on a different port** (e.g. `8095`) for every test session, and stop only
that one when finished.

### 1.2 Provider choice
- **For all "idea exploration" journeys (1, 2, 3, 5, 6): use `ollama`.** It produces real LLM
  thought traces, real spawn decisions, real generated files, and real negotiation text — which
  is exactly what the map/timeline must surface. The model `gemma4:latest` is available locally.
- The **Init modal's provider dropdown only offers local providers like `Ollama` and `MLX`** (`#init-provider`).
  Selecting `Ollama` is correct. (Goal decomposition always calls local Ollama regardless.)
- A **deterministic, no-LLM variant** for pure UI-plumbing smoke tests is in
  [Appendix B](#appendix-b--fast-deterministic-smoke-variant) — use it only to validate wiring,
  not idea content.

### 1.3 Launch the throwaway server
```bash
# from the repo root: /Users/louisye/Desktop/Louis/proximity_swarm
python3 web_dashboard.py --port 8095 --llm-provider ollama --ollama-model gemma4:latest
```
Confirm Ollama is up first:
```bash
curl -s http://localhost:11434/api/tags | grep gemma4   # must return a match
```
The frontend (`static/`) is served from disk per request, so any reload picks up the current
files; **no rebuild step exists.** Backend route changes would need a restart, but tests should
not edit backend code.

### 1.4 Open and reset to a clean slate
1. Navigate the browser to `http://localhost:8095/`.
2. Reset residual state so each journey starts empty. Either:
   - In the command bar (`#command-input`) type `/clean all` and press Enter, **or**
   - Click the **⚙️** gear (`#clean-btn`, `data-action="toggle-clean"`) → **🔥 Clean Everything**
     (`data-action="clean" data-target="all"`).
3. **Readiness gate (must hold before any journey):**
   - `#status-label` reads **`IDLE`** and `#status-pill` has class `status-pill--idle`.
   - `#agent-count` reads **`0`**; the `#agents-empty` empty-state is visible.
   - The **Init overlay** (`#init-overlay`) is **visible** (it auto-shows when
     `agents.length === 0`) and its close button `#init-close-btn` is **hidden**.
   - The blue status bar (`#status-bar`) shows an **`Idle`** dot and `◆ 0 agents`.

If any readiness condition fails, the SPA did not boot or SSE did not connect — see
[Appendix A](#appendix-a--cross-cutting-validation-run-on-every-journey) before continuing.

### 1.5 Executor capabilities assumed
Read the live DOM (query by `id`/`class`/`data-*`), click elements, type into inputs and submit
with Enter, take screenshots, and read console/network. For SVG nodes, target
`.cluster-node[data-agent-id="0XX"]` and click it. Poll the DOM on an interval (the app re-renders
on SSE pushes; there is no need to reload to see updates).

---

## 2. Selector & action reference

The app uses **event delegation on `data-action`**. To "click X," find the element carrying that
`data-action` (and any `data-*` qualifiers) and click it. Stable handles:

### Top bar
| Purpose | Selector / action |
|---|---|
| Status pill / label | `#status-pill`, `#status-label` (IDLE / RUNNING / COMPLETED) |
| Clean menu toggle | `#clean-btn` → `data-action="toggle-clean"`; menu `#clean-menu` |
| Clean a target | `data-action="clean" data-target="logs\|workspaces\|collisions\|tombstones\|memory\|all"` |
| Combined report (synthesis) | `#synthesis-btn` → `data-action="view-synthesis"` |
| New swarm (open Init) | `#launch-btn` → `data-action="open-launch"` |

### Activity bar (far left) & center stage
| Purpose | Selector / action |
|---|---|
| Switch center view | `data-action="switch-tab" data-tab="overview\|clusters\|logs"` |
| Stage Map⇄Timeline toggle | `data-action="toggle-stage" data-stage="map\|timeline"` |
| Map canvas / SVG | `#cluster-svg-parent`, `svg.cluster-svg` |
| A node | `g.cluster-node[data-agent-id="0XX"]` (single-click = select, double-click = inspector) |
| Node circle / boundary / edge / link | `.cluster-node-circle`, `.cluster-boundary`, `.cluster-edge`, `.cluster-link`, `.cluster-link--collision`, label text `.cluster-link-label` (`d:0.NN`) |
| Map legend | `.map-legend` |
| Cluster detail sidebar | `#cluster-sidebar-content` |
| Timeline scroll container | `#swarm-timeline-scroll`; entries `.thought-trace--<type>`, `.chat-message`, `.decision-card` |

### Agent rail (left)
| Purpose | Selector / action |
|---|---|
| Rail / count / list | `#agent-sidebar`, `#agent-count`, `#agent-list` |
| Select (focus) agent | `data-action="select-agent" data-agent-id="0XX"` |
| Row hover actions | `view-workspace`, `open-inspector` (`data-tab="trace"` or `"overview"`), `prune-agent` |

### Right editor panel
| Purpose | Selector / action |
|---|---|
| Panel / body | `#alerts-panel`, `#alerts-list` |
| File tab | `.editor-tab` → `data-action="select-file" data-file="<path>"` |

### Inspector (slide-in, right)
| Purpose | Selector / action |
|---|---|
| Open / close | `data-action="open-inspector" data-agent-id="0XX" data-tab="..."` / `close-inspector` |
| Panel / title / body | `#inspector`, `#inspector-title`, `#inspector-body` |
| Sub-tabs | `data-action="switch-inspector-tab" data-tab="overview\|budget\|trace\|memory"` |
| Edit agent budget | `data-action="edit-agent-budget"` |
| Redistribute to children | `data-action="redistribute-budget" data-parent-id="0XX" data-strategy="equal\|weighted\|priority"` |

### Bottom drawer (swarm feeds)
| Purpose | Selector / action |
|---|---|
| Open / close | `data-action="open-drawer" data-tab="activity\|logs"` / `close-drawer` |
| Switch tab | `data-action="switch-drawer-tab" data-tab="activity\|logs"` |
| Body | `#drawer`, `#drawer-body` |

### Decision controls (timeline cards & drawer)
| Purpose | Selector / action |
|---|---|
| Approve / reject spawn | `data-action="approve-spawn" data-agent-id="0XX"` / `reject-spawn` |
| Resolve blocker | `data-action="resolve-blocker" data-agent-id="0XX" data-choice="1\|2\|3"` (1=workaround, 2=bypass, 3=kill) |
| Prune agent | `data-action="prune-agent" data-agent-id="0XX"` |

### Init modal
| Purpose | Selector / action |
|---|---|
| Overlay / goal / provider | `#init-overlay`, `#init-goal`, `#init-provider` (`ollama`/`mlx`) |
| Budget preset | `data-action="set-budget-preset" data-preset="small\|medium\|large" data-value="5000\|20000\|50000"` |
| Exact budget (advanced) | `#init-budget` |
| Add / edit / remove designer agent | `add-designer-agent`; `update-designer-role`/`update-designer-goal` with `data-index`; `remove-designer-agent` |
| Launch / close | `#init-launch-btn` → `data-action="init-launch"` / `#init-close-btn` → `close-init` |

### Command bar (`#command-input`, submit with **Enter**)
| Input | Effect |
|---|---|
| `@0XX <message>` | Send chat directive to agent `0XX` (→ PIVOT/ADD_CONTEXT decision) |
| `/budget <N>` | Set global token cap |
| `/prune <id>` | Prune agent |
| `/approve <id>` / `/reject <id>` | Resolve a spawn request |
| `/resolve <id> <1\|2\|3>` | Resolve a blocker |
| `/trace <id>` | Open Trace view for agent |
| `/view memory\|logs\|synthesis\|<agentid>` | Jump to memory/logs/report/workspace |
| `/memory`, `/help` | Memory list / overview |
| `/clean <target>` | Storage cleanup |
| *plain text (not `/`, not `@`)* | Pre-fills `#init-goal` and opens the Init modal |

### Status bar (`#status-bar`) & toasts
State dot (`.status-bar__dot--run\|done\|idle`), `◆ N agents`, `⛁ used / cap` (click → Activity
drawer), `🔔 K decisions` (click → Activity drawer), `⚡ N` collisions, `📜 Logs` (click → Logs
drawer). Toasts appear in `#toast-container` as `.toast--success\|error\|info`.

---

## 3. Visual-encoding glossary (how to read the map & timeline)

**This is the rubric for "is the idea map legible?"** A journey that asks you to "confirm the
ideas are distinguishable" means: confirm these encodings render and decode correctly.

### Map node = one agent = one line of attack
- **Label:** the agent **ID** (`001`…`00N`) inside the circle; below it `Agent 0XX`, the **role
  tag**, a **goal snippet** in quotes, and a `🔋 used/cap (pct%)` budget line. *The role + goal
  snippet are the human-readable name of the idea that branch is pursuing.*
- **Fill color (work state):** green = **exploring**, gray/muted = **idle**, light-blue =
  **completed**. (Budget tint may also apply: green/amber/red ring class on the circle.)
- **Attention ring (what the agent needs from *you*):** **blue ring** = *needs input* (a pending
  spawn/blocker targets it, or it is `syncing`/`pending_termination`); **orange ring** = *low
  budget* (>90% of its cap used).

### Map edges = structure of the idea space
- **Solid arrow (parent → child):** the **spawn tree** — a branch that forked off a sub-idea.
  Drawn with an arrowhead marker.
- **Dashed purple link with a `d:0.NN` label:** a **proximity/redundancy link** between two
  agents whose goals+files overlap (drawn when distance `< 0.85`; thicker/more opaque as they get
  closer). A **collision-class** link (`.cluster-link--collision`) marks an *active* redundancy
  collision the monitor flagged (distance `< 0.5`).
- **Boundary circle labeled `CLUSTER: AGENT 0XX`:** a soft hull around a parent and its children —
  a **sub-swarm** working a shared region of the idea space.

### Timeline thought-trace types (icons)
`evaluating 🔍` · `decision 🎯` · `executing 🔄` · `completed ✅` · `failed ❌` · `spawn 🚀` ·
`syncing ⚡` · `resolved 🤝` · generic `💭`. **These are the verbatim "ideas" the model emits** —
each trace's text is what the agent is thinking/trying at that moment.

### Decision cards
- **Spawn request:** shows the proposed child **goal** + **reason**; Approve/Reject.
- **Blocker:** shows file, tool, error; Workaround / Bypass / Kill.

---

## 4. Timing & liveness model

- The SPA holds a persistent **SSE** connection (`/api/events`). The backend pushes the whole
  `SwarmState` on every mutation; the client re-renders when a `state_hash` changes. **You do not
  reload to see updates** — poll the DOM.
- **Real Ollama runs are not instant.** Goal decomposition is one LLM call per agent; each step is
  another; step delay is ~1.5s; agents run up to 15 steps. Budget **3–10 minutes** for a 3–4 agent
  research run to produce a rich map. Use polling with generous timeouts (e.g. check every 3–5 s,
  up to several minutes) and assert on *state reached*, not on wall-clock.
- **Spawn gating:** isolation/novelty spawns are evaluated **every 5 steps**, and only when an
  agent is semantically isolated (TF-IDF similarity `< 0.35`) **or** historically novel (`< 0.50`).
  Journeys that must demonstrate spawning use **broad, multi-stage, semantically distinct** goals
  to satisfy this gate. If a journey needs a spawn and none arrives organically within the window,
  it provides a deterministic fallback trigger.
- **Collision gating:** the monitor flags a collision when two agents' distance drops `< 0.5`.
  Journeys that must demonstrate collisions deliberately configure **two near-identical goals**.

---

## Journey 1 — Cartographer of a Hard Conjecture (flagship research)

### Persona & scenario
A number theorist points the swarm at the **Collatz Conjecture** ("every positive integer, under
*n→n/2 if even, 3n+1 if odd*, eventually reaches 1"). She does **not** expect a proof. She wants
the dashboard to show her, at a glance, **which distinct attack vectors the models choose, how
those ideas branch into sub-ideas, and where two agents are circling the same idea** — i.e. she
is using the cluster map as a *map of the research frontier.*

### What this journey validates
1. Init modal → multi-agent launch with **custom, semantically distinct roles/goals** (the agent
   designer).
2. The **cluster map renders the idea space**: one labeled node per attack vector, legible role +
   goal snippet, correct state colors, a parent→child branch when a sub-idea is spawned.
3. **Selection propagation**: clicking a node/row updates the cluster detail sidebar, the editor,
   and (on double-click) the inspector — all to the *same* agent.
4. The **Timeline surfaces the verbatim ideas** (thought traces) per agent and globally.
5. **Spawn decision flow**: a pending spawn appears as a card + a blue ring + a `🔔 decisions`
   count; approving it grows a new branch on the map.
6. The operator can **enumerate the explored ideas** from the UI alone.

### Preconditions
Harness setup complete (§1); state clean; Init overlay visible; provider will be `Ollama`.

### Steps & expected observations

**1.1 — Open the designer and configure four distinct lenses.**
- The Init overlay (`#init-overlay`) is already visible. In `#init-goal` enter the macro goal:
  > `Explore strategies to prove or find a counterexample to the Collatz Conjecture (3n+1). Do not assume it is true; survey multiple independent approaches.`
- Set `#init-provider` to **`Ollama`**.
- Choose budget preset **Large (50k)** (`data-action="set-budget-preset" data-value="50000"`).
- Expand **"Configure custom agents (optional)"**. Using `add-designer-agent`, create **four**
  agent rows and fill each (`update-designer-role` / `update-designer-goal` by `data-index`):

  | # | Role | Goal |
  |---|---|---|
  | 1 | `Elementary Number Theorist` | `Attack Collatz via modular arithmetic and residue classes mod 2^k; look for invariants and parity-sequence structure.` |
  | 2 | `Dynamical Systems Analyst` | `Treat the Collatz map as a discrete dynamical system; study cycles, fixed points, and stopping-time behavior.` |
  | 3 | `Computational Verifier` | `Design and describe large-scale numerical verification, counterexample search bounds, and statistical distribution of stopping times.` |
  | 4 | `Analytic / Probabilistic Heuristic` | `Use probabilistic and analytic heuristics (expected drift of log n, density arguments) to argue why Collatz should hold.` |

  > Goals are deliberately **distinct lenses** so the map shows four separate ideas, and broad &
  > multi-stage so the spawn gate (§4) can fire.

**1.2 — Launch.** Click **🐝 Launch Swarm Task** (`#init-launch-btn`, `data-action="init-launch"`).
- *Expected within ~2–5 s:* a `🔄/info` toast ("Initializing swarm task…") then a **success**
  toast; `#init-overlay` hides; `#status-label` → **`RUNNING`** (`status-pill--running`);
  `#agent-count` → **`4`**; status bar dot → **`Running`**, `◆ 4 agents`.

**1.3 — Read the idea map.** Ensure the center is on the **Map** view: activity-bar
`data-tab="clusters"` is active and the stage toggle shows **◆ Map** selected
(`data-action="toggle-stage" data-stage="map"`).
- *Expected as agents start exploring (poll over 30–90 s):*
  - **Four nodes** appear in `#cluster-svg-parent`, each `g.cluster-node[data-agent-id]` = `001`…
    `004`.
  - Each node shows its **role tag** and a **goal snippet** in quotes matching the table above
    (truncated). **This is the core assertion: the four ideas are individually legible on the map.**
  - Nodes are **green** (`node--exploring`) while working; the `.map-legend` is visible and
    explains the encodings.
  - A `🔋 used/cap (pct%)` budget line renders under each node and the % climbs as steps complete.

**1.4 — Drill into one idea via selection.**
- **Single-click** node `002` (`g.cluster-node[data-agent-id="002"]`).
  - *Expected:* node `002` gains `node--selected` (thicker stroke); `#cluster-sidebar-content`
    updates to Agent 002's role/goal and quick actions; the agent rail row for `002` reflects
    selection; the right editor (`#alerts-list`) loads 002's workspace files (or an empty-state if
    none yet).
- Switch to **Timeline** (`data-action="toggle-stage" data-stage="timeline"`).
  - *Expected:* the timeline **scopes to Agent 002** (its chat/thought stream). Confirm at least
    one `.thought-trace--executing` (🔄) and, as steps complete, `.thought-trace--completed` (✅),
    each prefixed `Agent 002:` and containing **substantive, on-topic text** about its dynamical-
    systems approach. *This is the verbatim idea content.*

**1.5 — Read the global idea stream.**
- The **global** interleaved timeline renders only when **no agent is selected**
  (`selectedAgentId === null`). You can clear the selection (deselect) at any time by clicking on the empty map canvas, pressing the `Escape` key, or clicking the **✕ Show all agents** button next to the stage toggle. Switch the stage to **Timeline** while nothing is selected.
- *Expected:* an interleaved, time-ordered stream of thought traces from **all four** agents, each
  tagged with its `Agent 0XX:` author — you can watch four ideas progress in parallel. **Contract
  to validate:** once you single-click any agent, the same Timeline **scopes to that agent**; this
  scoping-on-selection is the intended behavior (the global feed is the unscoped default).

**1.6 — Catch a branch (spawn).**
- Let the swarm run. Within the spawn-evaluation windows (every 5 steps; §4), watch for a
  **spawn request**: a `🔔 N decisions` item appears in `#status-bar`, a `.decision-card--spawn`
  appears in the Timeline (and/or Activity drawer), and the **originating node gains a blue ring**.
  - *Expected card content:* a proposed **child goal** (a narrower sub-idea, e.g. "build a helper
    to tabulate stopping times for n < 10^6") and a **reason**.
- **Approve** it (`data-action="approve-spawn" data-agent-id="0XX"`, or `/approve 0XX`).
  - *Expected:* success toast; `#agent-count` increments to **5**; a **new node** appears on the
    map **connected to its parent by a solid arrow** (the branch); the parent's blue ring clears;
    `🔔` count decrements.
  - **If no spawn arrives within ~3–4 min** (model declined every time): use the deterministic
    fallback — send `@001 This sub-problem is large; spawn a helper agent to handle the modular
    arithmetic tabulation separately.` and continue watching for the card. Record that the organic
    gate did not fire (informational, not a UI failure) but the approve/branch flow still must work.

**1.7 — Enumerate the idea map (the deliverable of this journey).**
- From the map + each node's Timeline/workspace, produce a short table: **for each node →
  {agent id, role, the idea it is pursuing (1 sentence), its current state, any child branch}.**
- *Expected:* you can name **≥3 distinct, non-trivial ideas** and at least **one parent→child
  branch**, sourced entirely from the UI.

### PASS / FAIL checklist
- [ ] Designer accepted 4 custom role/goal rows; launch produced exactly 4 initial agents.
- [ ] Map shows 4 distinct nodes, each with a **legible, correct role + goal snippet**.
- [ ] Node fills track work state (green while exploring; light-blue when an agent completes).
- [ ] Single-click selection propagates to cluster sidebar **and** editor; double-click opens the
      Inspector scoped to that agent.
- [ ] Timeline shows substantive, on-topic, per-agent thought traces with correct type icons.
- [ ] At least one spawn request rendered as a card **and** a blue ring **and** a `🔔` count; approving it added a child node joined to its parent by a solid arrow.
- [ ] You enumerated ≥3 distinct ideas + ≥1 branch **from the UI alone**.

### Likely cause if a check fails
- *No nodes / count stuck at 0:* SSE not connected (check `/api/events` in network) or supervisor
  failed to launch (check Logs drawer / `monitor.log`).
- *Nodes but blank role/goal:* designer rows not captured (the `input` handler binds
  `update-designer-role/goal` by `data-index`; verify indices) or `personality/goal` not threaded
  into agent JSON.
- *Timeline empty while map populates:* `thought_traces` not being read into the timeline, or
  Ollama calls failing (traces would show generic fallback text — check `monitor.log`).
- *Spawn approved but no child node:* `/api/approve` succeeded but supervisor didn't launch the
  child, or the map's parent→child edge (`parent_id`) isn't wired.

### Evidence to capture
Screenshot of the populated 4-node map (with legend); screenshot of the Timeline scoped to one
agent; screenshot of the spawn decision card; screenshot of the map after approval showing the new
branch; the enumerated idea table (text).

---

## Journey 2 — Steering the Search (operator-in-the-loop pivoting)

### Persona & scenario
A researcher is watching the swarm work the **Goldbach Conjecture** ("every even integer > 2 is a
sum of two primes"). One agent is grinding on an approach she judges unpromising. She wants to
**redirect that agent toward a different idea** mid-run and confirm the agent (a) registers her
directive, (b) decides whether to **PIVOT** its goal or merely **ADD_CONTEXT**, and (c) the map +
inspector reflect the new direction.

### What this journey validates
1. The **command bar `@agent` chat path** delivers a directive to a running agent.
2. The agent's **PIVOT vs ADD_CONTEXT decision loop** is surfaced in the Timeline as thought
   traces (`evaluating 🔍` → `decision 🎯`).
3. On **PIVOT**, the agent's **goal updates everywhere** (rail row, map node goal snippet,
   inspector Overview).
4. The **Inspector ▸ Overview/Trace** reflects the redirected line of attack.
5. Subsequent generated work (editor file content / later traces) reflects the new directive.

### Preconditions
Clean state. Launch a **2-agent** Ollama swarm via the Init modal:
- Macro goal: `Survey approaches to the Goldbach Conjecture (every even n>2 is a sum of two primes).`
- Designer agents:
  - `001` — role `Sieve-Based Combinatorialist`, goal `Use sieve methods and prime-counting density to argue every even number decomposes into two primes.`
  - `002` — role `Additive Number Theorist`, goal `Explore additive number theory and circle-method style heuristics for representing even numbers as prime sums.`
- Budget preset **Medium (20k)**. Launch and wait until both nodes are green and each has emitted
  at least one `executing`/`completed` trace (poll ~30–60 s).

### Steps & expected observations

**2.1 — Establish the baseline idea.** Single-click node `001`; switch the stage to **Timeline**;
read its current approach. Open the Inspector for `001` (double-click the node, or
`open-inspector data-agent-id="001" data-tab="overview"`); note its **current goal** verbatim from
`#inspector-body` (Overview tab). Screenshot.

**2.2 — Send a steering directive that should force a PIVOT.** In `#command-input` type and Enter:
> `@001 Stop pursuing pure sieve density bounds — they are too weak here. Pivot to studying the Hardy–Littlewood circle method and major/minor arc estimates instead.`
- *Expected immediately:* a **success toast** "💬 Message sent to Agent 001". (The message is
  written to agent 001's `chat_messages`; the running agent will process it on its next step.)

**2.3 — Watch the decision loop.** Keep the Timeline scoped to `001` and poll (the agent processes
operator messages at the start of its next step — allow up to ~1–2 steps, ~10–30 s).
- *Expected sequence of traces (prefixed `Agent 001:`):*
  1. `.thought-trace--evaluating` (🔍): *"New operator message received. Evaluating implications on
     current goal…"*
  2. A `decision` (🎯) trace (or equivalent) whose text states **PIVOT** and gives 2–3 sentences of
     reasoning that reference the circle method.
- *Also expected:* while the agent is in this state it may show a **blue attention ring** on its
  map node (status transitions such as `syncing`/`pending_termination` raise the ring; a
  mid-processing state may briefly do so).

**2.4 — Confirm the pivot propagated everywhere.**
- Re-open Inspector ▸ Overview for `001`: its **goal text now reflects the circle method**, not the
  original sieve goal.
- On the **Map**, node `001`'s **goal snippet** (in quotes under the node) now shows the updated
  goal (truncated).
- The **agent rail** row for `001` shows the updated goal/role text.
- *Expected:* all three locations agree — **one selection/one source of truth.**

**2.5 — Confirm the work follows the new idea.** Let `001` run 1–2 more steps. Open its workspace
in the right **editor** (`view-workspace data-agent-id="001"`), open a generated file
(`.editor-tab` → `select-file`). *Expected:* the newest file content / latest thought traces
mention circle-method / arc-estimate concepts introduced by your directive — proving the directive
reached the generation prompt, not just the goal label.

**2.6 — Negative control (ADD_CONTEXT).** Send a *non-redirecting* enrichment to the other agent:
> `@002 Also keep ternary Goldbach (odd numbers as three primes) in mind as supporting context.`
- *Expected:* agent `002`'s decision trace chooses **ADD_CONTEXT** (goal **unchanged** in inspector
  + map), and later work merely *incorporates* the note. This confirms the UI distinguishes the two
  outcomes rather than always rewriting the goal.

### PASS / FAIL checklist
- [ ] `@001 …` produced a "message sent" success toast.
- [ ] Timeline showed the `evaluating` → `decision` loop with **PIVOT** and on-topic reasoning.
- [ ] After PIVOT, agent 001's goal changed **consistently** in Inspector, map node snippet, and rail row.
- [ ] New generated content / later traces reflect the redirected idea.
- [ ] `@002 …` enrichment produced **ADD_CONTEXT** (goal unchanged) — the two outcomes are visibly different.

### Likely cause if a check fails
- *No "message sent" toast / error toast:* `@(\w+)` regex didn't match the id format (use 3-digit
  `001`), or `/api/agents/<id>/chat` POST failed.
- *Directive ignored (no evaluating trace):* the running agent isn't re-reading `chat_messages`,
  or the swarm already completed (`COMPLETED` pill) so no further steps run — relaunch with more
  steps/budget.
- *Goal label changes but work doesn't:* directive reached the PIVOT goal but not the generation
  prompt's "HUMAN OPERATOR DIRECTIVES" block.
- *Inspector/map/rail disagree:* selection/source-of-truth desync — `selectedAgentId` not driving
  all three renders.

### Evidence to capture
Before/after Inspector-Overview screenshots of agent 001's goal; the Timeline decision traces;
the map node snippet after pivot; an editor file showing circle-method content.

---

## Journey 3 — Convergent Minds (redundancy collision & negotiation)

### Persona & scenario
The "Git for LLM trajectories" story. A researcher launches **two agents with near-identical
goals** (deliberately, to simulate two members independently chasing the *same* idea). She expects
the swarm to **detect the redundancy (a merge conflict in idea-space), draw it on the map, force a
negotiation, and resolve it** — either by knowledge-sharing or by one branch self-terminating
(overpopulation).

### What this journey validates
1. **Proximity → collision detection** surfaced as a **dashed redundancy link** (with a `d:0.NN`
   distance label) and, when close enough, a **collision-class link** on the map.
2. The status bar **`⚡ N` collision count** and the **Activity drawer** collision feed.
3. **Negotiation**: affected agents enter `syncing ⚡` (blue ring) and emit negotiation thought
   traces, ending in a `resolved 🤝` trace.
4. **Overpopulation resolution**: a redundant agent transitions to `pending_termination` →
   `dead`/pruned (or knowledge is shared and one survives) — visible on the map and in the
   Activity/Tombstones feed.
5. Operator can resolve via the drawer/command bar if prompted.

### Preconditions
Clean state. Launch a **2-agent** Ollama swarm with intentionally overlapping goals:
- Macro goal: `Implement a function to validate email addresses with a regular expression and unit tests.`
- Designer agents (note the **near-duplicate** goals + overlapping target files):
  - `001` — role `Backend Engineer`, goal `Write an email validation function using regex in validators.py with tests in test_validators.py.`
  - `002` — role `Utilities Developer`, goal `Create a regex email validator in validators.py and add unit tests in test_validators.py.`
- Budget preset **Medium (20k)**. Launch.

> Identical target files + synonymous goals drive the pairwise distance below the link threshold
> (`< 0.85`) and then below the collision threshold (`< 0.5`).

### Steps & expected observations

**3.1 — Watch proximity form on the map.** Stage = **Map**. Poll for ~30–90 s.
- *Expected:* a **link** appears between nodes `001` and `002` carrying a **`d:0.NN` label**; as the
  agents touch the same files the distance **shrinks** (label number drops, link thickens/brightens).

**3.2 — Confirm collision detection.** When distance crosses below `0.5` the monitor flags a
collision.
- *Expected:* the link becomes **collision-styled** (`.cluster-link--collision`); the status bar
  shows **`⚡ 1`** (or more); opening the **Activity drawer** (click `📜`/`🔔` or
  `open-drawer data-tab="activity"`) lists the collision between Agent 001 and Agent 002.

**3.3 — Observe the negotiation.** One or both agents transition to **`syncing`**.
- *Expected:* the affected node(s) show a **blue attention ring**; the **Timeline** emits
  `syncing ⚡` traces and negotiation narration (the agents exchanging findings / arguing
  redundancy), concluding with a `resolved 🤝` trace.

**3.4 — Observe the resolution (overpopulation).**
- *Expected one of:*
  - **Self-termination:** the slower/redundant agent transitions to `pending_termination` then
    `dead` — its node leaves the active set / greys out, `#agent-count` decreases, and a record
    appears in the **Tombstones** portion of the Activity drawer; **or**
  - **Knowledge share + survive:** one agent absorbs the other's files (a `resolved` trace notes the
    transfer) and both continue, with the redundancy link clearing.
- If the UI surfaces an explicit prune candidate or termination needing approval (blue ring +
  `🔔`), resolve it: prune via `data-action="prune-agent"` or `/prune 0XX`. *Expected:* success
  toast; node removed; a **pruned tombstone** recorded.

**3.5 — Confirm the conflict cleared.** After resolution the **collision link disappears** (or
downgrades to a plain proximity link), `⚡` count drops, and rings clear.

### PASS / FAIL checklist
- [ ] A proximity link with a `d:0.NN` label rendered between the two agents and the distance shrank over time.
- [ ] A collision was flagged: collision-styled link **and** `⚡` count **and** an Activity-drawer entry.
- [ ] Affected agent(s) entered `syncing` with a blue ring and emitted negotiation traces ending in `resolved`.
- [ ] Resolution occurred (self-termination → tombstone, or knowledge-share survive) and was visible on the map + Activity/Tombstones feed.
- [ ] After resolution, collision link + `⚡` count cleared.

### Likely cause if a check fails
- *No link ever forms:* distance never drops below `0.85` — goals/files weren't similar enough;
  re-launch with **identical** `touched_files` and more synonymous goals.
- *Link but never collision-styled:* distance floored above `0.5`, or `collisions[]` not pushed
  over SSE; check `/api/collisions` and `monitor.log`.
- *Collision but no syncing/negotiation:* monitor flagged it but didn't set agents to `syncing`, or
  the negotiation skill isn't running (check supervisor/monitor logs).
- *Negotiation but node never leaves:* termination/prune path or tombstone write failed.

### Evidence to capture
Screenshot of the shrinking `d:0.NN` link; screenshot of the collision-styled link + `⚡` count;
the Activity drawer collision entry; Timeline syncing→resolved traces; the post-resolution map +
the tombstone entry.

---

## Journey 4 — Compute Triage (budget pressure, redistribution & pruning)

### Persona & scenario
A researcher runs an **expensive, multi-pronged exploration on a tight token budget** (the
**Riemann Hypothesis**, surveyed). Compute is scarce, so she uses the UI to **see which branches
are starving, pour budget into the most promising idea, and prune a dead-end** — i.e. she manages
the swarm like a portfolio.

### What this journey validates
1. **Status-bar global budget readout** `⛁ used / cap` and its click-through to the Activity
   drawer; `/budget <N>` command.
2. **Low-budget signaling**: agents above 90% usage get an **orange ring** on the map; budget
   labels turn amber/red.
3. **Inspector ▸ Budget**: per-agent cap + usage, **inline edit**, and **redistribute to children**
   (equal / weighted / priority).
4. **Pruning a leaf**: removing a dead-end agent and seeing the tombstone + count update.

### Preconditions
Clean state. Launch a **3-agent** Ollama swarm with a **small** budget so pressure appears fast:
- Macro goal: `Survey strategies toward the Riemann Hypothesis (non-trivial zeros lie on Re(s)=1/2).`
- Designer agents:
  - `001` — `Complex Analyst`, goal `Study the zeta function's analytic continuation and zero-free regions.`
  - `002` — `Random Matrix Theorist`, goal `Explore Montgomery's pair correlation and GUE statistics of zeta zeros.`
  - `003` — `Explicit Formula Specialist`, goal `Use explicit formulae linking zeros to prime counting and error terms.`
- Budget preset **Small (5k)**. Launch.

### Steps & expected observations

**4.1 — Read the global budget.** In `#status-bar` find `⛁ used / cap` (cap shows `5,000`). Poll as
agents work; *expected:* the **used** figure climbs.

**4.2 — Watch starvation appear.** As any agent crosses **90%** of its per-agent cap:
- *Expected:* that node gains an **orange ring**; its `🔋 used/cap (pct%)` label turns **red**;
  legend's "Low Budget" swatch matches.

**4.3 — Inspect one agent's budget.** Open Inspector ▸ **Budget** for the highest-usage agent
(`open-inspector data-agent-id="0XX" data-tab="budget"`).
- *Expected:* `#inspector-body` shows that agent's **token cap, used tokens, a usage bar**, an
  **inline edit** affordance (`edit-agent-budget`), and **redistribute** buttons
  (`redistribute-budget … data-strategy="equal|weighted|priority"`).

**4.4 — Raise the global cap via command bar.** Type `/budget 30000` and Enter.
- *Expected:* success toast "Budget set to 30000"; the status-bar `⛁ … / cap` updates to
  `… / 30,000`; orange rings may clear as headroom returns.

**4.5 — Bias compute toward the promising idea (redistribute).** Decide which idea looks most
promising (e.g. `002`, random-matrix). If `002` has children, open its Inspector ▸ Budget and click
**Weighted** then **Priority** (`redistribute-budget data-parent-id="002" data-strategy="weighted"`
/ `"priority"`).
- *Expected:* success toast; children's caps change accordingly; map budget labels for that subtree
  update. *(If the chosen agent has no children yet, instead use the inline per-agent edit in 4.3 to
  raise just that agent's cap and confirm only its node's label changes.)*

**4.6 — Prune a dead-end.** Pick the least-progressing agent (lowest progress, or one that emitted a
`failed ❌` trace). Prune it via the rail row action (`prune-agent data-agent-id="0XX"`) or
`/prune 0XX`.
- *Expected:* success toast; `#agent-count` decrements; node removed from the active map; a
  **pruned tombstone** appears in the Activity drawer (Tombstones); `🔔/⚡` counts unaffected unless
  it had pending items.

### PASS / FAIL checklist
- [ ] Status-bar `⛁ used / cap` rendered and the used value climbed live.
- [ ] An agent crossing 90% showed an **orange ring** + red budget label.
- [ ] Inspector ▸ Budget showed cap/used/bar + inline edit + 3 redistribute strategies.
- [ ] `/budget 30000` updated the cap in the status bar.
- [ ] A redistribute (or per-agent edit) changed the targeted agent/subtree's budget labels only.
- [ ] Pruning removed the node, decremented the count, and wrote a tombstone visible in the drawer.

### Likely cause if a check fails
- *Used never climbs:* token accounting not pushed over SSE, or agents stalled (check
  `monitor.log`).
- *No orange ring at >90%:* `lowBudget` threshold logic or ring render broken in `renderSwarmMap`.
- *Redistribute no-op:* agent has no children (expected) or `/api/budget/redistribute` failed —
  check network.
- *Prune no-op / node stays:* `/api/prune/<id>` rejected (e.g. non-leaf safety restriction) — the
  toast message will say so; pick a leaf.

### Evidence to capture
Status-bar budget before/after `/budget`; map screenshot with an orange-ring starved node;
Inspector ▸ Budget panel; the map after redistribute; the Activity drawer tombstone after prune.

---

## Journey 5 — From Sprawl to Synthesis (coding build + deliverable)

### Persona & scenario
A coder uses the swarm to **build a small multi-module library** — a **token-bucket rate limiter
with tests and a README** — splitting the work across agents. He watches them divide files,
self-heal a failing test, then reads the assembled product via the **editor**, the **causal
trace**, and the **combined synthesis report.** This is the "useful for coders" end-to-end.

### What this journey validates
1. Multi-agent **coding** decomposition; the right **editor** panel with **file tabs** and
   syntax-highlighted content per selected agent.
2. **Self-healing verification loop**: a step whose verification (e.g. `pytest`) fails triggers a
   heal/retry; surfaced via `failed ❌` → retry → `completed ✅` traces and/or a **blocker card**.
3. **Blocker resolution controls** (workaround / bypass / kill) if a blocker is raised to the
   operator.
4. **Inspector ▸ Trace**: the causal lineage (steps, state transitions, spawns) renders.
5. **Combined deliverable**: the **📄 Report** (synthesis) modal assembles all agents' outputs into
   one markdown document.

### Preconditions
Clean state. Launch a **3-agent** Ollama swarm:
- Macro goal: `Build a thread-safe token-bucket rate limiter in Python with unit tests and a README.`
- Designer agents (distinct files → little collision, lots of parallel build):
  - `001` — `Core Library Author`, goal `Implement the TokenBucket class with refill logic in ratelimiter.py.`
  - `002` — `Test Engineer`, goal `Write pytest unit tests for the rate limiter in test_ratelimiter.py covering refill, burst, and exhaustion.`
  - `003` — `Docs Writer`, goal `Write a README.md documenting usage, configuration, and examples for the rate limiter.`
- Budget preset **Medium (20k)**. Launch.

### Steps & expected observations

**5.1 — Watch the build fan out.** Map shows 3 green nodes with the three roles. Single-click each
and confirm the **right editor** (`#alerts-list`) loads that agent's file(s) as **`.editor-tab`s**
(e.g. `ratelimiter.py`, `test_ratelimiter.py`, `README.md`), with content shown when a tab is
selected (`select-file`). *Expected:* selecting different agents swaps the editor's files — the
editor follows selection.

**5.2 — Observe self-healing (if a verification step fails).** Watch the **Test Engineer (002)** and
any agent whose step uses a verification tool.
- *Expected on a failure:* a `.thought-trace--failed` (❌) trace describing the test/compile error,
  then a **heal/retry** (the runner re-queries the model with the traceback), then a
  `.thought-trace--completed` (✅) when it passes. Progress only advances on a passing verification.
- *If the agent escalates to the operator:* a **blocker decision card** appears (Timeline +
  Activity drawer + `🔔` count + blue ring on the node) showing **file / tool / error**.

**5.3 — Resolve a blocker (if raised).** On a blocker card choose **🔧 Workaround**
(`resolve-blocker data-agent-id="0XX" data-choice="1"`); if it persists, **⏭ Bypass** (`choice=2`).
Reserve **💀 Kill** (`choice=3`) for a truly stuck agent.
- *Expected:* success toast; the blocker clears (`🔔` decrements, ring clears); the agent resumes
  (workaround/bypass) or dies + tombstones (kill).

**5.4 — Read the causal trace.** Open Inspector ▸ **Trace** for `001`
(`open-inspector data-agent-id="001" data-tab="trace"`).
- *Expected:* `#inspector-body` renders a **causal lineage** for 001 — its state transitions
  (exploring → … → completed), step nodes, and any spawn/heal events (a Mermaid diagram and/or a
  timeline list). The command-bar form `/trace 001` should reach the same content.

**5.5 — Let it finish, then synthesize.** Wait until `#status-label` → **`COMPLETED`** (pill
`status-pill--idle`, label COMPLETED; nodes light-blue / completed).
- Click **📄 Report** (`#synthesis-btn`, `data-action="view-synthesis"`).
- *Expected:* `#synthesis-modal` opens; `#synthesis-body` first shows "Generating synthesis…" then a
  **combined markdown deliverable** that includes contributions from **all three** agents (the rate
  limiter, the tests, and the README assembled into one document). The command `/view synthesis`
  opens the same modal. Close with `data-action="close-synthesis"`.

### PASS / FAIL checklist
- [ ] Each agent's files load as editor tabs; selecting an agent swaps the editor to its files; file content renders.
- [ ] At least one verification-gated step showed the `failed → (heal) → completed` pattern **or** raised a blocker card (file/tool/error) — i.e. progress is test-gated, not free.
- [ ] If a blocker was raised, a resolve choice (1/2/3) cleared it with a matching toast and state change.
- [ ] Inspector ▸ Trace rendered a causal lineage for the selected agent; `/trace 001` reached it too.
- [ ] On completion, **📄 Report** produced a combined markdown deliverable spanning all 3 agents.

### Likely cause if a check fails
- *Editor doesn't follow selection:* `selectedAgentId`/`selectedWorkspaceAgent` not driving the
  right panel render, or `/api/workspaces/<id>` empty (no files written yet — wait for steps).
- *No heal/blocker ever:* none of the steps carried a verification tool / trap (depends on the
  LLM-generated step plan) — informational, not necessarily a UI bug; confirm the *mechanism* via
  the deterministic variant (Appendix B) which can force a trap.
- *Trace empty:* `/api/trace/<id>` returned nothing — causal graph not populated for that agent.
- *Report empty / error:* `/api/synthesis` failed or `build_synthesis` found no agent outputs (run
  didn't complete) — re-check `COMPLETED` state first.

### Evidence to capture
Editor showing each agent's file; Timeline `failed→completed` heal sequence (or a blocker card);
Inspector ▸ Trace diagram; the synthesis modal with the combined deliverable.

---

## Journey 6 — Institutional Memory (learning across runs)

### Persona & scenario
A researcher runs the **same family of problem twice**. On the second run she expects agents to
**recall prior episodes** — preloading files from the earlier attempt and steering away from
previously **tombstoned** dead-ends — and she verifies this via **Inspector ▸ Memory** and the
`/memory` view. This is the "research compounds over time" story.

### What this journey validates
1. **Episodic memory persistence** across runs (`memory.db`) surfaced in **Inspector ▸ Memory** and
   the `/memory` command/view.
2. Agents **query memory at startup** (a thought trace / preloaded files referencing a past
   episode).
3. **Tombstone avoidance**: a dead-end recorded in run 1 is visibly avoided/warned in run 2.

### Preconditions
**Do NOT clean memory between the two runs** (that is the whole point). You may clean
logs/workspaces/collisions, but **never** `memory` or `all` between run 1 and run 2.

### Steps & expected observations

**6.1 — Run 1 (seed memory).** Launch a **2-agent** Ollama swarm:
- Macro goal: `Implement a recursive Fibonacci function and a memoized version, with tests.`
- `001` — `Algorithms Engineer`, goal `Implement naive and memoized Fibonacci in fib.py with tests in test_fib.py.`
- `002` — `Performance Analyst`, goal `Benchmark recursive vs memoized Fibonacci and document the complexity tradeoff.`
- Budget **Medium**. Let it run to **COMPLETED**. (If any agent hit a dead-end, note the tombstone in
  the Activity drawer.)

**6.2 — Inspect the seeded memory.** Type `/memory` (or set view to memory). *Expected:* a list of
**episodes** from run 1 — each with goal, role, status, and a self-reflection. Also open Inspector ▸
**Memory** for an agent and confirm episodes render there.

**6.3 — Run 2 (related problem).** Without cleaning memory, launch a **2-agent** swarm on a
**closely related** goal:
- Macro goal: `Implement an iterative Fibonacci and a matrix-exponentiation Fibonacci, with tests.`
- `001` — `Algorithms Engineer`, goal `Implement iterative and matrix-power Fibonacci in fib.py with tests in test_fib.py.`
- `002` — `Performance Analyst`, goal `Compare iterative vs matrix-exponentiation Fibonacci performance.`
- Budget **Medium**. Launch.

**6.4 — Confirm recall at startup.** Scope the Timeline to `001` early in run 2.
- *Expected:* an early trace indicating the agent **loaded historical context / similar past
  episodes** (e.g. references prior Fibonacci work or preloads `fib.py`), and/or Inspector ▸ Memory
  for the new agent lists the **run-1 episodes** as similar prior runs.

**6.5 — Confirm tombstone avoidance (if a tombstone exists).** If run 1 produced a tombstone (a
failed tool/step), watch run 2 for a trace that **checks tombstones and steers away** from that
file/tool before acting (no re-crash on the same dead-end).

### PASS / FAIL checklist
- [ ] After run 1, `/memory` and Inspector ▸ Memory list run-1 episodes (goal/role/status/reflection).
- [ ] In run 2, an agent surfaced recalled context / similar prior episodes from run 1 (trace or Memory tab).
- [ ] If a run-1 tombstone existed, run 2 visibly avoided that dead-end (tombstone-check trace; no repeat crash).
- [ ] Memory survived between runs (it was never cleaned) — proving persistence, not in-session caching.

### Likely cause if a check fails
- *Empty memory after run 1:* episodes not saved (`save_memory_episode` / `memory.db` write failed),
  or run never reached completed/failed.
- *No recall in run 2:* startup memory query not running or similarity below recall threshold —
  make run-2 goals more similar to run-1.
- *Memory tab empty in inspector but `/memory` works (or vice-versa):* one of the two surfaces isn't
  reading `/api/memory`.

### Evidence to capture
`/memory` list after run 1; Inspector ▸ Memory panel; run-2 startup trace showing recall; (if
applicable) the tombstone-avoidance trace.

---

## Appendix A — Cross-cutting validation (run on every journey)

Spot-check these regardless of the specific journey:

1. **SSE liveness.** In the browser network panel, `/api/events` is an open `text/event-stream`
   that periodically pushes data. Map/rail/status update **without a manual reload** when state
   changes. *If updates only appear on reload, SSE is broken.*
2. **Single source of truth (selection).** Selecting an agent in the **rail**, on a **map node**, or
   via the command bar drives the **same** `selectedAgentId` → cluster sidebar, editor, and an open
   inspector all show that agent. No surface lags or shows a different agent.
3. **Single-click vs double-click contract.** Single-click **focuses** (does *not* open the
   Inspector); double-click (or the ℹ️ details action) **opens the Inspector**. Verify a casual
   single-click never pops the Inspector.
4. **Status bar ↔ drawer wiring.** Clicking `🔔 K decisions` or `⛁ budget` opens the **Activity**
   drawer; clicking `📜 Logs` opens the **Logs** drawer; `close-drawer` dismisses it.
5. **Empty/init contract.** With `agents.length === 0` the **Init overlay is shown** and its close
   button hidden; with agents present, opening **+ New swarm** shows the overlay **with** a working
   close (`#init-close-btn`).
6. **Toasts.** Every POST action (launch, chat, approve/reject, resolve, prune, budget, clean,
   redistribute) yields a `success`/`error` toast whose text matches the action's outcome.
7. **Logs drawer reflects reality.** The Logs drawer / status-bar last-log line mirrors
   `monitor.log`; errors there explain any UI stall.
8. **No console errors.** The browser console shows no uncaught exceptions or repeated SSE
   parse/`API error:` lines during a journey.
9. **Resilience.** Reloading the page mid-run rehydrates from `/api/state` and reconnects SSE — the
   map repopulates to current state (no data loss in the UI).

---

## Appendix B — Fast deterministic smoke variant

Use this **only** to validate UI *plumbing* quickly without waiting on a local model (idea content
will be templated/generic, so it does **not** exercise "idea exploration" — journeys 1, 2, 6
require real LLM output).

- Start the throwaway server with the **rules** provider:
  `python3 web_dashboard.py --port 8096 --llm-provider rules`.
  Note the Init modal still posts the dropdown value; to truly force deterministic negotiation the
  server-level `rules` provider governs the supervisor/monitor paths. Decomposition still calls
  local Ollama if reachable, so for a *fully* offline structural smoke you may stop Ollama.
- What you can still validate deterministically: launch → agents appear; map renders nodes/edges;
  selection propagation; **collisions** (Journey 3 setup is reliable under rules); **prune/budget**
  controls; drawer/inspector open/close; status-bar counters; init/empty contract; toasts; SSE
  liveness.
- What you **cannot** validate here: substantive thought-trace *content*, PIVOT vs ADD_CONTEXT
  reasoning quality, organic novelty spawns, and synthesis richness — those need `ollama`.

### Programmatic backend cross-check (optional)
To corroborate that the UI matches backend state during any journey, the executor may read the
REST endpoints directly (read-only): `GET /api/state`, `/api/agents`, `/api/agents/<id>`,
`/api/collisions`, `/api/tombstones`, `/api/trace/<id>`, `/api/memory`, `/api/workspaces/<id>`,
`/api/synthesis`. A UI check **fails** if the DOM disagrees with these payloads (e.g. `/api/agents`
returns 5 agents but the map shows 4).
