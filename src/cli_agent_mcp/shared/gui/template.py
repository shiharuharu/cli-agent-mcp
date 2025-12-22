"""HTML 模板生成。

cli-agent-mcp shared/gui v0.2.0
同步日期: 2025-12-18

生成带侧边栏的 HTML 模板，支持 SSE 事件流。
"""

from __future__ import annotations

from .colors import COLORS, SOURCE_COLORS

__all__ = [
    "generate_html",
]


def generate_html(
    *,
    multi_source_mode: bool = False,
    title: str = "CLI Agent Live Output",
) -> str:
    """生成 HTML 模板。

    Args:
        multi_source_mode: 是否为多端模式
        title: 窗口标题

    Returns:
        完整的 HTML 字符串
    """
    # 侧边栏分组标题（多端模式下显示来源分组）
    sidebar_groups_js = ""
    if multi_source_mode:
        sidebar_groups_js = f"""
        const SOURCE_COLORS = {{
            gemini: '{SOURCE_COLORS["gemini"]}',
            codex: '{SOURCE_COLORS["codex"]}',
            claude: '{SOURCE_COLORS["claude"]}',
            unknown: '{SOURCE_COLORS["unknown"]}'
        }};
        """

    return f'''<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>{title}</title>
<style>
* {{ margin: 0; padding: 0; box-sizing: border-box; }}
html {{
    overscroll-behavior: none;
}}
body {{
    background: {COLORS["bg"]};
    color: {COLORS["fg"]};
    font-family: Monaco, Menlo, Consolas, 'Courier New', monospace;
    font-size: 12px;
    line-height: 1.4;
    height: 100vh;
    display: flex;
    flex-direction: column;
    overscroll-behavior: none;
    -webkit-overflow-scrolling: auto;
}}

/* Toolbar */
#toolbar {{
    background: {COLORS["bg_secondary"]};
    border-bottom: 1px solid {COLORS["border"]};
    padding: 4px 8px;
    display: flex;
    gap: 8px;
    align-items: center;
    flex-shrink: 0;
}}
#toolbar input {{
    background: #333;
    border: 1px solid {COLORS["border"]};
    color: {COLORS["fg"]};
    padding: 3px 8px;
    font-size: 11px;
    width: 180px;
    font-family: inherit;
    border-radius: 3px;
}}
#toolbar input:focus {{ outline: none; border-color: {COLORS["session"]}; }}
#toolbar button {{
    background: #333;
    border: 1px solid {COLORS["border"]};
    color: {COLORS["fg"]};
    padding: 3px 10px;
    cursor: pointer;
    font-size: 11px;
    border-radius: 3px;
}}
#toolbar button:hover {{ background: {COLORS["hover"]}; }}
#event-count {{ color: {COLORS["fg_dim"]}; margin-left: auto; }}
.status-text {{
    font-size: 10px;
    color: {COLORS["fg_muted"]};
    padding: 2px 6px;
    background: {COLORS["bg"]};
    border-radius: 3px;
}}
.status-text.paused {{ color: {COLORS["warning"]}; }}
.task-info {{
    flex: 1;
    font-size: 11px;
    color: {COLORS["session"]};
    padding: 0 8px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}
.task-info:empty {{ display: none; }}
.task-note {{
    font-size: 10px;
    color: {COLORS["fg_dim"]};
    margin-top: 1px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
}}

/* Main container */
#main {{
    flex: 1;
    display: flex;
    overflow: hidden;
}}

/* Content area */
#content {{
    flex: 1;
    overflow-y: auto;
    padding: 4px 8px;
    user-select: text;
    -webkit-user-select: text;
    overscroll-behavior: none;
}}

/* Sidebar */
#sidebar {{
    width: 160px;
    background: {COLORS["bg_secondary"]};
    border-left: 1px solid {COLORS["border"]};
    display: flex;
    flex-direction: column;
    flex-shrink: 0;
}}
#sidebar.collapsed {{ width: 0; overflow: hidden; border-left: none; }}
#sidebar.collapsed #sidebar-content {{ display: none; }}

#sidebar-header {{
    padding: 6px 8px;
    border-bottom: 1px solid {COLORS["border"]};
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-size: 11px;
    color: {COLORS["fg_muted"]};
}}
#sidebar-content {{
    flex: 1;
    overflow-y: auto;
    padding: 4px 0;
}}
.sidebar-item {{
    padding: 4px 8px;
    cursor: pointer;
    display: flex;
    justify-content: space-between;
    font-size: 11px;
    color: {COLORS["fg_muted"]};
}}
.sidebar-item:hover {{ background: {COLORS["hover"]}; }}
.sidebar-item.active {{ background: {COLORS["selection"]}; color: {COLORS["fg"]}; }}
.sidebar-item .count {{ color: {COLORS["fg_dim"]}; }}
.sidebar-group {{
    padding: 4px 8px;
    font-size: 10px;
    color: {COLORS["fg_dim"]};
    text-transform: uppercase;
    letter-spacing: 0.5px;
    margin-top: 4px;
}}

/* Event styles */
.e {{
    white-space: pre-wrap;
    word-wrap: break-word;
    padding: 1px 0;
}}
.e.hidden {{ display: none; }}
.ts {{ color: {COLORS["timestamp"]}; }}
.ss {{ color: {COLORS["session"]}; cursor: pointer; }}
.ss:hover {{ text-decoration: underline; }}
.src {{ font-weight: bold; }}
.lb {{ color: {COLORS["label"]}; }}
.usr {{ color: {COLORS["user"]}; }}
.ast {{ color: {COLORS["assistant"]}; }}
.rsn {{ color: {COLORS["reasoning"]}; font-style: italic; }}
.tl {{ color: {COLORS["tool"]}; }}
.cmd {{ color: {COLORS["command"]}; }}
.file {{ color: {COLORS["file"]}; }}
.mcp {{ color: {COLORS["mcp"]}; }}
.search {{ color: {COLORS["search"]}; }}
.ok {{ color: {COLORS["success"]}; }}
.err {{ color: {COLORS["error"]}; }}
.wrn {{ color: {COLORS["warning"]}; }}
.run {{ color: {COLORS["running"]}; }}
.dm {{ color: {COLORS["fg_dim"]}; }}

/* Fold/collapse */
.fold {{ cursor: pointer; user-select: none; margin-left: 4px; }}
.fold:hover {{ opacity: 0.7; }}
.fold-content {{
    display: none;
    margin-left: 16px;
    padding-left: 8px;
    border-left: 1px solid {COLORS["border"]};
    margin-top: 2px;
}}
.fold-content.show {{ display: block; }}

/* Image grid */
.img-grid {{ display: flex; flex-wrap: wrap; gap: 8px; margin-top: 8px; }}
.img-thumb {{ max-width: 200px; max-height: 150px; border-radius: 4px; cursor: pointer; border: 1px solid {COLORS["border"]}; }}
.img-thumb:hover {{ border-color: #666; transform: scale(1.02); }}

/* Highlight */
.hl {{ background: #3A3A00; }}

/* Scrollbar */
::-webkit-scrollbar {{ width: 8px; height: 8px; }}
::-webkit-scrollbar-track {{ background: {COLORS["bg"]}; }}
::-webkit-scrollbar-thumb {{ background: {COLORS["border"]}; border-radius: 4px; }}
::-webkit-scrollbar-thumb:hover {{ background: #555; }}
</style>
</head>
<body>

<div id="toolbar">
    <input type="text" id="search" placeholder="Search..." onkeyup="filterEvents()">
    <button onclick="clearLog()">Clear</button>
    <button onclick="toggleAutoScroll()" id="scroll-toggle-btn">
        <span id="scroll-icon">⏸</span>
    </button>
    <span id="scroll-status" class="status-text">Auto</span>
    <span id="current-task" class="task-info"></span>
    <span id="event-count">0 events</span>
    <button onclick="toggleSidebar()" id="sidebar-toggle-btn" title="Toggle Sessions panel">
        <span id="sidebar-icon">▶</span>
    </button>
</div>

<div id="main">
    <div id="content"></div>
    <div id="sidebar">
        <div id="sidebar-header">
            <span>Sessions</span>
        </div>
        <div id="sidebar-content">
            <div class="sidebar-item active" data-filter="all" onclick="filterBySession('all')">
                <span>All</span>
                <span class="count" id="all-count">0</span>
            </div>
            <div id="session-list"></div>
        </div>
    </div>
</div>

<script>
// Configuration
const MULTI_SOURCE_MODE = {'true' if multi_source_mode else 'false'};
{sidebar_groups_js}

// State
let autoScroll = true;
let eventCount = 0;
let currentFilter = 'all';
let sessions = {{}};  // session_id -> {{ source, count, taskNote }}
let currentTask = '';  // 当前任务标题
const content = document.getElementById('content');
const sessionList = document.getElementById('session-list');

// Add event to display
function addEvent(html, sessionId, source, taskNote) {{
    const div = document.createElement('div');
    div.innerHTML = html;
    const eventDiv = div.firstChild;
    if (eventDiv) {{
        eventDiv.dataset.raw = eventDiv.textContent.toLowerCase();
        content.appendChild(eventDiv);
    }}

    eventCount++;
    document.getElementById('event-count').textContent = eventCount + ' events';
    document.getElementById('all-count').textContent = eventCount;

    // Update session list
    if (sessionId) {{
        if (!sessions[sessionId]) {{
            sessions[sessionId] = {{ source: source || 'unknown', count: 0, taskNote: taskNote || '' }};
            updateSessionList();
        }} else if (taskNote && !sessions[sessionId].taskNote) {{
            // 更新 taskNote（如果之前没有）
            sessions[sessionId].taskNote = taskNote;
            updateSessionList();
        }}
        sessions[sessionId].count++;
        updateSessionCount(sessionId);
    }}

    // Update current task display
    if (taskNote && taskNote !== currentTask) {{
        currentTask = taskNote;
        document.getElementById('current-task').textContent = taskNote;
    }}

    // Auto scroll
    if (autoScroll) {{
        content.scrollTop = content.scrollHeight;
    }}

    // Apply current filter
    applyFilter();
}}

// Update session list in sidebar
function updateSessionList() {{
    if (MULTI_SOURCE_MODE) {{
        // Group by source
        const bySource = {{}};
        for (const [sid, info] of Object.entries(sessions)) {{
            const src = info.source || 'unknown';
            if (!bySource[src]) bySource[src] = [];
            bySource[src].push(sid);
        }}

        let html = '';
        for (const [src, sids] of Object.entries(bySource)) {{
            const color = SOURCE_COLORS ? SOURCE_COLORS[src] || '#6A6A6A' : '#6A6A6A';
            html += `<div class="sidebar-group" style="color:${{color}}">— ${{src}} —</div>`;
            for (const sid of sids) {{
                const info = sessions[sid];
                const shortId = sid.length > 8 ? '#' + sid.slice(-8) : '#' + sid;
                const noteHtml = info.taskNote ? `<div class="task-note" title="${{info.taskNote}}">${{info.taskNote}}</div>` : '';
                html += `<div class="sidebar-item" data-filter="${{sid}}" onclick="filterBySession('${{sid}}')">
                    <div>
                        <span>${{shortId}}</span>
                        ${{noteHtml}}
                    </div>
                    <span class="count" id="count-${{sid}}">${{info.count}}</span>
                </div>`;
            }}
        }}
        sessionList.innerHTML = html;
    }} else {{
        // Simple list
        let html = '';
        for (const [sid, info] of Object.entries(sessions)) {{
            const shortId = sid.length > 8 ? '#' + sid.slice(-8) : '#' + sid;
            const noteHtml = info.taskNote ? `<div class="task-note" title="${{info.taskNote}}">${{info.taskNote}}</div>` : '';
            html += `<div class="sidebar-item" data-filter="${{sid}}" onclick="filterBySession('${{sid}}')">
                <div>
                    <span>${{shortId}}</span>
                    ${{noteHtml}}
                </div>
                <span class="count" id="count-${{sid}}">${{info.count}}</span>
            </div>`;
        }}
        sessionList.innerHTML = html;
    }}
}}

// Update session event count
function updateSessionCount(sessionId) {{
    const el = document.getElementById('count-' + sessionId);
    if (el) {{
        el.textContent = sessions[sessionId].count;
    }}
}}

// Filter by session
function filterBySession(sessionId) {{
    currentFilter = sessionId;

    // Update sidebar active state
    document.querySelectorAll('.sidebar-item').forEach(el => {{
        el.classList.toggle('active', el.dataset.filter === sessionId);
    }});

    applyFilter();
}}

// Apply current filter
function applyFilter() {{
    const searchQuery = document.getElementById('search').value.toLowerCase();

    document.querySelectorAll('#content .e').forEach(el => {{
        let visible = true;

        // Session filter
        if (currentFilter !== 'all') {{
            const elSession = el.dataset.session || '';
            visible = elSession === currentFilter;
        }}

        // Search filter
        if (visible && searchQuery) {{
            visible = el.dataset.raw && el.dataset.raw.includes(searchQuery);
        }}

        el.classList.toggle('hidden', !visible);
        el.classList.toggle('hl', searchQuery && visible && el.dataset.raw.includes(searchQuery));
    }});
}}

// Filter events (search)
function filterEvents() {{
    applyFilter();
}}

// Toggle fold
function toggle(id, triggerEl) {{
    const el = document.getElementById(id);
    if (el.classList.toggle('show')) {{
        triggerEl.textContent = '▼';
    }} else {{
        triggerEl.textContent = '▶';
    }}
}}

// Copy text to clipboard
function copyText(text) {{
    navigator.clipboard.writeText(text);
}}

// Copy session ID (called when clicking .ss element)
function copySessionId(el) {{
    const sessionId = el.dataset.sessionId || el.textContent.replace('#', '');
    navigator.clipboard.writeText(sessionId).then(() => {{
        // 视觉反馈
        const original = el.textContent;
        el.textContent = '✓ copied';
        setTimeout(() => {{ el.textContent = original; }}, 800);
    }});
}}

// Clear log
function clearLog() {{
    content.innerHTML = '';
    eventCount = 0;
    sessions = {{}};
    document.getElementById('event-count').textContent = '0 events';
    document.getElementById('all-count').textContent = '0';
    sessionList.innerHTML = '';
}}

// Toggle auto scroll
function toggleAutoScroll() {{
    autoScroll = !autoScroll;
    const icon = document.getElementById('scroll-icon');
    const status = document.getElementById('scroll-status');
    if (autoScroll) {{
        icon.textContent = '⏸';
        status.textContent = 'Auto';
        status.classList.remove('paused');
    }} else {{
        icon.textContent = '▶';
        status.textContent = 'Paused';
        status.classList.add('paused');
    }}
}}

// Toggle sidebar
function toggleSidebar() {{
    const sidebar = document.getElementById('sidebar');
    const icon = document.getElementById('sidebar-icon');
    sidebar.classList.toggle('collapsed');
    icon.textContent = sidebar.classList.contains('collapsed') ? '◀' : '▶';
}}

// Disable auto scroll when user scrolls up, re-enable when at bottom
content.addEventListener('scroll', () => {{
    const atBottom = content.scrollHeight - content.scrollTop - content.clientHeight < 30;
    const icon = document.getElementById('scroll-icon');
    const status = document.getElementById('scroll-status');

    if (atBottom && !autoScroll) {{
        // 滚动到底部时自动恢复
        autoScroll = true;
        icon.textContent = '⏸';
        status.textContent = 'Auto';
        status.classList.remove('paused');
    }} else if (!atBottom && autoScroll) {{
        // 向上滚动时自动暂停
        autoScroll = false;
        icon.textContent = '▶';
        status.textContent = 'Paused';
        status.classList.add('paused');
    }}
}});

// ========== updateStatus 函数 ==========
function updateStatus(status) {{
    const statusBar = document.getElementById('status-bar');
    if (!statusBar) return;

    let parts = [];
    if (status.model) parts.push(`Model: ${{status.model}}`);
    if (status.session) parts.push(`Session: ${{status.session.slice(0, 8)}}...`);
    if (status.tokens) parts.push(`Tokens: ${{status.tokens}}`);
    if (status.duration) parts.push(`Duration: ${{status.duration.toFixed(1)}}s`);
    if (status.tools) parts.push(`Tools: ${{status.tools}}`);
    if (status.streaming) parts.push('⏳ Streaming...');

    statusBar.textContent = parts.join(' | ') || 'Ready';
}}

// ========== SSE 客户端 ==========
(function() {{
    let evtSource = null;
    let reconnectAttempts = 0;
    const maxReconnectAttempts = 10;

    function connect() {{
        evtSource = new EventSource('/sse');

        evtSource.onopen = function() {{
            console.log('SSE connected');
            reconnectAttempts = 0;
        }};

        evtSource.onmessage = function(e) {{
            try {{
                const data = JSON.parse(e.data);
                if (data.type === 'event') {{
                    addEvent(data.html, data.session, data.source, data.task_note);
                }} else if (data.type === 'status') {{
                    updateStatus(data.status);
                }}
            }} catch (err) {{
                console.error('SSE parse error:', err);
            }}
        }};

        evtSource.onerror = function() {{
            console.log('SSE connection lost');
            evtSource.close();

            if (reconnectAttempts < maxReconnectAttempts) {{
                reconnectAttempts++;
                const delay = Math.min(1000 * reconnectAttempts, 10000);
                console.log(`Reconnecting in ${{delay}}ms (attempt ${{reconnectAttempts}})`);
                setTimeout(connect, delay);
            }}
        }};
    }}

    connect();

    window.addEventListener('beforeunload', function() {{
        if (evtSource) evtSource.close();
    }});
}})();
</script>
</body>
</html>'''
