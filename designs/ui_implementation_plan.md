# Proximity Swarm V3 — Web UI Implementation Brief (Phases 2–6)

**Audience:** an autonomous coding agent implementing the remaining web-dashboard work.
**Read these first, in order:** this file, then [`ui_design_document.md`](ui_design_document.md)
(the target spec), then [`simplified_ui_design.md`](simplified_ui_design.md) (rationale &
phasing), then [`design_doc.md`](design_doc.md) (backend features).

> **Scope:** Phase 1 (the IDE shell — activity bar + blue status bar + command bar + 3-zone grid)
> is **already done and merged**. Your job is **Phases 2–6**, which transform the center, right
> panel, and modals into the approved design **without breaking any existing feature**.

---

## 0. How to run, edit, and verify (no build step)

This is a vanilla SPA (no framework, no bundler, no transpile). The Python server serves the three
static files **from disk on every request**, so your edit loop is just **edit → reload browser**.

```bash
# Start the dashboard (provider "rules" needs no Ollama/network)
python3 web_dashboard.py --port 8080 --llm-provider rules
# open http://localhost:8080
```

- **Frontend files (all your work is here unless a phase says otherwise):**
  - `static/index.html` — DOM skeleton
  - `static/app.js` — all logic (state, SSE, render, event dispatch)
  - `static/styles.css` — all styles (CSS custom properties at `:root`)
- **Backend** `web_dashboard.py` — only touch it if a phase explicitly requires a new endpoint.
- **Tests:** `python3 -m unittest discover tests` (uses `unittest`, **not** pytest). Frontend has
  no unit tests; verify the frontend in a browser.
- **Verify every phase in the browser:** open the page, open devtools console, confirm **zero
  errors**, then exercise the feature (click things) and confirm the network/SSE still updates.

### Non-negotiable invariants (breaking any of these is a regression)

1. **Preserve every DOM `id` that `app.js` reads.** Grep before deleting any element:
   `grep -o "getElementById('[^']*')" static/app.js`. Required static ids include:
   `agent-list`, `agent-count`, `viewport-content`, `alerts-list`, `alerts-count`,
   `right-tab-editor`, `right-tab-activity`, `command-input`, `log-tail`, `status-pill`,
   `status-label`, `status-bar`, `clean-menu`, `init-overlay`, `init-goal`, `init-provider`,
   `init-budget`, `launch-modal`, `launch-goal`, `launch-budget`, `designer-agents`,
   `synthesis-modal`, `synthesis-body`, `agent-chat-tab`, `toast-container`,
   `agent-edit-panel`, `slide-backdrop`. If a phase relocates one of these, keep the id on the
   moved element.
2. **All interactivity goes through the delegated dispatcher.** There is exactly one
   `document.addEventListener('click', …)` in `app.js` that switches on
   `e.target.closest('[data-action]').dataset.action`. **Add new behaviors by (a) putting
   `data-action="…"` (+ `data-*`) attributes in your HTML and (b) adding a `case` to that
   switch.** Do not sprinkle inline `onclick=` or ad-hoc listeners (the one existing exception is
   the command-bar `keydown` listener and a couple of inline-edit listeners — follow the
   delegated pattern for anything new).
3. **Never break the SSE/render loop.** `connectSSE()` merges pushed state into `SwarmState` and
   calls `render()` when `state_hash` changes. `render()` calls the per-region render functions.
   When you add a region, add its render call to `render()` — do not create a parallel update path.
4. **`render()` is called frequently and re-creates DOM via `innerHTML`.** Any transient UI state
   (which stage view is active, whether a drawer/inspector is open, which sub-tab) must live in
   the `UIState` object so it survives a re-render. Do **not** store it only in the DOM.
5. **Escape all dynamic text** with the existing `escapeHtml()` / `escapeAttr()` helpers before
   putting it in `innerHTML`.
6. **Reuse the CSS custom properties** in `:root` (`--bg-*`, `--accent-*`, `--text-*`,
   `--border-*`, `--space-*`, `--radius-*`, `--font-*`). Do not hardcode hex colors.
7. **Keep it framework-free.** No npm, no imports, no external CDNs. Plain DOM + template strings.

---

## 1. Architecture you must integrate with

### 1.1 Client state objects (top of `app.js`)

```js
const SwarmState = {            // mirrors the server; replaced/merged by SSE + /api/state
  agents: [],                   // array of agent JSON (schema in §1.3)
  collisions: [],               // [{ agent_a, agent_b, distance, ... }]
  tombstones: [],               // [{ file_path, tool_used, error_message, fix_action, is_pruned? }]
  orchestrator: {},             // { sub_swarms: { <id>: {...} }, ... } (three-tier scaling)
  budget_alert: {},             // { active_count, per_agent_status:[...], subtree_alerts:[...] }
  logs: [],                     // array of log line strings
  pending_spawns: [],           // [{ agent_id, ... }] awaiting approve/reject
  pending_blockers: [],         // [{ agent_id, ... }] awaiting workaround/bypass/kill
  swarm_running: false,
  macro_goal: '',
  session_budget: 20000,        // global token cap
  predefined_agents: [],
  state_hash: '',
};

const UIState = {               // client-only view state (NOT sent to server)
  activeTab: 'clusters',        // which activity-bar view is showing in the center
  rightPanelTab: 'editor',      // 'editor' | 'activity' (right panel)
  selectedAgentId: null,        // THE selection — drives map highlight, editor, inspector
  editingAgentId: null,         // agent whose chat/edit panel is open
  selectedWorkspaceAgent: null,
  selectedTraceAgent: null,
  selectedFile: null,
  workspaceData: null,          // cached /api/workspaces/<id> result
  traceData: null,              // cached /api/trace/<id> result
  memoryData: null,             // cached /api/memory result
  designerAgents: [{ role: 'Generalist', goal: '' }],
  // YOU WILL ADD (see phases): stageView, inspectorOpen, inspectorTab, drawerOpen, drawerTab
};
```

### 1.2 The render pipeline

```js
function render() {
  renderStatusPill();      // title-bar Running/Idle/Completed chip
  renderStatusBar();       // blue bottom status bar (Phase 1)
  renderAgentSidebar();    // left rail  -> #agent-list
  renderAlertsPanel();     // right panel -> #alerts-list (editor OR activity, per rightPanelTab)
  renderViewportContent(); // center      -> #viewport-content (switch on UIState.activeTab)
  renderLogTail();         // #log-tail (currently hidden; full feed)
}
```

`renderViewportContent()` switches on `UIState.activeTab` and calls one of:
`renderOverviewTab`, `renderClustersTab`, `renderWorkspaceTab`, `renderTraceTab`,
`renderMemoryTab`, `renderLogsTab`, `renderAgentChatTab` — each takes the `#viewport-content`
container element and sets its `innerHTML`.

It also syncs active state across `.viewport__tab, .activity-bar__item` by matching `dataset.tab`
to `UIState.activeTab`. **Keep this sync working** when you add the stage toggle.

### 1.3 Agent JSON schema (each item of `SwarmState.agents`)

```
id                 "001"            string id, zero-padded
parent_id          "001" | null     hierarchy parent (null/"None" = root)
parent_ids         ["001", ...]     multi-parent (cross-swarm takeovers); optional
personality        "Generalist"     a.k.a. role
goal               "Build ..."      current goal text
status             "exploring" | "syncing" | "pending_termination" | "completed" | "dead"
progress           0..100
steps_completed    int
current_step       { step_id, name, description } | null
touched_files      ["src/x.py", ...]
tools_used         ["pytest", ...]
thought_traces     [{ content, type, details, timestamp }]   // drives the Timeline
output_tokens      int              // tokens used (for budget %)
token_budget       int              // this agent's cap
subtree_token_budget int            // cap for the agent + descendants
sub_swarm_id       "frontend" | null// which sub-swarm/cluster it belongs to (three-tier)
spawn_request      {...} | null     // a child this agent wants to spawn
blocker_details    {...} | null     // present when blocked
chat_messages      [{ role, content, timestamp, processed }]
```

> Not every field is always present — **default defensively** (`agent.output_tokens || 0`).

### 1.4 REST endpoints (already implemented in `web_dashboard.py`)

GET: `/api/state`, `/api/agents`, `/api/agents/<id>`, `/api/workspaces/<id>`, `/api/trace/<id>`,
`/api/memory`, `/api/collisions`, `/api/tombstones`, `/api/logs`, `/api/synthesis`,
`/api/events` (SSE).
POST: `/api/config`, `/api/run`, `/api/add-agent`, `/api/agents/<id>/preset`,
`/api/agents/<id>/edit`, `/api/agents/<id>/chat`, `/api/approve/<id>`, `/api/reject/<id>`,
`/api/resolve/<id>` (`{choice:1|2|3}`), `/api/prune/<id>`, `/api/budget` (`{budget}`),
`/api/agents/<id>/budget`, `/api/budget/redistribute` (`{parent_id, strategy}`), `/api/clean`
(`{target}`).

Helpers already exist: `apiGet(path)`, `apiPost(path, body)`, `showToast(msg, type)`,
`escapeHtml`, `escapeAttr`, `getMaxLeafTokens()`.

### 1.5 Existing dispatcher actions (do not duplicate; reuse)

`switch-tab` (sets `activeTab`), `switch-right-tab` (sets `rightPanelTab`), `select-agent`,
`edit-agent`, `close-edit`, `save-agent`, `view-workspace`, `view-trace`, `select-file`,
`approve-spawn`, `reject-spawn`, `resolve-blocker` (+`data-choice`), `prune-agent`,
`edit-budget`, `edit-agent-budget`, `redistribute-budget` (+`data-strategy`),
`toggle-clean`, `clean` (+`data-target`), `send-chat`, `open-launch`, `close-launch`,
`launch-swarm`, `add-designer-agent`, `remove-designer-agent`, `init-launch`,
`view-synthesis`, `close-synthesis`.

---

## 2. Functions to reuse (don't rewrite — wrap/relocate)

| Function (in `app.js`) | Produces | Reuse for |
|---|---|---|
| `renderClustersTab(container)` | The swarm **map** SVG (already builds tree, orbital layout, **cluster boundary hulls**, proximity/collision links, node + budget color) | Phase 2 Map view (enhance it) |
| `renderClusterSidebar(agentId)` | Selected-agent detail beside the map (role, goal, similarity) | Phase 4 Inspector ▸ Overview |
| `renderAgentChatTab(container)` | Per-agent thought-trace stream + chat split-pane | Phase 2 Timeline (agent-scoped) |
| `renderAlertsPanel()` | Right panel: global budget, **per-agent budget tree + redistribute**, **spawn cards**, **blocker cards**, collisions, tombstones | Phase 4 Inspector ▸ Budget; Phase 5 Activity drawer |
| `renderWorkspaceTab(container)` | File tree + syntax-lite code viewer (`/api/workspaces/<id>`) | Phase 3 Editor |
| `renderTraceTab(container)` | Causal trace (Mermaid + timeline) (`/api/trace/<id>`) | Phase 4 Inspector ▸ Trace |
| `renderMemoryTab(container)` | Episodic memory list (`/api/memory`) | Phase 4 Inspector ▸ Memory |
| `openEditPanel(agentId)` / slide-panel | Existing right slide-over for editing an agent | Phase 4 Inspector shell pattern |
| `calculateAgentDistance(a,b)` (inside clusters) | proximity distance + goal/file/tool similarity | map links + similarity metrics |

---

## 3. PHASE 2 — Center stage: Map ⇄ Timeline toggle + map enhancements

**Goal:** the center becomes a **stage** with a segmented `[ Map | Timeline ]` toggle. Map is the
clustered network graph (enhanced); Timeline is the conversation/activity stream. Default to
**Map when `agents.length > 1`, Timeline when exactly 1 agent**.

### 3.1 State + dispatch
- Add to `UIState`: `stageView: null` (computed default each render if null — see 3.4).
- Add dispatcher case:
  ```js
  case 'toggle-stage':
      UIState.stageView = target.dataset.stage; // 'map' | 'timeline'
      render();
      break;
  ```

### 3.2 Render entry point
Create `renderStage(container)` and call it from `renderViewportContent()`'s `case 'clusters':`
**instead of** `renderClustersTab(container)`:

```js
function renderStage(container) {
  const n = SwarmState.agents.length;
  if (UIState.stageView == null) UIState.stageView = (n > 1) ? 'map' : 'timeline';
  const view = UIState.stageView;
  container.innerHTML = `
    <div class="stage">
      <div class="stage__toolbar">
        <div class="seg">
          <button class="seg__btn ${view==='map'?'seg__btn--on':''}" data-action="toggle-stage" data-stage="map">◆ Map</button>
          <button class="seg__btn ${view==='timeline'?'seg__btn--on':''}" data-action="toggle-stage" data-stage="timeline">💬 Timeline</button>
        </div>
        <span class="stage__status">${SwarmState.swarm_running ? '● Swarm optimal' : ''} · ${n} agent${n===1?'':'s'}</span>
      </div>
      <div class="stage__body" id="stage-body"></div>
    </div>`;
  const body = document.getElementById('stage-body');
  if (view === 'map') renderSwarmMap(body); else renderTimeline(body);
}
```
- **Rename** `renderClustersTab` → `renderSwarmMap` (keep the body; update the one call site). It
  already renders into the container you pass; ensure it targets `#stage-body`'s children, i.e.
  it still does `container.innerHTML = …` then `document.getElementById('cluster-svg-parent')`.
  (Those ids are created inside its own output, so they keep working.)

### 3.3 Map enhancements (edit inside `renderSwarmMap`, formerly `renderClustersTab`)
The map already draws: tree, orbital layout, **boundary hulls** (`drawBoundaries`), proximity +
collision links with distance labels, and nodes with id/role/goal + budget color. **Add two
things:**

1. **Parent → child directional edges.** After the boundary hulls and before the proximity links,
   draw a solid neutral line from each parent node to each child node, with an arrowhead. Add an
   SVG `<marker>` to `<defs>` once:
   ```html
   <defs><marker id="arrow" markerWidth="7" markerHeight="7" refX="6" refY="3" orient="auto">
     <path d="M0,0 L6,3 L0,6 Z" fill="var(--text-muted)"/></marker></defs>
   ```
   For every node with a parent, draw
   `<line class="cluster-edge" x1=parent.x y1=parent.y x2=child.x y2=child.y marker-end="url(#arrow)"/>`.
   Style `.cluster-edge { stroke: var(--border-primary); stroke-width: 1.4; opacity:.6; }`.
   (The existing proximity/collision links stay; they represent redundancy, not hierarchy.)

2. **Attention rings** around nodes that need the operator. Compute per agent:
   - **needs input** (blue ring) if `SwarmState.pending_spawns` or `SwarmState.pending_blockers`
     contains an entry with `agent_id === agent.id`, **or** `agent.status === 'pending_termination'`
     or `'syncing'`.
   - **low budget** (orange ring) if `output_tokens / max(token_budget,1) > 0.9`.
   Draw an extra ring **behind** the node circle (slightly larger r, no fill):
   ```js
   if (needsInput) svgHtml += `<circle cx=${node.x} cy=${node.y} r="29" fill="none" stroke="var(--accent-blue)" stroke-width="2"/>`;
   else if (lowBudget) svgHtml += `<circle cx=${node.x} cy=${node.y} r="29" fill="none" stroke="var(--accent-orange)" stroke-width="2"/>`;
   ```
   Add a small legend row above the SVG: green=exploring, gray=idle, ✓=done, blue ring=needs
   input, orange ring=low budget, solid=parent→child, dashed=redundancy.

3. **Single-click vs inspector:** the node click handler currently sets `selectedAgentId`. Keep
   single-click = focus (set `selectedAgentId`, `render()`). **Add** `dblclick` on a node →
   `openInspector(agentId)` (Phase 4). Until Phase 4 lands, dblclick may no-op.

### 3.4 Timeline view — `renderTimeline(container)`
A vertical, scrollable stream (newest at bottom). Two modes:
- **Agent-scoped** (when `UIState.selectedAgentId` is set): reuse `renderAgentChatTab`'s structure
  for that agent — render its `thought_traces` as bubbles and keep the chat input that posts to
  `/api/agents/<id>/chat`. Easiest: set `UIState.editingAgentId = selectedAgentId` and call
  `renderAgentChatTab(container)`.
- **Swarm-wide** (no selection): merge `thought_traces` across all agents (tag each with its
  `Agent <id>`), sort by `timestamp`, render the last ~40 as a stream; **interleave decision
  cards** for each `pending_spawns` / `pending_blockers` item, reusing the **exact card markup**
  from `renderAlertsPanel` (the spawn card with `approve-spawn`/`reject-spawn`, the blocker card
  with `resolve-blocker` + `data-choice`). Add a command/`@mention` hint at the bottom (the real
  input is the global command bar).

### 3.5 CSS (append to `styles.css`)
`.stage{display:flex;flex-direction:column;height:100%}`,
`.stage__toolbar{display:flex;align-items:center;justify-content:space-between;padding:6px 10px;border-bottom:1px solid var(--border-secondary)}`,
`.seg{display:inline-flex;border:1px solid var(--border-primary);border-radius:var(--radius-md);overflow:hidden}`,
`.seg__btn{font-size:.72rem;padding:4px 12px;background:var(--bg-tertiary);color:var(--text-secondary);border:none;cursor:pointer}`,
`.seg__btn--on{background:var(--accent-blue);color:#fff}`,
`.stage__body{flex:1;overflow:auto;position:relative}`,
`.cluster-edge{stroke:var(--border-primary)}`.

### 3.6 Acceptance criteria
- [ ] Toggling `Map`/`Timeline` swaps the center without a full page reload and keeps the selected
      agent. Active segment is highlighted.
- [ ] With >1 agent, Map shows first; with 1 agent, Timeline shows first.
- [ ] Map shows solid arrowed parent→child edges **and** the existing dashed proximity/collision
      links, plus boundary hulls; a node with a pending spawn/blocker shows a **blue** ring; a
      node over 90% budget shows an **orange** ring; legend present.
- [ ] Timeline (swarm-wide) shows recent thought traces from multiple agents and renders working
      Approve/Reject and Workaround/Bypass/Kill buttons (verify they POST and toast).
- [ ] Console has zero errors after toggling and clicking.

---

## 4. PHASE 3 — Right panel becomes the Editor (kill Workspace/Editor duplication)

**Goal:** the right panel is a single **code editor**; the `Workspace` activity-bar view and the
`Code Editor` right-tab stop being two separate things.

- The right panel currently has two tabs (`right-tab-editor`, `right-tab-activity`) rendered by
  `renderAlertsPanel`. **Phase 3:** make the right panel **always the editor** (move "Activity"
  to the bottom drawer in Phase 5). For now: when `rightPanelTab==='editor'`, render the editor;
  leave `'activity'` working until Phase 5 removes it.
- Make the editor reuse `renderWorkspaceTab`'s file-tree + code-viewer logic. Show **file tabs**
  across the top (one per file in `UIState.workspaceData.files`), a breadcrumb, and line-numbered
  contents. Selecting a file uses the existing `select-file` action.
- Remove the `Workspace` icon from the activity bar in `index.html` (its function now lives in the
  right Editor, driven by `selectedAgentId`). Keep `renderWorkspaceTab` (the editor calls into it)
  — do not delete the function.
- **Selection wiring:** when `selectedAgentId` changes (the `select-agent` case), set
  `selectedWorkspaceAgent = selectedAgentId` and clear `workspaceData` so the editor loads that
  agent's files (this already happens — verify).

**Acceptance:** clicking an agent loads its files into the right editor; switching files works;
there is no longer both a center "Workspace" view and a right "Code Editor" showing the same files.

---

## 5. PHASE 4 — Inspector (right slide-over): Overview · Budget · Trace · Memory

**Goal:** a contextual, agent-scoped panel that opens on **double-click / details icon**, with
four sub-tabs. This folds the center `Trace` and `Memory` views and the agent detail card into one
place.

### 5.1 State + dispatch
- `UIState.inspectorOpen = false`, `UIState.inspectorTab = 'overview'`.
- Cases: `open-inspector` (`UIState.inspectorOpen=true; UIState.selectedAgentId=data-agent-id; render()`),
  `close-inspector`, `switch-inspector-tab` (`UIState.inspectorTab=data-tab; render()`).
- Rail rows: keep single-click = `select-agent` (focus). Add a **details icon** button per row
  with `data-action="open-inspector"`, and add `ondblclick`→open-inspector on the row.

### 5.2 DOM + render
- Add a slide-over container to `index.html` (mirror the existing `#agent-edit-panel`
  slide-panel + `#slide-backdrop` pattern) with id `inspector`, plus a sub-tab header.
- Add `renderInspector()` to `render()`. When `inspectorOpen && selectedAgentId`, populate the
  active sub-tab into `#inspector-body`:
  - **Overview** → reuse `renderClusterSidebar(selectedAgentId)` content (role, goal, similarity).
  - **Budget** → the per-agent budget block + `redistribute-budget` buttons from
    `renderAlertsPanel` (extract that markup into a helper both can call).
  - **Trace** → `renderTraceTab(inspectorBody)` (it already fetches `/api/trace/<id>`).
  - **Memory** → `renderMemoryTab(inspectorBody)`.
- Remove the `Trace` and `Memory` icons from the activity bar (now in the Inspector). Keep the
  render functions.

**Acceptance:** double-click an agent (or click its details icon) opens the Inspector; the four
sub-tabs show that agent's overview, budget (with working redistribute), trace, and memory;
single-click still just focuses; closing works; `render()` from SSE keeps the Inspector open and
re-scoped to `selectedAgentId`.

---

## 6. PHASE 5 — Activity / Logs bottom drawer

**Goal:** swarm-wide feeds rise from the bottom on demand; the right panel no longer needs an
Activity tab.

- `UIState.drawerOpen=false`, `UIState.drawerTab='activity'`. Cases: `open-drawer`
  (`data-tab`), `close-drawer`, `switch-drawer-tab`.
- The blue status bar already has clickable `🔔 K decisions` and `📜 Logs` items wired to
  `switch-right-tab`. **Re-point them** to `open-drawer` with `data-tab="activity"` / `"logs"`.
- Add a `#drawer` element (absolute, bottom, above the command+status bars) + `renderDrawer()` in
  `render()`. Two tabs:
  - **Activity** → decisions (spawn cards, blocker cards), collisions list, prune candidates,
    tombstones — move this markup out of `renderAlertsPanel` into the drawer.
  - **Logs** → the `SwarmState.logs` feed (reuse `renderLogTail` formatting; show more lines).
- Once the drawer owns Activity, the right panel is **editor-only**: drop the
  `right-tab-activity` tab and make `renderAlertsPanel` render just the editor (or rename it).
  Keep `alerts-count` updated as the drawer's decision badge.

**Acceptance:** clicking `K decisions` or `Logs` in the status bar opens the bottom drawer to the
right tab; approve/reject/resolve/prune all work from inside the drawer; the right panel shows only
the editor; the decision count badge stays accurate via SSE.

---

## 7. PHASE 6 — Consolidated Init modal (segmented compute presets)

**Goal:** one "Initialize Swarm Task" modal; no separate launch modal; compute budget as
segmented presets with an advanced reveal.

- There are currently two entry points: `#init-overlay` (center, when no agents) and
  `#launch-modal` (the agent designer). **Merge** into the init flow:
  - Keep `#init-overlay`'s fields (`init-goal`, `init-provider`, `init-budget`).
  - Replace the numeric `init-budget` with a **segmented control** `Small | Medium | Large`
    mapping to token caps (e.g. `5000 / 20000 / 50000` — confirm values in
    `simplified_ui_design.md` §7) plus an **"Advanced ▸ exact tokens"** disclosure that reveals a
    number input. Store the chosen value where `init-budget` is read today.
  - Fold the **agent designer** (the `#designer-agents` list + `add-designer-agent` /
    `remove-designer-agent` / `update-designer-role` / `update-designer-goal`) into an expandable
    "Configure agents (optional)" section of the **same** modal. Route launch through the existing
    `initLaunch()` (it POSTs `/api/config` then `/api/run`).
- Remove the separate `#launch-modal` and its `open-launch`/`close-launch`/`launch-swarm` path, or
  make `open-launch` open the unified init modal. Keep all underlying API calls.

**Acceptance:** with no swarm running, one modal launches a swarm with a preset or exact budget and
optional custom agents; the old separate launch modal is gone; `+ New swarm` opens the same modal.

---

## 8. Pitfalls & gotchas (read before you start)

- **`render()` wipes `innerHTML`.** Inputs you typed into (chat, budget editors) lose focus/value
  on re-render. The existing code rebuilds them from state; follow that pattern. For the command
  bar this is avoided because it's outside the re-rendered regions — keep it that way.
- **Element ids created *inside* render output** (e.g. `cluster-svg-parent`, `stage-body`) are
  fine to `getElementById` *right after* you set the parent's `innerHTML`, in the same function.
- **The map SVG uses a `viewBox="0 0 1000 600"`** and lays out around `cx=500, cy=300`. Keep new
  SVG elements in that coordinate space.
- **Status values** are exactly: `exploring`, `syncing`, `pending_termination`, `completed`,
  `dead`. Map them to colors via the existing `node--<status>` classes; don't invent new ones.
- **Defensive defaults everywhere** — agents mid-spawn may lack `output_tokens`, `token_budget`,
  `thought_traces`, etc.
- **Don't touch the backend** except Phase-specific endpoints (none of 2–6 require new endpoints;
  everything needed already exists, including `/api/synthesis`).
- **`--accent-orange`** exists in `:root` (`#ce9178`) — use it for the low-budget ring.
- Test with **`--llm-provider rules`** so you don't need Ollama; the UI is identical.

---

## 9. Definition of done (per phase, then overall)

For **each** phase: (1) feature works in the browser with the `rules` provider, (2) **zero console
errors**, (3) SSE updates still re-render correctly (start a run or edit state and watch it
update), (4) no previously-working feature regressed (spot-check: select agent, view files, view
trace, open memory, approve/reject a spawn, resolve a blocker, edit budget, clean state, launch a
swarm), (5) `python3 -m unittest discover tests` still passes (you shouldn't be touching backend,
but confirm).

**Overall done:** the dashboard matches the layout in `ui_design_document.md` §3 — activity bar,
agents rail, center Map⇄Timeline stage (clustered map with attention rings), right Editor,
on-demand Inspector and Activity/Logs drawer, blue status bar, command bar, and one Init modal —
with every `design_doc.md` feature reachable (see the coverage map in `ui_design_document.md` §7).

---

## 10. Suggested order & smallest-safe commits

Do phases **in order** (2→6); each is independently shippable and leaves the app working. Commit
after each phase with a message like `feat(ui): phase N — <summary>`. Within a phase, prefer the
sequence: add `UIState` fields → add CSS → add HTML containers (preserving ids) → add render
function + wire into `render()` → add dispatcher cases → verify in browser.
