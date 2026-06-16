# Proximity Swarm — Simplified UI Design Proposal

> Companion to [`ui_design_document.md`](ui_design_document.md) (the current V3 spec) and
> [`design_doc.md`](design_doc.md) (the backend/feature spec). This document proposes a
> **simpler information architecture that preserves 100% of existing features** — nothing is
> removed, things are relocated to calmer homes. An interactive mockup of this layout was
> delivered alongside this doc.

---

## 1. The problem: too many doors into the same rooms

The current dashboard exposes **nine always-visible navigation targets** before you've done
anything:

- **7 center tabs**: Overview · Cluster Map · Workspace · Trace Graph · Memory · Logs · Agent Chat
- **2 right-panel tabs**: Code Editor · Activity

Plus a left agent sidebar, a settings/clean dropdown, a launch modal, an agent-edit slide
panel, the init overlay, and a command bar. That's a lot of chrome competing for attention,
and several destinations are **redundant or overlapping**:

| Redundancy | Why it's confusing |
|---|---|
| `Workspace` tab **vs** `Code Editor` right-tab | Two different places that both show an agent's generated files. |
| `Overview` tab **vs** `Cluster Map` tab **vs** agent sidebar | Three views of "which agents exist and what are they doing." |
| `Activity` right-tab **vs** decision cards | Budget, spawns, blockers, collisions, tombstones all crammed into one scrolling tab that's hidden behind a toggle. |
| `Agent Chat` tab (hidden until activated) | A whole top-level tab that only appears contextually — easy to lose. |

The result (see the uploaded screenshot): a powerful tool that *looks* like a control panel
for a nuclear reactor, when the day-to-day job is "watch agents work, steer them, read their
code."

---

## 2. Design principles (from the aspired mockups + Claude Code / VS Code / Antigravity)

1. **Three persistent zones, one focus area.** Like an IDE: a *who* rail (left), a *what's
   happening* stage (center), an *output* editor (right). Everything else is summoned, not
   permanently parked.
2. **Selection drives everything.** Click an agent once → the stage, editor, and inspector all
   follow it. No more re-selecting the same agent in four places.
3. **Deep/rare views are drawers, not tabs.** Trace, Memory, budget controls, and the
   decision/collision feeds are pulled up *when you need them*, then dismissed. They don't tax
   you when you don't.
4. **Decisions come to you.** Pending spawns, blockers, and collisions surface inline in the
   timeline **and** as a clickable count in the status bar — you never have to go hunting in a tab.
5. **One way to see a thing.** Kill the Workspace-vs-Editor and Overview-vs-Map duplications.
6. **Borrow VS Code / Antigravity chrome.** A far-left **activity bar** (icon switcher), VS
   Code editor **tabs**, and a **blue status bar** at the very bottom (swarm status, agent count,
   budget, decision count, provider, line/col). Flat gray surfaces, minimal radius — it should
   read as an *agentic IDE*, not a sci-fi console. The palette reuses the app's existing VS Code
   tokens already in `static/styles.css`.

---

## 3. Proposed layout

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ ⬡ Proximity Swarm V3 — auth-service              ▶ Running   ⚙   + New swarm  │  Title bar
├──┬──────────┬──────────────────────────────────────────┬──────────────────────┤
│⬡ │ AGENTS 6 │  [ ◆ Map │ 💬 Timeline ]   ● Swarm optimal │ AuthForm.jsx ×  …    │
│◆ │ ▾ Orch.  │            (001)                           │ src › … › jsx        │
│💬│ 001 Lead │          ╱  │  ╲  ╲                         │  3 export const      │
│🔍│ •active  │     (002)(003◉)(004)(005✓)                  │  4  const[user] ⌷002 │
│🔔│ ▾ Sub    │       │    ◉ blue = needs input             │  …                   │
│  │ 002 FE   │     (006◍)    ◍ orange = low budget         │ [ Code │ Terminal ]  │
│  │ 003 ◉API │      ┄ redundancy link (003 ┄ 006)          │                      │
│⚙ │ 006 ◍sub │      ─ solid edge = parent → child          │                      │
├──┴──────────┴──────────────────────────────────────────┴──────────────────────┤
│ ❯ Enter a goal, command, or @agent_id message…                                 │  Command bar
├────────────────────────────────────────────────────────────────────────────────┤
│ ⎇ auth-service  ● Running  ◆ 6 agents  ⛁ 3,157/20,000     🔔 2 decisions  Logs │  Status bar (blue)
└────────────────────────────────────────────────────────────────────────────────┘
  ▲ far-left activity bar (VS Code)   ▲ on-demand: Inspector slides from right · Activity/Logs drawer rises from bottom
```

### Zone 1 — Agents rail (left, the *who*)
Hierarchical tree (Main agent → Sub-agents), each row showing **status badge · role · truncated
goal · progress bar · mini token usage** — exactly the density of mockup 1. This single rail
replaces the old sidebar **and** the Overview tab's agent grid. Clicking a row is the universal
"focus this agent" gesture.

### Zone 2 — Stage (center, the *what's happening*) — the **Map ⇄ Timeline** toggle
A segmented control flips the center between the two paradigms your mockups showed:

- **Map** — a **clustered network graph** (mockup 2's signature view). Agents group into
  **sub-swarms**, each drawn inside a soft **boundary hull** (the design doc's "nested transparent
  boundary circles"); the cluster's **lead** sits central with its **worker** agents orbiting it,
  positioned organically rather than on a grid. An **orchestrator hub** floats above and connects
  down to each cluster lead. Every node is labeled with its agent **ID** (`001`–`00N`) and a role
  tag; **solid directional edges run parent → child** so the spawn tree is readable; a **dashed
  amber link with a glowing ring** bridges two clusters to mark a cross-swarm *redundancy*
  collision (proximity spring). Node **fill** encodes work state (green = exploring, gray = idle,
  check = done), while a colored **attention ring** encodes what the agent needs from *you*:
  **blue ring = needs input** (pending spawn/blocker decision), **orange ring = low token budget**.
  Faint ambient dots inside each hull hint at additional swarm members at scale.
- **Timeline** — a Claude-Code-style conversation/activity stream: your prompts, agent
  narration, live code snippets, and **inline decision/collision cards**. This absorbs the old
  `Agent Chat` tab — when an agent is selected (or you `@mention` one), the timeline scopes to
  it.

One toggle replaces three tabs (Overview, Cluster Map, Agent Chat).

### Zone 3 — Editor (right, the *output*)
A VS-Code-style editor: **file tabs**, breadcrumb, syntax-highlighted contents with line
numbers, and **multiplayer agent cursors** (the "Agent 004/005" labels from mockup 2). A
collapsible **Code ⇄ Terminal** switch lives at its foot (mockup 1). This single editor
replaces the redundant `Workspace` tab + `Code Editor` right-tab.

### On-demand: Inspector drawer (agent deep-dive)
Slides in from the right when you open an agent's details. Internal tabs:
**Overview · Budget · Trace · Memory** — scoped to the selected agent. This is the new home for
the agent detail card, task-similarity metrics, the inline budget editor + redistribute
strategies (equal/weighted/priority), the causal trace graph, and that agent's memory episodes.
Collapses three former top-level tabs into one contextual panel.

### On-demand: Activity / Logs drawer (swarm feeds)
Rises from the bottom when you click the **"N decisions"** count or **Logs** item in the blue
status bar (the count is the attention cue, VS Code's errors/warnings pattern). Holds the
swarm-wide feeds: pending spawn approvals,
blocker resolutions (workaround/bypass/kill), live collisions, prune candidates, tombstones,
and the `monitor.log` stream.

### Empty / init state (mockup 3)
When `agents.length === 0`, the three zones sit empty and dimmed and a single centered
**"Initialize Swarm Task"** modal appears: prompt textarea, provider select, and a compute
budget control. The agent-designer (custom roles/goals, add/remove agents) lives as an
expandable section inside this one modal — no separate launch modal.

---

## 4. Feature mapping — proof that nothing is lost

| Current feature / location | New home |
|---|---|
| `Overview` tab | **Removed as a tab** → merged into Agents rail (list) + Map (viz) + Inspector (detail) |
| `Cluster Map` tab | Stage → **Map** |
| `Workspace` tab | **Merged** into right Editor |
| `Code Editor` right-tab | Right Editor (the one editor) |
| `Agent Chat` tab | Stage → **Timeline** (scoped via selection / `@agent`) |
| `Trace Graph` tab | Inspector → **Trace** (agent-scoped) |
| `Memory` tab | Inspector → **Memory** (+ swarm-wide filter in header) |
| `Logs` tab | Bottom drawer → **Logs** (and Editor's **Terminal** switch) |
| `Activity` right-tab: global budget | **Status-bar budget readout** `⛁ 3,157 / 20,000` (glanceable, click to edit) |
| `Activity` right-tab: per-agent budget tree + redistribute | Inspector → **Budget** |
| `Activity` right-tab: spawns / blockers / collisions / tombstones | Bottom **Activity drawer** + inline **Timeline cards** |
| Agent detail card (role/goal/similarity) | Inspector → **Overview** |
| Launch modal + agent designer | One **Init modal** (designer as expandable section) |
| Clean/storage dropdown | **Settings ⚙** menu in title bar |
| Status pill (idle/running/completed) | Title-bar **Running** chip + blue **status bar** state |
| Per-agent actions (workspace/trace/edit/prune) | Row hover actions + Inspector |
| Command bar (`@agent`, commands, goals) | **Unchanged** — persistent at bottom |
| Toasts | Unchanged |

**Net change in always-visible navigation:** from **9 tabs** → **3 panes + 1 center toggle**,
with **2 on-demand drawers** holding the deep/rare views. Every backend endpoint in
`ui_design_document.md` §3 still has a UI trigger.

---

## 5. State synchronization (simpler than today)

| Trigger | State update | Visual effect |
|---|---|---|
| **Single-click** agent in rail | `selectedAgentId` (single source of truth) | Map node highlights (thicker stroke) · Editor loads that agent's files · Inspector (if already open) re-scopes. **Does not open the Inspector.** |
| **Double-click** agent, or click its **details icon** | `inspectorOpen`, `selectedAgentId` | Inspector slides in — so it never pops on a casual click |
| Toggle Map / Timeline | `stageView` | Center swaps; selection preserved |
| Switch Inspector sub-tab | `inspectorTab` | Overview / Budget / Trace / Memory for `selectedAgentId` |
| Decision arrives (SSE) | `decisions[]` | Inline Timeline card **+** status-bar "N decisions" count increments; if it targets an agent, that node gets a **blue ring** (needs input) |
| Budget runs low (SSE) | agent budget state | Node gets an **orange ring** (low budget) |
| New swarm launch | `agents[]` from SSE | Init modal fades; rail + Map populate |

The big win: today the same agent must be re-picked in the sidebar, the map, the workspace
dropdown, and the trace dropdown. Here, **one selection propagates everywhere.**

---

## 6. Suggested phasing (when you're ready to build)

1. **Shell + selection model** — top bar, 3-zone flex layout, single `selectedAgentId` wired
   through rail → map → editor. Retire the 7-tab strip.
2. **Stage toggle** — fold existing `renderClustersTab` (Map) and a timeline built from
   `renderAgentChatTab` + activity stream (Timeline) behind the segmented control.
3. **Merge Workspace into Editor** — one file viewer; delete the duplicate.
4. **Inspector drawer** — move `renderTraceTab`, `renderMemoryTab`, the agent detail card, and
   the budget editor/redistribute controls into the four inspector sub-tabs.
5. **Activity/Logs drawer** — relocate spawns/blockers/collisions/tombstones + log tail; add the
   badge on the bottom pill.
6. **Init modal** — consolidate the init overlay + launch modal + agent designer.

Each step is independently shippable and leaves the app working.

---

## 7. Decisions (resolved 2026-06-15)

- ✅ **Default stage view:** **Map when >1 agent, Timeline for a single agent.** The map's node
  ring colors also flag what each agent needs from the operator (blue = needs input, orange =
  low budget).
- ✅ **Inspector trigger:** **focus on single-click, Inspector on a details icon / double-click** —
  so the Inspector doesn't pop on every casual selection.
- ✅ **Compute budget control:** **segmented presets (Small / Medium / Large)** in the init modal,
  with an **"advanced → exact tokens"** reveal for precise caps.
- ✅ **Branding:** keep the name **Proximity Swarm V3**.

### Still worth confirming during build
- Exact **token mapping** for the Small/Medium/Large presets (e.g. 5k / 20k / 50k?).
- Whether **single-click should also flip the editor** to the agent's most-recently-touched file,
  or leave the editor on the current file until explicitly changed.
