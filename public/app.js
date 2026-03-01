/* ============================================================
   ShipPull — Client Application
   All state managed in localStorage. Backend is stateless.
   ============================================================ */

// ---- Storage Keys ----
const STORAGE_ACCOUNTS = 'shippull_accounts';
const STORAGE_ORDERS   = 'shippull_orders';
const STORAGE_VIEW     = 'shippull_view';

// ---- API paths ----
const API = {
    auth: '/api/auth',
    sync: '/api/sync',
};

// ---- In-memory state (loaded from localStorage) ----
let accounts = [];  // [{email, access_token, refresh_token, connected_at, last_synced}]
let orders   = [];  // [{gmail_message_id, account_email, retailer, ...}]
let currentPage = 'connect';
let currentView = localStorage.getItem(STORAGE_VIEW) || 'grid';

// ---- Account colors (deterministic per email) ----
const ACCOUNT_COLORS = [
    '#3B82F6', '#22C55E', '#F59E0B', '#8B5CF6', '#EF4444',
    '#06B6D4', '#F97316', '#EC4899', '#10B981', '#6366F1',
];
function accountColor(email) {
    let hash = 0;
    for (let i = 0; i < email.length; i++) hash = email.charCodeAt(i) + ((hash << 5) - hash);
    return ACCOUNT_COLORS[Math.abs(hash) % ACCOUNT_COLORS.length];
}

// ---- localStorage helpers ----
function loadFromStorage() {
    try {
        accounts = JSON.parse(localStorage.getItem(STORAGE_ACCOUNTS) || '[]');
        orders   = JSON.parse(localStorage.getItem(STORAGE_ORDERS)   || '[]');
    } catch {
        accounts = [];
        orders   = [];
    }
}

function saveAccounts() {
    localStorage.setItem(STORAGE_ACCOUNTS, JSON.stringify(accounts));
}

function saveOrders() {
    localStorage.setItem(STORAGE_ORDERS, JSON.stringify(orders));
}

// ---- Account management ----
function addOrUpdateAccount(email, access_token, refresh_token) {
    const existing = accounts.find(a => a.email === email);
    if (existing) {
        existing.access_token  = access_token;
        if (refresh_token) existing.refresh_token = refresh_token;
    } else {
        accounts.push({
            email,
            access_token,
            refresh_token,
            connected_at: new Date().toISOString(),
            last_synced:  null,
        });
    }
    saveAccounts();
}

function removeAccount(email) {
    accounts = accounts.filter(a => a.email !== email);
    orders   = orders.filter(o => o.account_email !== email);
    saveAccounts();
    saveOrders();
}

// ---- Compute stats from in-memory orders ----
function computeStats() {
    const filtered = getFilteredOrders();
    const total      = filtered.length;
    const in_transit = filtered.filter(o => o.status === 'in_transit' || o.status === 'out_for_delivery').length;
    const delivered  = filtered.filter(o => o.status === 'delivered').length;
    const processing = filtered.filter(o => o.status === 'processing' || o.status === 'shipped').length;
    const total_spent = filtered.reduce((sum, o) => sum + (o.order_cost || 0), 0);
    const retailers  = [...new Set(filtered.map(o => o.retailer).filter(Boolean))].sort();
    return { total, in_transit, delivered, processing, total_spent, retailers };
}

// ---- Filtering & sorting (client-side) ----
function getFilterParams() {
    return {
        status:   document.getElementById('filterStatus').value,
        retailer: document.getElementById('filterRetailer').value,
        sort:     document.getElementById('sortSelect').value,
        search:   document.getElementById('searchInput').value.trim().toLowerCase(),
    };
}

function getFilteredOrders() {
    const { status, retailer, sort, search } = getFilterParams();
    let result = [...orders];

    if (status)   result = result.filter(o => o.status === status);
    if (retailer) result = result.filter(o => o.retailer === retailer);
    if (search) {
        result = result.filter(o =>
            (o.retailer       || '').toLowerCase().includes(search) ||
            (o.item_name      || '').toLowerCase().includes(search) ||
            (o.tracking_number|| '').toLowerCase().includes(search) ||
            (o.account_email  || '').toLowerCase().includes(search)
        );
    }

    // Sort
    if (sort === 'newest' || !sort) {
        result.sort((a, b) => (b.order_date || '').localeCompare(a.order_date || ''));
    } else if (sort === 'status') {
        const order = ['out_for_delivery', 'in_transit', 'shipped', 'processing', 'delivered'];
        result.sort((a, b) => order.indexOf(a.status) - order.indexOf(b.status));
    } else if (sort === 'eta') {
        result.sort((a, b) => {
            if (!a.estimated_delivery && !b.estimated_delivery) return 0;
            if (!a.estimated_delivery) return 1;
            if (!b.estimated_delivery) return -1;
            return a.estimated_delivery.localeCompare(b.estimated_delivery);
        });
    } else if (sort === 'cost_desc') {
        result.sort((a, b) => (b.order_cost || 0) - (a.order_cost || 0));
    }

    return result;
}

// ---- Router ----
function getHashPath() {
    const raw = window.location.hash.replace(/^#/, '') || 'connect';
    const [path] = raw.split('?');
    return path;
}

function getHashParam(key) {
    const raw = window.location.hash.replace(/^#/, '');
    const qIndex = raw.indexOf('?');
    if (qIndex === -1) return null;
    const qs = raw.slice(qIndex + 1);
    return new URLSearchParams(qs).get(key);
}

function navigate(page) {
    window.location.hash = '#' + page;
}

function handleRoute() {
    const path = getHashPath();

    // Handle OAuth callback — tokens arrive in the hash fragment
    if (path === '/callback') {
        handleCallback();
        return;
    }

    const error = getHashParam('error');
    if (error) {
        const msgs = {
            no_code:          'OAuth was cancelled or failed.',
            token_exchange:   'Failed to exchange auth code. Check your OAuth credentials.',
            no_access_token:  'No access token received from Google.',
            no_email:         'Could not retrieve your email from Google.',
        };
        showToast(msgs[error] || `OAuth error: ${error}`, 'error');
        // Clean up hash
        window.history.replaceState(null, '', window.location.pathname + '#connect');
    }

    // Gate routes that require accounts
    if (accounts.length === 0 && path !== 'connect') {
        navigate('connect');
        return;
    }
    if (accounts.length > 0 && path === 'connect') {
        navigate('dashboard');
        return;
    }

    currentPage = path;
    showPage(path);
    updateNavLinks(path);
}

function handleCallback() {
    const access_token  = getHashParam('access_token');
    const refresh_token = getHashParam('refresh_token');
    const email         = getHashParam('email');
    const error         = getHashParam('error');

    if (error) {
        const msgs = {
            no_code:          'OAuth was cancelled.',
            token_exchange:   'Failed to exchange auth code.',
            no_access_token:  'No access token received.',
            no_email:         'Could not retrieve email from Google.',
        };
        // Clean hash, show error, go to connect page
        window.history.replaceState(null, '', window.location.pathname + '#connect');
        showPage('connect');
        updateNavLinks('connect');
        showToast(msgs[error] || `OAuth error: ${error}`, 'error');
        return;
    }

    if (!access_token || !email) {
        window.history.replaceState(null, '', window.location.pathname + '#connect');
        showPage('connect');
        updateNavLinks('connect');
        showToast('OAuth callback missing required tokens.', 'error');
        return;
    }

    // Save the new account
    addOrUpdateAccount(email, access_token, refresh_token || '');

    // Clean up hash before redirecting
    window.history.replaceState(null, '', window.location.pathname + '#dashboard');

    showToast(`Connected ${email} — fetching your shipments...`, 'success');

    currentPage = 'dashboard';
    showPage('dashboard');
    updateNavLinks('dashboard');
    updateAccountsUI();

    // Auto-sync immediately after connecting
    syncAccounts(true);
}

function showPage(page) {
    document.querySelectorAll('.page').forEach(p => (p.style.display = 'none'));

    if (page === 'connect') {
        document.getElementById('pageConnect').style.display = 'flex';
    } else if (page === 'dashboard') {
        document.getElementById('pageDashboard').style.display = 'block';
        loadDashboard();
    } else if (page === 'settings' || page === 'accounts') {
        document.getElementById('pageSettings').style.display = 'block';
        renderSettingsAccounts();
    } else {
        // Fallback to dashboard
        document.getElementById('pageDashboard').style.display = 'block';
        loadDashboard();
    }
}

function updateNavLinks(page) {
    // Normalise "accounts" -> "settings" for nav highlight
    const normPage = page === 'accounts' ? 'settings' : page;
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.dataset.page === normPage);
    });
}

// ---- Accounts UI ----
function updateAccountsUI() {
    const dropdown = document.getElementById('accountsDropdown');
    const syncBtn  = document.getElementById('btnSync');
    const syncInd  = document.getElementById('syncIndicator');

    if (accounts.length > 0) {
        dropdown.style.display = 'block';
        syncBtn.style.display  = 'flex';
        syncInd.style.display  = 'flex';

        const avatarsEl = document.getElementById('accountsAvatars');
        avatarsEl.innerHTML = accounts.slice(0, 3).map(a => {
            const initial = a.email.charAt(0).toUpperCase();
            const color   = accountColor(a.email);
            return `<span class="avatar-dot" style="background:${color}">${initial}</span>`;
        }).join('');

        document.getElementById('accountsCount').textContent =
            accounts.length === 1 ? '1 account' : `${accounts.length} accounts`;

        const listEl = document.getElementById('dropdownAccountsList');
        listEl.innerHTML = accounts.map(a => {
            const initial = a.email.charAt(0).toUpperCase();
            const color   = accountColor(a.email);
            return `<div class="dropdown-item">
                <span style="width:24px;height:24px;border-radius:50%;background:${color};display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;font-family:var(--font-mono);flex-shrink:0">${initial}</span>
                <span class="dropdown-item-email">${escHtml(a.email)}</span>
            </div>`;
        }).join('');

        updateSyncTime();
    } else {
        dropdown.style.display = 'none';
        syncBtn.style.display  = 'none';
        syncInd.style.display  = 'none';
    }
}

function updateSyncTime() {
    if (accounts.length === 0) return;
    const synced = accounts
        .map(a => a.last_synced)
        .filter(Boolean)
        .sort()
        .pop();
    const textEl = document.getElementById('syncText');
    if (synced) {
        const diff = Math.floor((Date.now() - new Date(synced).getTime()) / 60000);
        let text;
        if (diff < 1)  text = 'just now';
        else if (diff < 60) text = `${diff}m ago`;
        else text = `${Math.floor(diff / 60)}h ago`;
        textEl.textContent = `Last synced: ${text}`;
    } else {
        textEl.textContent = 'Not yet synced';
    }
}

// ---- Dashboard ----
function loadDashboard() {
    updateAccountsUI();
    const stats = computeStats();
    renderStats(stats);
    renderRetailerFilter(stats.retailers);
    renderOrders();
}

function renderStats(stats) {
    animateCounter('statTotal',      stats.total      || 0);
    animateCounter('statTransit',    stats.in_transit  || 0);
    animateCounter('statDelivered',  stats.delivered   || 0);
    animateCounter('statProcessing', stats.processing  || 0);
    document.getElementById('statSpent').textContent =
        '$' + (stats.total_spent || 0).toLocaleString('en-US', {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        });
}

function animateCounter(id, target) {
    const el = document.getElementById(id);
    if (!el) return;
    const start = parseInt(el.textContent) || 0;
    if (start === target) { el.textContent = target; return; }
    const duration = 400;
    const startTime = performance.now();
    function step(now) {
        const progress = Math.min((now - startTime) / duration, 1);
        const eased    = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(start + (target - start) * eased);
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

function renderRetailerFilter(retailers) {
    const select  = document.getElementById('filterRetailer');
    const current = select.value;
    const opts    = ['<option value="">All Retailers</option>'];
    (retailers || []).forEach(r => {
        opts.push(`<option value="${escHtml(r)}" ${r === current ? 'selected' : ''}>${escHtml(r)}</option>`);
    });
    select.innerHTML = opts.join('');
}

// ---- Order Rendering ----
function renderOrders() {
    const filtered  = getFilteredOrders();
    const grid      = document.getElementById('ordersGrid');
    const listWrap  = document.getElementById('ordersListWrap');
    const empty     = document.getElementById('emptyState');
    const msg       = document.getElementById('emptyStateMsg');

    if (filtered.length === 0) {
        grid.innerHTML = '';
        listWrap.style.display = 'none';
        empty.style.display    = 'block';
        msg.textContent = accounts.length > 0
            ? 'No orders matched your filters, or no shipment emails were found. Try syncing.'
            : 'Connect a Gmail account and sync to see your shipments.';
        return;
    }

    empty.style.display = 'none';

    if (currentView === 'list') {
        grid.style.display     = 'none';
        listWrap.style.display = 'block';
        renderListView(filtered);
    } else {
        grid.style.display     = '';
        listWrap.style.display = 'none';
        renderGridView(filtered);
    }
}

function renderGridView(filtered) {
    const grid = document.getElementById('ordersGrid');
    grid.innerHTML = filtered.map(o => createOrderCard(o)).join('');
    grid.querySelectorAll('.order-card').forEach(card => {
        card.addEventListener('click', () => openOrderModal(card.dataset.id));
    });
}

function renderListView(filtered) {
    const tbody = document.getElementById('ordersTableBody');
    tbody.innerHTML = filtered.map(o => createOrderRow(o)).join('');
    document.querySelectorAll('.order-table-row').forEach(row => {
        row.addEventListener('click', e => {
            if (e.target.tagName === 'A') return;
            openOrderModal(row.dataset.id);
        });
    });
}

function createOrderCard(order) {
    const statusText  = formatStatus(order.status);
    const statusClass = `status-${order.status}`;
    const initial     = (order.retailer || '?').charAt(0).toUpperCase();
    const accountEmail = (order.account_email || '').split('@')[0];
    const color       = accountColor(order.account_email || '');
    const costStr     = order.order_cost ? `$${Number(order.order_cost).toFixed(2)}` : '—';

    return `<div class="order-card" data-id="${escHtml(order.gmail_message_id)}" data-status="${order.status}">
        <div class="card-header">
            <div class="card-image">
                <span class="card-image-placeholder">${initial}</span>
            </div>
            <div class="card-info">
                <div class="card-retailer">${escHtml(order.retailer || 'Unknown')}</div>
                <div class="card-name">${escHtml(order.item_name || 'Order')}</div>
                <div class="card-cost">${costStr}</div>
            </div>
        </div>
        <div class="card-details">
            <div class="card-row">
                <span class="card-label">Status</span>
                <span class="status-badge ${statusClass}">${statusText}</span>
            </div>
            <div class="card-row">
                <span class="card-label">Carrier</span>
                <span class="card-value">${escHtml(order.shipping_carrier || '—')}</span>
            </div>
            <div class="card-row">
                <span class="card-label">Tracking</span>
                <span class="card-value">${order.tracking_number
                    ? `<a href="${escHtml(order.tracking_url || '#')}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">${escHtml(order.tracking_number)}</a>`
                    : '—'
                }</span>
            </div>
            <div class="card-row">
                <span class="card-label">ETA</span>
                <span class="card-value">${formatDate(order.estimated_delivery)}</span>
            </div>
            <div class="card-row">
                <span class="card-label">Account</span>
                <span class="card-account-tag">
                    <span class="card-account-dot" style="background:${color}"></span>
                    ${escHtml(accountEmail)}
                </span>
            </div>
        </div>
    </div>`;
}

function createOrderRow(order) {
    const statusText  = formatStatus(order.status);
    const dotClass    = `status-dot status-dot-${order.status}`;
    const accountEmail = (order.account_email || '').split('@')[0] || '—';
    const color       = accountColor(order.account_email || '');
    const costStr     = order.order_cost ? `$${Number(order.order_cost).toFixed(2)}` : '—';
    const trackingHtml = order.tracking_number
        ? `<a href="${escHtml(order.tracking_url || '#')}" target="_blank" rel="noopener noreferrer">${escHtml(order.tracking_number)}</a>`
        : '—';

    return `<tr class="order-table-row" data-id="${escHtml(order.gmail_message_id)}">
        <td>
            <div class="table-status-cell">
                <span class="${dotClass}"></span>
                <span>${statusText}</span>
            </div>
        </td>
        <td><span class="table-item-name" title="${escHtml(order.item_name || '')}">${escHtml(order.item_name || 'Order')}</span></td>
        <td><span class="table-retailer">${escHtml(order.retailer || '—')}</span></td>
        <td><span class="table-cost">${costStr}</span></td>
        <td><span class="table-carrier">${escHtml(order.shipping_carrier || '—')}</span></td>
        <td class="table-tracking">${trackingHtml}</td>
        <td><span class="table-eta">${formatDate(order.estimated_delivery)}</span></td>
        <td>
            <span class="card-account-tag">
                <span class="card-account-dot" style="background:${color}"></span>
                ${escHtml(accountEmail)}
            </span>
        </td>
    </tr>`;
}

function showLoadingSkeleton() {
    const grid = document.getElementById('ordersGrid');
    grid.style.display = '';
    document.getElementById('ordersListWrap').style.display = 'none';
    document.getElementById('emptyState').style.display     = 'none';
    grid.innerHTML = Array(6).fill(`
        <div class="skeleton-card">
            <div style="display:flex;gap:14px;margin-bottom:14px;">
                <div class="skeleton-image"></div>
                <div style="flex:1">
                    <div class="skeleton-line w-30"></div>
                    <div class="skeleton-line w-70 h-lg"></div>
                    <div class="skeleton-line w-50"></div>
                </div>
            </div>
            <div class="skeleton-line"></div>
            <div class="skeleton-line w-70"></div>
            <div class="skeleton-line w-50"></div>
        </div>
    `).join('');
}

// ---- View Toggle ----
function setView(view) {
    currentView = view;
    localStorage.setItem(STORAGE_VIEW, view);
    document.getElementById('btnViewGrid').classList.toggle('active', view === 'grid');
    document.getElementById('btnViewList').classList.toggle('active', view === 'list');
    renderOrders();
}

// ---- Order Modal (click to expand) ----
function openOrderModal(msgId) {
    const order = orders.find(o => o.gmail_message_id === msgId);
    if (!order) return;

    const overlay = document.getElementById('modalOverlay');
    const content = document.getElementById('modalContent');
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';
    content.innerHTML = renderOrderModal(order);
}

function closeModal() {
    document.getElementById('modalOverlay').classList.remove('open');
    document.body.style.overflow = '';
}

function renderOrderModal(order) {
    const statusText  = formatStatus(order.status);
    const statusClass = `status-${order.status}`;
    const initial     = (order.retailer || '?').charAt(0).toUpperCase();
    const costStr     = order.order_cost ? `$${Number(order.order_cost).toFixed(2)}` : '—';
    const color       = accountColor(order.account_email || '');

    const statusOrder  = ['processing', 'shipped', 'in_transit', 'out_for_delivery', 'delivered'];
    const currentIdx   = statusOrder.indexOf(order.status);
    const timelineSteps = [
        { key: 'processing',       label: 'Order Placed' },
        { key: 'shipped',          label: 'Shipped' },
        { key: 'in_transit',       label: 'In Transit' },
        { key: 'out_for_delivery', label: 'Out for Delivery' },
        { key: 'delivered',        label: 'Delivered' },
    ];
    const timelineHTML = timelineSteps.map((step, i) => {
        let cls = '';
        if (i < currentIdx)      cls = 'completed';
        else if (i === currentIdx) cls = 'active';
        return `<div class="timeline-step ${cls}">
            <div class="timeline-step-dot">
                <svg width="12" height="12" viewBox="0 0 12 12" fill="none"><path d="M3 6L5 8L9 4" stroke="#fff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
            </div>
            <div class="timeline-step-label">${step.label}</div>
        </div>`;
    }).join('');

    const trackingHtml = order.tracking_number
        ? `<a href="${escHtml(order.tracking_url || '#')}" target="_blank" rel="noopener noreferrer">${escHtml(order.tracking_number)}</a>`
        : '—';

    return `
        <div class="modal-header">
            <div class="modal-image">
                <span class="modal-image-placeholder">${initial}</span>
            </div>
            <div class="modal-title-section">
                <div class="modal-retailer">${escHtml(order.retailer || 'Unknown')}</div>
                <div class="modal-item-name">${escHtml(order.item_name || 'Order')}</div>
                <div class="modal-cost">${costStr}</div>
            </div>
        </div>

        <div class="modal-timeline">
            <div class="timeline-title">Shipment Progress</div>
            <div class="timeline-steps">${timelineHTML}</div>
        </div>

        <div class="modal-details">
            <div class="modal-detail-item">
                <div class="modal-detail-label">Status</div>
                <div class="modal-detail-value"><span class="status-badge ${statusClass}">${statusText}</span></div>
            </div>
            <div class="modal-detail-item">
                <div class="modal-detail-label">Order Date</div>
                <div class="modal-detail-value">${formatDate(order.order_date)}</div>
            </div>
            <div class="modal-detail-item">
                <div class="modal-detail-label">Carrier</div>
                <div class="modal-detail-value">${escHtml(order.shipping_carrier || '—')}</div>
            </div>
            <div class="modal-detail-item">
                <div class="modal-detail-label">Est. Delivery</div>
                <div class="modal-detail-value">${formatDate(order.estimated_delivery)}</div>
            </div>
            <div class="modal-detail-item full-width">
                <div class="modal-detail-label">Tracking Number</div>
                <div class="modal-detail-value">${trackingHtml}</div>
            </div>
            <div class="modal-detail-item">
                <div class="modal-detail-label">Account</div>
                <div class="modal-detail-value">
                    <span class="card-account-tag">
                        <span class="card-account-dot" style="background:${color}"></span>
                        ${escHtml(order.account_email || '—')}
                    </span>
                </div>
            </div>
            <div class="modal-detail-item">
                <div class="modal-detail-label">Message ID</div>
                <div class="modal-detail-value" style="font-family:var(--font-mono);font-size:11px;word-break:break-all;">${escHtml(order.gmail_message_id || '—')}</div>
            </div>
        </div>

        <div class="modal-email-info">
            <div class="modal-email-label">Source Email Subject</div>
            <div class="modal-email-subject">"${escHtml(order.raw_email_subject || 'N/A')}"</div>
        </div>
    `;
}

// ---- Settings ----
function renderSettingsAccounts() {
    const list = document.getElementById('settingsAccountsList');
    if (accounts.length === 0) {
        list.innerHTML = '<p style="color:var(--text-muted);font-size:13px;padding:12px 0;">No accounts connected yet.</p>';
        return;
    }
    list.innerHTML = accounts.map(a => {
        const initial      = a.email.charAt(0).toUpperCase();
        const color        = accountColor(a.email);
        const connectedDate = a.connected_at
            ? new Date(a.connected_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
            : '';
        const lastSynced    = a.last_synced
            ? new Date(a.last_synced).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
            : 'Never';
        const orderCount    = orders.filter(o => o.account_email === a.email).length;
        return `<div class="account-item">
            <div class="account-avatar" style="background:${color}">${initial}</div>
            <div class="account-info">
                <div class="account-email">${escHtml(a.email)}</div>
                <div class="account-meta">Connected ${connectedDate} · Last synced: ${lastSynced} · ${orderCount} order${orderCount !== 1 ? 's' : ''}</div>
            </div>
            <button class="btn-remove" onclick="disconnectAccount('${escHtml(a.email)}')">Disconnect</button>
        </div>`;
    }).join('');
}

function disconnectAccount(email) {
    if (!confirm(`Disconnect ${email}? This will remove all ${orders.filter(o => o.account_email === email).length} orders associated with this account.`)) return;
    removeAccount(email);
    updateAccountsUI();
    showToast(`${email} disconnected`, 'info');
    if (accounts.length === 0) {
        navigate('connect');
    } else {
        renderSettingsAccounts();
        if (currentPage === 'dashboard') loadDashboard();
    }
}

// ---- Sync ----
async function syncAccounts(isInitial = false) {
    if (accounts.length === 0) {
        showToast('No accounts connected', 'info');
        return;
    }

    const btn = document.getElementById('btnSync');
    btn.classList.add('syncing');
    btn.disabled = true;

    if (currentPage === 'dashboard') showLoadingSkeleton();

    try {
        const payload = {
            accounts: accounts.map(a => ({
                email:         a.email,
                access_token:  a.access_token,
                refresh_token: a.refresh_token,
            })),
        };

        const res  = await fetch(API.sync, {
            method:  'POST',
            headers: { 'Content-Type': 'application/json' },
            body:    JSON.stringify(payload),
        });

        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.error || `HTTP ${res.status}`);
        }

        const data = await res.json();

        // Update any refreshed tokens
        if (data.token_updates && typeof data.token_updates === 'object') {
            for (const [email, newToken] of Object.entries(data.token_updates)) {
                const acct = accounts.find(a => a.email === email);
                if (acct) acct.access_token = newToken;
            }
        }

        // Merge new orders, deduplicating by gmail_message_id
        const newOrders = data.orders || [];
        const existingIds = new Set(orders.map(o => o.gmail_message_id));
        let added = 0;
        for (const order of newOrders) {
            if (!existingIds.has(order.gmail_message_id)) {
                orders.push(order);
                existingIds.add(order.gmail_message_id);
                added++;
            } else {
                // Update existing order status in case it changed
                const idx = orders.findIndex(o => o.gmail_message_id === order.gmail_message_id);
                if (idx !== -1) orders[idx] = order;
            }
        }

        // Update last_synced timestamps
        const syncTime = data.synced_at || new Date().toISOString();
        for (const acct of accounts) {
            acct.last_synced = syncTime;
        }

        saveAccounts();
        saveOrders();

        // Refresh UI
        if (currentPage === 'dashboard') loadDashboard();
        if (currentPage === 'settings' || currentPage === 'accounts') renderSettingsAccounts();
        updateSyncTime();

        // Show toast
        const errorEmails = Object.keys(data.account_errors || {});
        if (errorEmails.length > 0) {
            showToast(`Sync completed with errors for: ${errorEmails.join(', ')}`, 'error');
        } else {
            const msg = added > 0
                ? `Sync complete — ${added} new order${added === 1 ? '' : 's'} found`
                : isInitial
                    ? 'Sync complete — no new orders yet. Check back later.'
                    : 'Sync complete — no new orders';
            showToast(msg, added > 0 ? 'success' : 'info');
        }

    } catch (e) {
        if (currentPage === 'dashboard') loadDashboard(); // show what we have
        showToast('Sync failed: ' + (e.message || 'unknown error'), 'error');
    } finally {
        btn.classList.remove('syncing');
        btn.disabled = false;
    }
}

// ---- Toast Notifications ----
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast     = document.createElement('div');
    toast.className = `toast toast-${type}`;

    const icons = {
        success: '<svg class="toast-icon" viewBox="0 0 18 18" fill="none"><circle cx="9" cy="9" r="8" stroke="#22C55E" stroke-width="1.5"/><path d="M6 9L8 11L12 7" stroke="#22C55E" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>',
        error:   '<svg class="toast-icon" viewBox="0 0 18 18" fill="none"><circle cx="9" cy="9" r="8" stroke="#EF4444" stroke-width="1.5"/><path d="M6.5 6.5L11.5 11.5M11.5 6.5L6.5 11.5" stroke="#EF4444" stroke-width="1.5" stroke-linecap="round"/></svg>',
        info:    '<svg class="toast-icon" viewBox="0 0 18 18" fill="none"><circle cx="9" cy="9" r="8" stroke="#3B82F6" stroke-width="1.5"/><path d="M9 5V9M9 12V12.5" stroke="#3B82F6" stroke-width="1.5" stroke-linecap="round"/></svg>',
    };

    toast.innerHTML = `${icons[type] || icons.info}<span>${escHtml(message)}</span>`;
    container.appendChild(toast);
    setTimeout(() => {
        toast.style.animation = 'toast-out 300ms ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, 4000);
}

// ---- Utility ----
function formatStatus(status) {
    const map = {
        processing:        'Processing',
        shipped:           'Shipped',
        in_transit:        'In Transit',
        out_for_delivery:  'Out for Delivery',
        delivered:         'Delivered',
    };
    return map[status] || status || 'Unknown';
}

function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        const d = new Date(dateStr + 'T00:00:00');
        return d.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' });
    } catch {
        return dateStr;
    }
}

function escHtml(str) {
    if (str == null) return '';
    return String(str)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

// ---- Event Listeners ----
function initEventListeners() {
    // Sync button
    document.getElementById('btnSync').addEventListener('click', () => syncAccounts());

    // Filters — re-render client-side (no server call needed)
    let debounceTimer;
    document.getElementById('searchInput').addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            if (currentPage === 'dashboard') renderOrders();
        }, 200);
    });
    document.getElementById('filterStatus').addEventListener('change', () => {
        if (currentPage === 'dashboard') {
            const stats = computeStats();
            renderStats(stats);
            renderOrders();
        }
    });
    document.getElementById('filterRetailer').addEventListener('change', () => {
        if (currentPage === 'dashboard') {
            const stats = computeStats();
            renderStats(stats);
            renderOrders();
        }
    });
    document.getElementById('sortSelect').addEventListener('change', () => {
        if (currentPage === 'dashboard') renderOrders();
    });

    // View toggle
    document.getElementById('btnViewGrid').addEventListener('click', () => setView('grid'));
    document.getElementById('btnViewList').addEventListener('click', () => setView('list'));

    // Apply saved view state
    document.getElementById('btnViewGrid').classList.toggle('active', currentView === 'grid');
    document.getElementById('btnViewList').classList.toggle('active', currentView === 'list');

    // Accounts dropdown toggle
    document.getElementById('btnAccounts').addEventListener('click', e => {
        e.stopPropagation();
        document.getElementById('dropdownMenu').classList.toggle('open');
    });
    document.addEventListener('click', () => {
        document.getElementById('dropdownMenu').classList.remove('open');
    });

    // Modal
    document.getElementById('modalClose').addEventListener('click', closeModal);
    document.getElementById('modalOverlay').addEventListener('click', e => {
        if (e.target === e.currentTarget) closeModal();
    });
    document.addEventListener('keydown', e => {
        if (e.key === 'Escape') closeModal();
    });

    // Hash routing
    window.addEventListener('hashchange', handleRoute);
}

// ---- Init ----
function init() {
    loadFromStorage();
    initEventListeners();
    updateAccountsUI();
    handleRoute();
}

init();
