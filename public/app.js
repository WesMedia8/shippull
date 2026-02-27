/* ============================================
   ShipPull — Client Application
   ============================================ */

const API = '/api';

// ---- State ----
let accounts = [];
let orders = [];
let stats = {};
let currentPage = 'connect';

// ---- API Helpers ----
async function api(action, options = {}) {
    const { method = 'GET', body = null, params = {} } = options;
    let url = `${API}?action=${action}`;
    Object.entries(params).forEach(([k, v]) => {
        if (v !== '' && v !== null && v !== undefined) {
            url += `&${encodeURIComponent(k)}=${encodeURIComponent(v)}`;
        }
    });
    const fetchOptions = { method };
    if (body) {
        fetchOptions.headers = { 'Content-Type': 'application/json' };
        fetchOptions.body = JSON.stringify(body);
    }
    const res = await fetch(url, fetchOptions);
    const data = await res.json();
    if (!res.ok && data.error) {
        throw new Error(data.error);
    }
    return data;
}

// ---- Router ----
function getHash() {
    return (window.location.hash || '#connect').replace('#', '');
}

function navigate(page) {
    window.location.hash = `#${page}`;
}

function handleRoute() {
    const hash = getHash();

    // If no accounts, always go to connect
    if (accounts.length === 0 && hash !== 'connect') {
        navigate('connect');
        return;
    }

    // If has accounts and on connect, go to dashboard
    if (accounts.length > 0 && hash === 'connect') {
        navigate('dashboard');
        return;
    }

    currentPage = hash;
    showPage(hash);
    updateNavLinks(hash);
}

function showPage(page) {
    document.querySelectorAll('.page').forEach(p => p.style.display = 'none');

    if (page === 'connect') {
        document.getElementById('pageConnect').style.display = 'flex';
    } else if (page === 'dashboard') {
        document.getElementById('pageDashboard').style.display = 'block';
        loadDashboard();
    } else if (page === 'settings') {
        document.getElementById('pageSettings').style.display = 'block';
        renderSettingsAccounts();
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
        accounts = await api('accounts');
        updateAccountsUI();
    } catch (e) {
        console.error('Failed to load accounts:', e);
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

        // Avatars
        const avatarsEl = document.getElementById('accountsAvatars');
        avatarsEl.innerHTML = accounts.slice(0, 3).map(a => {
            const initial = a.email.charAt(0).toUpperCase();
            return `<span class="avatar-dot" style="background:${a.avatar_color}">${initial}</span>`;
        }).join('');

        // Count
        document.getElementById('accountsCount').textContent =
            accounts.length === 1 ? '1 account' : `${accounts.length} accounts`;

        // Dropdown list
        const listEl = document.getElementById('dropdownAccountsList');
        listEl.innerHTML = accounts.map(a => {
            const initial = a.email.charAt(0).toUpperCase();
            return `<div class="dropdown-item">
                <span class="avatar-dot" style="background:${a.avatar_color};width:24px;height:24px;font-size:11px;display:inline-flex;align-items:center;justify-content:center;border-radius:50%;color:#fff;font-family:var(--font-mono);font-weight:700;flex-shrink:0">${initial}</span>
                <span class="dropdown-item-email">${a.email}</span>
            </div>`;
        }).join('');

        // Sync time
        updateSyncTime();
    } else {
        dropdown.style.display = 'none';
        syncBtn.style.display = 'none';
        syncInd.style.display = 'none';
    }
}

function updateSyncTime() {
    if (accounts.length === 0) return;
    const latest = accounts.reduce((a, b) =>
        new Date(a.last_synced || 0) > new Date(b.last_synced || 0) ? a : b
    );
    if (latest.last_synced) {
        const diff = Math.floor((Date.now() - new Date(latest.last_synced + 'Z').getTime()) / 60000);
        let text;
        if (diff < 1) text = 'just now';
        else if (diff < 60) text = `${diff}m ago`;
        else text = `${Math.floor(diff / 60)}h ago`;
        document.getElementById('syncText').textContent = `Last synced: ${text}`;
    }
}

async function connectAccount(email, btnEl) {
    const textEl = btnEl.querySelector('.btn-connect-text');
    const loadingEl = btnEl.querySelector('.btn-connect-loading');

    textEl.style.display = 'none';
    loadingEl.style.display = 'inline-flex';
    btnEl.disabled = true;

    try {
        await api('add_account', { method: 'POST', body: { email } });
        await loadAccounts();
        showToast('Account connected! Syncing orders...', 'success');

        // Small delay for effect
        await new Promise(r => setTimeout(r, 800));
        navigate('dashboard');
    } catch (e) {
        showToast(e.message || 'Failed to connect account', 'error');
    } finally {
        textEl.style.display = 'inline';
        loadingEl.style.display = 'none';
        btnEl.disabled = false;
    }
}

async function removeAccount(id) {
    try {
        await api('remove_account', { method: 'DELETE', params: { id } });
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
            api('stats'),
            api('orders', { params: getFilterParams() }),
            api('accounts'),
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
        showToast('Failed to load dashboard', 'error');
    }
}

function getFilterParams() {
    return {
        status: document.getElementById('filterStatus').value,
        retailer: document.getElementById('filterRetailer').value,
        sort: document.getElementById('sortSelect').value,
        search: document.getElementById('searchInput').value,
    };
}

function renderStats() {
    animateCounter('statTotal', stats.total || 0);
    animateCounter('statTransit', stats.in_transit || 0);
    animateCounter('statDelivered', stats.delivered || 0);
    animateCounter('statProcessing', stats.processing || 0);
    document.getElementById('statSpent').textContent = `$${(stats.total_spent || 0).toLocaleString('en-US', { minimumFractionDigits: 0, maximumFractionDigits: 0 })}`;
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

function renderOrders() {
    const grid = document.getElementById('ordersGrid');
    const empty = document.getElementById('emptyState');

    if (orders.length === 0) {
        grid.innerHTML = '';
        empty.style.display = 'block';
        return;
    }

    empty.style.display = 'none';
    grid.innerHTML = orders.map(order => createOrderCard(order)).join('');

    // Add click handlers
    grid.querySelectorAll('.order-card').forEach(card => {
        card.addEventListener('click', () => {
            const orderId = card.dataset.id;
            openOrderModal(orderId);
        });
    });

    // Handle image fallbacks
    grid.querySelectorAll('.card-image img').forEach(img => {
        img.addEventListener('error', function () {
            const placeholder = this.nextElementSibling;
            this.style.display = 'none';
            if (placeholder) placeholder.style.display = 'flex';
        });
    });
}

function createOrderCard(order) {
    const statusText = formatStatus(order.status);
    const statusClass = `status-${order.status}`;
    const initial = (order.retailer || '?').charAt(0);
    const accountEmail = order.account_email ? order.account_email.split('@')[0] : '';

    return `<div class="order-card" data-id="${order.id}" data-status="${order.status}">
        <div class="card-header">
            <div class="card-image">
                <img src="${order.item_image_url || ''}" alt="${order.item_name}" loading="lazy">
                <span class="card-image-placeholder" style="display:none">${initial}</span>
            </div>
            <div class="card-info">
                <div class="card-retailer">${order.retailer}</div>
                <div class="card-name">${order.item_name}</div>
                <div class="card-cost">$${order.order_cost.toFixed(2)}</div>
            </div>
        </div>
        <div class="card-details">
            <div class="card-row">
                <span class="card-label">Status</span>
                <span class="status-badge ${statusClass}">${statusText}</span>
            </div>
            <div class="card-row">
                <span class="card-label">Carrier</span>
                <span class="card-value">${order.shipping_carrier}</span>
            </div>
            <div class="card-row">
                <span class="card-label">Tracking</span>
                <span class="card-value"><a href="${order.tracking_url}" target="_blank" rel="noopener noreferrer" onclick="event.stopPropagation()">${order.tracking_number}</a></span>
            </div>
            <div class="card-row">
                <span class="card-label">ETA</span>
                <span class="card-value">${formatDate(order.estimated_delivery)}</span>
            </div>
            <div class="card-row">
                <span class="card-label">Account</span>
                <span class="card-account-tag">
                    <span class="card-account-dot" style="background:${order.account_color || '#3B82F6'}"></span>
                    ${accountEmail}
                </span>
            </div>
        </div>
    </div>`;
}

function showLoadingSkeleton() {
    const grid = document.getElementById('ordersGrid');
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

// ---- Order Modal ----
async function openOrderModal(orderId) {
    const overlay = document.getElementById('modalOverlay');
    const content = document.getElementById('modalContent');
    overlay.classList.add('open');
    document.body.style.overflow = 'hidden';

    content.innerHTML = '<div style="text-align:center;padding:40px;"><span class="spinner" style="width:24px;height:24px;border-width:3px;color:var(--accent-green)"></span></div>';

    try {
        const order = await api('order', { params: { id: orderId } });
        content.innerHTML = renderOrderModal(order);

        // Image fallback in modal
        const img = content.querySelector('.modal-image img');
        if (img) {
            img.addEventListener('error', function () {
                const placeholder = this.nextElementSibling;
                this.style.display = 'none';
                if (placeholder) placeholder.style.display = 'flex';
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
    const initial = (order.retailer || '?').charAt(0);

    const statusOrder = ['processing', 'shipped', 'in_transit', 'out_for_delivery', 'delivered'];
    const currentIdx = statusOrder.indexOf(order.status);

    const timelineSteps = [
        { key: 'processing', label: 'Order Placed' },
        { key: 'shipped', label: 'Shipped' },
        { key: 'in_transit', label: 'In Transit' },
        { key: 'out_for_delivery', label: 'Out for Delivery' },
        { key: 'delivered', label: 'Delivered' },
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

    return `
        <div class="modal-header">
            <div class="modal-image">
                <img src="${order.item_image_url || ''}" alt="${order.item_name}">
                <span class="modal-image-placeholder" style="display:none">${initial}</span>
            </div>
            <div class="modal-title-section">
                <div class="modal-retailer">${order.retailer}</div>
                <div class="modal-item-name">${order.item_name}</div>
                <div class="modal-item-desc">${order.item_description || ''}</div>
                <div class="modal-cost">$${order.order_cost.toFixed(2)}</div>
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
                <div class="modal-detail-value">${order.shipping_carrier}</div>
            </div>
            <div class="modal-detail-item">
                <div class="modal-detail-label">Est. Delivery</div>
                <div class="modal-detail-value">${formatDate(order.estimated_delivery)}</div>
            </div>
            <div class="modal-detail-item full-width">
                <div class="modal-detail-label">Tracking Number</div>
                <div class="modal-detail-value"><a href="${order.tracking_url}" target="_blank" rel="noopener noreferrer">${order.tracking_number}</a></div>
            </div>
            <div class="modal-detail-item">
                <div class="modal-detail-label">Account</div>
                <div class="modal-detail-value">
                    <span class="card-account-tag">
                        <span class="card-account-dot" style="background:${order.account_color || '#3B82F6'}"></span>
                        ${order.account_email || '—'}
                    </span>
                </div>
            </div>
            <div class="modal-detail-item">
                <div class="modal-detail-label">Order ID</div>
                <div class="modal-detail-value" style="font-family:var(--font-mono);font-size:12px;">#${String(order.id).padStart(5, '0')}</div>
            </div>
        </div>

        <div class="modal-email-info">
            <div class="modal-email-label">Original Email</div>
            <div class="modal-email-subject">"${order.raw_email_subject || 'N/A'}"</div>
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
        const connectedDate = a.connected_at ? new Date(a.connected_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' }) : '';
        return `<div class="account-item">
            <div class="account-avatar" style="background:${a.avatar_color}">${initial}</div>
            <div class="account-info">
                <div class="account-email">${a.email}</div>
                <div class="account-meta">Connected ${connectedDate}</div>
            </div>
            <button class="btn-remove" onclick="removeAccount(${a.id})">Remove</button>
        </div>`;
    }).join('');
}

// ---- Sync ----
async function syncAccounts() {
    const btn = document.getElementById('btnSync');
    btn.classList.add('syncing');
    try {
        await api('sync', { method: 'POST' });
        await loadAccounts();
        if (currentPage === 'dashboard') await loadDashboard();
        showToast('Sync complete', 'success');
    } catch (e) {
        showToast('Sync failed', 'error');
    } finally {
        btn.classList.remove('syncing');
    }
}

// ---- Toast Notifications ----
function showToast(message, type = 'info') {
    const container = document.getElementById('toastContainer');
    const toast = document.createElement('div');
    toast.className = `toast toast-${type}`;

    let iconSVG = '';
    if (type === 'success') {
        iconSVG = '<svg class="toast-icon" viewBox="0 0 18 18" fill="none"><circle cx="9" cy="9" r="8" stroke="#22C55E" stroke-width="1.5"/><path d="M6 9L8 11L12 7" stroke="#22C55E" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>';
    } else if (type === 'error') {
        iconSVG = '<svg class="toast-icon" viewBox="0 0 18 18" fill="none"><circle cx="9" cy="9" r="8" stroke="#EF4444" stroke-width="1.5"/><path d="M6.5 6.5L11.5 11.5M11.5 6.5L6.5 11.5" stroke="#EF4444" stroke-width="1.5" stroke-linecap="round"/></svg>';
    } else {
        iconSVG = '<svg class="toast-icon" viewBox="0 0 18 18" fill="none"><circle cx="9" cy="9" r="8" stroke="#3B82F6" stroke-width="1.5"/><path d="M9 5V9M9 12V12.5" stroke="#3B82F6" stroke-width="1.5" stroke-linecap="round"/></svg>';
    }

    toast.innerHTML = `${iconSVG}<span>${message}</span>`;
    container.appendChild(toast);

    setTimeout(() => {
        toast.style.animation = 'toast-out 300ms ease forwards';
        setTimeout(() => toast.remove(), 300);
    }, 3500);
}

// ---- Utility ----
function formatStatus(status) {
    const map = {
        'processing': 'Processing',
        'shipped': 'Shipped',
        'in_transit': 'In Transit',
        'out_for_delivery': 'Out for Delivery',
        'delivered': 'Delivered',
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

// ---- Event Listeners ----
function initEventListeners() {
    // Connect form
    document.getElementById('btnConnect').addEventListener('click', () => {
        const email = document.getElementById('connectEmailInput').value.trim();
        if (email) connectAccount(email, document.getElementById('btnConnect'));
    });
    document.getElementById('connectEmailInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const email = e.target.value.trim();
            if (email) connectAccount(email, document.getElementById('btnConnect'));
        }
    });

    // Settings connect
    document.getElementById('btnSettingsConnect').addEventListener('click', () => {
        const email = document.getElementById('settingsEmailInput').value.trim();
        if (email) {
            connectAccount(email, document.getElementById('btnSettingsConnect'));
            document.getElementById('settingsEmailInput').value = '';
        }
    });
    document.getElementById('settingsEmailInput').addEventListener('keydown', (e) => {
        if (e.key === 'Enter') {
            const email = e.target.value.trim();
            if (email) {
                connectAccount(email, document.getElementById('btnSettingsConnect'));
                document.getElementById('settingsEmailInput').value = '';
            }
        }
    });

    // Sync
    document.getElementById('btnSync').addEventListener('click', syncAccounts);

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
