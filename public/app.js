/* ============================================
   ShipPull — Client Application
   Real Gmail OAuth, Grid/List view, Vercel API
   ============================================ */

// ---- API paths ----
const API = {
    accounts: '/api/accounts',
    orders:   '/api/orders',
    order:    '/api/order',
    stats:    '/api/stats',
    sync:     '/api/sync',
    auth:     '/api/auth',
};

// ---- State ----
let accounts = [];
let orders = [];
let stats = {};
let currentPage = 'connect';
let currentView = localStorage.getItem('shippull_view') || 'grid'; // 'grid' | 'list'

// ---- API Helpers ----
async function apiFetch(url, options = {}) {
    const res = await fetch(url, options);
    let data;
    try {
        data = await res.json();
    } catch {
        data = {};
    }
    if (!res.ok && data && data.error) {
        throw new Error(data.error);
    }
    return data;
}

async function getAccounts() {
    return apiFetch(API.accounts);
}

async function getOrders(params = {}) {
    const qs = Object.entries(params)
        .filter(([, v]) => v !== '' && v != null)
        .map(([k, v]) => `${encodeURIComponent(k)}=${encodeURIComponent(v)}`)
        .join('&');
    return apiFetch(`${API.orders}${qs ? '?' + qs : ''}`);
}

async function getOrder(id) {
    return apiFetch(`${API.order}?id=${id}`);
}

async function getStats() {
    return apiFetch(API.stats);
}

async function postSync() {
    return apiFetch(API.sync, { method: 'POST' });
}

async function deleteAccount(id) {
    return apiFetch(`${API.accounts}?id=${id}`, { method: 'DELETE' });
}

// ---- Router ----
function getHashPath() {
    // hash can be "#dashboard?connected=1" or "#dashboard" or "#connect"
    const raw = window.location.hash.replace(/^#/, '') || 'connect';
    const [path] = raw.split('?');
    return path;
}

function getHashParam(key) {
    const raw = window.location.hash.replace(/^#/, '');
    const [, qs] = raw.split('?');
    if (!qs) return null;
    const p = new URLSearchParams(qs);
    return p.get(key);
}

function navigate(page) {
    window.location.hash = '#' + page;
}

function handleRoute() {
    const path = getHashPath();
    const connected = getHashParam('connected');
    const error = getHashParam('error');

    // Clear the ?connected=1 from hash after reading it
    if (connected || error) {
        window.history.replaceState(null, '', window.location.pathname + '#' + getHashPath());
    }

    if (error) {
        const msgs = {
            no_code: 'OAuth was cancelled or failed.',
            token_exchange: 'Failed to exchange auth code. Check your OAuth credentials.',
            no_access_token: 'No access token received from Google.',
            no_email: 'Could not retrieve email from Google.',
        };
        showToast(msgs[error] || `OAuth error: ${error}`, 'error');
    }

    // If no accounts, go to connect page (unless just connected)
    if (accounts.length === 0 && path !== 'connect' && !connected) {
        navigate('connect');
        return;
    }

    // If has accounts (or just connected) and on connect page, go to dashboard
    if ((accounts.length > 0 || connected) && path === 'connect') {
        navigate('dashboard');
        return;
    }

    currentPage = path;
    showPage(path, connected);
    updateNavLinks(path);
}

function showPage(page, freshConnect = false) {
    document.querySelectorAll('.page').forEach(p => (p.style.display = 'none'));

    if (page === 'connect') {
        document.getElementById('pageConnect').style.display = 'flex';
    } else if (page === 'dashboard') {
        document.getElementById('pageDashboard').style.display = 'block';
        if (freshConnect) {
            // Immediately sync after OAuth connection
            showToast('Gmail connected! Fetching your shipments...', 'success');
            syncAccounts(true);
        } else {
            loadDashboard();
        }
    } else if (page === 'settings') {
        document.getElementById('pageSettings').style.display = 'block';
        renderSettingsAccounts();
    } else {
        // Fallback
        document.getElementById('pageDashboard').style.display = 'block';
        loadDashboard();
    }
}

function updateNavLinks(page) {
    document.querySelectorAll('.nav-link').forEach(link => {
        link.classList.toggle('active', link.dataset.page === page);
    });
}

// ---- Accounts ----
async function loadAccounts() {
    try {
        accounts = await getAccounts();
        updateAccountsUI();
    } catch (e) {
        console.error('Failed to load accounts:', e);
        accounts = [];
    }
}

function updateAccountsUI() {
    const dropdown = document.getElementById('accountsDropdown');
    const syncBtn = document.getElementById('btnSync');
    const syncInd = document.getElementById('syncIndicator');

    if (accounts.length > 0) {
        dropdown.style.display = 'block';
        syncBtn.style.display = 'flex';
        syncInd.style.display = 'flex';

        const avatarsEl = document.getElementById('accountsAvatars');
        avatarsEl.innerHTML = accounts.slice(0, 3).map(a => {
            const initial = a.email.charAt(0).toUpperCase();
            return `<span class="avatar-dot" style="background:${a.avatar_color}">${initial}</span>`;
        }).join('');

        document.getElementById('accountsCount').textContent =
            accounts.length === 1 ? '1 account' : `${accounts.length} accounts`;

        const listEl = document.getElementById('dropdownAccountsList');
        listEl.innerHTML = accounts.map(a => {
            const initial = a.email.charAt(0).toUpperCase();
            return `<div class="dropdown-item">
                <span style="width:24px;height:24px;border-radius:50%;background:${a.avatar_color};display:inline-flex;align-items:center;justify-content:center;font-size:11px;font-weight:700;color:#fff;font-family:var(--font-mono);flex-shrink:0">${initial}</span>
                <span class="dropdown-item-email">${a.email}</span>
            </div>`;
        }).join('');

        updateSyncTime();
    } else {
        dropdown.style.display = 'none';
        syncBtn.style.display = 'none';
        syncInd.style.display = 'none';
    }
}

function updateSyncTime() {
    if (accounts.length === 0) return;
    const synced = accounts
        .map(a => a.last_synced)
        .filter(Boolean)
        .sort()
        .pop();
    if (synced) {
        const diff = Math.floor((Date.now() - new Date(synced + 'Z').getTime()) / 60000);
        let text;
        if (diff < 1) text = 'just now';
        else if (diff < 60) text = `${diff}m ago`;
        else text = `${Math.floor(diff / 60)}h ago`;
        document.getElementById('syncText').textContent = `Last synced: ${text}`;
    }
}

async function removeAccount(id) {
    try {
        await deleteAccount(id);
        await loadAccounts();
        showToast('Account removed', 'info');

        if (accounts.length === 0) {
            navigate('connect');
        } else {
            renderSettingsAccounts();
            if (currentPage === 'dashboard') loadDashboard();
        }
    } catch (e) {
        showToast('Failed to remove account', 'error');
    }
}

// ---- Dashboard ----
async function loadDashboard() {
    showLoadingSkeleton();
    try {
        const [statsData, ordersData, accountsData] = await Promise.all([
            getStats(),
            getOrders(getFilterParams()),
            getAccounts(),
        ]);
        stats = statsData;
        orders = ordersData;
        accounts = accountsData;
        updateAccountsUI();
        renderStats();
        renderRetailerFilter();
        renderOrders();
    } catch (e) {
        console.error('Dashboard load error:', e);
        showToast('Failed to load dashboard data', 'error');
        // Show empty state so user isn't stuck
        document.getElementById('ordersGrid').innerHTML = '';
        document.getElementById('ordersListWrap').style.display = 'none';
        document.getElementById('emptyState').style.display = 'block';
        document.getElementById('emptyStateMsg').textContent =
            'Unable to load orders. Make sure you have a Gmail account connected.';
    }
}

function getFilterParams() {
    return {
        status:   document.getElementById('filterStatus').value,
        retailer: document.getElementById('filterRetailer').value,
        sort:     document.getElementById('sortSelect').value,
        search:   document.getElementById('searchInput').value.trim(),
    };
}

function renderStats() {
    animateCounter('statTotal', stats.total || 0);
    animateCounter('statTransit', stats.in_transit || 0);
    animateCounter('statDelivered', stats.delivered || 0);
    animateCounter('statProcessing', stats.processing || 0);
    document.getElementById('statSpent').textContent =
        '$' + (stats.total_spent || 0).toLocaleString('en-US', {
            minimumFractionDigits: 0,
            maximumFractionDigits: 0,
        });
}

function animateCounter(id, target) {
    const el = document.getElementById(id);
    const start = parseInt(el.textContent) || 0;
    if (start === target) { el.textContent = target; return; }
    const duration = 400;
    const startTime = performance.now();
    function step(now) {
        const progress = Math.min((now - startTime) / duration, 1);
        const eased = 1 - Math.pow(1 - progress, 3);
        el.textContent = Math.round(start + (target - start) * eased);
        if (progress < 1) requestAnimationFrame(step);
    }
    requestAnimationFrame(step);
}

function renderRetailerFilter() {
    const select = document.getElementById('filterRetailer');
    const current = select.value;
    const opts = ['<option value="">All Retailers</option>'];
    (stats.retailers || []).forEach(r => {
        opts.push(`<option value="${r}" ${r === current ? 'selected' : ''}>${r}</option>`);
    });
    select.innerHTML = opts.join('');
}

// ---- Order Rendering (Grid + List) ----
function renderOrders() {
    const grid = document.getElementById('ordersGrid');
    const listWrap = document.getElementById('ordersListWrap');
    const empty = document.getElementById('emptyState');
    const msg = document.getElementById('emptyStateMsg');

    if (orders.length === 0) {
        grid.innerHTML = '';
        listWrap.style.display = 'none';
        empty.style.display = 'block';
        msg.textContent = accounts.length > 0
            ? 'No orders matched your filters, or no shipment emails were found. Try syncing.'
            : 'Connect a Gmail account and sync to see your shipments.';
        return;
    }

    empty.style.display = 'none';

    if (currentView === 'list') {
        grid.style.display = 'none';
        listWrap.style.display = 'block';
        renderListView();
    } else {
        grid.style.display = '';
        listWrap.style.display = 'none';
        renderGridView();
    }
}

function renderGridView() {
    const grid = document.getElementById('ordersGrid');
    grid.innerHTML = orders.map(o => createOrderCard(o)).join('');
    grid.querySelectorAll('.order-card').forEach(card => {
        card.addEventListener('click', () => openOrderModal(card.dataset.id));
    });
    grid.querySelectorAll('.card-image img').forEach(img => {
        img.addEventListener('error', function () {
            this.style.display = 'none';
            const ph = this.nextElementSibling;
            if (ph) ph.style.display = 'flex';
        });
    });
}

function renderListView() {
    const tbody = document.getElementById('ordersTableBody');
    tbody.innerHTML = orders.map(o => createOrderRow(o)).join('');
    document.querySelectorAll('.order-table-row').forEach(row => {
        row.addEventListener('click', (e) => {
            // Don't open modal when clicking a link
            if (e.target.tagName === 'A') return;
            openOrderModal(row.dataset.id);
        });
    });
}

function createOrderCard(order) {
    const statusText = formatStatus(order.status);
    const statusClass = `status-${order.status}`;
    const initial = (order.retailer || '?').charAt(0).toUpperCase();
    const accountEmail = order.account_email ? order.account_email.split('@')[0] : '';
    const costStr = order.order_cost ? `$${Number(order.order_cost).toFixed(2)}` : '—';
    const imageHtml = order.item_image_url
        ? `<img src="${escHtml(order.item_image_url)}" alt="${escHtml(order.item_name || '')}" loading="lazy"><span class="card-image-placeholder" style="display:none">${initial}</span>`
        : `<span class="card-image-placeholder">${initial}</span>`;

    return `<div class="order-card" data-id="${order.id}" data-status="${order.status}">
        <div class="card-header">
            <div class="card-image">${imageHtml}</div>
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
                    <span class="card-account-dot" style="background:${order.account_color || '#3B82F6'}"></span>
                    ${escHtml(accountEmail)}
                </span>
            </div>
        </div>
    </div>`;
}

function createOrderRow(order) {
    const statusText = formatStatus(order.status);
    const dotClass = `status-dot status-dot-${order.status}`;
    const accountEmail = order.account_email ? order.account_email.split('@')[0] : '—';
    const costStr = order.order_cost ? `$${Number(order.order_cost).toFixed(2)}` : '—';
    const trackingHtml = order.tracking_number
        ? `<a href="${escHtml(order.tracking_url || '#')}" target="_blank" rel="noopener noreferrer">${escHtml(order.tracking_number)}</a>`
        : '—';

    return `<tr class="order-table-row" data-id="${order.id}">
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
                <span class="card-account-dot" style="background:${order.account_color || '#3B82F6'}"></span>
                ${escHtml(accountEmail)}
            </span>
        </td>
    </tr>`;
}

function showLoadingSkeleton() {
    const grid = document.getElementById('ordersGrid');
    grid.style.display = '';
    document.getElementById('ordersListWrap').style.display = 'none';
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
    localStorage.setItem('shippull_view', view);

    document.getElementById('btnViewGrid').classList.toggle('active', view === 'grid');
    document.getElementById('btnViewList').classList.toggle('active', view === 'list');

    renderOrders();
}

// ---- Order Modal ----
async function openOrderModal(orderId) {
    const overlay = document.getElementById('modalOverlay');
    const content = document.getElementById('modalContent');
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';

    content.innerHTML = '<div style="text-align:center;padding:40px;"><span class="spinner" style="width:24px;height:24px;border-width:3px;color:var(--accent-green)"></span></div>';

    try {
        const order = await getOrder(orderId);
        content.innerHTML = renderOrderModal(order);
        const img = content.querySelector('.modal-image img');
        if (img) {
            img.addEventListener('error', function () {
                this.style.display = 'none';
                const ph = this.nextElementSibling;
                if (ph) ph.style.display = 'flex';
            });
        }
    } catch (e) {
        content.innerHTML = '<p style="text-align:center;padding:40px;color:var(--text-tertiary)">Failed to load order details.</p>';
    }
}

function closeModal() {
    document.getElementById('modalOverlay').classList.remove('open');
    document.body.style.overflow = '';
}

function renderOrderModal(order) {
    const statusText = formatStatus(order.status);
    const statusClass = `status-${order.status}`;
    const initial = (order.retailer || '?').charAt(0).toUpperCase();
    const costStr = order.order_cost ? `$${Number(order.order_cost).toFixed(2)}` : '—';
    const imageHtml = order.item_image_url
        ? `<img src="${escHtml(order.item_image_url)}" alt="${escHtml(order.item_name || '')}"><span class="modal-image-placeholder" style="display:none">${initial}</span>`
        : `<span class="modal-image-placeholder">${initial}</span>`;

    const statusOrder = ['processing', 'shipped', 'in_transit', 'out_for_delivery', 'delivered'];
    const currentIdx = statusOrder.indexOf(order.status);

    const timelineSteps = [
        { key: 'processing',       label: 'Order Placed' },
        { key: 'shipped',          label: 'Shipped' },
        { key: 'in_transit',       label: 'In Transit' },
        { key: 'out_for_delivery', label: 'Out for Delivery' },
        { key: 'delivered',        label: 'Delivered' },
    ];

    const timelineHTML = timelineSteps.map((step, i) => {
        let cls = '';
        if (i < currentIdx) cls = 'completed';
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
            <div class="modal-image">${imageHtml}</div>
            <div class="modal-title-section">
                <div class="modal-retailer">${escHtml(order.retailer || 'Unknown')}</div>
                <div class="modal-item-name">${escHtml(order.item_name || 'Order')}</div>
                ${order.item_description ? `<div class="modal-item-desc">${escHtml(order.item_description)}</div>` : ''}
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
                        <span class="card-account-dot" style="background:${order.account_color || '#3B82F6'}"></span>
                        ${escHtml(order.account_email || '—')}
                    </span>
                </div>
            </div>
            <div class="modal-detail-item">
                <div class="modal-detail-label">Order ID</div>
                <div class="modal-detail-value" style="font-family:var(--font-mono);font-size:12px;">#${String(order.id).padStart(5, '0')}</div>
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
        const initial = a.email.charAt(0).toUpperCase();
        const connectedDate = a.connected_at
            ? new Date(a.connected_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })
            : '';
        const lastSynced = a.last_synced
            ? new Date(a.last_synced).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })
            : 'Never';
        return `<div class="account-item">
            <div class="account-avatar" style="background:${a.avatar_color}">${initial}</div>
            <div class="account-info">
                <div class="account-email">${escHtml(a.email)}</div>
                <div class="account-meta">Connected ${connectedDate} · Last synced: ${lastSynced}</div>
            </div>
            <button class="btn-remove" onclick="removeAccount(${a.id})">Remove</button>
        </div>`;
    }).join('');
}

// ---- Sync ----
async function syncAccounts(isInitial = false) {
    const btn = document.getElementById('btnSync');
    btn.classList.add('syncing');
    btn.disabled = true;

    try {
        const result = await postSync();
        await loadAccounts();
        if (currentPage === 'dashboard') await loadDashboard();
        const msg = result.new_orders > 0
            ? `Sync complete — ${result.new_orders} new order${result.new_orders === 1 ? '' : 's'} found`
            : isInitial
                ? 'Sync complete — no new orders found yet. Check back later or try a manual sync.'
                : 'Sync complete — no new orders found';
        showToast(msg, result.new_orders > 0 ? 'success' : 'info');
    } catch (e) {
        showToast('Sync failed: ' + (e.message || 'unknown error'), 'error');
    } finally {
        btn.classList.remove('syncing');
        btn.disabled = false;
    }
}

// ---- Toast Notifications ----
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
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
        processing:       'Processing',
        shipped:          'Shipped',
        in_transit:       'In Transit',
        out_for_delivery: 'Out for Delivery',
        delivered:        'Delivered',
    };
    return map[status] || status;
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

    // Filters
    let debounceTimer;
    document.getElementById('searchInput').addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => {
            if (currentPage === 'dashboard') loadDashboard();
        }, 300);
    });
    document.getElementById('filterStatus').addEventListener('change', () => {
        if (currentPage === 'dashboard') loadDashboard();
    });
    document.getElementById('filterRetailer').addEventListener('change', () => {
        if (currentPage === 'dashboard') loadDashboard();
    });
    document.getElementById('sortSelect').addEventListener('change', () => {
        if (currentPage === 'dashboard') loadDashboard();
    });

    // View toggle
    document.getElementById('btnViewGrid').addEventListener('click', () => setView('grid'));
    document.getElementById('btnViewList').addEventListener('click', () => setView('list'));

    // Apply saved view state
    if (currentView === 'list') {
        document.getElementById('btnViewGrid').classList.remove('active');
        document.getElementById('btnViewList').classList.add('active');
    }

    // Accounts dropdown
    document.getElementById('btnAccounts').addEventListener('click', (e) => {
        e.stopPropagation();
        document.getElementById('dropdownMenu').classList.toggle('open');
    });
    document.addEventListener('click', () => {
        document.getElementById('dropdownMenu').classList.remove('open');
    });

    // Modal
    document.getElementById('modalClose').addEventListener('click', closeModal);
    document.getElementById('modalOverlay').addEventListener('click', (e) => {
        if (e.target === e.currentTarget) closeModal();
    });
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') closeModal();
    });

    // Hash routing
    window.addEventListener('hashchange', handleRoute);
}

// ---- Init ----
async function init() {
    initEventListeners();
    await loadAccounts();
    handleRoute();
}

init();
