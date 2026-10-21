/**
 * Campus Ballot — Admin Control Center SPA Module
 * Single-Page Application controller for Administrator operations.
 */

import { api, escapeHtml } from './api.js';
import { showToast, showModal, createBadge, formatDate, showLoading, showEmpty } from './ui.js';

// State
let currentUser = null;
let currentView = 'dashboard';
let applicationsPollInterval = null;
let auditOffset = 0;
const AUDIT_LIMIT = 20;

// DOM Cache
const sidebar = document.getElementById('sidebar');
const mobileToggle = document.getElementById('mobile-toggle');
const adminUsernameEl = document.getElementById('admin-username');
const adminAvatarEl = document.getElementById('admin-avatar');
const btnLogout = document.getElementById('btn-logout');
const btnChangePassword = document.getElementById('btn-change-password');
const pwdModal = document.getElementById('modal-change-password');
const formChangePassword = document.getElementById('form-change-password');
const pwdChangeNotice = document.getElementById('pwd-change-notice');
const changePwdError = document.getElementById('change-pwd-error');

// ============================================================
// Initialization & Guard
// ============================================================
async function initAdminApp() {
    try {
        currentUser = await api.get('/api/auth/me');
        if (!currentUser || currentUser.role !== 'admin') {
            window.location.href = '/index.html';
            return;
        }

        adminUsernameEl.textContent = currentUser.username;
        adminAvatarEl.textContent = currentUser.username.charAt(0).toUpperCase();

        setupNavigation();
        setupMobileToggle();
        setupPasswordModal();
        setupLogout();

        if (currentUser.must_change_password) {
            pwdChangeNotice.style.display = 'block';
            pwdModal.classList.add('active');
        }

        // Initial view load
        switchView('dashboard');
    } catch {
        window.location.href = '/index.html';
    }
}

// ============================================================
// Navigation & Views
// ============================================================
function setupNavigation() {
    document.querySelectorAll('.sidebar-nav .nav-item').forEach((btn) => {
        btn.addEventListener('click', () => {
            const view = btn.getAttribute('data-view');
            switchView(view);
            // Close mobile sidebar if open
            sidebar.classList.remove('open');
        });
    });

    document.getElementById('btn-quick-new-election')?.addEventListener('click', () => {
        switchView('elections');
        document.getElementById('panel-create-election')?.classList.remove('hidden');
        document.getElementById('election-name')?.focus();
    });
}

function switchView(viewName) {
    currentView = viewName;

    // Update active nav button
    document.querySelectorAll('.sidebar-nav .nav-item').forEach((btn) => {
        if (btn.getAttribute('data-view') === viewName) {
            btn.classList.add('active');
        } else {
            btn.classList.remove('active');
        }
    });

    // Toggle view sections
    document.querySelectorAll('.view-section').forEach((section) => {
        section.classList.add('hidden');
    });

    const activeSection = document.getElementById(`view-${viewName}`);
    if (activeSection) {
        activeSection.classList.remove('hidden');
    }

    // Stop application polling if navigating away
    if (viewName !== 'applications') {
        stopApplicationsPolling();
    }

    // Trigger view loader
    switch (viewName) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'elections':
            loadElectionsView();
            break;
        case 'applications':
            loadApplicationsView();
            startApplicationsPolling();
            break;
        case 'results':
            loadResultsView();
            break;
        case 'audit':
            loadAuditLog();
            break;
    }
}

function setupMobileToggle() {
    mobileToggle.addEventListener('click', () => {
        sidebar.classList.toggle('open');
    });
}

// ============================================================
// 1. Dashboard View
// ============================================================
async function loadDashboard() {
    try {
        const data = await api.get('/api/admin/dashboard');

        const counts = data.counts || data;
        document.getElementById('stat-total-elections').textContent = counts.total_elections ?? 0;
        document.getElementById('stat-active-elections').textContent = counts.active_elections ?? 0;
        document.getElementById('stat-total-candidates').textContent = counts.total_candidates ?? 0;
        document.getElementById('stat-registered-students').textContent = counts.registered_students ?? 0;
        document.getElementById('stat-total-votes').textContent = counts.total_votes ?? 0;

        const tbody = document.getElementById('recent-elections-tbody');
        tbody.innerHTML = '';

        if (!data.recent_elections || data.recent_elections.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 24px; color: var(--text-muted);">No elections scheduled yet.</td></tr>';
            return;
        }

        data.recent_elections.forEach((el) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(el.name)}</td>
                <td>${formatDate(el.start_time)}</td>
                <td>${formatDate(el.end_time)}</td>
                <td><span class="badge ${el.status === 'ON' ? 'badge-on' : 'badge-off'}">${el.status}</span></td>
                <td><span class="badge badge-${el.state.toLowerCase().replace('_', '-')}">${el.state}</span></td>
                <td><span class="badge ${el.results_declared ? 'badge-results-available' : 'badge-pending'}">${el.results_declared ? 'Declared' : 'Pending'}</span></td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        showToast('Failed to load dashboard: ' + err.message, 'error');
    }
}

// ============================================================
// 2. Elections View
// ============================================================
function setupElectionsView() {
    const toggleBtn = document.getElementById('btn-toggle-create-election');
    const panel = document.getElementById('panel-create-election');
    const cancelBtn = document.getElementById('btn-cancel-create-election');
    const form = document.getElementById('form-create-election');
    const errorEl = document.getElementById('create-election-error');

    toggleBtn.onclick = () => {
        panel.classList.toggle('hidden');
        if (!panel.classList.contains('hidden')) {
            document.getElementById('election-name').focus();
        }
    };

    cancelBtn.onclick = () => {
        panel.classList.add('hidden');
        form.reset();
        errorEl.textContent = '';
    };

    document.getElementById('btn-refresh-elections').onclick = () => loadElectionsView();

    form.onsubmit = async (e) => {
        e.preventDefault();
        errorEl.textContent = '';

        const name = document.getElementById('election-name').value.trim();
        const startVal = document.getElementById('election-start').value;
        const endVal = document.getElementById('election-end').value;

        if (!name || !startVal || !endVal) {
            errorEl.textContent = 'Please provide name, start time, and end time.';
            return;
        }

        // Convert "YYYY-MM-DDTHH:MM" to "YYYY-MM-DD HH:MM"
        const startTime = startVal.replace('T', ' ');
        const endTime = endVal.replace('T', ' ');

        try {
            await api.post('/api/admin/elections', {
                name,
                start_time: startTime,
                end_time: endTime,
            });

            showToast('Election scheduled successfully!', 'success');
            form.reset();
            panel.classList.add('hidden');
            loadElectionsView();
        } catch (err) {
            errorEl.textContent = err.message;
            showToast(err.message, 'error');
        }
    };
}

async function loadElectionsView() {
    const tbody = document.getElementById('all-elections-tbody');
    tbody.innerHTML = '<tr><td colspan="8" style="text-align:center;">Loading...</td></tr>';

    try {
        const elections = await api.get('/api/admin/elections');
        tbody.innerHTML = '';

        if (!elections || elections.length === 0) {
            tbody.innerHTML = '<tr><td colspan="8" style="text-align:center; padding: 24px; color: var(--text-muted);">No elections found. Create your first election above.</td></tr>';
            return;
        }

        elections.forEach((el) => {
            const tr = document.createElement('tr');

            // Action buttons
            const actionTd = document.createElement('td');
            actionTd.style.textAlign = 'right';
            actionTd.style.whiteSpace = 'nowrap';

            // Switch button (ON / OFF)
            if (el.status === 'OFF') {
                const btnOn = document.createElement('button');
                btnOn.className = 'btn btn-success btn-sm';
                btnOn.style.marginRight = '6px';
                btnOn.textContent = '▶ Turn ON';
                if (el.results_declared) {
                    btnOn.disabled = true;
                    btnOn.title = 'Cannot turn ON a declared election.';
                } else {
                    btnOn.onclick = () => confirmToggleElection(el, 'on');
                }
                actionTd.appendChild(btnOn);
            } else {
                const btnOff = document.createElement('button');
                btnOff.className = 'btn btn-warning btn-sm';
                btnOff.style.marginRight = '6px';
                btnOff.textContent = '⏸ Turn OFF';
                btnOff.onclick = () => confirmToggleElection(el, 'off');
                actionTd.appendChild(btnOff);
            }

            // Declare results button
            if (!el.results_declared) {
                const btnDeclare = document.createElement('button');
                btnDeclare.className = 'btn btn-ghost btn-sm';
                btnDeclare.style.marginRight = '6px';
                btnDeclare.textContent = '📢 Declare Results';
                btnDeclare.onclick = () => confirmDeclareResults(el);
                actionTd.appendChild(btnDeclare);
            }

            // Delete button
            const btnDel = document.createElement('button');
            btnDel.className = 'btn btn-danger btn-sm';
            btnDel.textContent = '🗑';
            btnDel.setAttribute('aria-label', `Delete ${el.name}`);
            btnDel.onclick = () => confirmDeleteElection(el);
            actionTd.appendChild(btnDel);

            tr.innerHTML = `
                <td>#${el.id}</td>
                <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(el.name)}</td>
                <td>${formatDate(el.start_time)}</td>
                <td>${formatDate(el.end_time)}</td>
                <td><span class="badge ${el.status === 'ON' ? 'badge-on' : 'badge-off'}">${el.status}</span></td>
                <td><span class="badge badge-${el.state.toLowerCase().replace('_', '-')}">${el.state}</span></td>
                <td><span class="badge ${el.results_declared ? 'badge-results-available' : 'badge-pending'}">${el.results_declared ? 'Declared' : 'Pending'}</span></td>
            `;
            tr.appendChild(actionTd);
            tbody.appendChild(tr);
        });
    } catch (err) {
        showToast('Failed to load elections: ' + err.message, 'error');
    }
}

function confirmToggleElection(election, action) {
    const isTurningOn = action === 'on';
    showModal({
        title: isTurningOn ? 'Turn Election ON' : 'Turn Election OFF',
        message: isTurningOn
            ? `Are you sure you want to turn ON "${election.name}"? Eligible students will be able to cast votes during the scheduled window.`
            : `Are you sure you want to turn OFF "${election.name}"? Voting will be paused immediately.`,
        confirmText: isTurningOn ? 'Turn ON' : 'Turn OFF',
        confirmClass: isTurningOn ? 'btn-success' : 'btn-warning',
        onConfirm: async () => {
            try {
                await api.post(`/api/admin/elections/${election.id}/${action}`);
                showToast(`Election "${election.name}" turned ${action.toUpperCase()}.`, 'success');
                loadElectionsView();
            } catch (err) {
                showToast(err.message, 'error');
            }
        },
    });
}

function confirmDeclareResults(election) {
    if (election.status === 'ON') {
        showModal({
            title: 'Stop Voting First',
            message: 'You cannot declare results while the election is currently ON. Please turn the election OFF before declaring final results.',
            confirmText: 'Understood',
            confirmClass: 'btn-ghost',
        });
        return;
    }

    showModal({
        title: 'Declare Official Election Results',
        message: `Are you sure you want to declare the official results for "${election.name}"? Once declared, this election CANNOT be turned ON again, and the tally will be finalized.`,
        confirmText: 'Declare Results Now',
        confirmClass: 'btn-primary',
        onConfirm: async () => {
            try {
                await api.post(`/api/admin/elections/${election.id}/declare`);
                showToast(`Results declared for "${election.name}"!`, 'success');
                loadElectionsView();
            } catch (err) {
                showToast(err.message, 'error');
            }
        },
    });
}

function confirmDeleteElection(election) {
    showModal({
        title: 'Delete Election',
        message: `DANGER: Are you sure you want to delete "${election.name}"? This will permanently delete the election, all candidate registrations, and all recorded votes!`,
        confirmText: 'Permanently Delete',
        confirmClass: 'btn-danger',
        onConfirm: async () => {
            try {
                await api.delete(`/api/admin/elections/${election.id}`);
                showToast('Election deleted successfully.', 'success');
                loadElectionsView();
            } catch (err) {
                showToast(err.message, 'error');
            }
        },
    });
}

// ============================================================
// 3. Registered Applicants View
// ============================================================
function setupApplicationsView() {
    const searchInput = document.getElementById('applicant-search');
    const electionFilter = document.getElementById('applicant-election-filter');
    const statusFilter = document.getElementById('applicant-status-filter');
    const exportBtn = document.getElementById('btn-export-csv');
    const backupBtn = document.getElementById('btn-download-backup');

    let debounceTimer = null;
    searchInput.addEventListener('input', () => {
        clearTimeout(debounceTimer);
        debounceTimer = setTimeout(() => fetchApplications(), 300);
    });

    electionFilter.addEventListener('change', () => fetchApplications());
    statusFilter.addEventListener('change', () => fetchApplications());

    // CSV export
    exportBtn.addEventListener('click', async () => {
        try {
            showToast('Preparing applications CSV export...', 'info');
            const response = await api.download('/api/admin/applications/export.csv');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `candidate_applications_${Date.now()}.csv`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
            showToast('CSV export downloaded!', 'success');
        } catch (err) {
            showToast('Export failed: ' + err.message, 'error');
        }
    });

    // Database backup
    backupBtn.addEventListener('click', async () => {
        try {
            showToast('Generating SQLite live database snapshot...', 'info');
            const response = await api.download('/api/admin/backup');
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `campus_ballot_backup_${Date.now()}.db`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
            showToast('Database backup downloaded!', 'success');
        } catch (err) {
            showToast('Backup failed: ' + err.message, 'error');
        }
    });
}

async function loadApplicationsView() {
    // Populate election filter
    try {
        const elections = await api.get('/api/admin/elections');
        const select = document.getElementById('applicant-election-filter');
        const currentVal = select.value;
        select.innerHTML = '<option value="">All Elections</option>';
        elections.forEach((el) => {
            const opt = document.createElement('option');
            opt.value = el.id;
            opt.textContent = el.name;
            if (String(el.id) === currentVal) opt.selected = true;
            select.appendChild(opt);
        });
    } catch {
        // Ignore silent failure of dropdown populate
    }

    await fetchApplications();
}

async function fetchApplications() {
    const search = document.getElementById('applicant-search')?.value.trim() || '';
    const electionId = document.getElementById('applicant-election-filter')?.value || '';
    const status = document.getElementById('applicant-status-filter')?.value || '';

    const params = new URLSearchParams();
    if (search) params.append('search', search);
    if (electionId) params.append('election_id', electionId);
    if (status) params.append('status', status);

    const tbody = document.getElementById('applications-tbody');
    if (!tbody) return;

    try {
        const apps = await api.get(`/api/admin/applications?${params.toString()}`);
        tbody.innerHTML = '';

        if (!apps || apps.length === 0) {
            tbody.innerHTML = '<tr><td colspan="10" style="text-align:center; padding: 24px; color: var(--text-muted);">No applications matching criteria.</td></tr>';
            return;
        }

        apps.forEach((app) => {
            const tr = document.createElement('tr');

            const actionTd = document.createElement('td');
            actionTd.style.textAlign = 'right';
            actionTd.style.whiteSpace = 'nowrap';

            if (app.status === 'Pending') {
                const btnApprove = document.createElement('button');
                btnApprove.className = 'btn btn-success btn-sm';
                btnApprove.style.marginRight = '6px';
                btnApprove.textContent = '✓ Approve';
                btnApprove.onclick = () => confirmApplicationAction(app, 'approve');

                const btnReject = document.createElement('button');
                btnReject.className = 'btn btn-danger btn-sm';
                btnReject.textContent = '✕ Reject';
                btnReject.onclick = () => confirmApplicationAction(app, 'reject');

                actionTd.appendChild(btnApprove);
                actionTd.appendChild(btnReject);
            } else {
                const badge = createBadge(app.status);
                actionTd.appendChild(badge);
            }

            // Manifesto button/dialog
            const manifestoTd = document.createElement('td');
            manifestoTd.style.maxWidth = '180px';
            manifestoTd.style.whiteSpace = 'nowrap';
            manifestoTd.style.overflow = 'hidden';
            manifestoTd.style.textOverflow = 'ellipsis';
            manifestoTd.title = app.manifesto || '';
            manifestoTd.textContent = app.manifesto || '—';
            manifestoTd.style.cursor = 'pointer';
            manifestoTd.onclick = () => {
                showModal({
                    title: `Manifesto: ${app.full_name} (${app.post})`,
                    message: app.manifesto || 'No manifesto submitted.',
                    confirmText: 'Close',
                    confirmClass: 'btn-primary',
                });
            };

            tr.innerHTML = `
                <td>#${app.id}</td>
                <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(app.full_name)}</td>
                <td><code>${escapeHtml(app.student_id)}</code></td>
                <td>${escapeHtml(app.election_name || 'Election #' + app.election_id)}</td>
                <td><strong>${escapeHtml(app.post)}</strong></td>
                <td>${escapeHtml(app.department || '—')}</td>
            `;
            tr.appendChild(manifestoTd);
            tr.innerHTML += `
                <td><span class="badge ${app.status === 'Approved' ? 'badge-approved' : app.status === 'Rejected' ? 'badge-rejected' : 'badge-pending'}">${app.status}</span></td>
                <td>${formatDate(app.applied_at)}</td>
            `;
            tr.appendChild(actionTd);
            tbody.appendChild(tr);
        });
    } catch {
        // Polling errors handled silently
    }
}

function startApplicationsPolling() {
    stopApplicationsPolling();
    // 2-second polling with visibility check
    applicationsPollInterval = setInterval(() => {
        if (document.visibilityState === 'visible' && currentView === 'applications') {
            fetchApplications();
        }
    }, 2000);
}

function stopApplicationsPolling() {
    if (applicationsPollInterval) {
        clearInterval(applicationsPollInterval);
        applicationsPollInterval = null;
    }
}

function confirmApplicationAction(app, action) {
    const isApprove = action === 'approve';
    showModal({
        title: isApprove ? 'Approve Candidacy' : 'Reject Application',
        message: isApprove
            ? `Approve ${app.full_name} for the post of ${app.post} in "${app.election_name}"? This student will be officially added to the ballot candidate list.`
            : `Are you sure you want to reject the application of ${app.full_name} for ${app.post}?`,
        confirmText: isApprove ? 'Approve Candidate' : 'Reject Nomination',
        confirmClass: isApprove ? 'btn-success' : 'btn-danger',
        onConfirm: async () => {
            try {
                await api.post(`/api/admin/applications/${app.id}/${action}`);
                showToast(`Application #${app.id} ${action}d.`, 'success');
                fetchApplications();
            } catch (err) {
                showToast(err.message, 'error');
            }
        },
    });
}

// ============================================================
// 4. Results View
// ============================================================
async function loadResultsView() {
    const select = document.getElementById('results-election-select');
    select.innerHTML = '<option value="">Choose an election...</option>';

    try {
        const elections = await api.get('/api/admin/elections');
        const declared = elections.filter((e) => e.results_declared);

        if (declared.length === 0) {
            select.innerHTML = '<option value="">No declared elections yet</option>';
            document.getElementById('results-placeholder').innerHTML = `
                <div class="empty-icon">📊</div>
                <div class="empty-text">No election results have been declared yet.</div>
                <div class="empty-sub">Once an election has closed and results are declared, they will appear here.</div>
            `;
            document.getElementById('results-display-area').classList.add('hidden');
            return;
        }

        declared.forEach((el) => {
            const opt = document.createElement('option');
            opt.value = el.id;
            opt.textContent = `${el.name} (ID: ${el.id})`;
            select.appendChild(opt);
        });

        select.onchange = () => {
            const val = select.value;
            if (val) {
                renderElectionResults(val);
            } else {
                document.getElementById('results-display-area').classList.add('hidden');
                document.getElementById('results-placeholder').classList.remove('hidden');
            }
        };

        // If there is only one or more, preselect first
        if (declared.length > 0) {
            select.value = declared[0].id;
            renderElectionResults(declared[0].id);
        }
    } catch (err) {
        showToast('Failed to load declared elections: ' + err.message, 'error');
    }
}

async function renderElectionResults(electionId) {
    const displayArea = document.getElementById('results-display-area');
    const placeholder = document.getElementById('results-placeholder');
    const chartContainer = document.getElementById('results-chart-container');
    const tableBody = document.getElementById('results-table-tbody');

    try {
        const results = await api.get(`/api/admin/results/${electionId}`);
        placeholder.classList.add('hidden');
        displayArea.classList.remove('hidden');

        const totalVotes = results.total_votes ?? 0;
        document.getElementById('results-election-title').textContent = `${results.election_name} — Final Tally`;
        document.getElementById('results-election-meta').textContent = `Total votes cast: ${totalVotes}`;

        const winnerBanner = document.getElementById('results-winner-banner');
        const winnerNameEl = document.getElementById('results-winner-name');
        const winnerMetaEl = document.getElementById('results-winner-meta');

        if (winnerBanner && winnerNameEl && winnerMetaEl) {
            if (results.winner && results.winner.vote_count > 0) {
                const winnerPct = totalVotes > 0 ? ((results.winner.vote_count / totalVotes) * 100).toFixed(1) : '0.0';
                winnerBanner.style.display = 'block';
                winnerNameEl.textContent = `🏆 ${results.winner.candidate_name}`;
                winnerMetaEl.textContent = `${results.winner.department || 'General'} • ${results.winner.vote_count} votes (${winnerPct}% of total votes)`;
            } else if (results.results && results.results.length > 0 && results.results[0].vote_count > 0) {
                const top = results.results[0];
                const winnerPct = totalVotes > 0 ? ((top.vote_count / totalVotes) * 100).toFixed(1) : '0.0';
                winnerBanner.style.display = 'block';
                winnerNameEl.textContent = `🏆 ${top.candidate_name}`;
                winnerMetaEl.textContent = `${top.department || 'General'} • ${top.vote_count} votes (${winnerPct}% of total votes)`;
            } else {
                winnerBanner.style.display = 'none';
            }
        }

        chartContainer.innerHTML = '';
        tableBody.innerHTML = '';

        if (!results.results || results.results.length === 0) {
            chartContainer.innerHTML = '<p class="form-help">No candidates were registered for this election.</p>';
            return;
        }

        // Candidates sorted by vote count descending
        const sorted = [...results.results].sort((a, b) => b.vote_count - a.vote_count);
        const maxVotes = Math.max(...sorted.map((c) => c.vote_count), 1);

        sorted.forEach((item, index) => {
            const pct = results.total_votes > 0 ? ((item.vote_count / results.total_votes) * 100).toFixed(1) : '0.0';
            const barWidth = Math.max((item.vote_count / maxVotes) * 100, item.vote_count > 0 ? 5 : 2);

            // Chart row
            const barBox = document.createElement('div');
            barBox.className = 'result-bar-container';
            barBox.innerHTML = `
                <div class="result-bar-label">
                    <span class="result-bar-name">${index === 0 && item.vote_count > 0 ? '👑 ' : ''}${escapeHtml(item.candidate_name)} (${escapeHtml(item.department || 'General')})</span>
                    <span class="result-bar-count">${item.vote_count} votes (${pct}%)</span>
                </div>
                <div class="result-bar-track">
                    <div class="result-bar-fill" style="width: ${barWidth}%;"></div>
                </div>
            `;
            chartContainer.appendChild(barBox);

            // Table row
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 700;">#${index + 1}</td>
                <td style="font-weight: 600; color: var(--text-primary);">${index === 0 && item.vote_count > 0 ? '🏆 ' : ''}${escapeHtml(item.candidate_name)}</td>
                <td>${escapeHtml(item.department || '—')}</td>
                <td style="font-weight: 700; color: var(--accent-light);">${item.vote_count}</td>
                <td>${pct}%</td>
            `;
            tableBody.appendChild(tr);
        });
    } catch (err) {
        showToast('Failed to load results: ' + err.message, 'error');
    }
}

// ============================================================
// 5. Audit Log View
// ============================================================
function setupAuditView() {
    const btnRefresh = document.getElementById('btn-refresh-audit');
    const btnPrev = document.getElementById('btn-audit-prev');
    const btnNext = document.getElementById('btn-audit-next');

    btnRefresh.onclick = () => loadAuditLog();

    btnPrev.onclick = () => {
        if (auditOffset >= AUDIT_LIMIT) {
            auditOffset -= AUDIT_LIMIT;
            loadAuditLog();
        }
    };

    btnNext.onclick = () => {
        auditOffset += AUDIT_LIMIT;
        loadAuditLog();
    };
}

async function loadAuditLog() {
    const tbody = document.getElementById('audit-tbody');
    const btnPrev = document.getElementById('btn-audit-prev');
    const btnNext = document.getElementById('btn-audit-next');
    const pageInfo = document.getElementById('audit-page-info');

    tbody.innerHTML = '<tr><td colspan="6" style="text-align:center;">Loading audit trail...</td></tr>';

    try {
        const logs = await api.get(`/api/admin/audit-log?limit=${AUDIT_LIMIT}&offset=${auditOffset}`);
        tbody.innerHTML = '';

        const pageNum = Math.floor(auditOffset / AUDIT_LIMIT) + 1;
        pageInfo.textContent = `Page ${pageNum}`;
        btnPrev.disabled = auditOffset === 0;
        btnNext.disabled = !logs || logs.length < AUDIT_LIMIT;

        if (!logs || logs.length === 0) {
            tbody.innerHTML = '<tr><td colspan="6" style="text-align:center; padding: 24px; color: var(--text-muted);">No audit events recorded.</td></tr>';
            return;
        }

        logs.forEach((log) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td>#${log.id}</td>
                <td style="white-space: nowrap;">${formatDate(log.created_at)}</td>
                <td><code>${escapeHtml(log.action)}</code></td>
                <td><span class="badge ${log.actor_type === 'admin' ? 'badge-on' : 'badge-upcoming'}">${escapeHtml(log.actor_type)}</span></td>
                <td><code>${escapeHtml(log.actor_id || 'system')}</code></td>
                <td style="font-size: 0.85rem; color: var(--text-muted);">${escapeHtml(log.details || '')}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        showToast('Failed to load audit logs: ' + err.message, 'error');
    }
}

// ============================================================
// Password Change & Sign Out
// ============================================================
function setupPasswordModal() {
    btnChangePassword.onclick = () => {
        pwdChangeNotice.style.display = 'none';
        changePwdError.textContent = '';
        formChangePassword.reset();
        pwdModal.classList.add('active');
    };

    document.getElementById('btn-close-pwd-modal').onclick = () => pwdModal.classList.remove('active');
    document.getElementById('btn-cancel-pwd-modal').onclick = () => pwdModal.classList.remove('active');

    formChangePassword.onsubmit = async (e) => {
        e.preventDefault();
        changePwdError.textContent = '';

        const old_password = document.getElementById('old-password').value;
        const new_password = document.getElementById('new-password').value;
        const confirm_new_password = document.getElementById('confirm-new-password').value;

        if (!old_password || !new_password || !confirm_new_password) {
            changePwdError.textContent = 'All fields are required.';
            return;
        }

        if (new_password !== confirm_new_password) {
            changePwdError.textContent = 'New passwords do not match.';
            return;
        }

        try {
            await api.post('/api/admin/change-password', {
                old_password,
                new_password,
                confirm_new_password,
            });

            showToast('Password updated successfully!', 'success');
            pwdModal.classList.remove('active');
            currentUser.must_change_password = 0;
        } catch (err) {
            changePwdError.textContent = err.message;
            showToast(err.message, 'error');
        }
    };
}

function setupLogout() {
    btnLogout.onclick = () => {
        showModal({
            title: 'Sign Out',
            message: 'Are you sure you want to log out of the Administrator Control Center?',
            confirmText: 'Sign Out',
            confirmClass: 'btn-danger',
            onConfirm: async () => {
                try {
                    await api.post('/api/auth/logout');
                } catch {
                    // Ignore logout error
                }
                window.location.href = '/index.html';
            },
        });
    };
}

// Wire everything on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initAdminApp();
    setupElectionsView();
    setupApplicationsView();
    setupAuditView();
});
