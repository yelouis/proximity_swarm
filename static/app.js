/* ================================================================
   Proximity Swarm V3 — Application Logic
   SPA with SSE live updates, event delegation, and component rendering.
   ================================================================ */

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const SwarmState = {
    agents: [],
    collisions: [],
    tombstones: [],
    orchestrator: {},
    budget_alert: {},
    logs: [],
    pending_spawns: [],
    pending_blockers: [],
    swarm_running: false,
    macro_goal: '',
    session_budget: 20000,
    predefined_agents: [],
    state_hash: '',
};

const UIState = {
    activeTab: 'overview',
    selectedAgentId: null,
    editingAgentId: null,
    selectedWorkspaceAgent: null,
    selectedTraceAgent: null,
    selectedFile: null,
    workspaceData: null,
    traceData: null,
    designerAgents: [
        { role: 'Generalist', goal: '' },
    ],
};

let eventSource = null;
let reconnectTimer = null;

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
async function api(path, options = {}) {
    try {
        const res = await fetch(path, {
            headers: { 'Content-Type': 'application/json' },
            ...options,
        });
        return await res.json();
    } catch (err) {
        console.error(`API error: ${path}`, err);
        return { error: err.message };
    }
}

const apiGet = (path) => api(path);
const apiPost = (path, body) => api(path, { method: 'POST', body: JSON.stringify(body) });
const apiDelete = (path) => api(path, { method: 'DELETE' });

// ---------------------------------------------------------------------------
// SSE Connection
// ---------------------------------------------------------------------------
function connectSSE() {
    if (eventSource) {
        eventSource.close();
    }
    eventSource = new EventSource('/api/events');

    eventSource.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            const prevHash = SwarmState.state_hash;
            Object.assign(SwarmState, data);
            if (data.state_hash !== prevHash) {
                render();
            }
        } catch (e) {
            console.error('SSE parse error:', e);
        }
    };

    eventSource.onerror = () => {
        eventSource.close();
        eventSource = null;
        // Reconnect after 3 seconds
        clearTimeout(reconnectTimer);
        reconnectTimer = setTimeout(connectSSE, 3000);
    };
}

// ---------------------------------------------------------------------------
// Toast Notifications
// ---------------------------------------------------------------------------
function showToast(message, type = 'info') {
    const container = document.getElementById('toast-container');
    const toast = document.createElement('div');
    toast.className = `toast toast--${type}`;
    toast.textContent = message;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.opacity = '0';
        toast.style.transform = 'translateX(100%)';
        toast.style.transition = 'all 0.3s ease';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ---------------------------------------------------------------------------
// Render Engine
// ---------------------------------------------------------------------------
function render() {
    renderStatusPill();
    renderAgentSidebar();
    renderAlertsPanel();
    renderViewportContent();
    renderLogTail();
}

// ---------------------------------------------------------------------------
// Status Pill
// ---------------------------------------------------------------------------
function renderStatusPill() {
    const pill = document.getElementById('status-pill');
    const label = document.getElementById('status-label');
    if (SwarmState.swarm_running) {
        pill.className = 'status-pill status-pill--running';
        label.textContent = 'RUNNING';
    } else {
        pill.className = 'status-pill status-pill--idle';
        label.textContent = SwarmState.agents.length > 0 ? 'COMPLETED' : 'IDLE';
    }
}

// ---------------------------------------------------------------------------
// Agent Sidebar
// ---------------------------------------------------------------------------
function renderAgentSidebar() {
    const list = document.getElementById('agent-list');
    const countBadge = document.getElementById('agent-count');
    const agents = SwarmState.agents;
    countBadge.textContent = agents.length;

    if (agents.length === 0) {
        list.innerHTML = `
            <div class="empty-state">
                <div class="empty-state__icon">🤖</div>
                <div class="empty-state__title">No Agents Yet</div>
                <div class="empty-state__desc">Launch a new swarm to see agents appear here.</div>
            </div>
        `;
        return;
    }

    let html = '';
    for (const agent of agents) {
        const status = agent.status || 'unknown';
        const progress = computeProgress(agent);
        const role = agent.personality || agent.role || 'Generalist';
        const goal = agent.goal || agent.task_id || '';
        const truncGoal = goal.length > 80 ? goal.slice(0, 77) + '...' : goal;
        const isSelected = UIState.selectedAgentId === agent.id;

        html += `
            <div class="agent-card agent-card--${status} ${isSelected ? 'agent-card--selected' : ''}"
                 data-action="select-agent" data-agent-id="${agent.id}">
                <div class="agent-card__header">
                    <span class="agent-card__id">Agent ${agent.id}</span>
                    <span class="agent-card__status agent-card__status--${status}">${statusLabel(status)}</span>
                </div>
                <div class="agent-card__role">${escapeHtml(role)}</div>
                <div class="agent-card__goal">${escapeHtml(truncGoal)}</div>
                <div class="progress-bar">
                    <div class="progress-bar__fill" style="width: ${progress}%"></div>
                </div>
                <div class="agent-card__actions">
                    <button class="btn btn--sm btn--ghost" data-action="view-workspace" data-agent-id="${agent.id}" title="View workspace">📁</button>
                    <button class="btn btn--sm btn--ghost" data-action="view-trace" data-agent-id="${agent.id}" title="View trace">🔍</button>
                    <button class="btn btn--sm btn--ghost" data-action="edit-agent" data-agent-id="${agent.id}" title="Edit agent">✏️</button>
                    ${status !== 'completed' && status !== 'dead' ? `<button class="btn btn--sm btn--danger" data-action="prune-agent" data-agent-id="${agent.id}" title="Prune agent">✕</button>` : ''}
                </div>
            </div>
        `;
    }
    list.innerHTML = html;
}

function getStepNumber(agent) {
    const cs = agent.current_step;
    if (cs == null) return agent.steps_completed || 0;
    if (typeof cs === 'number') return cs;
    if (typeof cs === 'object' && cs.step_id != null) return cs.step_id;
    return agent.steps_completed || 0;
}

function computeProgress(agent) {
    const steps = agent.steps || [];
    const current = getStepNumber(agent);
    const total = steps.length || agent.total_steps || 1;
    if (agent.status === 'completed') return 100;
    if (agent.status === 'dead') return 0;
    return Math.min(Math.round((current / total) * 100), 100);
}

function statusLabel(status) {
    const labels = {
        exploring: '● Active',
        completed: '✓ Done',
        dead: '✕ Dead',
        syncing: '⟳ Syncing',
        pending_termination: '⚠ Blocked',
    };
    return labels[status] || status;
}

// ---------------------------------------------------------------------------
// Alerts Panel
// ---------------------------------------------------------------------------
function renderAlertsPanel() {
    const list = document.getElementById('alerts-list');
    const countBadge = document.getElementById('alerts-count');

    const budgetAlert = SwarmState.budget_alert || {};
    const budgetExceeded = budgetAlert.budget_exceeded || false;

    let alertCount = SwarmState.pending_spawns.length + SwarmState.pending_blockers.length + SwarmState.collisions.length + (budgetExceeded ? 1 : 0);
    countBadge.textContent = alertCount;

    let html = '';

    // Budget Widget
    const maxTokens = budgetAlert.active_count || getMaxLeafTokens();
    const budgetCap = SwarmState.session_budget || 20000;
    const budgetPct = Math.min((maxTokens / budgetCap) * 100, 100);
    const budgetBarClass = budgetPct > 90 ? 'budget-widget__bar-fill--exceeded' : budgetPct > 70 ? 'budget-widget__bar-fill--warning' : '';

    html += `
        <div class="budget-widget">
            <div class="budget-widget__label">Output Token Budget</div>
            <div class="budget-widget__value ${budgetExceeded ? 'budget-widget__value--exceeded' : ''}"
                 data-action="edit-budget" title="Click to edit budget cap">
                ${maxTokens.toLocaleString()} / ${budgetCap.toLocaleString()}
            </div>
            <div class="budget-widget__bar">
                <div class="budget-widget__bar-fill ${budgetBarClass}" style="width: ${budgetPct}%"></div>
            </div>
        </div>
    `;

    if (budgetExceeded) {
        html += `
            <div class="decision-card decision-card--blocker">
                <div class="decision-card__type decision-card__type--blocker">BUDGET EXCEEDED</div>
                <div class="decision-card__title">Output tokens cap reached!</div>
                <div class="decision-card__desc" style="margin-bottom: 0;">
                    Leaf agent tokens: <strong>${maxTokens.toLocaleString()}</strong> / Cap: <strong>${budgetCap.toLocaleString()}</strong>
                    <br><br>
                    <strong>Leaf Pruning Candidates:</strong>
                    <div style="margin-top: var(--space-sm); display: flex; flex-direction: column; gap: var(--space-sm);">
                        ${(budgetAlert.candidates || []).map((c) => `
                            <div style="border-top: 1px solid var(--border-secondary); padding-top: var(--space-xs);">
                                <div style="font-family: var(--font-mono); font-weight: 600; color: var(--accent-cyan); font-size: 0.72rem; margin-bottom: 2px;">Agent ${escapeHtml(c.id)}</div>
                                <div style="font-size: 0.68rem; color: var(--text-secondary); margin-bottom: var(--space-xs); line-height: 1.4;">${escapeHtml(c.reason || 'No explanation')}</div>
                                <button class="btn btn--danger btn--sm" data-action="prune-agent" data-agent-id="${c.id}">🔥 Prune Agent ${c.id}</button>
                            </div>
                        `).join('')}
                        ${(budgetAlert.candidates || []).length === 0 ? '<div style="font-size: 0.68rem; color: var(--text-muted);">No candidates to prune.</div>' : ''}
                    </div>
                </div>
            </div>
        `;
    }

    // Pending Spawn Decisions
    if (SwarmState.pending_spawns.length > 0) {
        html += '<div class="section-label">⚡ Pending Spawns</div>';
        for (const spawn of SwarmState.pending_spawns) {
            html += `
                <div class="decision-card decision-card--spawn">
                    <div class="decision-card__type decision-card__type--spawn">SPAWN REQUEST</div>
                    <div class="decision-card__title">Agent ${escapeHtml(spawn.agent_id)}</div>
                    <div class="decision-card__desc">
                        <strong>Goal:</strong> ${escapeHtml(spawn.goal)}<br>
                        <strong>Reason:</strong> ${escapeHtml(spawn.reason)}
                    </div>
                    <div class="decision-card__actions">
                        <button class="btn btn--success btn--sm" data-action="approve-spawn" data-agent-id="${spawn.agent_id}">✓ Approve</button>
                        <button class="btn btn--danger btn--sm" data-action="reject-spawn" data-agent-id="${spawn.agent_id}">✕ Reject</button>
                    </div>
                </div>
            `;
        }
    }

    // Pending Blockers
    if (SwarmState.pending_blockers.length > 0) {
        html += '<div class="section-label">🚧 Blockers</div>';
        for (const blocker of SwarmState.pending_blockers) {
            const blk = blocker.blocker || {};
            html += `
                <div class="decision-card decision-card--blocker">
                    <div class="decision-card__type decision-card__type--blocker">BLOCKER</div>
                    <div class="decision-card__title">Agent ${escapeHtml(blocker.agent_id)}</div>
                    <div class="decision-card__desc">
                        <strong>File:</strong> ${escapeHtml(blk.file_path || 'N/A')}<br>
                        <strong>Tool:</strong> ${escapeHtml(blk.tool_used || 'N/A')}<br>
                        <strong>Error:</strong> ${escapeHtml(blk.error_message || 'Unknown error')}
                    </div>
                    <div class="decision-card__actions">
                        <button class="btn btn--success btn--sm" data-action="resolve-blocker" data-agent-id="${blocker.agent_id}" data-choice="1">🔧 Workaround</button>
                        <button class="btn btn--warning btn--sm" data-action="resolve-blocker" data-agent-id="${blocker.agent_id}" data-choice="2">⏭ Bypass</button>
                        <button class="btn btn--danger btn--sm" data-action="resolve-blocker" data-agent-id="${blocker.agent_id}" data-choice="3">💀 Kill</button>
                    </div>
                </div>
            `;
        }
    }

    // Collisions
    if (SwarmState.collisions.length > 0) {
        html += '<div class="section-label">⚡ Collisions</div>';
        for (const col of SwarmState.collisions) {
            html += `
                <div class="collision-entry">
                    <div class="collision-entry__agents">
                        Agent ${escapeHtml(col.agent_a || '?')} ↔ Agent ${escapeHtml(col.agent_b || '?')}
                    </div>
                    <div class="collision-entry__detail">
                        Distance: ${(col.distance || 0).toFixed(3)} | Status: ${escapeHtml(col.status || 'active')}
                    </div>
                </div>
            `;
        }
    }

    // Tombstones
    if (SwarmState.tombstones.length > 0) {
        html += '<div class="section-label">💀 Tombstones</div>';
        for (const tomb of SwarmState.tombstones) {
            if (tomb.file_path) {
                html += `
                    <div class="tombstone-entry">
                        <div class="tombstone-entry__agent">⚡ BLOCKER FAILURE</div>
                        <div class="tombstone-entry__reason" style="line-height: 1.45;">
                            <strong>File:</strong> ${escapeHtml(tomb.file_path)}<br>
                            <strong>Tool:</strong> ${escapeHtml(tomb.tool_used)}<br>
                            <strong>Error:</strong> <span style="color: var(--accent-red);">${escapeHtml(tomb.error_message)}</span><br>
                            <strong>Fix:</strong> <span style="color: var(--accent-green);">${escapeHtml(tomb.fix_action)}</span>
                        </div>
                    </div>
                `;
            } else {
                html += `
                    <div class="tombstone-entry">
                        <div class="tombstone-entry__agent">💀 Agent ${escapeHtml(tomb.agent_id || '?')}</div>
                        <div class="tombstone-entry__reason" style="line-height: 1.45;">
                            <strong>Status:</strong> ${tomb.is_pruned ? 'Pruned' : 'Terminated'}<br>
                            <strong>Goal:</strong> ${escapeHtml(tomb.goal || '')}<br>
                            <strong>Reason:</strong> ${escapeHtml(tomb.reason || 'No reason')}
                        </div>
                    </div>
                `;
            }
        }
    }

    // Empty state
    if (!html.includes('decision-card') && !html.includes('collision-entry') && !html.includes('tombstone-entry') && !budgetExceeded) {
        html += `
            <div style="padding: var(--space-lg); text-align: center; color: var(--text-muted); font-size: 0.78rem;">
                💤 No active alerts or decisions pending.
            </div>
        `;
    }

    list.innerHTML = html;
}

function getMaxLeafTokens() {
    const active = SwarmState.agents.filter(a => ['exploring', 'syncing', 'pending_termination'].includes(a.status));
    const parentIds = new Set(active.map(a => a.parent_id).filter(Boolean));
    const leaves = active.filter(a => !parentIds.has(a.id));
    if (leaves.length === 0) return 0;
    return Math.max(...leaves.map(a => a.output_tokens || 0));
}

// ---------------------------------------------------------------------------
// Viewport Content
// ---------------------------------------------------------------------------
function renderViewportContent() {
    // Update tab active state
    document.querySelectorAll('.viewport__tab').forEach(tab => {
        tab.classList.toggle('viewport__tab--active', tab.dataset.tab === UIState.activeTab);
    });

    const container = document.getElementById('viewport-content');

    switch (UIState.activeTab) {
        case 'overview':
            renderOverviewTab(container);
            break;
        case 'clusters':
            renderClustersTab(container);
            break;
        case 'workspace':
            renderWorkspaceTab(container);
            break;
        case 'trace':
            renderTraceTab(container);
            break;
        case 'memory':
            renderMemoryTab(container);
            break;
        case 'logs':
            renderLogsTab(container);
            break;
    }
}

function renderClustersTab(container) {
    if (SwarmState.agents.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state__icon">🕸️</div>
                <div class="empty-state__title">No Active Swarm</div>
                <div class="empty-state__desc">Launch a new swarm to visualize agent task proximity clusters.</div>
            </div>
        `;
        return;
    }

    function truncate(str, len) {
        if (!str) return '';
        return str.length > len ? str.substring(0, len) + '...' : str;
    }

    container.innerHTML = `
        <div class="cluster-view-container">
            <div class="cluster-map-canvas" id="cluster-svg-parent"></div>
            <div class="cluster-sidebar" id="cluster-sidebar-content"></div>
        </div>
    `;

    // 1. Hierarchical Tree Construction
    const nodeMap = {};
    for (const agent of SwarmState.agents) {
        nodeMap[agent.id] = {
            id: agent.id,
            agent: agent,
            children: [],
            parent: null,
            x: 0,
            y: 0,
            radius: 70
        };
    }

    const roots = [];
    for (const node of Object.values(nodeMap)) {
        const parentId = node.agent.parent_id;
        if (parentId && nodeMap[parentId]) {
            nodeMap[parentId].children.push(node);
            node.parent = nodeMap[parentId];
        } else {
            roots.push(node);
        }
    }

    // 2. Position Nodes Orbitally (Phase A: compute tree sizes relative to 0,0)
    function layoutNode(node, level, parentAngle) {
        const k = node.children.length;
        if (k === 0) {
            node.radius = 70; // Base radius to hold text descriptions comfortably
            return;
        }

        const orbitRadius = Math.max(160 - level * 35, 90);
        for (let i = 0; i < k; i++) {
            const child = node.children[i];
            let angle;
            if (k === 1) {
                angle = (parentAngle !== undefined) ? parentAngle : (i * 2 * Math.PI / k);
            } else {
                const startAngle = (parentAngle !== undefined) ? parentAngle - Math.PI / 3 : 0;
                const endAngle = (parentAngle !== undefined) ? parentAngle + Math.PI / 3 : 2 * Math.PI;
                const arc = endAngle - startAngle;
                angle = startAngle + (i / (k - 1)) * arc;
            }
            child.x = node.x + Math.cos(angle) * orbitRadius;
            child.y = node.y + Math.sin(angle) * orbitRadius;
            layoutNode(child, level + 1, angle);
        }

        let maxDist = 0;
        for (const child of node.children) {
            const dist = Math.sqrt((child.x - node.x) ** 2 + (child.y - node.y) ** 2) + child.radius;
            if (dist > maxDist) maxDist = dist;
        }
        node.radius = Math.max(maxDist + 15, 80);
    }

    for (const root of roots) {
        root.x = 0;
        root.y = 0;
        layoutNode(root, 1);
    }

    // Phase B: Space roots on screen and shift descendants
    const cx = 500;
    const cy = 300;
    
    function shiftPositions(node, dx, dy) {
        node.x += dx;
        node.y += dy;
        for (const child of node.children) {
            shiftPositions(child, dx, dy);
        }
    }

    if (roots.length === 1) {
        const r = roots[0];
        shiftPositions(r, cx - r.x, cy - r.y);
    } else if (roots.length > 1) {
        let maxRootRadius = 0;
        for (const r of roots) {
            if (r.radius > maxRootRadius) maxRootRadius = r.radius;
        }
        const spacingRad = Math.max(maxRootRadius + 70, 270);
        
        for (let i = 0; i < roots.length; i++) {
            const r = roots[i];
            const angle = (i / roots.length) * 2 * Math.PI - Math.PI / 2;
            const targetX = cx + Math.cos(angle) * spacingRad;
            const targetY = cy + Math.sin(angle) * spacingRad;
            shiftPositions(r, targetX - r.x, targetY - r.y);
        }
    }

    // Proximity linkages calculation
    const listAgents = SwarmState.agents;
    const links = [];
    for (let i = 0; i < listAgents.length; i++) {
        for (let j = i + 1; j < listAgents.length; j++) {
            const a1 = listAgents[i];
            const a2 = listAgents[j];
            const prox = calculateAgentDistance(a1, a2);
            
            const isCollision = SwarmState.collisions.some(col => 
                (col.agent_a === a1.id && col.agent_b === a2.id) ||
                (col.agent_a === a2.id && col.agent_b === a1.id)
            );

            if (prox.distance < 0.85 || isCollision) {
                links.push({
                    source: a1.id,
                    target: a2.id,
                    distance: prox.distance,
                    isCollision: isCollision
                });
            }
        }
    }

    function calculateJaccard(setA, setB) {
        if (setA.size === 0 && setB.size === 0) return 0;
        const intersect = new Set([...setA].filter(x => setB.has(x)));
        const union = new Set([...setA, ...setB]);
        return intersect.size / union.size;
    }

    function tokenizeGoal(goalText) {
        if (!goalText) return new Set();
        const words = goalText.toLowerCase()
            .replace(/[.,\/#!$%\^&\*;:{}=\-_`~()?"']/g, '')
            .split(/\s+/)
            .filter(w => w.length > 2);
        return new Set(words);
    }

    function calculateAgentDistance(a1, a2) {
        const g1 = tokenizeGoal(a1.goal || '');
        const g2 = tokenizeGoal(a2.goal || '');
        const goalSim = calculateJaccard(g1, g2);

        const f1 = new Set(a1.touched_files || []);
        const f2 = new Set(a2.touched_files || []);
        const fileSim = calculateJaccard(f1, f2);

        const t1 = new Set(a1.tools_used || []);
        const t2 = new Set(a2.tools_used || []);
        const toolSim = calculateJaccard(t1, t2);

        const distance = 0.5 * (1.0 - goalSim) + 0.3 * (1.0 - fileSim) + 0.2 * (1.0 - toolSim);
        return { distance, goalSim, fileSim, toolSim };
    }

    const svgParent = document.getElementById('cluster-svg-parent');
    let svgHtml = `<svg class="cluster-svg" viewBox="0 0 1000 600" width="100%" height="100%">`;

    // Boundaries
    function drawBoundaries(node) {
        if (node.children.length > 0) {
            svgHtml += `<circle class="cluster-boundary" cx="${node.x}" cy="${node.y}" r="${node.radius}" />`;
            svgHtml += `<text x="${node.x}" y="${node.y - node.radius + 12}" 
                             style="font-family: var(--font-mono); font-size: 8px; fill: var(--text-muted); text-anchor: middle; font-weight: 600; opacity: 0.7;">
                             CLUSTER: AGENT ${node.id}
                        </text>`;
        }
        for (const child of node.children) {
            drawBoundaries(child);
        }
    }
    for (const root of roots) {
        drawBoundaries(root);
    }

    // Links
    for (const link of links) {
        const n1 = nodeMap[link.source];
        const n2 = nodeMap[link.target];
        if (n1 && n2) {
            const opacity = (1.0 - link.distance) * 0.8;
            const strokeWidth = (1.0 - link.distance) * 5;
            let linkClass = 'cluster-link ';
            
            if (link.isCollision) {
                linkClass += 'cluster-link--collision';
            } else if (link.distance < 0.5) {
                linkClass += 'cluster-link--proximity-high';
            } else {
                linkClass += 'cluster-link--proximity-mod';
            }

            svgHtml += `<line class="${linkClass}" x1="${n1.x}" y1="${n1.y}" x2="${n2.x}" y2="${n2.y}" 
                             stroke-width="${link.isCollision ? 4 : strokeWidth}" 
                             stroke-opacity="${opacity}" />`;
            
            const midX = (n1.x + n2.x) / 2;
            const midY = (n1.y + n2.y) / 2;
            svgHtml += `
                <g class="cluster-link-label-group">
                    <rect class="cluster-link-bg" x="${midX - 20}" y="${midY - 7}" width="40" height="14" />
                    <text class="cluster-link-label" x="${midX}" y="${midY}">d:${link.distance.toFixed(2)}</text>
                </g>
            `;
        }
    }

    // Nodes
    for (const node of Object.values(nodeMap)) {
        const agent = node.agent;
        const status = agent.status || 'unknown';
        const isSelected = agent.id === UIState.selectedAgentId;
        
        let statusClass = `node--${status}`;
        if (isSelected) {
            statusClass += ' node--selected';
        }

        const role = escapeHtml(truncate(agent.personality || agent.role || 'Generalist', 20));
        const goalSnippet = escapeHtml(truncate(agent.goal || '', 24));

        svgHtml += `
            <g class="cluster-node" data-agent-id="${agent.id}">
                <g class="cluster-node-g">
                    <circle class="cluster-node-circle ${statusClass}" cx="${node.x}" cy="${node.y}" r="22" />
                    <text class="cluster-node-text" x="${node.x}" y="${node.y}">${agent.id}</text>
                    
                    <text x="${node.x}" y="${node.y + 36}" 
                          style="font-family: var(--font-sans); font-size: 10px; font-weight: 600; fill: var(--text-bright); text-anchor: middle;">
                          Agent ${agent.id}
                    </text>
                    <text x="${node.x}" y="${node.y + 48}" 
                          style="font-family: var(--font-sans); font-size: 8px; font-weight: 500; fill: var(--text-muted); text-anchor: middle;">
                          ${role}
                    </text>
                    <text x="${node.x}" y="${node.y + 58}" 
                          style="font-family: var(--font-sans); font-size: 8px; fill: var(--text-muted); opacity: 0.7; text-anchor: middle; font-style: italic;">
                          "${goalSnippet}"
                    </text>
                </g>
            </g>
        `;
    }

    svgHtml += `</svg>`;
    svgParent.innerHTML = svgHtml;

    svgParent.querySelector('svg').addEventListener('click', (e) => {
        const nodeG = e.target.closest('.cluster-node');
        if (nodeG) {
            const agentId = nodeG.dataset.agentId;
            UIState.selectedAgentId = agentId;
            svgParent.querySelectorAll('.cluster-node-circle').forEach(circle => {
                circle.classList.remove('node--selected');
            });
            nodeG.querySelector('.cluster-node-circle').classList.add('node--selected');
            renderClusterSidebar(agentId);
        }
    });

    const selectedId = UIState.selectedAgentId || (SwarmState.agents.length > 0 ? SwarmState.agents[0].id : null);
    renderClusterSidebar(selectedId);

    function renderClusterSidebar(agentId) {
        const sidebarContent = document.getElementById('cluster-sidebar-content');
        if (!agentId) {
            sidebarContent.innerHTML = `
                <div style="flex:1; display:flex; align-items:center; justify-content:center; text-align:center; color:var(--text-muted); font-size:0.75rem;">
                    💡 Click an agent node in the cluster map to view detailed task similarities and actions.
                </div>
            `;
            return;
        }

        const agentNode = nodeMap[agentId];
        if (!agentNode) return;
        const agent = agentNode.agent;

        const listSims = [];
        for (const other of SwarmState.agents) {
            if (other.id !== agentId) {
                const res = calculateAgentDistance(agent, other);
                listSims.push({
                    agent: other,
                    distance: res.distance,
                    goalSim: res.goalSim,
                    fileSim: res.fileSim,
                    toolSim: res.toolSim
                });
            }
        }
        listSims.sort((a, b) => a.distance - b.distance);

        const statusColor = {
            exploring: 'var(--accent-cyan)',
            completed: 'var(--accent-green)',
            dead: 'var(--accent-red)',
            syncing: 'var(--accent-amber)',
            pending_termination: 'var(--accent-red)',
        }[agent.status] || 'var(--text-muted)';

        let sidebarHtml = `
            <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:var(--space-md);">
                <h3 style="font-family:var(--font-mono); font-size:0.92rem; font-weight:600; color:var(--accent-cyan); margin:0;">Agent ${agent.id}</h3>
                <span style="font-size: 0.62rem; font-weight: 600; text-transform: uppercase; padding: 1px 6px; border-radius: var(--radius-sm); background: ${statusColor}22; color: ${statusColor};">${agent.status || 'unknown'}</span>
            </div>
            
            <div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:var(--space-xs); font-weight:600;">ROLE:</div>
            <div style="font-size:0.78rem; color:var(--text-primary); margin-bottom:var(--space-md);">${escapeHtml(agent.personality || agent.role || 'Generalist')}</div>
            
            <div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:var(--space-xs); font-weight:600;">CURRENT GOAL:</div>
            <div style="font-size:0.78rem; color:var(--text-primary); margin-bottom:var(--space-md); line-height:1.4;">${escapeHtml(agent.goal || '')}</div>
            
            <div style="display:flex; flex-direction:column; gap:var(--space-xs); margin-bottom:var(--space-xl);">
                <button class="btn btn--primary btn--sm" data-action="view-workspace" data-agent-id="${agent.id}" style="justify-content:center; padding: var(--space-sm) 0;">📁 Browse Workspace</button>
                <button class="btn btn--sm" data-action="view-trace" data-agent-id="${agent.id}" style="justify-content:center; padding: var(--space-sm) 0;">🔍 View Causal Trace</button>
                <button class="btn btn--ghost btn--sm" data-action="edit-agent" data-agent-id="${agent.id}" style="justify-content:center; padding: var(--space-sm) 0;">✏️ Edit Goal/Role</button>
            </div>
            
            <div style="font-size:0.75rem; color:var(--text-secondary); margin-bottom:var(--space-sm); font-weight:600; text-transform:uppercase; border-top: 1px solid var(--border-secondary); padding-top: var(--space-md);">Task Similarity Metrics</div>
        `;

        if (listSims.length === 0) {
            sidebarHtml += `<div style="font-size:0.7rem; color:var(--text-muted);">No other agents in the swarm.</div>`;
        } else {
            sidebarHtml += `<div style="display:flex; flex-direction:column; gap:var(--space-sm);">`;
            for (const sim of listSims) {
                const levelColor = sim.distance < 0.5 ? 'var(--accent-amber)' : 'var(--text-muted)';
                sidebarHtml += `
                    <div style="background:var(--bg-primary); border:1px solid var(--border-primary); border-radius:var(--radius-sm); padding:var(--space-sm);">
                        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:var(--space-xs);">
                            <span style="font-family:var(--font-mono); font-size:0.72rem; font-weight:600; color:var(--accent-cyan);">Agent ${sim.agent.id}</span>
                            <span style="font-family:var(--font-mono); font-size:0.68rem; font-weight:600; color:${levelColor};">Dist: ${sim.distance.toFixed(3)}</span>
                        </div>
                        <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap: 4px; text-align:center; font-size:0.6rem; color:var(--text-muted);">
                            <div>Goal: ${(sim.goalSim * 100).toFixed(0)}%</div>
                            <div>Files: ${(sim.fileSim * 100).toFixed(0)}%</div>
                            <div>Tools: ${(sim.toolSim * 100).toFixed(0)}%</div>
                        </div>
                    </div>
                `;
            }
            sidebarHtml += `</div>`;
        }

        sidebarContent.innerHTML = sidebarHtml;
    }
}

function renderOverviewTab(container) {
    if (SwarmState.agents.length === 0 && !SwarmState.swarm_running) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state__icon">🐝</div>
                <div class="empty-state__title">Welcome to Proximity Swarm V3</div>
                <div class="empty-state__desc">
                    Launch a new swarm to coordinate autonomous agents working on complex tasks.
                    Click <strong>"New Swarm"</strong> to get started, or enter a goal in the command bar below.
                </div>
                <button class="btn btn--primary btn--lg" data-action="open-launch">🚀 Launch Your First Swarm</button>
            </div>
        `;
        return;
    }

    // Build overview dashboard
    const activeAgents = SwarmState.agents.filter(a => a.status === 'exploring').length;
    const completedAgents = SwarmState.agents.filter(a => a.status === 'completed').length;
    const deadAgents = SwarmState.agents.filter(a => a.status === 'dead').length;
    const totalAgents = SwarmState.agents.length;

    let html = `
        <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: var(--space-md); margin-bottom: var(--space-xl);">
            <div class="budget-widget">
                <div class="budget-widget__label">Total Agents</div>
                <div class="budget-widget__value" style="color: var(--accent-purple); cursor: default;">${totalAgents}</div>
            </div>
            <div class="budget-widget">
                <div class="budget-widget__label">Active</div>
                <div class="budget-widget__value" style="color: var(--accent-cyan); cursor: default;">${activeAgents}</div>
            </div>
            <div class="budget-widget">
                <div class="budget-widget__label">Completed</div>
                <div class="budget-widget__value" style="color: var(--accent-green); cursor: default;">${completedAgents}</div>
            </div>
            <div class="budget-widget">
                <div class="budget-widget__label">Failed</div>
                <div class="budget-widget__value" style="color: var(--accent-red); cursor: default;">${deadAgents}</div>
            </div>
        </div>
    `;

    // Macro goal
    if (SwarmState.macro_goal) {
        html += `
            <div style="background: var(--bg-tertiary); border: 1px solid var(--border-primary); border-radius: var(--radius-md); padding: var(--space-lg); margin-bottom: var(--space-xl);">
                <div style="font-size: 0.7rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text-muted); margin-bottom: var(--space-sm);">Macro Goal</div>
                <div style="font-size: 0.95rem; color: var(--text-primary); line-height: 1.5;">${escapeHtml(SwarmState.macro_goal)}</div>
            </div>
        `;
    }

    // Orchestrator sub-swarms
    const orc = SwarmState.orchestrator || {};
    const subSwarms = orc.sub_swarms || {};
    if (Object.keys(subSwarms).length > 0) {
        html += `<div style="font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); margin-bottom: var(--space-md);">Sub-Swarms</div>`;
        html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); gap: var(--space-md); margin-bottom: var(--space-xl);">';
        for (const [sid, swarm] of Object.entries(subSwarms)) {
            const swarmStatus = swarm.status || 'pending';
            const statusColor = swarmStatus === 'completed' ? 'var(--accent-green)' : swarmStatus === 'active' ? 'var(--accent-cyan)' : 'var(--text-muted)';
            html += `
                <div style="background: var(--bg-tertiary); border: 1px solid var(--border-primary); border-radius: var(--radius-md); padding: var(--space-md); border-left: 3px solid ${statusColor};">
                    <div style="font-family: var(--font-mono); font-size: 0.75rem; color: ${statusColor}; font-weight: 600; margin-bottom: var(--space-xs);">${escapeHtml(sid)} — ${escapeHtml(swarmStatus.toUpperCase())}</div>
                    <div style="font-size: 0.78rem; color: var(--text-primary);">${escapeHtml(swarm.goal || '')}</div>
                    <div style="font-size: 0.68rem; color: var(--text-muted); margin-top: var(--space-xs);">Agents: ${(swarm.agent_ids || []).join(', ') || 'None'}</div>
                </div>
            `;
        }
        html += '</div>';
    }

    // Agent detail cards
    if (SwarmState.agents.length > 0) {
        html += `<div style="font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); margin-bottom: var(--space-md);">Agent Details</div>`;
        html += '<div style="display: grid; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); gap: var(--space-md);">';
        for (const agent of SwarmState.agents) {
            const steps = agent.steps || [];
            const currentStep = getStepNumber(agent);
            const progress = computeProgress(agent);
            const statusColor = {
                exploring: 'var(--accent-cyan)',
                completed: 'var(--accent-green)',
                dead: 'var(--accent-red)',
                syncing: 'var(--accent-amber)',
                pending_termination: 'var(--accent-red)',
            }[agent.status] || 'var(--text-muted)';

            html += `
                <div style="background: var(--bg-tertiary); border: 1px solid var(--border-primary); border-radius: var(--radius-sm); padding: var(--space-lg); border-left: 2px solid ${statusColor}; cursor: pointer;"
                     data-action="edit-agent" data-agent-id="${agent.id}">
                    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: var(--space-sm);">
                        <span style="font-family: var(--font-mono); font-weight: 600; color: var(--accent-cyan);">Agent ${agent.id}</span>
                        <span style="font-size: 0.62rem; font-weight: 600; text-transform: uppercase; padding: 1px 6px; border-radius: var(--radius-sm); background: ${statusColor}22; color: ${statusColor};">${agent.status || 'unknown'}</span>
                    </div>
                    <div style="font-size: 0.72rem; color: var(--text-secondary); margin-bottom: 2px;">${escapeHtml(agent.personality || agent.role || 'Generalist')}</div>
                    <div style="font-size: 0.8rem; margin-bottom: var(--space-md);">${escapeHtml(agent.goal || '')}</div>
                    <div class="progress-bar"><div class="progress-bar__fill" style="width: ${progress}%"></div></div>
                    <div style="font-size: 0.68rem; color: var(--text-muted); margin-top: var(--space-xs);">Step ${currentStep}/${steps.length || '?'} · Tokens: ${(agent.output_tokens || 0).toLocaleString()}</div>
                </div>
            `;
        }
        html += '</div>';
    }

    container.innerHTML = html;
}

function renderWorkspaceTab(container) {
    const agentId = UIState.selectedWorkspaceAgent || (SwarmState.agents.length > 0 ? SwarmState.agents[0].id : null);

    if (!agentId) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state__icon">📁</div>
                <div class="empty-state__title">No Agent Selected</div>
                <div class="empty-state__desc">Click an agent card or the 📁 button to view workspace files.</div>
            </div>
        `;
        return;
    }

    // Agent selector
    let html = `
        <div style="display: flex; align-items: center; gap: var(--space-md); margin-bottom: var(--space-lg);">
            <span style="font-size: 0.75rem; color: var(--text-secondary); font-weight: 600;">WORKSPACE FOR:</span>
            <select class="form-select" style="width: auto; min-width: 200px;" id="workspace-agent-select" data-action="change-workspace-agent">
                ${SwarmState.agents.map(a => `<option value="${a.id}" ${a.id === agentId ? 'selected' : ''}>Agent ${a.id} — ${escapeHtml(a.personality || 'Generalist')}</option>`).join('')}
            </select>
        </div>
    `;

    if (UIState.workspaceData && UIState.selectedWorkspaceAgent === agentId) {
        const files = UIState.workspaceData.files || [];
        const contents = UIState.workspaceData.contents || {};

        if (files.length === 0) {
            html += `
                <div class="empty-state">
                    <div class="empty-state__icon">📄</div>
                    <div class="empty-state__title">No Files Yet</div>
                    <div class="empty-state__desc">Agent ${agentId} hasn't created any workspace files yet.</div>
                </div>
            `;
        } else {
            html += '<div style="display: grid; grid-template-columns: 220px 1fr; gap: var(--space-md);">';

            // File tree
            html += '<div class="file-tree">';
            for (const f of files) {
                const isActive = UIState.selectedFile === f;
                const ext = f.split('.').pop();
                const icon = { py: '🐍', js: '📜', json: '📋', md: '📝', txt: '📄', c: '⚙️', h: '⚙️' }[ext] || '📄';
                html += `<div class="file-tree__item ${isActive ? 'file-tree__item--active' : ''}" data-action="select-file" data-file="${escapeHtml(f)}">
                    <span class="file-tree__icon">${icon}</span>
                    <span>${escapeHtml(f)}</span>
                </div>`;
            }
            html += '</div>';

            // File content
            const selectedFile = UIState.selectedFile || files[0];
            const content = contents[selectedFile] || '';
            html += `
                <div class="code-viewer">
                    <div class="code-viewer__header">
                        <span>${escapeHtml(selectedFile)}</span>
                        <span>${content.split('\n').length} lines</span>
                    </div>
                    <div class="code-viewer__body">${escapeHtml(content)}</div>
                </div>
            `;
            html += '</div>';
        }
    } else {
        html += '<div style="text-align: center; padding: var(--space-xl);"><div class="skeleton skeleton--card"></div><div class="skeleton skeleton--card"></div></div>';
        loadWorkspace(agentId);
    }

    container.innerHTML = html;
}

async function loadWorkspace(agentId) {
    UIState.selectedWorkspaceAgent = agentId;
    const data = await apiGet(`/api/workspaces/${agentId}`);
    UIState.workspaceData = data;
    UIState.selectedFile = (data.files || [])[0] || null;
    renderViewportContent();
}

function renderTraceTab(container) {
    const agentId = UIState.selectedTraceAgent || (SwarmState.agents.length > 0 ? SwarmState.agents[0].id : null);

    if (!agentId) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state__icon">🔍</div>
                <div class="empty-state__title">No Agent Selected</div>
                <div class="empty-state__desc">Click the 🔍 button on an agent card to view its causal trace.</div>
            </div>
        `;
        return;
    }

    let html = `
        <div style="display: flex; align-items: center; gap: var(--space-md); margin-bottom: var(--space-lg);">
            <span style="font-size: 0.75rem; color: var(--text-secondary); font-weight: 600;">TRACE FOR:</span>
            <select class="form-select" style="width: auto; min-width: 200px;" id="trace-agent-select" data-action="change-trace-agent">
                ${SwarmState.agents.map(a => `<option value="${a.id}" ${a.id === agentId ? 'selected' : ''}>Agent ${a.id} — ${escapeHtml(a.personality || 'Generalist')}</option>`).join('')}
            </select>
        </div>
    `;

    if (UIState.traceData && UIState.selectedTraceAgent === agentId) {
        // Mermaid diagram (render as code block since we don't have mermaid.js)
        html += `
            <div class="code-viewer" style="margin-bottom: var(--space-xl);">
                <div class="code-viewer__header">
                    <span>Causal Flow Graph (Mermaid)</span>
                    <span>Agent ${agentId}</span>
                </div>
                <div class="code-viewer__body">${escapeHtml(UIState.traceData.mermaid || 'No trace data')}</div>
            </div>
        `;

        // Event timeline
        const timeline = UIState.traceData.timeline || [];
        if (timeline.length > 0) {
            html += '<div style="font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); margin-bottom: var(--space-md);">Event Timeline</div>';
            html += '<div class="timeline">';
            for (const event of timeline) {
                const eventClass = event.type.includes('spawn') ? 'timeline__event--spawn' :
                                   event.type.includes('collision') ? 'timeline__event--collision' : '';
                const time = new Date(event.timestamp * 1000).toLocaleTimeString();
                const details = event.details || {};
                let desc = `${event.type}: ${event.source} → ${event.target}`;
                if (details.goal) desc += ` (${details.goal})`;
                if (details.old_status) desc += ` [${details.old_status} → ${details.new_status}]`;
                html += `
                    <div class="timeline__event ${eventClass}">
                        <div class="timeline__time">${time}</div>
                        <div class="timeline__detail">${escapeHtml(desc)}</div>
                    </div>
                `;
            }
            html += '</div>';
        }
    } else {
        html += '<div style="text-align: center; padding: var(--space-xl);"><div class="skeleton skeleton--card"></div><div class="skeleton skeleton--card"></div></div>';
        loadTrace(agentId);
    }

    container.innerHTML = html;
}

async function loadTrace(agentId) {
    UIState.selectedTraceAgent = agentId;
    UIState.traceData = await apiGet(`/api/trace/${agentId}`);
    renderViewportContent();
}

function renderMemoryTab(container) {
    let html = `
        <div style="font-size: 0.78rem; font-weight: 700; text-transform: uppercase; letter-spacing: 0.06em; color: var(--text-secondary); margin-bottom: var(--space-md);">Episodic Memory Database</div>
    `;

    // We need to fetch memory data
    if (!UIState.memoryData) {
        html += '<div style="text-align: center; padding: var(--space-xl);"><div class="skeleton skeleton--card"></div></div>';
        container.innerHTML = html;
        loadMemory();
        return;
    }

    const episodes = UIState.memoryData || [];
    if (episodes.length === 0) {
        html += `
            <div class="empty-state">
                <div class="empty-state__icon">🧠</div>
                <div class="empty-state__title">No Episodes Recorded</div>
                <div class="empty-state__desc">Complete agent runs will be recorded here for future reference.</div>
            </div>
        `;
    } else {
        html += `
            <table class="data-table">
                <thead>
                    <tr>
                        <th>ID</th>
                        <th>Goal</th>
                        <th>Role</th>
                        <th>Status</th>
                        <th>Reflection</th>
                        <th>Date</th>
                    </tr>
                </thead>
                <tbody>
        `;
        for (const ep of episodes) {
            const statusStyle = ep.status === 'completed' ? 'color: var(--accent-green)' : 'color: var(--accent-red)';
            html += `
                <tr>
                    <td style="font-family: var(--font-mono); font-weight: 600;">${ep.id}</td>
                    <td>${escapeHtml(ep.goal || '')}</td>
                    <td style="color: var(--accent-purple);">${escapeHtml(ep.role || '')}</td>
                    <td style="${statusStyle}; font-weight: 700;">${escapeHtml(ep.status || '')}</td>
                    <td style="font-size: 0.72rem; color: var(--text-secondary);">${escapeHtml(ep.reflection || '')}</td>
                    <td style="font-size: 0.72rem; color: var(--text-muted);">${escapeHtml(ep.created_at || '')}</td>
                </tr>
            `;
        }
        html += '</tbody></table>';
    }

    container.innerHTML = html;
}

async function loadMemory() {
    UIState.memoryData = await apiGet('/api/memory');
    renderViewportContent();
}

function renderLogsTab(container) {
    const logs = SwarmState.logs || [];
    if (logs.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state__icon">📋</div>
                <div class="empty-state__title">No Logs Yet</div>
                <div class="empty-state__desc">Logs will appear here once the swarm is running.</div>
            </div>
        `;
        return;
    }

    let html = '<div style="font-family: var(--font-mono); font-size: 0.78rem; line-height: 1.8; background: var(--bg-tertiary); border: 1px solid var(--border-primary); border-radius: var(--radius-md); padding: var(--space-lg); max-height: calc(100vh - 200px); overflow-y: auto;">';
    for (const line of logs) {
        const cls = line.includes('[ERROR]') ? 'color: var(--accent-red)' :
                    line.includes('[WARN]') ? 'color: var(--accent-amber)' :
                    line.includes('[INFO]') ? 'color: var(--text-secondary)' : '';
        html += `<div style="${cls}">${escapeHtml(line)}</div>`;
    }
    html += '</div>';
    container.innerHTML = html;
}

// ---------------------------------------------------------------------------
// Log Tail (bottom bar)
// ---------------------------------------------------------------------------
function renderLogTail() {
    const tailEl = document.getElementById('log-tail');
    const logs = SwarmState.logs || [];
    const recentLogs = logs.slice(-5);
    if (recentLogs.length === 0) {
        tailEl.innerHTML = '<div class="log-tail__line log-tail__line--info">Proximity Swarm V3 initialized. Ready.</div>';
        return;
    }
    let html = '';
    for (const line of recentLogs) {
        const cls = line.includes('[ERROR]') ? 'log-tail__line--error' :
                    line.includes('[WARN]') ? 'log-tail__line--warn' :
                    'log-tail__line--info';
        html += `<div class="log-tail__line ${cls}">${escapeHtml(line)}</div>`;
    }
    tailEl.innerHTML = html;
    tailEl.scrollTop = tailEl.scrollHeight;
}

// ---------------------------------------------------------------------------
// Agent Edit Panel
// ---------------------------------------------------------------------------
function openEditPanel(agentId) {
    const agent = SwarmState.agents.find(a => a.id === agentId);
    if (!agent) return;

    UIState.editingAgentId = agentId;
    const panel = document.getElementById('agent-edit-panel');
    const backdrop = document.getElementById('slide-backdrop');
    const title = document.getElementById('edit-panel-title');
    const body = document.getElementById('edit-panel-body');

    title.textContent = `Agent ${agentId}`;

    const steps = agent.steps || [];
    let stepsHtml = '';
    if (steps.length > 0) {
        stepsHtml = '<div class="form-group"><label class="form-label">Task Steps</label><div style="display: flex; flex-direction: column; gap: var(--space-sm);">';
        const currentStepNum = getStepNumber(agent);
        for (const step of steps) {
            const stepStatus = currentStepNum > step.step_id ? '✅' :
                               currentStepNum === step.step_id ? '🔄' : '⏳';
            stepsHtml += `
                <div style="background: var(--bg-primary); padding: var(--space-md); border-radius: var(--radius-sm); border: 1px solid var(--border-primary);">
                    <div style="font-size: 0.75rem; color: var(--text-secondary);">${stepStatus} Step ${step.step_id}: <strong>${escapeHtml(step.name || '')}</strong></div>
                    <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: 2px;">${escapeHtml(step.description || '')}</div>
                </div>
            `;
        }
        stepsHtml += '</div></div>';
    }

    body.innerHTML = `
        <div class="form-group">
            <label class="form-label">Status</label>
            <div style="font-size: 0.85rem; font-weight: 600; color: ${{
                exploring: 'var(--accent-cyan)',
                completed: 'var(--accent-green)',
                dead: 'var(--accent-red)',
                syncing: 'var(--accent-amber)',
                pending_termination: 'var(--accent-red)',
            }[agent.status] || 'var(--text-primary)'};">${statusLabel(agent.status)}</div>
        </div>
        <div class="form-group">
            <label class="form-label" for="edit-role">Role / Personality</label>
            <input type="text" class="form-input" id="edit-role" value="${escapeAttr(agent.personality || agent.role || 'Generalist')}">
        </div>
        <div class="form-group">
            <label class="form-label" for="edit-goal">Goal</label>
            <textarea class="form-textarea" id="edit-goal" rows="4">${escapeHtml(agent.goal || '')}</textarea>
        </div>
        <div class="form-group">
            <label class="form-label">Progress</label>
            <div class="progress-bar" style="height: 8px;"><div class="progress-bar__fill" style="width: ${computeProgress(agent)}%"></div></div>
            <div style="font-size: 0.72rem; color: var(--text-muted); margin-top: var(--space-xs);">Step ${getStepNumber(agent)}/${steps.length || '?'} · Output tokens: ${(agent.output_tokens || 0).toLocaleString()}</div>
        </div>
        ${stepsHtml}
        <div class="form-group">
            <label class="form-label">Touched Files</label>
            <div style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-secondary);">
                ${(agent.touched_files || []).map(f => `<div>📄 ${escapeHtml(f)}</div>`).join('') || '<div style="color: var(--text-muted);">No files yet</div>'}
            </div>
        </div>
    `;

    panel.classList.add('slide-panel--active');
    backdrop.classList.add('modal-overlay--active');
}

function closeEditPanel() {
    UIState.editingAgentId = null;
    document.getElementById('agent-edit-panel').classList.remove('slide-panel--active');
    document.getElementById('slide-backdrop').classList.remove('modal-overlay--active');
}

async function saveAgentEdits() {
    if (!UIState.editingAgentId) return;
    const role = document.getElementById('edit-role').value;
    const goal = document.getElementById('edit-goal').value;
    const result = await apiPost(`/api/agents/${UIState.editingAgentId}/edit`, {
        personality: role,
        goal: goal,
    });
    if (result.success) {
        showToast(`Agent ${UIState.editingAgentId} updated`, 'success');
        closeEditPanel();
    } else {
        showToast(result.message || 'Failed to update agent', 'error');
    }
}

// ---------------------------------------------------------------------------
// Launch Modal
// ---------------------------------------------------------------------------
function openLaunchModal() {
    document.getElementById('launch-modal').classList.add('modal-overlay--active');
    document.getElementById('launch-goal').value = '';
    document.getElementById('launch-budget').value = SwarmState.session_budget || 20000;
    UIState.designerAgents = [{ role: 'Generalist', goal: '' }];
    renderDesignerAgents();
    document.getElementById('launch-goal').focus();
}

function closeLaunchModal() {
    document.getElementById('launch-modal').classList.remove('modal-overlay--active');
}

function renderDesignerAgents() {
    const container = document.getElementById('designer-agents');
    let html = '';
    for (let i = 0; i < UIState.designerAgents.length; i++) {
        const agent = UIState.designerAgents[i];
        html += `
            <div class="agent-designer-item">
                <span class="agent-designer-item__number">#${i + 1}</span>
                <div class="agent-designer-item__fields">
                    <input type="text" placeholder="Role (e.g. Backend Engineer)" value="${escapeAttr(agent.role)}"
                           data-action="update-designer-role" data-index="${i}">
                    <input type="text" placeholder="Goal (optional, inherits macro goal)" value="${escapeAttr(agent.goal)}"
                           data-action="update-designer-goal" data-index="${i}">
                </div>
                <button class="icon-btn" data-action="remove-designer-agent" data-index="${i}" title="Remove" style="flex-shrink: 0;">✕</button>
            </div>
        `;
    }
    container.innerHTML = html;
}

function addDesignerAgent() {
    UIState.designerAgents.push({ role: 'Generalist', goal: '' });
    renderDesignerAgents();
}

function removeDesignerAgent(index) {
    if (UIState.designerAgents.length <= 1) return;
    UIState.designerAgents.splice(index, 1);
    renderDesignerAgents();
}

async function launchSwarm() {
    const goal = document.getElementById('launch-goal').value.trim();
    const budget = parseInt(document.getElementById('launch-budget').value) || 20000;

    if (!goal) {
        showToast('Please enter a macro goal', 'error');
        return;
    }

    // Collect designer agents
    const agents = UIState.designerAgents.map((a, i) => ({
        agent_id: `${i + 1}`.padStart(3, '0'),
        personality: a.role || 'Generalist',
        role: a.role || 'Generalist',
        goal: a.goal || goal,
    }));

    closeLaunchModal();
    showToast('Launching swarm...', 'info');

    const result = await apiPost('/api/run', { goal, agents, budget });
    if (result.success) {
        showToast(result.message, 'success');
    } else {
        showToast(result.message || 'Failed to launch swarm', 'error');
    }
}

// ---------------------------------------------------------------------------
// Budget Editor
// ---------------------------------------------------------------------------
function editBudget(targetEl) {
    if (!targetEl || targetEl.querySelector('input')) return;

    const current = SwarmState.session_budget || 20000;
    
    targetEl.innerHTML = `
        <div style="display: flex; align-items: center; gap: 4px; margin-top: 4px;">
            <input type="number" class="form-input" id="budget-inline-input" value="${current}" 
                   style="padding: 2px 4px; font-size: 0.82rem; font-family: var(--font-mono); width: 85px; height: 22px; line-height: 1;" min="100">
            <button class="btn btn--primary btn--sm" id="budget-inline-save" style="padding: 0 6px; height: 22px; font-size: 0.65rem;">Save</button>
            <button class="btn btn--ghost btn--sm" id="budget-inline-cancel" style="padding: 0 4px; height: 22px; font-size: 0.65rem;">✕</button>
        </div>
    `;

    const input = document.getElementById('budget-inline-input');
    input.focus();
    input.select();

    const container = targetEl.querySelector('div');
    container.addEventListener('click', (e) => {
        e.stopPropagation();
    });

    document.getElementById('budget-inline-save').addEventListener('click', () => {
        const val = parseInt(input.value);
        if (isNaN(val) || val < 100) {
            showToast('Invalid budget value', 'error');
            return;
        }
        apiPost('/api/budget', { budget: val }).then(result => {
            if (result.success) {
                showToast(`Budget updated to ${val.toLocaleString()}`, 'success');
                SwarmState.session_budget = val;
                render();
            }
        });
    });

    document.getElementById('budget-inline-cancel').addEventListener('click', () => {
        render();
    });

    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            document.getElementById('budget-inline-save').click();
        } else if (e.key === 'Escape') {
            document.getElementById('budget-inline-cancel').click();
        }
    });
}

// ---------------------------------------------------------------------------
// Event Delegation
// ---------------------------------------------------------------------------
document.addEventListener('click', (e) => {
    const target = e.target.closest('[data-action]');
    if (!target) {
        // Close dropdown if clicking outside
        document.getElementById('clean-menu').classList.remove('dropdown__menu--active');
        return;
    }

    const action = target.dataset.action;

    switch (action) {
        case 'open-launch':
            openLaunchModal();
            break;
        case 'close-launch':
            closeLaunchModal();
            break;
        case 'launch-swarm':
            launchSwarm();
            break;
        case 'add-designer-agent':
            addDesignerAgent();
            break;
        case 'remove-designer-agent':
            removeDesignerAgent(parseInt(target.dataset.index));
            break;
        case 'select-agent':
            UIState.selectedAgentId = target.dataset.agentId;
            render();
            break;
        case 'edit-agent':
            e.stopPropagation();
            openEditPanel(target.dataset.agentId);
            break;
        case 'close-edit':
            closeEditPanel();
            break;
        case 'save-agent':
            saveAgentEdits();
            break;
        case 'view-workspace':
            e.stopPropagation();
            UIState.activeTab = 'workspace';
            UIState.selectedWorkspaceAgent = target.dataset.agentId;
            UIState.workspaceData = null;
            render();
            break;
        case 'view-trace':
            e.stopPropagation();
            UIState.activeTab = 'trace';
            UIState.selectedTraceAgent = target.dataset.agentId;
            UIState.traceData = null;
            render();
            break;
        case 'switch-tab':
            UIState.activeTab = target.dataset.tab;
            // Reset cached data for certain tabs
            if (target.dataset.tab === 'memory') UIState.memoryData = null;
            render();
            break;
        case 'select-file':
            UIState.selectedFile = target.dataset.file;
            renderViewportContent();
            break;
        case 'approve-spawn':
            apiPost(`/api/approve/${target.dataset.agentId}`).then(r => {
                showToast(r.success ? `Spawn approved for Agent ${target.dataset.agentId}` : r.message, r.success ? 'success' : 'error');
            });
            break;
        case 'reject-spawn':
            apiPost(`/api/reject/${target.dataset.agentId}`).then(r => {
                showToast(r.success ? `Spawn rejected for Agent ${target.dataset.agentId}` : r.message, r.success ? 'success' : 'error');
            });
            break;
        case 'resolve-blocker':
            apiPost(`/api/resolve/${target.dataset.agentId}`, { choice: parseInt(target.dataset.choice) }).then(r => {
                showToast(r.success ? r.message : r.message, r.success ? 'success' : 'error');
            });
            break;
        case 'prune-agent':
            e.stopPropagation();
            if (confirm(`Are you sure you want to prune Agent ${target.dataset.agentId}?`)) {
                apiPost(`/api/prune/${target.dataset.agentId}`).then(r => {
                    showToast(r.success ? `Agent ${target.dataset.agentId} pruned` : r.message, r.success ? 'success' : 'error');
                });
            }
            break;
        case 'edit-budget':
            editBudget(target);
            break;
        case 'toggle-clean':
            e.stopPropagation();
            document.getElementById('clean-menu').classList.toggle('dropdown__menu--active');
            break;
        case 'clean':
            document.getElementById('clean-menu').classList.remove('dropdown__menu--active');
            if (target.dataset.target === 'all') {
                if (!confirm('This will clean ALL swarm state. Continue?')) return;
            }
            apiPost('/api/clean', { target: target.dataset.target }).then(r => {
                showToast(r.success ? `Cleaned: ${(r.cleaned || []).join(', ')}` : 'Clean failed', r.success ? 'success' : 'error');
            });
            break;
    }
});

// Handle input events for designer fields
document.addEventListener('input', (e) => {
    const target = e.target;
    if (target.dataset.action === 'update-designer-role') {
        const idx = parseInt(target.dataset.index);
        if (UIState.designerAgents[idx]) UIState.designerAgents[idx].role = target.value;
    }
    if (target.dataset.action === 'update-designer-goal') {
        const idx = parseInt(target.dataset.index);
        if (UIState.designerAgents[idx]) UIState.designerAgents[idx].goal = target.value;
    }
});

// Handle change events for selects
document.addEventListener('change', (e) => {
    if (e.target.id === 'workspace-agent-select') {
        UIState.selectedWorkspaceAgent = e.target.value;
        UIState.workspaceData = null;
        renderViewportContent();
    }
    if (e.target.id === 'trace-agent-select') {
        UIState.selectedTraceAgent = e.target.value;
        UIState.traceData = null;
        renderViewportContent();
    }
});

// Command bar (Enter key)
document.getElementById('command-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        const input = e.target.value.trim();
        if (!input) return;
        e.target.value = '';

        // If not running, treat as a launch command
        if (!SwarmState.swarm_running && !input.startsWith('/')) {
            document.getElementById('launch-goal').value = input;
            openLaunchModal();
            return;
        }

        // Handle slash commands
        if (input.startsWith('/clean')) {
            const parts = input.split(/\s+/);
            const target = parts[1] || 'all';
            apiPost('/api/clean', { target }).then(r => {
                showToast(r.success ? `Cleaned: ${(r.cleaned || []).join(', ')}` : 'Failed', r.success ? 'success' : 'error');
            });
        } else if (input.startsWith('/budget')) {
            const val = parseInt(input.split(/\s+/)[1]);
            if (!isNaN(val)) {
                apiPost('/api/budget', { budget: val }).then(r => {
                    showToast(r.success ? `Budget set to ${val}` : 'Failed', r.success ? 'success' : 'error');
                });
            }
        } else if (input.startsWith('/prune')) {
            const id = input.split(/\s+/)[1];
            if (id) {
                apiPost(`/api/prune/${id}`).then(r => {
                    showToast(r.success ? `Pruned agent ${id}` : r.message, r.success ? 'success' : 'error');
                });
            }
        } else if (input.startsWith('/approve')) {
            const id = input.split(/\s+/)[1];
            if (id) {
                apiPost(`/api/approve/${id}`).then(r => {
                    showToast(r.success ? `Approved ${id}` : r.message, r.success ? 'success' : 'error');
                });
            }
        } else if (input.startsWith('/reject')) {
            const id = input.split(/\s+/)[1];
            if (id) {
                apiPost(`/api/reject/${id}`).then(r => {
                    showToast(r.success ? `Rejected ${id}` : r.message, r.success ? 'success' : 'error');
                });
            }
        } else if (input.startsWith('/resolve')) {
            const parts = input.split(/\s+/);
            const id = parts[1];
            const choice = parseInt(parts[2]) || 1;
            if (id) {
                apiPost(`/api/resolve/${id}`, { choice }).then(r => {
                    showToast(r.success ? r.message : r.message, r.success ? 'success' : 'error');
                });
            }
        } else if (input.startsWith('/trace')) {
            const id = input.split(/\s+/)[1];
            if (id) {
                UIState.activeTab = 'trace';
                UIState.selectedTraceAgent = id;
                UIState.traceData = null;
                render();
            }
        } else if (input.startsWith('/view')) {
            const target = input.split(/\s+/)[1];
            if (target === 'memory') {
                UIState.activeTab = 'memory';
                UIState.memoryData = null;
            } else if (target === 'logs') {
                UIState.activeTab = 'logs';
            } else if (target === 'help' || target === 'overview') {
                UIState.activeTab = 'overview';
            } else if (target) {
                UIState.activeTab = 'workspace';
                UIState.selectedWorkspaceAgent = target;
                UIState.workspaceData = null;
            }
            render();
        } else if (input === '/memory') {
            UIState.activeTab = 'memory';
            UIState.memoryData = null;
            render();
        } else if (input === '/help') {
            UIState.activeTab = 'overview';
            render();
        } else {
            // Treat as a new goal / launch
            document.getElementById('launch-goal').value = input;
            openLaunchModal();
        }
    }
});

// ---------------------------------------------------------------------------
// Utility
// ---------------------------------------------------------------------------
function escapeHtml(str) {
    if (!str) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#039;');
}

function escapeAttr(str) {
    return escapeHtml(str).replace(/\n/g, ' ');
}

// ---------------------------------------------------------------------------
// Initial load
// ---------------------------------------------------------------------------
async function init() {
    // Load initial state
    const state = await apiGet('/api/state');
    if (!state.error) {
        Object.assign(SwarmState, state);
    }
    render();
    connectSSE();
}

init();
