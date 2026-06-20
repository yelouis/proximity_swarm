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
    activeTab: 'clusters',
    rightPanelTab: 'editor',
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
    stageView: null,
    inspectorOpen: false,
    inspectorTab: 'overview',
    drawerOpen: false,
    drawerTab: 'activity',
    initModalOpen: false,
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
    renderStatusBar();
    renderAgentSidebar();
    renderAlertsPanel();
    renderViewportContent();
    renderLogTail();
    renderInspector();
    renderDrawer();

    // Toggle consolidated init modal / overlay
    const initOverlay = document.getElementById('init-overlay');
    if (initOverlay) {
        const showInit = ((!SwarmState.swarm_running && SwarmState.agents.length === 0) || UIState.initModalOpen);
        initOverlay.style.display = showInit ? 'flex' : 'none';
        
        // If it's shown, render designer agents
        if (showInit) {
            renderDesignerAgents();
            const providerSelect = document.getElementById('init-provider');
            if (providerSelect && SwarmState.llm_provider) {
                providerSelect.value = SwarmState.llm_provider;
            }
            const autoApproveCheckbox = document.getElementById('init-auto-approve');
            if (autoApproveCheckbox) {
                autoApproveCheckbox.checked = !!SwarmState.auto_approve_spawns;
            }
        }

        const closeBtn = document.getElementById('init-close-btn');
        if (closeBtn) {
            closeBtn.style.display = (SwarmState.swarm_running || SwarmState.agents.length > 0) ? 'block' : 'none';
        }
    }
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
// Blue Status Bar (VS Code) — glanceable global state
// ---------------------------------------------------------------------------
function renderStatusBar() {
    const bar = document.getElementById('status-bar');
    if (!bar) return;
    const running = SwarmState.swarm_running;
    const agents = SwarmState.agents.length;
    const stateLabel = running ? 'Running' : (agents > 0 ? 'Completed' : 'Idle');
    const dotCls = running ? 'run' : (agents > 0 ? 'done' : 'idle');
    const used = (SwarmState.budget_alert && SwarmState.budget_alert.active_count) || getMaxLeafTokens();
    const cap = SwarmState.session_budget || 20000;
    const decisions = (SwarmState.pending_spawns || []).length + (SwarmState.pending_blockers || []).length;
    const collisions = (SwarmState.collisions || []).length;
    const lastLog = (SwarmState.logs || []).slice(-1)[0] || '';

    let html = '';
    html += `<span class="status-bar__item"><span class="status-bar__dot status-bar__dot--${dotCls}"></span>${stateLabel}</span>`;
    html += `<span class="status-bar__item" title="Active agents">◆ ${agents} agent${agents === 1 ? '' : 's'}</span>`;
    html += `<span class="status-bar__item status-bar__item--clk" data-action="open-drawer" data-tab="activity" title="Token budget — open Activity">⛁ ${used.toLocaleString()} / ${cap.toLocaleString()}</span>`;
    html += `<span class="status-bar__spacer"></span>`;
    if (decisions > 0) {
        html += `<span class="status-bar__item status-bar__item--alert status-bar__item--clk" data-action="open-drawer" data-tab="activity" title="Pending decisions">🔔 ${decisions} decision${decisions === 1 ? '' : 's'}</span>`;
    }
    if (collisions > 0) {
        html += `<span class="status-bar__item" title="Active collisions">⚡ ${collisions}</span>`;
    }
    html += `<span class="status-bar__item status-bar__item--clk" data-action="open-drawer" data-tab="logs" title="View logs">📜 Logs</span>`;
    if (lastLog) {
        html += `<span class="status-bar__item status-bar__item--log">${escapeHtml(lastLog)}</span>`;
    }
    bar.innerHTML = html;
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
                 data-action="select-agent" data-agent-id="${agent.id}"
                 ondblclick="UIState.inspectorOpen=true; UIState.selectedAgentId='${agent.id}'; UIState.selectedWorkspaceAgent='${agent.id}'; UIState.workspaceData=null; render();">
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
                    <button class="btn btn--sm btn--ghost" data-action="open-inspector" data-agent-id="${agent.id}" data-tab="trace" title="View causal trace">🔍</button>
                    <button class="btn btn--sm btn--ghost" data-action="open-inspector" data-agent-id="${agent.id}" data-tab="overview" title="Open inspector">ℹ️</button>
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
        awaiting_child: '⧖ Awaiting child',
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
    if (countBadge) {
        countBadge.textContent = alertCount;
    }

    list.style.padding = '0';
    list.style.gap = '0';

    if (SwarmState.agents.length === 0) {
        list.innerHTML = `
            <div class="empty-state" style="padding: var(--space-lg); text-align: center; margin-top: var(--space-xl);">
                <div class="empty-state__icon">📄</div>
                <div class="empty-state__title">No Swarm Task Running</div>
                <div class="empty-state__desc">Initialize the swarm to generate code and view workspace files here.</div>
            </div>
        `;
        return;
    }

    const agentId = UIState.selectedWorkspaceAgent || SwarmState.agents[0].id;
    
    if (UIState.workspaceData && UIState.selectedWorkspaceAgent === agentId) {
        const files = UIState.workspaceData.files || [];
        const contents = UIState.workspaceData.contents || {};

        if (files.length === 0) {
            list.innerHTML = `
                <div style="padding: var(--space-md); border-bottom: 1px solid var(--border-secondary); background: var(--bg-secondary);">
                    <div style="font-size: 0.72rem; font-weight: 600; text-transform: uppercase; color: var(--text-secondary); letter-spacing: 0.05em; margin-bottom: var(--space-xs);">Agent Workspace</div>
                    <select class="form-select" id="change-workspace-agent" style="width: 100%; padding: 2px 6px; font-size: 0.75rem;">
                        ${SwarmState.agents.map(a => `<option value="${a.id}" ${a.id === agentId ? 'selected' : ''}>Agent ${a.id} (${escapeHtml(a.personality || 'Generalist')})</option>`).join('')}
                    </select>
                </div>
                <div class="empty-state" style="padding: var(--space-lg); text-align: center; margin-top: var(--space-xl);">
                    <div class="empty-state__icon">📄</div>
                    <div class="empty-state__title">No Files Yet</div>
                    <div class="empty-state__desc">Agent ${agentId} hasn't created any workspace files yet.</div>
                </div>
            `;
        } else {
            const selectedFile = UIState.selectedFile || files[0];
            const content = contents[selectedFile] || '';
            
            const fileTabsHtml = files.map(f => {
                const isActive = f === selectedFile;
                return `<button class="editor-tab ${isActive ? 'editor-tab--active' : ''}" data-action="select-file" data-file="${escapeAttr(f)}">${escapeHtml(f)}</button>`;
            }).join('');

            const breadcrumb = `src › agent_${agentId} › ${selectedFile.split('/').join(' › ')}`;
            const lines = content.split('\n');
            const lineNumbersHtml = lines.map((_, idx) => `<div class="editor-line-number">${idx + 1}</div>`).join('');
            const linesHtml = lines.map(line => `<div class="editor-code-line">${escapeHtml(line) || '&nbsp;'}</div>`).join('');

            list.innerHTML = `
                <div style="display: flex; flex-direction: column; height: 100%;">
                    <div class="editor-tabs-container" style="display: flex; overflow-x: auto; background: var(--bg-tertiary); border-bottom: 1px solid var(--border-secondary); flex-shrink: 0;">
                        ${fileTabsHtml}
                    </div>
                    <div class="editor-breadcrumb" style="padding: 4px var(--space-md); background: var(--bg-secondary); border-bottom: 1px solid var(--border-secondary); font-size: 0.68rem; color: var(--text-secondary); flex-shrink: 0; font-family: var(--font-sans);">
                        ${breadcrumb}
                    </div>
                    <div class="editor-body" style="flex: 1; display: flex; overflow: auto; background: var(--bg-primary); font-family: var(--font-mono); font-size: 0.75rem; line-height: 1.5;">
                        <div class="editor-line-numbers" style="padding: var(--space-sm) var(--space-xs); text-align: right; color: var(--text-muted); border-right: 1px solid var(--border-secondary); user-select: none; background: var(--bg-secondary); min-width: 30px; flex-shrink: 0;">
                            ${lineNumbersHtml}
                        </div>
                        <div class="editor-code" style="padding: var(--space-sm) var(--space-md); color: var(--text-bright); white-space: pre; flex: 1; overflow: auto;">
                            ${linesHtml}
                        </div>
                    </div>
                </div>
            `;
        }
    } else {
        list.innerHTML = '<div style="text-align: center; padding: var(--space-xl);"><div class="skeleton skeleton--card"></div><div class="skeleton skeleton--card"></div></div>';
        loadWorkspace(agentId);
    }
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
    // Update active state on the activity bar (and any legacy tab strip)
    document.querySelectorAll('.viewport__tab, .activity-bar__item').forEach(tab => {
        const active = tab.dataset.tab === UIState.activeTab;
        tab.classList.toggle('viewport__tab--active', active);
        tab.classList.toggle('activity-bar__item--active', active);
    });

    // Dynamically update agent chat tab text to show current agent identifier
    const chatTab = document.getElementById('agent-chat-tab');
    if (chatTab) {
        if (UIState.editingAgentId) {
            chatTab.textContent = `Agent Chat (${UIState.editingAgentId})`;
        } else {
            chatTab.textContent = 'Agent Chat';
        }
    }

    const container = document.getElementById('viewport-content');

    switch (UIState.activeTab) {
        case 'overview':
            renderOverviewTab(container);
            break;
        case 'clusters':
            renderStage(container);
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
        case 'agent-chat':
            renderAgentChatTab(container);
            break;
    }
}

function renderAgentChatTab(container) {
    const agentId = UIState.editingAgentId;
    const agent = SwarmState.agents.find(a => a.id === agentId);
    if (!agent) {
        container.innerHTML = `
            <div class="empty-state">
                <div class="empty-state__icon">🤖</div>
                <div class="empty-state__title">No Agent Selected</div>
                <div class="empty-state__desc">Select an agent from the sidebar list or cluster map to view details.</div>
            </div>
        `;
        return;
    }

    const steps = agent.steps || [];
    let stepsHtml = '';
    if (steps.length > 0) {
        stepsHtml = `
            <div class="workspace-section">
                <div class="workspace-section__title">📌 Task Steps</div>
                <div class="workspace-steps-list">
        `;
        const currentStepNum = getStepNumber(agent);
        for (const step of steps) {
            const stepStatusClass = currentStepNum > step.step_id ? 'step--completed' :
                                    currentStepNum === step.step_id ? 'step--active' : 'step--pending';
            const stepIcon = currentStepNum > step.step_id ? '✅' :
                             currentStepNum === step.step_id ? '🔄' : '⏳';
            stepsHtml += `
                <div class="workspace-step ${stepStatusClass}">
                    <div class="workspace-step__header">
                        <span class="workspace-step__icon">${stepIcon}</span>
                        <span class="workspace-step__name">Step ${step.step_id}: ${escapeHtml(step.name || '')}</span>
                    </div>
                    <div class="workspace-step__desc">${escapeHtml(step.description || '')}</div>
                </div>
            `;
        }
        stepsHtml += '</div></div>';
    }

    // Budget section
    const nodeBudget = agent.token_budget || SwarmState.session_budget || 20000;
    const subtreeBudget = agent.subtree_token_budget || null;
    const usedTokens = agent.output_tokens || 0;
    const budgetPctNode = Math.min(Math.round((usedTokens / Math.max(nodeBudget, 1)) * 100), 100);
    const budgetColorNode = budgetPctNode > 90 ? 'red' : budgetPctNode > 60 ? 'amber' : 'green';

    const allAgents = SwarmState.agents;
    const hasChildren = allAgents.some(a => a.parent_id === agentId && !['completed', 'dead'].includes(a.status));

    let budgetHtml = `
        <div class="workspace-section">
            <div class="workspace-section__title">🪙 Token Budget Cap</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-sm); margin-bottom: var(--space-sm);">
                <div>
                    <label class="form-label" style="font-size: 0.65rem;">Node Budget</label>
                    <input type="number" class="form-input form-input--compact" id="workspace-node-budget" value="${nodeBudget}" min="100" step="100">
                </div>
                <div>
                    <label class="form-label" style="font-size: 0.65rem;">Subtree Budget</label>
                    <input type="number" class="form-input form-input--compact" id="workspace-subtree-budget" value="${subtreeBudget || ''}" placeholder="Inherit global" min="100" step="100">
                </div>
            </div>
            <div class="budget-tree__bar" style="height: 6px; border-radius: 3px; background: var(--bg-tertiary); overflow: hidden;">
                <div class="budget-tree__bar-fill budget-tree__bar-fill--${budgetColorNode}" style="width: ${budgetPctNode}%"></div>
            </div>
            <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: var(--space-xs); display: flex; justify-content: space-between;">
                <span>Used: ${usedTokens.toLocaleString()} / ${nodeBudget.toLocaleString()}</span>
                <span>${budgetPctNode}%</span>
            </div>
    `;

    if (hasChildren) {
        budgetHtml += `
            <div style="margin-top: var(--space-md); border-top: 1px solid var(--border-secondary); padding-top: var(--space-sm);">
                <div style="font-size: 0.68rem; font-weight: 600; color: var(--text-secondary); margin-bottom: var(--space-xs);">Redistribute Budget</div>
                <div style="display: flex; gap: var(--space-xs);">
                    <button class="btn btn--sm btn--ghost" data-action="redistribute-budget" data-parent-id="${agentId}" data-strategy="equal" title="Split equally among children">⚖️ Equal</button>
                    <button class="btn btn--sm btn--ghost" data-action="redistribute-budget" data-parent-id="${agentId}" data-strategy="weighted" title="Proportional to progress">📊 Weighted</button>
                    <button class="btn btn--sm btn--ghost" data-action="redistribute-budget" data-parent-id="${agentId}" data-strategy="priority" title="Based on priority weights">🎯 Priority</button>
                </div>
            </div>
        `;
    }
    budgetHtml += `</div>`;

    // Combine and sort chat messages + thought traces
    const chatMessages = agent.chat_messages || [];
    const thoughts = agent.thought_traces || [];

    const timelineItems = [];
    for (const msg of chatMessages) {
        timelineItems.push({
            type: 'chat',
            timestamp: msg.timestamp,
            data: msg
        });
    }
    for (const th of thoughts) {
        timelineItems.push({
            type: 'thought',
            timestamp: th.timestamp,
            data: th
        });
    }

    timelineItems.sort((a, b) => a.timestamp - b.timestamp);

    let chatTimelineHtml = '';
    if (timelineItems.length === 0) {
        chatTimelineHtml = `
            <div class="chat-panel__empty" style="flex: 1; display: flex; flex-direction: column; justify-content: center; min-height: 200px;">
                <div style="font-size: 1.5rem;">💬</div>
                <div style="margin-top: var(--space-sm);">No messages or thoughts logged yet.</div>
                <div style="font-size: 0.72rem; color: var(--text-muted); max-width: 250px; margin: 4px auto 0;">Send a message to direct the agent or run the swarm to see thoughts in real time.</div>
            </div>
        `;
    } else {
        chatTimelineHtml = '<div class="agent-chat-timeline" id="agent-chat-timeline-scroll">';
        for (const item of timelineItems) {
            if (item.type === 'chat') {
                const msg = item.data;
                const timeStr = new Date(msg.timestamp * 1000).toLocaleTimeString();
                const isUser = msg.role === 'user';
                const roleClass = isUser ? 'chat-message--user' : 'chat-message--system';
                chatTimelineHtml += `
                    <div class="chat-message ${roleClass}" style="max-width: 80%; margin-bottom: var(--space-sm);">
                        <div class="chat-message__bubble" style="padding: var(--space-sm) var(--space-md); border-radius: var(--radius-md); font-size: 0.8rem;">${escapeHtml(msg.content)}</div>
                        <div class="chat-message__meta">
                            <span>${isUser ? 'You' : 'Agent'}</span>
                            <span>·</span>
                            <span>${timeStr}</span>
                            ${!msg.processed && isUser ? '<span class="chat-message__pending">pending</span>' : ''}
                            ${msg.processed && isUser ? '<span style="color: var(--accent-green);">✓ delivered</span>' : ''}
                        </div>
                    </div>
                `;
            } else {
                const th = item.data;
                const timeStr = new Date(th.timestamp * 1000).toLocaleTimeString();
                const iconMap = {
                    evaluating: '🔍',
                    decision: '🎯',
                    executing: '🔄',
                    completed: '✅',
                    failed: '❌',
                    spawn: '🚀',
                    syncing: '⚡',
                    resolved: '🤝'
                };
                const icon = iconMap[th.type] || '💭';
                chatTimelineHtml += `
                    <div class="thought-trace thought-trace--${th.type}">
                        <div class="thought-trace__icon">${icon}</div>
                        <div class="thought-trace__body">
                            <div class="thought-trace__content">${escapeHtml(th.content)}</div>
                            <div class="thought-trace__time">${timeStr}</div>
                        </div>
                    </div>
                `;
            }
        }
        chatTimelineHtml += '</div>';
    }

    container.innerHTML = `
        <div class="agent-chat-layout">
            <!-- Left Pane: LLM Chat Interface -->
            <div class="agent-chat-left">
                <div class="agent-chat-header">
                    <span style="font-size: 1rem; font-weight: 700; color: var(--text-primary); display: flex; align-items: center; gap: 8px;">
                        👤 Agent ${agentId} <span style="font-size:0.75rem; font-weight:normal; color:var(--text-muted);">(${escapeHtml(agent.personality || agent.role || 'Generalist')})</span>
                    </span>
                    <button class="btn btn--sm btn--ghost" data-action="close-edit" style="font-size: 0.75rem;">✕ Close Workspace</button>
                </div>
                
                <div class="agent-chat-body" style="flex: 1; display: flex; flex-direction: column; overflow: hidden; background: var(--bg-secondary); border-radius: var(--radius-md); padding: var(--space-md); border: 1px solid var(--border-primary);">
                    ${chatTimelineHtml}
                    
                    <div class="agent-chat-input-row" style="display: flex; gap: var(--space-sm); margin-top: var(--space-md); padding-top: var(--space-sm); border-top: 1px solid var(--border-primary);">
                        <input type="text" class="form-input" id="agent-workspace-chat-input" placeholder="Send message/directive to Agent ${agentId}..." style="flex: 1;" autocomplete="off">
                        <button class="btn btn--primary" id="agent-workspace-chat-send-btn" data-agent-id="${agentId}">Send</button>
                    </div>
                </div>
            </div>
            
            <!-- Right Pane: Workspace Details & Settings -->
            <div class="agent-chat-right">
                <div class="workspace-section" style="margin-top: 0;">
                    <div class="workspace-section__title">⚙️ Agent Settings</div>
                    <div class="form-group">
                        <label class="form-label">Role / Personality</label>
                        <input type="text" class="form-input form-input--compact" id="workspace-agent-role" value="${escapeAttr(agent.personality || agent.role || 'Generalist')}">
                    </div>
                    <div class="form-group">
                        <label class="form-label">Goal / Subtask</label>
                        <textarea class="form-textarea" id="workspace-agent-goal" rows="3" style="font-size: 0.78rem;">${escapeHtml(agent.goal || '')}</textarea>
                    </div>
                    <div class="form-group" style="display:flex; justify-content:space-between; align-items:center; margin-bottom: 0;">
                        <span style="font-size:0.75rem; color:var(--text-secondary);">Status: <strong style="color: ${{
                            exploring: 'var(--accent-cyan)',
                            completed: 'var(--accent-green)',
                            dead: 'var(--accent-red)',
                            syncing: 'var(--accent-amber)',
                            pending_termination: 'var(--accent-red)',
                        }[agent.status] || 'var(--text-primary)'};">${statusLabel(agent.status)}</strong></span>
                        <button class="btn btn--ghost btn--sm" id="workspace-agent-save-btn" data-agent-id="${agentId}">💾 Save Changes</button>
                    </div>
                </div>

                ${budgetHtml}

                <div class="workspace-section">
                    <div class="workspace-section__title">📈 Completion Progress</div>
                    <div class="progress-bar" style="height: 8px; border-radius: 4px;"><div class="progress-bar__fill" style="width: ${computeProgress(agent)}%"></div></div>
                    <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: var(--space-xs); display:flex; justify-content:space-between;">
                        <span>Step ${getStepNumber(agent)}/${steps.length || '?'}</span>
                        <span>${computeProgress(agent)}%</span>
                    </div>
                    <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: 2px;">
                        Output Tokens: <strong>${(agent.output_tokens || 0).toLocaleString()}</strong>
                    </div>
                </div>

                ${stepsHtml}

                <div class="workspace-section">
                    <div class="workspace-section__title">📁 Touched Files</div>
                    <div class="workspace-touched-files-list">
                        ${(agent.touched_files || []).map(f => `
                            <div class="workspace-file-item" data-action="view-workspace" data-agent-id="${agentId}" style="cursor: pointer; padding: 4px 6px; border-radius: var(--radius-sm); font-family: var(--font-mono); font-size: 0.72rem; color: var(--accent-cyan);">
                                📄 ${escapeHtml(f)}
                            </div>
                        `).join('') || '<div style="font-size:0.72rem; color: var(--text-muted); font-style:italic;">No files touched yet</div>'}
                    </div>
                </div>
            </div>
        </div>
    `;

    // Auto-scroll timeline to bottom
    const scrollContainer = document.getElementById('agent-chat-timeline-scroll');
    if (scrollContainer) {
        scrollContainer.scrollTop = scrollContainer.scrollHeight;
    }

    // Attach listeners inside this tab
    const chatInput = document.getElementById('agent-workspace-chat-input');
    if (chatInput) {
        chatInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendWorkspaceChatMessage(agentId);
            }
        });
    }

    const sendBtn = document.getElementById('agent-workspace-chat-send-btn');
    if (sendBtn) {
        sendBtn.onclick = () => sendWorkspaceChatMessage(agentId);
    }

    const saveBtn = document.getElementById('workspace-agent-save-btn');
    if (saveBtn) {
        saveBtn.onclick = () => saveWorkspaceAgentEdits(agentId);
    }
}

async function sendWorkspaceChatMessage(agentId) {
    const input = document.getElementById('agent-workspace-chat-input');
    if (!input) return;
    const message = input.value.trim();
    if (!message) return;

    input.value = '';

    const result = await apiPost(`/api/agents/${agentId}/chat`, { message });
    if (result.success) {
        showToast(`Message sent to Agent ${agentId}`, 'success');
        const agent = SwarmState.agents.find(a => a.id === agentId);
        if (agent) {
            if (!agent.chat_messages) agent.chat_messages = [];
            agent.chat_messages.push({
                role: 'user',
                content: message,
                timestamp: Date.now() / 1000,
                processed: false
            });
            render();
        }
    } else {
        showToast(result.message || 'Failed to send message', 'error');
    }
}

async function saveWorkspaceAgentEdits(agentId) {
    const role = document.getElementById('workspace-agent-role').value;
    const goal = document.getElementById('workspace-agent-goal').value;
    const nodeBudgetInput = document.getElementById('workspace-node-budget');
    const subtreeBudgetInput = document.getElementById('workspace-subtree-budget');

    const updates = {
        personality: role,
        goal: goal
    };

    if (nodeBudgetInput && nodeBudgetInput.value) {
        updates.token_budget = parseInt(nodeBudgetInput.value);
    }
    if (subtreeBudgetInput && subtreeBudgetInput.value) {
        updates.subtree_token_budget = parseInt(subtreeBudgetInput.value);
    }

    const result = await apiPost(`/api/agents/${agentId}/edit`, updates);
    if (result.success) {
        showToast(`Agent ${agentId} updated`, 'success');
        const agent = SwarmState.agents.find(a => a.id === agentId);
        if (agent) {
            agent.personality = role;
            agent.goal = goal;
            if (updates.token_budget) agent.token_budget = updates.token_budget;
            if (updates.subtree_token_budget) agent.subtree_token_budget = updates.subtree_token_budget;
            render();
        }
    } else {
        showToast(result.message || 'Failed to update agent', 'error');
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

function renderClusterSidebar(agentId, container) {
    if (!container) return;
    if (!agentId) {
        container.innerHTML = `
            <div style="flex:1; display:flex; align-items:center; justify-content:center; text-align:center; color:var(--text-muted); font-size:0.75rem;">
                💡 Click an agent node in the cluster map to view detailed task similarities and actions.
            </div>
        `;
        return;
    }

    const agent = SwarmState.agents.find(a => a.id === agentId);
    if (!agent) return;

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

    container.innerHTML = sidebarHtml;
}

function renderSwarmMap(container) {
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
        <div style="display: flex; flex-direction: column; height: 100%;">
            <div class="map-legend" style="display: flex; flex-wrap: wrap; gap: var(--space-md); padding: var(--space-sm) var(--space-xl); background: var(--bg-secondary); border-bottom: 1px solid var(--border-secondary); font-size: 0.72rem; color: var(--text-secondary); flex-shrink: 0;">
                <span style="display: flex; align-items: center; gap: 4px;"><span style="width: 8px; height: 8px; border-radius: 50%; background: var(--accent-green);"></span>Exploring</span>
                <span style="display: flex; align-items: center; gap: 4px;"><span style="width: 8px; height: 8px; border-radius: 50%; background: var(--text-muted);"></span>Idle</span>
                <span style="display: flex; align-items: center; gap: 4px;"><span style="width: 8px; height: 8px; border-radius: 50%; background: var(--accent-blue-light);"></span>Completed</span>
                <span style="display: flex; align-items: center; gap: 4px;"><span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--accent-blue);"></span>Needs Input</span>
                <span style="display: flex; align-items: center; gap: 4px;"><span style="display: inline-block; width: 12px; height: 12px; border-radius: 50%; border: 2px solid var(--accent-orange);"></span>Low Budget</span>
                <span style="display: flex; align-items: center; gap: 4px;"><span style="display: inline-block; width: 16px; height: 2px; background: var(--border-primary);"></span>Parent → Child</span>
                <span style="display: flex; align-items: center; gap: 4px;"><span style="display: inline-block; width: 16px; height: 2px; border-top: 2px dashed var(--accent-purple);"></span>Redundancy Link</span>
            </div>
            <div class="cluster-view-container" style="flex: 1; min-height: 0;">
                <div class="cluster-map-canvas" id="cluster-svg-parent"></div>
                <div class="cluster-sidebar" id="cluster-sidebar-content"></div>
            </div>
        </div>
    `;

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

    function layoutNode(node, level, parentAngle) {
        const k = node.children.length;
        if (k === 0) {
            node.radius = 70;
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

    const svgParent = document.getElementById('cluster-svg-parent');
    let svgHtml = `<svg class="cluster-svg" viewBox="0 0 1000 600" width="100%" height="100%">
        <defs>
            <marker id="arrow" markerWidth="7" markerHeight="7" refX="29" refY="3" orient="auto">
                <path d="M0,0 L6,3 L0,6 Z" fill="var(--border-primary)"/>
            </marker>
        </defs>`;

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

    // Parent -> child directional edges
    for (const node of Object.values(nodeMap)) {
        if (node.parent) {
            svgHtml += `<line class="cluster-edge" x1="${node.parent.x}" y1="${node.parent.y}" x2="${node.x}" y2="${node.y}" marker-end="url(#arrow)" style="stroke: var(--border-primary); stroke-width: 1.4; opacity: 0.6;"/>`;
        }
    }

    // Links (Proximity)
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

        // Budget color-coding
        const agentBudget = agent.token_budget || (SwarmState.session_budget || 20000);
        const agentTokens = agent.output_tokens || 0;
        const budgetPctCluster = Math.min(Math.round((agentTokens / Math.max(agentBudget, 1)) * 100), 100);
        const budgetColorClass = budgetPctCluster > 90 ? 'budget--red' : budgetPctCluster > 60 ? 'budget--amber' : 'budget--green';

        const role = escapeHtml(truncate(agent.personality || agent.role || 'Generalist', 20));
        const goalSnippet = escapeHtml(truncate(agent.goal || '', 24));
        const budgetLabel = `${agentTokens.toLocaleString()}/${agentBudget.toLocaleString()} (${budgetPctCluster}%)`;

        const needsInput = SwarmState.pending_spawns.some(s => s.agent_id === agent.id) ||
                           SwarmState.pending_blockers.some(b => b.agent_id === agent.id) ||
                           agent.status === 'pending_termination' ||
                           agent.status === 'syncing' ||
                           agent.status === 'awaiting_child';
        const lowBudget = budgetPctCluster > 90;

        svgHtml += `
            <g class="cluster-node" data-agent-id="${agent.id}">
                <g class="cluster-node-g">`;
        
        if (needsInput) {
            svgHtml += `<circle cx="${node.x}" cy="${node.y}" r="29" fill="none" stroke="var(--accent-blue)" stroke-width="2"/>`;
        } else if (lowBudget) {
            svgHtml += `<circle cx="${node.x}" cy="${node.y}" r="29" fill="none" stroke="var(--accent-orange)" stroke-width="2"/>`;
        }

        svgHtml += `
                    <circle class="cluster-node-circle ${statusClass} ${budgetColorClass}" cx="${node.x}" cy="${node.y}" r="22" />
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
                    <text x="${node.x}" y="${node.y + 68}" 
                          style="font-family: var(--font-mono); font-size: 7px; fill: ${budgetPctCluster > 90 ? 'var(--accent-red)' : budgetPctCluster > 60 ? 'var(--accent-amber)' : 'var(--accent-green)'}; text-anchor: middle; opacity: 0.8;">
                          🔋 ${budgetLabel}
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
            UIState.selectedWorkspaceAgent = agentId;
            UIState.workspaceData = null;
            svgParent.querySelectorAll('.cluster-node-circle').forEach(circle => {
                circle.classList.remove('node--selected');
            });
            nodeG.querySelector('.cluster-node-circle').classList.add('node--selected');
            renderClusterSidebar(agentId, document.getElementById('cluster-sidebar-content'));
            render();
        } else {
            UIState.selectedAgentId = null;
            render();
        }
    });

    svgParent.querySelector('svg').addEventListener('dblclick', (e) => {
        const nodeG = e.target.closest('.cluster-node');
        if (nodeG) {
            const agentId = nodeG.dataset.agentId;
            UIState.selectedAgentId = agentId;
            UIState.inspectorOpen = true;
            render();
        }
    });

    const selectedId = UIState.selectedAgentId || (SwarmState.agents.length > 0 ? SwarmState.agents[0].id : null);
    renderClusterSidebar(selectedId, document.getElementById('cluster-sidebar-content'));
}

function renderStage(container) {
    if (SwarmState.agents.length === 0) {
        if (SwarmState.swarm_running) {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state__icon">🐝</div>
                    <div class="empty-state__title">Decomposing Goals...</div>
                    <div class="empty-state__desc">The swarm is initializing and planning steps. Please wait...</div>
                </div>
            `;
        } else {
            container.innerHTML = `
                <div class="empty-state">
                    <div class="empty-state__icon">🗺️</div>
                    <div class="empty-state__title">No Active Swarm</div>
                    <div class="empty-state__desc">Launch a new swarm to visualize task network map.</div>
                </div>
            `;
        }
        return;
    }
    const n = SwarmState.agents.length;
    if (UIState.stageView == null) {
        UIState.stageView = (n > 1) ? 'map' : 'timeline';
    }
    const view = UIState.stageView;
    container.innerHTML = `
        <div class="stage" style="display:flex; flex-direction:column; height:100%;">
            <div class="stage__toolbar" style="display:flex; align-items:center; justify-content:space-between; padding:6px 10px; border-bottom:1px solid var(--border-secondary); background:var(--bg-secondary); flex-shrink:0;">
                <div style="display:flex; gap:10px; align-items:center;">
                    <div class="seg" style="display:inline-flex; border:1px solid var(--border-primary); border-radius:var(--radius-sm); overflow:hidden;">
                        <button class="seg__btn ${view === 'map' ? 'seg__btn--on' : ''}" data-action="toggle-stage" data-stage="map" style="font-size:0.75rem; padding:4px 12px; background:${view === 'map' ? 'var(--accent-blue)' : 'var(--bg-tertiary)'}; color:${view === 'map' ? '#fff' : 'var(--text-secondary)'}; border:none; cursor:pointer;">◆ Map</button>
                        <button class="seg__btn ${view === 'timeline' ? 'seg__btn--on' : ''}" data-action="toggle-stage" data-stage="timeline" style="font-size:0.75rem; padding:4px 12px; background:${view === 'timeline' ? 'var(--accent-blue)' : 'var(--bg-tertiary)'}; color:${view === 'timeline' ? '#fff' : 'var(--text-secondary)'}; border:none; cursor:pointer;">💬 Timeline</button>
                    </div>
                    ${UIState.selectedAgentId ? `<button class="btn btn--sm" data-action="deselect-agent" style="font-size:0.7rem; padding:2px 8px; border:1px solid var(--border-primary); border-radius:var(--radius-sm); cursor:pointer; background:var(--bg-tertiary); color:var(--text-secondary);">✕ Show all agents</button>` : ''}
                </div>
                <span class="stage__status" style="font-size:0.75rem; color:var(--text-secondary);">${SwarmState.swarm_running ? '<span style="color:var(--accent-green);">●</span> Swarm optimal' : '<span style="color:var(--text-muted);">●</span> Swarm idle'} · ${n} agent${n === 1 ? '' : 's'}</span>
            </div>
            <div class="stage__body" id="stage-body" style="flex: 1; overflow: auto; position: relative;"></div>
        </div>
    `;
    const body = document.getElementById('stage-body');
    if (view === 'map') {
        renderSwarmMap(body);
    } else {
        renderTimeline(body);
    }
}

function renderTimeline(container) {
    const agentId = UIState.selectedAgentId;
    if (agentId) {
        UIState.editingAgentId = agentId;
        renderAgentChatTab(container);
    } else {
        let timelineItems = [];
        for (const agent of SwarmState.agents) {
            const thoughts = agent.thought_traces || [];
            for (const th of thoughts) {
                timelineItems.push({
                    type: 'thought',
                    timestamp: th.timestamp,
                    agentId: agent.id,
                    data: th
                });
            }
            const chatMessages = agent.chat_messages || [];
            for (const msg of chatMessages) {
                timelineItems.push({
                    type: 'chat',
                    timestamp: msg.timestamp,
                    agentId: agent.id,
                    data: msg
                });
            }
        }

        timelineItems.sort((a, b) => a.timestamp - b.timestamp);
        const recentItems = timelineItems.slice(-40);

        let timelineHtml = '<div class="swarm-timeline" id="swarm-timeline-scroll" style="display:flex; flex-direction:column; height:100%; overflow-y:auto; padding:var(--space-xl); background:var(--bg-secondary); gap: var(--space-md);">';
        
        if (recentItems.length === 0) {
            timelineHtml += `
                <div style="flex:1; display:flex; flex-direction:column; justify-content:center; align-items:center; text-align:center; color:var(--text-muted); min-height: 200px;">
                    <div style="font-size: 2rem; margin-bottom: var(--space-sm);">💬</div>
                    <div>No swarm activity yet. Run the swarm or select an agent to interact.</div>
                </div>
            `;
        } else {
            for (const item of recentItems) {
                const timeStr = new Date(item.timestamp * 1000).toLocaleTimeString();
                if (item.type === 'chat') {
                    const msg = item.data;
                    const isUser = msg.role === 'user';
                    const roleClass = isUser ? 'chat-message--user' : 'chat-message--system';
                    timelineHtml += `
                        <div class="chat-message ${roleClass}" style="max-width: 80%; margin-bottom: var(--space-sm); align-self: ${isUser ? 'flex-end' : 'flex-start'};">
                            <div class="chat-message__bubble" style="padding: var(--space-sm) var(--space-md); border-radius: var(--radius-md); font-size: 0.8rem; background: ${isUser ? 'var(--accent-blue-dim)' : 'var(--bg-tertiary)'}; border: 1px solid var(--border-primary);">
                                <strong style="color:var(--accent-cyan);">Agent ${item.agentId}:</strong> ${escapeHtml(msg.content)}
                            </div>
                            <div class="chat-message__meta" style="font-size:0.65rem; color:var(--text-muted); margin-top:2px;">
                                <span>${isUser ? 'You' : `Agent ${item.agentId}`}</span>
                                <span>·</span>
                                <span>${timeStr}</span>
                            </div>
                        </div>
                    `;
                } else {
                    const th = item.data;
                    const iconMap = {
                        evaluating: '🔍',
                        decision: '🎯',
                        executing: '🔄',
                        completed: '✅',
                        failed: '❌',
                        spawn: '🚀',
                        syncing: '⚡',
                        resolved: '🤝'
                    };
                    const icon = iconMap[th.type] || '💭';
                    timelineHtml += `
                        <div class="thought-trace thought-trace--${th.type}" style="display:flex; gap:var(--space-md); padding:var(--space-sm) var(--space-md); border-radius:var(--radius-sm); border-left:3px solid var(--border-primary); background:var(--bg-tertiary); max-width: 80%; align-self: flex-start;">
                            <div class="thought-trace__icon" style="font-size:1.1rem; padding-top:2px;">${icon}</div>
                            <div class="thought-trace__body">
                                <div class="thought-trace__content" style="font-size:0.8rem; line-height:1.45;"><strong style="color:var(--accent-cyan);">Agent ${item.agentId}:</strong> ${escapeHtml(th.content)}</div>
                                <div class="thought-trace__time" style="font-size:0.65rem; color:var(--text-muted); margin-top:2px;">${timeStr}</div>
                            </div>
                        </div>
                    `;
                }
            }
        }

        // Interleave decision cards for pending_spawns and pending_blockers
        let decisionsHtml = '';
        if (SwarmState.pending_spawns.length > 0 || SwarmState.pending_blockers.length > 0) {
            decisionsHtml += '<div style="margin-top: var(--space-lg); border-top: 1px solid var(--border-primary); padding-top: var(--space-md); display:flex; flex-direction:column; gap:var(--space-md);">';
            decisionsHtml += '<div style="font-size:0.77rem; font-weight:600; color:var(--text-secondary); letter-spacing:0.04em;">PENDING OPERATIONS</div>';
            for (const spawn of SwarmState.pending_spawns) {
                decisionsHtml += `
                    <div class="decision-card decision-card--spawn" style="margin-bottom: 0;">
                        <div class="decision-card__type decision-card__type--spawn">SPAWN REQUEST (Agent ${escapeHtml(spawn.agent_id)})</div>
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
            for (const blocker of SwarmState.pending_blockers) {
                const blk = blocker.blocker || {};
                decisionsHtml += `
                    <div class="decision-card decision-card--blocker" style="margin-bottom: 0;">
                        <div class="decision-card__type decision-card__type--blocker">BLOCKER (Agent ${escapeHtml(blocker.agent_id)})</div>
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
            decisionsHtml += '</div>';
        }

        timelineHtml += decisionsHtml;
        timelineHtml += `
            <div style="padding: var(--space-md); border-top: 1px solid var(--border-primary); margin-top: var(--space-lg); font-size:0.72rem; color:var(--text-muted); text-align:center;">
                💡 Send directives via command bar (e.g. <code>@001 add test comments</code>) or select an agent in sidebar to scope the chat.
            </div>
        `;
        timelineHtml += '</div>';

        container.innerHTML = timelineHtml;

        // Auto-scroll timeline to bottom
        const scrollContainer = document.getElementById('swarm-timeline-scroll');
        if (scrollContainer) {
            scrollContainer.scrollTop = scrollContainer.scrollHeight;
        }
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
    render();
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
    render();
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
    render();
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
// Agent Inspector Slide Panel
// ---------------------------------------------------------------------------
function renderInspector() {
    const inspectorEl = document.getElementById('inspector');
    const backdropEl = document.getElementById('slide-backdrop');
    if (!inspectorEl) return;

    if (!UIState.inspectorOpen || !UIState.selectedAgentId) {
        inspectorEl.classList.remove('slide-panel--active');
        if (backdropEl) backdropEl.classList.remove('modal-overlay--active');
        return;
    }

    const agentId = UIState.selectedAgentId;
    const agent = SwarmState.agents.find(a => a.id === agentId);
    if (!agent) {
        inspectorEl.classList.remove('slide-panel--active');
        if (backdropEl) backdropEl.classList.remove('modal-overlay--active');
        return;
    }

    inspectorEl.classList.add('slide-panel--active');
    if (backdropEl) {
        backdropEl.classList.add('modal-overlay--active');
    }

    // Update active tab styles
    inspectorEl.querySelectorAll('.inspector-tab').forEach(btn => {
        const active = btn.dataset.tab === UIState.inspectorTab;
        btn.classList.toggle('inspector-tab--active', active);
    });

    const titleEl = document.getElementById('inspector-title');
    if (titleEl) {
        titleEl.textContent = `Agent ${agentId} Inspector`;
    }

    const bodyEl = document.getElementById('inspector-body');
    if (!bodyEl) return;

    switch (UIState.inspectorTab) {
        case 'overview':
            renderInspectorOverview(agent, bodyEl);
            break;
        case 'budget':
            renderInspectorBudget(agent, bodyEl);
            break;
        case 'trace':
            renderInspectorTrace(agent, bodyEl);
            break;
        case 'memory':
            renderInspectorMemory(agent, bodyEl);
            break;
    }
}

function renderInspectorOverview(agent, bodyEl) {
    renderClusterSidebar(agent.id, bodyEl);
}

function renderInspectorBudget(agent, bodyEl) {
    const nodeBudget = agent.token_budget || SwarmState.session_budget || 20000;
    const subtreeBudget = agent.subtree_token_budget || null;
    const usedTokens = agent.output_tokens || 0;
    const budgetPctNode = Math.min(Math.round((usedTokens / Math.max(nodeBudget, 1)) * 100), 100);
    const budgetColorNode = budgetPctNode > 90 ? 'red' : budgetPctNode > 60 ? 'amber' : 'green';

    const allAgents = SwarmState.agents;
    const hasChildren = allAgents.some(a => a.parent_id === agent.id && !['completed', 'dead'].includes(a.status));

    let budgetHtml = `
        <div class="workspace-section" style="padding: 0; border: none; background: none;">
            <div class="workspace-section__title" style="margin-bottom: var(--space-md); font-size: 0.8rem; font-weight: 600; text-transform: uppercase; color: var(--text-secondary);">🪙 Token Budget Cap</div>
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: var(--space-sm); margin-bottom: var(--space-md);">
                <div>
                    <label class="form-label" style="font-size: 0.65rem;">Node Budget</label>
                    <input type="number" class="form-input form-input--compact" id="inspector-node-budget" value="${nodeBudget}" min="100" step="100">
                </div>
                <div>
                    <label class="form-label" style="font-size: 0.65rem;">Subtree Budget</label>
                    <input type="number" class="form-input form-input--compact" id="inspector-subtree-budget" value="${subtreeBudget || ''}" placeholder="Inherit global" min="100" step="100">
                </div>
            </div>
            <div class="budget-tree__bar" style="height: 6px; border-radius: 3px; background: var(--bg-tertiary); overflow: hidden;">
                <div class="budget-tree__bar-fill budget-tree__bar-fill--${budgetColorNode}" style="width: ${budgetPctNode}%"></div>
            </div>
            <div style="font-size: 0.7rem; color: var(--text-muted); margin-top: var(--space-xs); display: flex; justify-content: space-between; margin-bottom: var(--space-md);">
                <span>Used: ${usedTokens.toLocaleString()} / ${nodeBudget.toLocaleString()}</span>
                <span>${budgetPctNode}%</span>
            </div>
            <button class="btn btn--primary btn--sm" id="inspector-save-budget-btn" style="width: 100%; justify-content: center; margin-bottom: var(--space-lg);">💾 Save Budget Cap</button>
    `;

    if (hasChildren) {
        budgetHtml += `
            <div style="margin-top: var(--space-md); border-top: 1px solid var(--border-secondary); padding-top: var(--space-sm);">
                <div style="font-size: 0.68rem; font-weight: 600; color: var(--text-secondary); margin-bottom: var(--space-xs);">Redistribute Budget</div>
                <div style="display: flex; gap: var(--space-xs);">
                    <button class="btn btn--sm btn--ghost" data-action="redistribute-budget" data-parent-id="${agent.id}" data-strategy="equal" title="Split equally among children">⚖️ Equal</button>
                    <button class="btn btn--sm btn--ghost" data-action="redistribute-budget" data-parent-id="${agent.id}" data-strategy="weighted" title="Proportional to progress">📊 Weighted</button>
                    <button class="btn btn--sm btn--ghost" data-action="redistribute-budget" data-parent-id="${agent.id}" data-strategy="priority" title="Based on priority weights">🎯 Priority</button>
                </div>
            </div>
        `;
    }
    budgetHtml += `</div>`;
    
    bodyEl.innerHTML = budgetHtml;
    
    const saveBtn = document.getElementById('inspector-save-budget-btn');
    if (saveBtn) {
        saveBtn.onclick = async () => {
            const nodeBudgetInput = document.getElementById('inspector-node-budget');
            const subtreeBudgetInput = document.getElementById('inspector-subtree-budget');
            
            const updates = {
                personality: agent.personality || agent.role || 'Generalist',
                goal: agent.goal || ''
            };
            
            if (nodeBudgetInput && nodeBudgetInput.value) {
                updates.token_budget = parseInt(nodeBudgetInput.value);
            }
            if (subtreeBudgetInput && subtreeBudgetInput.value) {
                updates.subtree_token_budget = parseInt(subtreeBudgetInput.value);
            }
            
            const result = await apiPost(`/api/agents/${agent.id}/edit`, updates);
            if (result.success) {
                showToast(`Agent ${agent.id} budget updated`, 'success');
                agent.token_budget = updates.token_budget;
                agent.subtree_token_budget = updates.subtree_token_budget;
                render();
            } else {
                showToast(result.message || 'Failed to update budget', 'error');
            }
        };
    }
}

function renderInspectorTrace(agent, bodyEl) {
    if (UIState.selectedTraceAgent !== agent.id) {
        UIState.selectedTraceAgent = agent.id;
        UIState.traceData = null;
    }
    renderTraceTab(bodyEl);
}

function renderInspectorMemory(agent, bodyEl) {
    renderMemoryTab(bodyEl);
}


// ---------------------------------------------------------------------------
// Bottom Drawer (Activity & Logs)
// ---------------------------------------------------------------------------
function renderDrawer() {
    const drawerEl = document.getElementById('drawer');
    if (!drawerEl) return;

    if (!UIState.drawerOpen) {
        drawerEl.classList.remove('bottom-drawer--active');
        return;
    }

    drawerEl.classList.add('bottom-drawer--active');

    // Update active tab buttons in drawer header
    drawerEl.querySelectorAll('.bottom-drawer__tab').forEach(btn => {
        const active = btn.dataset.tab === UIState.drawerTab;
        btn.classList.toggle('bottom-drawer__tab--active', active);
    });

    const bodyEl = document.getElementById('drawer-body');
    if (!bodyEl) return;

    if (UIState.drawerTab === 'activity') {
        renderDrawerActivity(bodyEl);
    } else {
        renderDrawerLogs(bodyEl);
    }
}

function renderDrawerActivity(container) {
    const budgetAlert = SwarmState.budget_alert || {};
    const budgetExceeded = budgetAlert.budget_exceeded || false;
    const maxTokens = getMaxLeafTokens();
    const budgetCap = SwarmState.session_budget || 20000;

    let html = '';

    if (budgetExceeded) {
        html += `
            <div class="decision-card decision-card--blocker" style="margin-bottom: var(--space-md);">
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
        html += '<div class="section-label" style="font-size: 0.68rem; font-weight: 600; text-transform: uppercase; color: var(--text-secondary); margin-bottom: var(--space-sm);">⚡ Pending Spawns</div>';
        html += '<div style="display: flex; flex-wrap: wrap; gap: var(--space-md); margin-bottom: var(--space-md);">';
        for (const spawn of SwarmState.pending_spawns) {
            html += `
                <div class="decision-card decision-card--spawn" style="flex: 1; min-width: 280px; max-width: 400px; margin: 0;">
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
        html += '</div>';
    }

    // Pending Blockers
    if (SwarmState.pending_blockers.length > 0) {
        html += '<div class="section-label" style="font-size: 0.68rem; font-weight: 600; text-transform: uppercase; color: var(--text-secondary); margin-bottom: var(--space-sm);">🚧 Blockers</div>';
        html += '<div style="display: flex; flex-wrap: wrap; gap: var(--space-md); margin-bottom: var(--space-md);">';
        for (const blocker of SwarmState.pending_blockers) {
            const blk = blocker.blocker || {};
            html += `
                <div class="decision-card decision-card--blocker" style="flex: 1; min-width: 280px; max-width: 400px; margin: 0;">
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
        html += '</div>';
    }

    // Collisions
    if (SwarmState.collisions.length > 0) {
        html += '<div class="section-label" style="font-size: 0.68rem; font-weight: 600; text-transform: uppercase; color: var(--text-secondary); margin-bottom: var(--space-sm);">⚡ Collisions</div>';
        html += '<div style="display: flex; flex-direction: column; gap: var(--space-xs); margin-bottom: var(--space-md);">';
        for (const col of SwarmState.collisions) {
            html += `
                <div class="collision-entry" style="margin: 0; background: var(--bg-tertiary); border: 1px solid var(--border-primary); padding: var(--space-sm); border-radius: var(--radius-sm);">
                    <div class="collision-entry__agents" style="font-weight: 600; font-size: 0.75rem;">
                        Agent ${escapeHtml(col.agent_a || '?')} ↔ Agent ${escapeHtml(col.agent_b || '?')}
                    </div>
                    <div class="collision-entry__detail" style="font-size: 0.68rem; color: var(--text-secondary);">
                        Distance: ${(col.distance || 0).toFixed(3)} | Status: ${escapeHtml(col.status || 'active')}
                    </div>
                </div>
            `;
        }
        html += '</div>';
    }

    // Tombstones
    if (SwarmState.tombstones.length > 0) {
        html += '<div class="section-label" style="font-size: 0.68rem; font-weight: 600; text-transform: uppercase; color: var(--text-secondary); margin-bottom: var(--space-sm);">💀 Tombstones</div>';
        html += '<div style="display: flex; flex-direction: column; gap: var(--space-sm); margin-bottom: var(--space-md);">';
        for (const tomb of SwarmState.tombstones) {
            if (tomb.file_path) {
                html += `
                    <div class="tombstone-entry" style="margin: 0; background: var(--bg-tertiary); border: 1px solid var(--border-primary); padding: var(--space-sm); border-radius: var(--radius-sm);">
                        <div class="tombstone-entry__agent" style="font-weight: 600; color: var(--accent-orange); font-size: 0.75rem;">⚡ BLOCKER FAILURE</div>
                        <div class="tombstone-entry__reason" style="line-height: 1.45; font-size: 0.7rem;">
                            <strong>File:</strong> ${escapeHtml(tomb.file_path)}<br>
                            <strong>Tool:</strong> ${escapeHtml(tomb.tool_used)}<br>
                            <strong>Error:</strong> <span style="color: var(--accent-red);">${escapeHtml(tomb.error_message)}</span><br>
                            <strong>Fix:</strong> <span style="color: var(--accent-green);">${escapeHtml(tomb.fix_action)}</span>
                        </div>
                    </div>
                `;
            } else {
                html += `
                    <div class="tombstone-entry" style="margin: 0; background: var(--bg-tertiary); border: 1px solid var(--border-primary); padding: var(--space-sm); border-radius: var(--radius-sm);">
                        <div class="tombstone-entry__agent" style="font-weight: 600; color: var(--text-bright); font-size: 0.75rem;">💀 Agent ${escapeHtml(tomb.agent_id || '?')}</div>
                        <div class="tombstone-entry__reason" style="line-height: 1.45; font-size: 0.7rem;">
                            <strong>Status:</strong> ${tomb.is_pruned ? 'Pruned' : 'Terminated'}<br>
                            <strong>Goal:</strong> ${escapeHtml(tomb.goal || '')}<br>
                            <strong>Reason:</strong> ${escapeHtml(tomb.reason || 'No reason')}
                        </div>
                    </div>
                `;
            }
        }
        html += '</div>';
    }

    if (!html.includes('decision-card') && !html.includes('collision-entry') && !html.includes('tombstone-entry') && !budgetExceeded) {
        html += `
            <div style="padding: var(--space-lg); text-align: center; color: var(--text-muted); font-size: 0.78rem;">
                💤 No active alerts or decisions pending.
            </div>
        `;
    }

    container.innerHTML = html;
}

function renderDrawerLogs(container) {
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

    let html = '<div style="font-family: var(--font-mono); font-size: 0.75rem; line-height: 1.6; background: var(--bg-tertiary); border: 1px solid var(--border-primary); border-radius: var(--radius-sm); padding: var(--space-md); height: 100%; overflow-y: auto;" id="drawer-logs-box">';
    for (const line of logs) {
        const cls = line.includes('[ERROR]') ? 'color: var(--accent-red)' :
                    line.includes('[WARN]') ? 'color: var(--accent-amber)' :
                    'color: var(--text-secondary)';
        html += `<div style="${cls}; white-space: pre-wrap; margin-bottom: var(--space-xs);">${escapeHtml(line)}</div>`;
    }
    html += '</div>';
    container.innerHTML = html;
    
    // Auto scroll to bottom
    const box = document.getElementById('drawer-logs-box');
    if (box) {
        box.scrollTop = box.scrollHeight;
    }
}

// ---------------------------------------------------------------------------
// Agent Edit Panel
// ---------------------------------------------------------------------------
function openEditPanel(agentId) {
    const agent = SwarmState.agents.find(a => a.id === agentId);
    if (!agent) return;

    UIState.editingAgentId = agentId;
    UIState.activeTab = 'agent-chat';

    const tabEl = document.getElementById('agent-chat-tab');
    if (tabEl) {
        tabEl.style.display = 'flex';
    }

    render();
}

function closeEditPanel() {
    UIState.editingAgentId = null;
    const tabEl = document.getElementById('agent-chat-tab');
    if (tabEl) {
        tabEl.style.display = 'none';
    }
    if (UIState.activeTab === 'agent-chat') {
        UIState.activeTab = 'overview';
    }
    render();
}

async function sendChatMessage(agentId) {
    const input = document.getElementById('chat-input');
    if (!input) return;
    const message = input.value.trim();
    if (!message) return;
    input.value = '';

    const result = await apiPost(`/api/agents/${agentId}/chat`, { message });
    if (result.success) {
        showToast(`Message sent to Agent ${agentId}`, 'success');
        // Re-open panel to refresh chat
        openEditPanel(agentId);
    } else {
        showToast(result.message || 'Failed to send message', 'error');
    }
}

async function saveAgentEdits() {
    if (!UIState.editingAgentId) return;
    const role = document.getElementById('edit-role').value;
    const goal = document.getElementById('edit-goal').value;
    const nodeBudgetInput = document.getElementById('edit-node-budget');
    const subtreeBudgetInput = document.getElementById('edit-subtree-budget');

    const updates = {
        personality: role,
        goal: goal,
    };

    if (nodeBudgetInput && nodeBudgetInput.value) {
        updates.token_budget = parseInt(nodeBudgetInput.value);
    }
    if (subtreeBudgetInput && subtreeBudgetInput.value) {
        updates.subtree_token_budget = parseInt(subtreeBudgetInput.value);
    }

    const result = await apiPost(`/api/agents/${UIState.editingAgentId}/edit`, updates);
    if (result.success) {
        showToast(`Agent ${UIState.editingAgentId} updated`, 'success');
        closeEditPanel();
    } else {
        showToast(result.message || 'Failed to update agent', 'error');
    }
}

// ---------------------------------------------------------------------------
// Launch Modal / Unified Init Overlay Management
// ---------------------------------------------------------------------------
function openLaunchModal() {
    UIState.initModalOpen = true;
    UIState.designerAgents = [{ role: 'Generalist', goal: '' }];
    const goalInput = document.getElementById('init-goal');
    if (goalInput) {
        goalInput.value = '';
    }
    render();
    if (goalInput) {
        goalInput.focus();
    }
}

function closeLaunchModal() {
    UIState.initModalOpen = false;
    render();
}

function renderDesignerAgents() {
    const container = document.getElementById('designer-agents');
    if (!container) return;
    let html = '';
    for (let i = 0; i < UIState.designerAgents.length; i++) {
        const agent = UIState.designerAgents[i];
        html += `
            <div class="agent-designer-item" style="display: flex; gap: var(--space-sm); align-items: center; background: var(--bg-tertiary); border: 1px solid var(--border-primary); padding: var(--space-sm); border-radius: var(--radius-sm); margin-bottom: var(--space-xs);">
                <span class="agent-designer-item__number" style="font-family: var(--font-mono); font-size: 0.75rem; color: var(--text-muted);">#${i + 1}</span>
                <div class="agent-designer-item__fields" style="flex: 1; display: flex; flex-direction: column; gap: var(--space-xs);">
                    <input type="text" placeholder="Role (e.g. Backend Engineer)" value="${escapeAttr(agent.role)}"
                           data-action="update-designer-role" data-index="${i}" class="form-input" style="height: 28px; padding: 2px var(--space-sm); font-size: 0.75rem;">
                    <input type="text" placeholder="Goal (optional, inherits macro goal)" value="${escapeAttr(agent.goal)}"
                           data-action="update-designer-goal" data-index="${i}" class="form-input" style="height: 28px; padding: 2px var(--space-sm); font-size: 0.75rem;">
                </div>
                <button type="button" class="icon-btn" data-action="remove-designer-agent" data-index="${i}" title="Remove" style="flex-shrink: 0; padding: 4px;">✕</button>
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
    const goal = document.getElementById('init-goal').value.trim();
    const budget = parseInt(document.getElementById('init-budget').value) || 20000;

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

function editAgentBudgetInline(targetEl) {
    const agentId = targetEl.dataset.agentId;
    const agent = SwarmState.agents.find(a => a.id === agentId);
    const currentBudget = agent ? (agent.token_budget || SwarmState.session_budget || 20000) : 20000;
    
    const parentNode = targetEl.closest('.budget-tree__node');
    if (!parentNode) return;

    // Replace the action link with an inline editor
    const actionEl = parentNode.querySelector('.budget-tree__action');
    if (!actionEl) return;

    actionEl.outerHTML = `
        <div class="budget-inline-editor">
            <input type="number" id="inline-budget-${agentId}" value="${currentBudget}" min="100" step="100">
            <button class="btn btn--primary btn--sm" style="padding: 0 6px; height: 22px; font-size: 0.62rem;"
                    onclick="saveInlineAgentBudget('${agentId}')">Save</button>
            <button class="btn btn--ghost btn--sm" style="padding: 0 4px; height: 22px; font-size: 0.62rem;"
                    onclick="render()">✕</button>
        </div>
    `;

    const input = document.getElementById(`inline-budget-${agentId}`);
    if (input) {
        input.focus();
        input.select();
        input.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') saveInlineAgentBudget(agentId);
            if (e.key === 'Escape') render();
        });
    }
}

async function saveInlineAgentBudget(agentId) {
    const input = document.getElementById(`inline-budget-${agentId}`);
    if (!input) return;
    const val = parseInt(input.value);
    if (isNaN(val) || val < 100) {
        showToast('Budget must be at least 100', 'error');
        return;
    }
    const result = await apiPost(`/api/agents/${agentId}/budget`, { token_budget: val });
    if (result.success) {
        showToast(`Agent ${agentId} budget set to ${val.toLocaleString()}`, 'success');
        // Update local state
        const agent = SwarmState.agents.find(a => a.id === agentId);
        if (agent) agent.token_budget = val;
        render();
    } else {
        showToast(result.message || 'Failed to set budget', 'error');
    }
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
        case 'open-inspector':
            e.stopPropagation();
            UIState.inspectorOpen = true;
            UIState.selectedAgentId = target.dataset.agentId;
            if (target.dataset.tab) {
                UIState.inspectorTab = target.dataset.tab;
            }
            render();
            break;
        case 'close-inspector':
            UIState.inspectorOpen = false;
            render();
            break;
        case 'switch-inspector-tab':
            UIState.inspectorTab = target.dataset.tab;
            render();
            break;
        case 'close-slide-panels':
            closeEditPanel();
            UIState.inspectorOpen = false;
            render();
            break;
        case 'open-drawer':
            UIState.drawerOpen = true;
            if (target.dataset.tab) {
                UIState.drawerTab = target.dataset.tab;
            }
            render();
            break;
        case 'close-drawer':
            UIState.drawerOpen = false;
            render();
            break;
        case 'switch-drawer-tab':
            UIState.drawerTab = target.dataset.tab;
            render();
            break;
        case 'switch-right-tab':
            UIState.rightPanelTab = target.dataset.tab;
            render();
            break;
        case 'toggle-stage':
            UIState.stageView = target.dataset.stage;
            render();
            break;
        case 'init-launch':
        case 'launch-swarm':
            initLaunch();
            break;
        case 'open-launch':
            openLaunchModal();
            break;
        case 'close-launch':
        case 'close-init':
            UIState.initModalOpen = false;
            render();
            break;
        case 'set-budget-preset':
            e.stopPropagation();
            {
                const btnGroup = target.parentNode;
                btnGroup.querySelectorAll('.seg__btn').forEach(btn => {
                    btn.classList.remove('seg__btn--on');
                    btn.style.background = 'var(--bg-tertiary)';
                    btn.style.color = 'var(--text-secondary)';
                });
                target.classList.add('seg__btn--on');
                target.style.background = 'var(--accent-blue)';
                target.style.color = '#fff';
                const exactInput = document.getElementById('init-budget');
                if (exactInput) {
                    exactInput.value = target.dataset.value;
                }
            }
            break;
        case 'add-designer-agent':
            addDesignerAgent();
            break;
        case 'remove-designer-agent':
            removeDesignerAgent(parseInt(target.dataset.index));
            break;
        case 'select-agent':
            UIState.selectedAgentId = target.dataset.agentId;
            UIState.selectedWorkspaceAgent = target.dataset.agentId;
            UIState.workspaceData = null;
            render();
            break;
        case 'deselect-agent':
            UIState.selectedAgentId = null;
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
        case 'send-chat':
            e.stopPropagation();
            sendChatMessage(target.dataset.agentId);
            break;
        case 'edit-agent-budget':
            e.stopPropagation();
            editAgentBudgetInline(target);
            break;
        case 'redistribute-budget':
            e.stopPropagation();
            {
                const parentId = target.dataset.parentId;
                const strategy = target.dataset.strategy;
                apiPost('/api/budget/redistribute', { parent_id: parentId, strategy }).then(r => {
                    showToast(r.success ? r.message : (r.message || 'Redistribution failed'), r.success ? 'success' : 'error');
                    if (r.success && UIState.editingAgentId) {
                        openEditPanel(UIState.editingAgentId);
                    }
                });
            }
            break;
        case 'view-synthesis':
            openSynthesis();
            break;
        case 'close-synthesis':
            document.getElementById('synthesis-modal').classList.remove('modal-overlay--active');
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
    if (e.target.id === 'workspace-agent-select' || e.target.id === 'change-workspace-agent') {
        UIState.selectedWorkspaceAgent = e.target.value;
        UIState.workspaceData = null;
        render();
    }
    if (e.target.id === 'trace-agent-select') {
        UIState.selectedTraceAgent = e.target.value;
        UIState.traceData = null;
        renderViewportContent();
    }
    if (e.target.id === 'change-workspace-file') {
        UIState.selectedFile = e.target.value;
        render();
    }
});

// Document-level Esc key listener to clear agent selection
document.addEventListener('keydown', (e) => {
    if (e.key !== 'Escape') return;
    const t = e.target;
    if (t && (t.tagName === 'INPUT' || t.tagName === 'TEXTAREA' || t.tagName === 'SELECT')) return;
    if (UIState.inspectorOpen) return;
    if (UIState.selectedAgentId !== null) {
        UIState.selectedAgentId = null;
        render();
    }
});

// Command bar (Enter key)
document.getElementById('command-input').addEventListener('keydown', (e) => {
    if (e.key === 'Enter') {
        const input = e.target.value.trim();
        if (!input) return;
        e.target.value = '';

        // Handle @agent_id message syntax for chat
        const chatMatch = input.match(/^@(\w+)\s+(.+)$/);
        if (chatMatch) {
            const agentId = chatMatch[1];
            const message = chatMatch[2];
            apiPost(`/api/agents/${agentId}/chat`, { message }).then(r => {
                if (r.success) {
                    showToast(`💬 Message sent to Agent ${agentId}`, 'success');
                } else {
                    showToast(r.message || `Failed to send to Agent ${agentId}`, 'error');
                }
            });
            return;
        }

        // If not running, treat as a launch command
        if (!SwarmState.swarm_running && !input.startsWith('/')) {
            document.getElementById('init-goal').value = input;
            openLaunchModal();
            return;
        }

        // Handle slash commands
        if (input.startsWith('/clean')) {
            const parts = input.split(/\s+/);
            const target = parts[1] || 'all';
            if (target === 'all' && !confirm('This will clean ALL swarm state. Continue?')) return;
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
            } else if (target === 'synthesis' || target === 'report') {
                openSynthesis();
                return;
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
            document.getElementById('init-goal').value = input;
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
// Swarm Task Initialization (Overlay)
// ---------------------------------------------------------------------------
async function initLaunch() {
    const goal = document.getElementById('init-goal').value.trim();
    const provider = document.getElementById('init-provider').value;
    const budget = parseInt(document.getElementById('init-budget').value) || 20000;
    const autoApprove = document.getElementById('init-auto-approve')?.checked || false;

    if (!goal) {
        showToast('Please enter a task prompt to initialize the swarm', 'error');
        return;
    }

    // Collect designer agents
    const agents = UIState.designerAgents.map((a, i) => ({
        agent_id: `${i + 1}`.padStart(3, '0'),
        personality: a.role || 'Generalist',
        role: a.role || 'Generalist',
        goal: a.goal || goal,
    }));

    showToast('Configuring LLM provider...', 'info');
    await apiPost('/api/config', { llm_provider: provider, auto_approve_spawns: autoApprove });

    showToast('Initializing swarm task...', 'info');
    const result = await apiPost('/api/run', { goal, agents, budget });
    if (result.success) {
        showToast(result.message, 'success');
        UIState.initModalOpen = false;
        render();
    } else {
        showToast(result.message || 'Failed to initialize swarm', 'error');
    }
}

// ---------------------------------------------------------------------------
// Combined Deliverable Synthesis (design_doc §7)
// ---------------------------------------------------------------------------
async function openSynthesis() {
    const modal = document.getElementById('synthesis-modal');
    const body = document.getElementById('synthesis-body');
    modal.classList.add('modal-overlay--active');
    body.innerHTML = '<div class="empty-state"><div class="empty-state__desc">Generating synthesis…</div></div>';
    const res = await apiGet('/api/synthesis');
    const md = (res && res.markdown) ? res.markdown : 'No synthesis available.';
    body.innerHTML = `<pre style="white-space: pre-wrap; word-break: break-word; font-family: var(--font-mono); font-size: 0.78rem; line-height: 1.6; color: var(--text-primary); margin: 0;">${escapeHtml(md)}</pre>`;
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
