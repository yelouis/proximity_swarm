# Proximity Swarm V3 — Bug Fix Specification

> **Companion to [`ongoing_bugs.md`](ongoing_bugs.md).** This is an implementation spec for an
> engineer/LLM to resolve the five bugs found while validating
> [Journey 1](designs/user_journeys.md). Each fix lists the exact files/functions, current vs.
> desired behavior, concrete code guidance, acceptance criteria, and tests.
>
> **Dev workflow reminders:** tests run via `python3 -m unittest` (no pytest). The web dashboard
> serves `static/` from disk per request (frontend edits need only a browser reload; **backend
> edits in `web_dashboard.py` / `supervisor.py` / `proximity_monitor.py` / `agent_runner.py`
> require restarting the server**). Use a throwaway port (e.g. `8095`) — do not kill the
> operator's `:8080` instance. Ollama (`gemma4:latest`) is available locally.

---

## 0. Verification summary (read before implementing)

All five reported bugs are **real and reproducible**. Two root-cause details in `ongoing_bugs.md`
were inaccurate and are corrected here:

| Bug | Status | Correction to the report |
|---|---|---|
| 1 — Spawn auto-approval | Confirmed | Root cause accurate. (`web_dashboard.py` → `supervisor.py` → `proximity_monitor.py` chain.) |
| 2 — Blocking launch | Confirmed (symptom) | The server **is** threaded (`ThreadedHTTPServer(ThreadingMixIn,…)`). The blocking affects only the launching client's request (and thus the UI await), **not** the whole server/SSE. |
| 3 — Orphaned pending spawns | Confirmed | `evaluate_isolation_spawn()` is **not** "at the beginning of `execute_step()`" — it runs near the **end** (`agent_runner.py:967`), right before completion (`:983-988`). Mechanism is otherwise correct. |
| 4 — Inconsistent confirm | Confirmed | Root cause accurate. |
| 5 — No deselect gesture | Confirmed | Root cause accurate (`selectedAgentId` is never set to `null` except by a page reload). |

**Critical coupling the report missed:** **Bugs 1 and 3 are interdependent.** Enabling approval
(fix 1) makes fix 3 *mandatory*: an approved request on a `completed` agent is silently dropped,
because `proximity_monitor.load_active_agents()` excludes `completed` agents, so the monitor never
acts on the approval. They must be implemented together (see [Fix 1+3](#fix-13-coupled-spawn-approval-toggle--parentchild-join)).

**Two safety facts that constrain the design (verified in code):**
1. `proximity_monitor.py` has **no `input()` calls** — flipping its spawn-gating flag is safe in a
   headless subprocess.
2. `agent_runner.py` **does** call `input()` (line 1399, collision negotiation) and `supervisor.py`
   forwards `--interactive` to the runner. **Therefore the spawn-approval feature must use a NEW,
   dedicated flag — do not reuse `--interactive`,** or the web-launched runner will hang on stdin.

---

## 1. Decisions incorporated (from the product owner)

- **Spawn approval = a toggle.** Default behavior is **require operator approval**; an
  **"auto-approve spawns"** setting restores instant spawning. Plumb a dedicated flag
  `web_dashboard → supervisor → proximity_monitor`, plus an init-modal checkbox.
- **Parent–child join semantics (for Bug 3):** *"An agent shouldn't be allowed to finish if it
  created a spawn without getting the spawn's output as input to its own results. A parent that has
  finished its own task while the child is still running should be able to **check in** with the
  child and **decide whether it is worth waiting** for the child's result."*
  → A parent **must not transition to `completed` while it has an unresolved spawn/child.** It
  enters an `awaiting_child` state, ingests child output when ready, and otherwise makes an explicit
  wait-vs-proceed decision (with a deadlock cap so it can never hang forever).

---

## 2. Recommended implementation order

1. **Fix 4** (confirm parity) — trivial, isolated warm-up.
2. **Fix 5** (deselect) — frontend-only, isolated.
3. **Fix 2** (async launch) — backend-only, isolated; improves the loop for testing the rest.
4. **Fix 1 + 3** (spawn approval toggle + parent–child join) — the substantial, coupled change.

Each step leaves the app working and is independently testable.

---

## Fix 4 — Consistent destructive-action confirmation

**Bug:** `/clean all` in the command bar runs instantly; the gear-menu "Clean Everything" prompts.

**File:** `static/app.js` — command-bar `keydown` handler, the `if (input.startsWith('/clean'))`
branch (≈ line 2619).

**Reference (existing dropdown logic to match), `case 'clean'` ≈ line 2521:**
```js
if (target.dataset.target === 'all') {
    if (!confirm('This will clean ALL swarm state. Continue?')) return;
}
```

**Change:** add the same guard to the command path before the POST:
```js
if (input.startsWith('/clean')) {
    const parts = input.split(/\s+/);
    const target = parts[1] || 'all';
    if (target === 'all' && !confirm('This will clean ALL swarm state. Continue?')) return;
    apiPost('/api/clean', { target }).then(r => {
        showToast(r.success ? `Cleaned: ${(r.cleaned || []).join(', ')}` : 'Failed',
                  r.success ? 'success' : 'error');
    });
}
```
This achieves exact parity with the dropdown (only `all` confirms). *(Optional hardening: also
confirm for `memory` and `workspaces`; if you do, apply the same to the dropdown handler so the two
stay consistent.)*

**Acceptance:** `/clean all` shows a confirm; Cancel aborts (no POST, no toast); OK proceeds.
`/clean logs` still runs without a prompt (parity).

---

## Fix 5 — Deselect / clear-selection gesture

**Bug:** once an agent is selected, `selectedAgentId` is only reset by a full page reload, so the
global (unscoped) Timeline is unreachable.

**File:** `static/app.js`. Add **three** ways to clear selection, all doing
`UIState.selectedAgentId = null; render();`.

**(a) Click empty map canvas.** In `renderSwarmMap`, the SVG click handler (≈ line 1150) currently
only handles clicks that hit `.cluster-node`. Add an else-branch:
```js
svgParent.querySelector('svg').addEventListener('click', (e) => {
    const nodeG = e.target.closest('.cluster-node');
    if (nodeG) {
        /* …existing selection code… */
    } else {
        UIState.selectedAgentId = null;   // clicked empty canvas → deselect
        render();
    }
});
```

**(b) `Esc` key.** Add a document-level `keydown` listener (place near the existing
`command-input` listener ≈ line 2590). Guard against typing contexts and other Esc handlers:
```js
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
    if (UIState.inspectorOpen) return;   // let Esc-to-close-inspector win if you add that
    if (UIState.selectedAgentId !== null) {
        UIState.selectedAgentId = null;
        render();
    }
});
```

**(c) An explicit affordance.** When an agent is selected, render a small "✕ Show all agents"
button in the stage toolbar (`renderStage`, ≈ line 1196) or the cluster sidebar header, carrying
`data-action="deselect-agent"`. Add the case to the delegated click handler (the big `switch` ≈
line 2358):
```js
case 'deselect-agent':
    UIState.selectedAgentId = null;
    render();
    break;
```

**Note:** `renderTimeline` already shows the global interleaved stream when `selectedAgentId` is
`null` (line 1217), so no timeline change is needed. After this fix, **update
[`designs/user_journeys.md`](designs/user_journeys.md) Journey 1 §1.5**, which currently documents
the absence of a deselect gesture as a workaround.

**Acceptance:** select an agent (rail or map) → Timeline scopes to it and its node shows selected.
Then Esc, or click empty canvas, or click "Show all" → no node selected, Timeline returns to the
global stream, **without a page reload**.

---

## Fix 2 — Non-blocking (async) swarm launch

**Bug:** `POST /api/run` blocks ~30s (sequential `generate_task_steps_via_llm` per agent) before the
supervisor starts and the response returns; the UI stays `IDLE` the whole time.

**File:** `web_dashboard.py` — `launch_swarm()` (≈ line 425) and, indirectly, the `/api/run`
handler (≈ line 895). The server is already `ThreadingMixIn`, so backgrounding is safe.

**Change:** flip state synchronously (so the UI reacts immediately), then do decomposition +
supervisor launch on a daemon thread; return right away.

```python
def launch_swarm(goal, agents_config, budget):
    if server_state["swarm_running"]:
        return False, "Swarm is already running"

    server_state["macro_goal"] = goal
    server_state["session_budget"] = budget
    server_state["swarm_running"] = True          # optimistic: UI flips to RUNNING now
    write_to_monitor_log(f"Launching swarm for goal: '{goal}' "
                         f"with {len(agents_config)} agents", "INFO")

    def _bg_launch():
        try:
            # ── move the EXISTING body here unchanged: ──
            #   • write orchestrator.json
            #   • for each agent: generate_task_steps_via_llm(...) + register_dynamic_task(...)
            #   • build cmd, subprocess.Popen(supervisor.py, ...)
            #   • set server_state["supervisor_proc"], start the monitor_proc watcher thread
            ...
        except Exception as ex:
            server_state["swarm_running"] = False
            write_to_monitor_log(f"Swarm launch failed: {ex}", "ERROR")

    threading.Thread(target=_bg_launch, daemon=True).start()
    return True, f"Swarm launching with {len(agents_config)} agents…"
```
The `/api/run` handler is unchanged — it calls `launch_swarm` and returns its (now immediate)
result.

**Required companion frontend guard (`static/app.js`, `render()` ≈ line 133).** Today the init
overlay shows whenever `agents.length === 0`. With an async launch there is a window where
`swarm_running === true` but no agent files exist yet — the overlay would **wrongly reappear**.
Guard it:
```js
const showInit = ((!SwarmState.swarm_running && SwarmState.agents.length === 0)
                  || UIState.initModalOpen);
```
*(Optional polish: while `swarm_running && agents.length === 0`, show a "Decomposing goals…"
placeholder in the viewport so the user has feedback until nodes appear.)*

**Acceptance:** clicking **🐝 Launch Swarm Task** returns in < ~1s; the status pill flips to
**RUNNING** immediately; the init overlay closes and does **not** fl/reappear; agent nodes populate
via SSE as decomposition finishes; no ~30s dead window. If decomposition/launch throws,
`swarm_running` resets to `false` and an error is logged (visible in the Logs drawer).

**Test:** unit-test that `launch_swarm` returns quickly and sets `swarm_running=True` before the
subprocess exists (mock `subprocess.Popen` and `generate_task_steps_via_llm` with a sleep; assert
return latency and state). Manual: launch a 4-agent Ollama swarm and confirm the pill flips
instantly.

---

## Fix 1+3 (coupled) — Spawn approval toggle + parent–child join

This is the core change. **Part A** makes spawns require approval by default (toggleable). **Part B**
makes a parent agent wait for / ingest its spawned child's output and never strand a pending request.

### Architecture refresher (spawn lifecycle today)
1. `AgentRunner.evaluate_isolation_spawn()` (`agent_runner.py:495`, called at `:967` near the end of
   `execute_step`) may call `request_spawn_agent()`, writing `state["spawn_request"] = {status:
   "pending", goal, …}`.
2. `proximity_monitor.handle_spawn_requests()` (`:261`) runs over `load_active_agents()` (`:228`,
   statuses `exploring|syncing|pending_termination`). With `INTERACTIVE=False` it **skips the
   pending check and spawns immediately**; it creates the child agent file, clears the parent's
   `spawn_request`, and appends the child id to `parent["children"]`.
3. `web_dashboard.handle_approve/handle_reject` set `spawn_request.status` to `approved`/`rejected`.
   `get_full_state()` (`:336`) lists any agent's `pending` request in `pending_spawns` (drives 🔔).

### Part A — Approval toggle (Bug 1)

Introduce a dedicated flag **`--auto-approve-spawns`** (default off ⇒ approval required). **Do not
reuse `--interactive`** (see §0 safety fact #2).

**`proximity_monitor.py`:**
- Add module global `AUTO_APPROVE_SPAWNS = False` (next to `INTERACTIVE` ≈ line 258).
- In `main()` argparse (≈ line 783): `parser.add_argument("--auto-approve-spawns",
  action="store_true", help="Spawn child agents immediately without operator approval")`; then
  `AUTO_APPROVE_SPAWNS = args.auto_approve_spawns` (≈ line 788).
- In `handle_spawn_requests()` (`:261`), change the gate from `if INTERACTIVE:` to
  `if not AUTO_APPROVE_SPAWNS:` — keep the inner logic identical:
  - `status == "pending"` → `continue` (wait for the operator);
  - `status == "rejected"` → clear `spawn_request`, `continue`;
  - `status == "approved"` (and the auto path) → fall through to the existing spawn block.
  (`INTERACTIVE` is now unused for spawns; leave the `--interactive` flag as-is for collision
  negotiation, or remove its spawn coupling — but do not pass it from the web dashboard.)

**`supervisor.py`:**
- `run_swarm(..., auto_approve_spawns=False)` new kwarg (≈ line 99).
- When building `monitor_cmd` (≈ line 147): `if auto_approve_spawns:
  monitor_cmd.append("--auto-approve-spawns")`.
- argparse (≈ line 326): add `--auto-approve-spawns` (store_true); pass
  `auto_approve_spawns=args.auto_approve_spawns` into the `run_swarm(...)` calls (≈ lines 338/354/376).
- **Do not** add `--interactive` to the agent-runner `cmd`.

**`web_dashboard.py`:**
- `server_state` (≈ line 42): add `"auto_approve_spawns": False`.
- `/api/config` POST (≈ line 885): accept and store `auto_approve_spawns` if present
  (`if "auto_approve_spawns" in body: server_state["auto_approve_spawns"] = bool(...)`).
- `launch_swarm` cmd builder (≈ line 482): `if server_state["auto_approve_spawns"]:
  cmd.append("--auto-approve-spawns")`.

**Frontend (`static/index.html` + `static/app.js`):**
- In the init modal (near the provider/budget row in `index.html`, ≈ line 92), add:
  ```html
  <label class="form-checkbox" style="display:flex; align-items:center; gap:6px; font-size:0.75rem;">
      <input type="checkbox" id="init-auto-approve">
      Auto-approve spawn requests (default: ask me first)
  </label>
  ```
- In `initLaunch()` (`app.js` ≈ line 2723), read it and include in the config POST:
  ```js
  const autoApprove = document.getElementById('init-auto-approve')?.checked || false;
  await apiPost('/api/config', { llm_provider: provider, auto_approve_spawns: autoApprove });
  ```
- No new approve/reject UI is needed — `data-action="approve-spawn"/"reject-spawn"` and the decision
  cards already exist; with the toggle **off** they will finally appear and function (the monitor now
  waits).

### Part B — Parent–child join (Bug 3, per the owner's spec)

Goal: a parent that spawned a child **does not complete** until the child's spawn is resolved; it
**checks in**, **ingests** the child's output, or **decides** to proceed without it (bounded).

**New agent status:** `awaiting_child`.

**`agent_runner.py` changes:**

1) **Detect unresolved spawns/children** — new helper:
```python
def has_unresolved_spawn(self):
    sr = self.state.get("spawn_request") or {}
    if sr.get("status") in ("pending", "approved"):
        return True                      # awaiting approval, or approved but child not created/done
    for child_id in self.state.get("children", []):
        child = load_json(os.path.join(AGENTS_DIR, f"agent_{child_id}.json"))
        if child and child.get("status") not in ("completed", "dead"):
            return True                  # child still running
    return False
```

2) **Gate completion** — replace the inline completions (the "all steps done" block at
`:983-988`, the final-step completion at ≈ `:1312`, and optionally the missing-task path at
`:974-977`) with a single guard:
```python
def finalize_or_await(self):
    """Complete, unless a spawned child is still unresolved — then await it."""
    if self.has_unresolved_spawn():
        if self.state.get("status") != "awaiting_child":
            self.state["status"] = "awaiting_child"
            self.add_thought_trace(
                "Finished my own steps but a spawned child is unresolved. "
                "Holding completion to check in on it.", "evaluating")
            save_json(self.state_file, self.state)
        return False
    self.state["status"] = "completed"
    self.state["progress"] = 100
    save_json(self.state_file, self.state)
    self.save_memory_episode()
    return True
```
e.g. the `:983-988` block becomes:
```python
if completed_count >= len(steps):
    print(f"Agent {self.agent_id} has completed all steps of Task {task_id}.")
    self.finalize_or_await()
    return
```

3) **Handle `awaiting_child` at the top of `execute_step`** — mirror the existing
`pending_termination` (`:871`) and `syncing` (`:884`) branches:
```python
if self.state["status"] == "awaiting_child":
    self.check_in_on_children()
    return
```

4) **Check-in + decision loop** (the owner's "check in and decide if it's worth waiting"):
```python
MAX_AWAIT_ITERS = 20   # deadlock cap → guarantees termination

def check_in_on_children(self):
    if not self.has_unresolved_spawn():
        self.ingest_child_outputs()          # child(ren) done (or request rejected): take results
        self.finalize_or_await()             # now actually completes
        return

    iters = self.state.get("await_iters", 0) + 1
    self.state["await_iters"] = iters
    if iters > MAX_AWAIT_ITERS:
        self.add_thought_trace("Waited too long for child result; finalizing without it.", "decision")
        self.ingest_child_outputs(partial=True)
        self.state["status"] = "completed"; self.state["progress"] = 100
        save_json(self.state_file, self.state); self.save_memory_episode(); return

    decision = self._decide_wait_or_proceed()    # "WAIT" | "PROCEED"
    if decision == "PROCEED":
        self.add_thought_trace("Child result not worth waiting for; finalizing now.", "decision")
        self.ingest_child_outputs(partial=True)
        self.state["status"] = "completed"; self.state["progress"] = 100
        save_json(self.state_file, self.state); self.save_memory_episode()
    else:
        self.add_thought_trace("Decided to keep waiting for the child's result.", "evaluating")
        save_json(self.state_file, self.state)
        time.sleep(self.step_delay)            # pace the next check-in
```
- `_decide_wait_or_proceed()` — query the LLM (`self.llm_provider`, with a rules fallback) given the
  parent's goal + each child's `status`/`progress`; return `"WAIT"` or `"PROCEED"`. **Rules
  fallback:** `WAIT` while any child has progress < 100 and `await_iters` is small; else `PROCEED`.
- `ingest_child_outputs(partial=False)` — for each child id, read its workspace
  (`WORKSPACES_DIR/agent_<child_id>/`) and/or a short summary, append it to the parent's context
  (e.g. a `results`/notes file in the parent workspace) and add a thought trace
  `"Ingested results from child <id>."`. This satisfies *"getting the spawn's output as input to its
  own results."* `partial=True` records whatever exists so far.

5) **Keep the runner looping while awaiting** — `agent_runner.py:1780-1781`:
```python
for _ in range(args.steps):
    runner.execute_step()
    if runner.state.get("status") in ("completed", "dead"):
        break
# drain the await state (bounded by MAX_AWAIT_ITERS inside check_in_on_children)
while runner.state.get("status") == "awaiting_child":
    runner.execute_step()
```

**`proximity_monitor.py` changes (keep awaiting parents tracked; process approvals):**
- `load_active_agents()` (`:240`): add `"awaiting_child"` →
  `["exploring", "syncing", "pending_termination", "awaiting_child"]`.
- The active filter at `:616`: same addition.
- Result: an awaiting parent stays in the active list, so `handle_spawn_requests` runs on it and an
  **approved** request actually spawns the child — eliminating the original orphan. Because the
  parent can no longer be `completed` while its request is unresolved, `get_full_state()` will not
  surface a stranded `pending` request, so the **🔔 counter resolves** on approval/rejection.

**`static/app.js` changes (surface the new state):**
- `statusLabel()` (≈ line 268): map `awaiting_child` → e.g. `"Awaiting child"`.
- Map "needs input" ring condition in `renderSwarmMap` (≈ lines 1106-1109): add
  `agent.status === 'awaiting_child'` so the parent shows a blue attention ring while it waits.
- (Optional) give `awaiting_child` a distinct node fill/legend entry (amber) so "waiting on a
  child" reads differently from "exploring."

### Edge cases (must be handled / documented)
- **Reject:** monitor clears `spawn_request` → `has_unresolved_spawn()` is False → parent completes.
  (Rejection unblocks; 🔔 clears.)
- **Auto-approve ON:** child spawns instantly; the parent still enters `awaiting_child` until the
  child finishes, then ingests and completes — preserving "ingest child output" in both modes.
- **Parent gives up (PROCEED or cap):** parent completes; **the child is left running** and still
  contributes to synthesis (default). *(Alternative if you prefer hard cancellation: set the child's
  status to `dead`/prune it — note this in the toggle/docs; default is "do not kill.")*
- **Nested spawns:** a child that itself spawns a grandchild joins on it recursively — no special
  handling needed.
- **Deadlock:** `MAX_AWAIT_ITERS` guarantees the parent terminates even if a child never finishes.

### Acceptance criteria (Fix 1+3)
- **Default (approval required):** launch a swarm whose agent spawns on its last step.
  - A spawn **decision card** appears and **persists**; 🔔 count > 0; the parent shows a blue ring
    and status `Awaiting child` — it does **not** flip to COMPLETED.
  - **Approve** → child agent appears (new node, solid parent→child edge), runs to completion; the
    parent emits an "Ingested results from child …" trace, then completes; 🔔 clears; **no orphaned
    pending request remains** in `/api/state`.
  - **Reject** → no child is created; parent completes; 🔔 clears.
- **Auto-approve ON** (init checkbox): child spawns immediately; parent still awaits the child,
  ingests, and completes.
- **Deadlock cap:** if a child is forced to never finish, the parent completes after the cap with a
  "finalizing without it" trace — no infinite hang.

### Tests (`python3 -m unittest`)
Add `tests/test_spawn_lifecycle.py` (and/or extend `tests/test_collatz_research.py`):
- `test_requires_approval_by_default` — monitor with `AUTO_APPROVE_SPAWNS=False`: a `pending`
  request is **not** spawned; an `approved` one **is**; a `rejected` one is cleared.
- `test_auto_approve_spawns_immediately` — with the flag set, a `pending` request spawns at once.
- `test_parent_awaits_child_before_completion` — a parent with an in-flight child does not reach
  `completed`; it sits in `awaiting_child`.
- `test_parent_ingests_then_completes` — once the child is `completed`, the parent ingests and
  completes.
- `test_rejected_spawn_unblocks_parent` — rejection lets the parent complete.
- `test_await_deadlock_cap` — a never-finishing child still lets the parent complete after the cap.
- `test_completed_parent_not_required` (monitor) — `awaiting_child` is included in
  `load_active_agents()`.

---

## 3. Cross-fix regression checks
- Re-run [Journey 1](designs/user_journeys.md): step **1.6 (approve spawn)** now works as written
  (a card appears and waits). Step **1.5** can drop the "no deselect" caveat once Fix 5 lands.
- Re-run [Journey 3](designs/user_journeys.md): collisions/negotiation are untouched by these fixes.
- Confirm `python3 -m unittest discover -s tests` is green.
- Smoke the deterministic path too: `python3 web_dashboard.py --port 8096 --llm-provider rules`
  (Appendix B of the journeys) to validate the approval/await plumbing without LLM latency.

## 4. Stable file/symbol index (line numbers are approximate — match by name)
| Symbol | File | ~line |
|---|---|---|
| `handle_spawn_requests` (spawn gate) | `proximity_monitor.py` | 261 |
| `load_active_agents` (status filter) | `proximity_monitor.py` | 228/240 |
| `INTERACTIVE` / argparse | `proximity_monitor.py` | 258 / 783-788 |
| `run_swarm` / monitor_cmd / argparse | `supervisor.py` | 99 / 147 / 326 |
| `launch_swarm` / `/api/run` / `server_state` / `/api/config` | `web_dashboard.py` | 425 / 895 / 42 / 885 |
| `get_full_state` (pending_spawns) | `web_dashboard.py` | 330-344 |
| `handle_approve` / `handle_reject` | `web_dashboard.py` | 522 / 537 |
| `execute_step` / completion / `evaluate_isolation_spawn` call | `agent_runner.py` | 864 / 983-988 / 967 |
| `request_spawn_agent` | `agent_runner.py` | 470 |
| runner main loop | `agent_runner.py` | 1780 |
| `render()` init-overlay guard | `static/app.js` | 133 |
| `renderSwarmMap` click handler / needs-input ring | `static/app.js` | 1150 / 1106 |
| command-bar `/clean` | `static/app.js` | 2619 |
| delegated click `switch` / `case 'clean'` | `static/app.js` | 2358 / 2521 |
| `initLaunch` | `static/app.js` | 2723 |
| init modal markup | `static/index.html` | 80-131 |
