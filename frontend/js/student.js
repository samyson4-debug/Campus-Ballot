/**
 * Campus Ballot — Student Portal SPA Module
 * Single-Page Application controller for Student voter operations.
 */

import { api, escapeHtml } from './api.js';
import { showToast, showModal, createBadge, formatDate, showLoading, showEmpty } from './ui.js';

// State
let currentStudent = null;
let currentView = 'dashboard';
let dashboardData = null;

// DOM Cache
const sidebar = document.getElementById('sidebar');
const mobileToggle = document.getElementById('mobile-toggle');
const studentDisplayNameEl = document.getElementById('student-display-name');
const studentIdBadgeEl = document.getElementById('student-id-badge');
const studentAvatarEl = document.getElementById('student-avatar');
const btnLogout = document.getElementById('btn-logout');

// ============================================================
// Initialization & Guard
// ============================================================
async function initStudentApp() {
    try {
        currentStudent = await api.get('/api/auth/me');
        if (!currentStudent || currentStudent.role !== 'student') {
            window.location.href = '/index.html';
            return;
        }

        studentDisplayNameEl.textContent = currentStudent.full_name || currentStudent.username;
        studentIdBadgeEl.textContent = currentStudent.student_id;
        studentAvatarEl.textContent = (currentStudent.full_name || currentStudent.username).charAt(0).toUpperCase();

        document.getElementById('greeting-title').textContent = `Welcome, ${currentStudent.full_name || currentStudent.username}!`;
        document.getElementById('greeting-subtitle').textContent = `Student ID: ${currentStudent.student_id} • One person, one vote`;

        setupNavigation();
        setupMobileToggle();
        setupLogout();
        setupVotingForm();
        setupNominationForm();

        // Initial view
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
            sidebar.classList.remove('open');
        });
    });

    document.getElementById('btn-back-to-dashboard')?.addEventListener('click', () => {
        switchView('dashboard');
    });
}

function switchView(viewName, payload = null) {
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

    // Trigger view loader
    switch (viewName) {
        case 'dashboard':
            loadDashboard();
            break;
        case 'voting':
            loadVotingScreen(payload);
            break;
        case 'apply':
            loadNominationScreen(payload);
            break;
        case 'my-applications':
            loadMyApplications();
            break;
        case 'profile':
            loadProfileView();
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
    const cardGrid = document.getElementById('elections-card-grid');
    const historyTbody = document.getElementById('dashboard-history-tbody');

    try {
        dashboardData = await api.get('/api/student/dashboard');

        // Personal Stats
        document.getElementById('stat-open-elections').textContent = dashboardData.open_elections_count;
        document.getElementById('stat-votes-cast').textContent = dashboardData.my_votes_count;
        document.getElementById('stat-my-applications').textContent = dashboardData.my_applications_count;
        document.getElementById('stat-approved-candidacies').textContent = dashboardData.approved_candidacies_count;

        // Elections Cards
        cardGrid.innerHTML = '';
        if (!dashboardData.elections || dashboardData.elections.length === 0) {
            cardGrid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1;"><div class="empty-icon">🗳️</div><div class="empty-text">No elections scheduled currently.</div></div>';
        } else {
            dashboardData.elections.forEach((el) => {
                const card = document.createElement('div');
                card.className = 'card';

                const badgeClass = getBadgeCss(el.badge);
                const canVote = el.badge === 'Voting Open';

                card.innerHTML = `
                    <div class="card-header">
                        <span class="badge ${badgeClass}">${el.badge}</span>
                        <span style="font-size: 0.8rem; color: var(--text-muted);">${formatDate(el.start_time)}</span>
                    </div>
                    <h3 style="font-size: 1.15rem; font-weight: 700; color: var(--text-primary); margin-bottom: 8px;">
                        ${escapeHtml(el.name)}
                    </h3>
                    <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 16px;">
                        Closes: <strong>${formatDate(el.end_time)}</strong>
                    </p>
                    <div style="margin-bottom: 16px;">
                        <span class="form-help">Approved Candidates: <strong>${el.candidate_count}</strong></span>
                    </div>
                `;

                const footerDiv = document.createElement('div');
                footerDiv.style.display = 'flex';
                footerDiv.style.gap = '8px';

                if (canVote) {
                    const btnVote = document.createElement('button');
                    btnVote.className = 'btn btn-primary btn-sm';
                    btnVote.style.width = '100%';
                    btnVote.textContent = '🗳️ Cast Vote Now';
                    btnVote.onclick = () => switchView('voting', { electionId: el.id });
                    footerDiv.appendChild(btnVote);
                } else if (el.has_voted) {
                    const votedSpan = document.createElement('div');
                    votedSpan.style.fontSize = '0.85rem';
                    votedSpan.style.color = '#a78bfa';
                    votedSpan.style.fontWeight = '600';
                    votedSpan.textContent = '✓ Ballot Submitted';
                    footerDiv.appendChild(votedSpan);
                } else {
                    const btnNominate = document.createElement('button');
                    btnNominate.className = 'btn btn-ghost btn-sm';
                    btnNominate.style.width = '100%';
                    btnNominate.textContent = 'Nominate for Post';
                    btnNominate.onclick = () => switchView('apply', { electionId: el.id });
                    footerDiv.appendChild(btnNominate);
                }

                card.appendChild(footerDiv);
                cardGrid.appendChild(card);
            });
        }

        // Recent Activity History
        historyTbody.innerHTML = '';
        if (!dashboardData.participation_history || dashboardData.participation_history.length === 0) {
            historyTbody.innerHTML = '<tr><td colspan="3" style="text-align:center; padding: 20px; color: var(--text-muted);">No votes cast yet.</td></tr>';
        } else {
            dashboardData.participation_history.forEach((item) => {
                const tr = document.createElement('tr');
                tr.innerHTML = `
                    <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(item.election_name)}</td>
                    <td><span class="badge badge-vote-submitted">Vote Recorded</span></td>
                    <td>${formatDate(item.voted_at)}</td>
                `;
                historyTbody.appendChild(tr);
            });
        }
    } catch (err) {
        showToast('Failed to load dashboard: ' + err.message, 'error');
    }
}

function getBadgeCss(badge) {
    switch (badge) {
        case 'Voting Open': return 'badge-open';
        case 'Vote Submitted': return 'badge-vote-submitted';
        case 'Upcoming': return 'badge-upcoming';
        case 'Closed': return 'badge-closed';
        case 'Results Available': return 'badge-results-available';
        default: return 'badge-pending';
    }
}

// ============================================================
// 2. Voting Screen
// ============================================================
function setupVotingForm() {
    const select = document.getElementById('voting-election-select');
    const form = document.getElementById('form-cast-vote');
    const votingError = document.getElementById('voting-error');

    select.addEventListener('change', () => {
        const electionId = select.value;
        if (electionId) {
            loadBallot(electionId);
        } else {
            document.getElementById('voting-ballot-card').classList.add('hidden');
            document.getElementById('voting-success-card').classList.add('hidden');
            document.getElementById('voting-empty-state').classList.remove('hidden');
        }
    });

    form.addEventListener('submit', (e) => {
        e.preventDefault();
        votingError.textContent = '';

        const electionId = select.value;
        if (!electionId) {
            votingError.textContent = 'Please select an election.';
            return;
        }

        const selectedRadio = document.querySelector('input[name="candidate_choice"]:checked');
        if (!selectedRadio) {
            votingError.textContent = 'Select Candidate';
            showToast('Select Candidate', 'warning');
            return;
        }

        const candidateId = parseInt(selectedRadio.value, 10);
        const candidateName = selectedRadio.getAttribute('data-name');

        showModal({
            title: 'Confirm Your Vote',
            message: `Are you sure you want to cast your official vote for "${candidateName}"?\n\nIMPORTANT: Once submitted, your vote is final and cannot be modified or withdrawn under any circumstances.`,
            confirmText: 'Yes, Submit My Vote',
            confirmClass: 'btn-primary',
            onConfirm: async () => {
                await submitVote(electionId, candidateId);
            },
        });
    });
}

async function loadVotingScreen(payload) {
    const select = document.getElementById('voting-election-select');
    const ballotCard = document.getElementById('voting-ballot-card');
    const successCard = document.getElementById('voting-success-card');
    const emptyState = document.getElementById('voting-empty-state');

    ballotCard.classList.add('hidden');
    successCard.classList.add('hidden');
    emptyState.classList.remove('hidden');

    try {
        const dashboard = await api.get('/api/student/dashboard');
        const openElections = (dashboard.elections || []).filter((e) => e.badge === 'Voting Open' || e.badge === 'Upcoming' || e.badge === 'Vote Submitted');

        if (openElections.length > 0) {
            select.innerHTML = '<option value="">Choose an election...</option>';
            openElections.forEach((el) => {
                const opt = document.createElement('option');
                opt.value = el.id;
                opt.textContent = `${el.name} [${el.badge}]`;
                select.appendChild(opt);
            });
        }

        // Preselect if navigated via "Vote Now" button
        if (payload && payload.electionId) {
            select.value = payload.electionId;
            loadBallot(payload.electionId);
        }
    } catch (err) {
        console.warn('Failed to refresh elections:', err);
    }
}

async function loadBallot(electionId) {
    const ballotCard = document.getElementById('voting-ballot-card');
    const successCard = document.getElementById('voting-success-card');
    const emptyState = document.getElementById('voting-empty-state');
    const candidatesList = document.getElementById('candidates-radio-list');
    const titleEl = document.getElementById('voting-election-title');
    const votingError = document.getElementById('voting-error');

    successCard.classList.add('hidden');
    emptyState.classList.add('hidden');
    votingError.textContent = '';
    candidatesList.innerHTML = '<div class="loading-overlay"><div class="loading-spinner"></div></div>';
    ballotCard.classList.remove('hidden');

    try {
        const data = await api.get(`/api/student/elections/${electionId}/candidates`);
        titleEl.textContent = `${data.election_name} Ballot`;

        candidatesList.innerHTML = '';
        if (!data.candidates || data.candidates.length === 0) {
            candidatesList.innerHTML = '<p class="form-help" style="padding: 20px; text-align: center;">No approved candidates registered for this election.</p>';
            return;
        }

        data.candidates.forEach((cand) => {
            const label = document.createElement('label');
            label.className = 'radio-item';

            label.innerHTML = `
                <input
                    type="radio"
                    name="candidate_choice"
                    value="${cand.id}"
                    data-name="${escapeHtml(cand.name)}"
                    required
                >
                <div class="radio-item-info">
                    <div class="radio-item-name">${escapeHtml(cand.name)}</div>
                    <div class="radio-item-dept">${escapeHtml(cand.department || 'General Candidate')}</div>
                </div>
            `;

            // Visual feedback on click
            label.addEventListener('click', () => {
                document.querySelectorAll('.radio-item').forEach((item) => item.classList.remove('selected'));
                label.classList.add('selected');
            });

            candidatesList.appendChild(label);
        });
    } catch (err) {
        ballotCard.classList.add('hidden');
        emptyState.classList.remove('hidden');
        showToast(err.message, 'error');
    }
}

async function submitVote(electionId, candidateId) {
    const submitBtn = document.getElementById('btn-submit-ballot');
    const votingError = document.getElementById('voting-error');
    const ballotCard = document.getElementById('voting-ballot-card');
    const successCard = document.getElementById('voting-success-card');

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span> Securing Ballot...';
    votingError.textContent = '';

    try {
        await api.post(`/api/student/elections/${electionId}/vote`, {
            candidate_id: candidateId,
        });

        // Show success screen
        ballotCard.classList.add('hidden');
        successCard.classList.remove('hidden');
        showToast('Your vote has been officially recorded!', 'success');
    } catch (err) {
        // Master prompt scenarios: "Already Voted", "Voting Not Started", "Voting Closed"
        votingError.textContent = err.message || 'Voting failed.';
        showToast(err.message || 'Voting failed.', 'error');
    } finally {
        submitBtn.disabled = false;
        submitBtn.innerHTML = '🗳️ Cast Vote';
    }
}

// ============================================================
// 3. Candidate Nomination (Apply)
// ============================================================
function setupNominationForm() {
    const form = document.getElementById('form-candidate-apply');
    const manifestoInput = document.getElementById('apply-manifesto');
    const countEl = document.getElementById('manifesto-count');
    const errorEl = document.getElementById('apply-error');
    const submitBtn = document.getElementById('btn-submit-nomination');

    manifestoInput.addEventListener('input', () => {
        const len = manifestoInput.value.length;
        countEl.textContent = `${len} / 2000`;
        if (len > 1900) {
            countEl.style.color = 'var(--warning)';
        } else {
            countEl.style.color = 'var(--text-muted)';
        }
    });

    form.addEventListener('submit', async (e) => {
        e.preventDefault();
        errorEl.textContent = '';

        const election_id = parseInt(document.getElementById('apply-election-select').value, 10);
        const post = document.getElementById('apply-post-select').value;
        const department = document.getElementById('apply-department').value.trim();
        const manifesto = manifestoInput.value.trim();

        if (!election_id || !post || !department || !manifesto) {
            errorEl.textContent = 'Please complete all required nomination fields.';
            return;
        }

        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner"></span> Submitting Nomination...';

        try {
            await api.post('/api/student/applications', {
                election_id,
                post,
                department,
                manifesto,
            });

            showToast('Nomination application submitted successfully!', 'success');
            form.reset();
            countEl.textContent = '0 / 2000';
            switchView('my-applications');
        } catch (err) {
            // Master prompt scenario: "Already applied"
            errorEl.textContent = err.message || 'Nomination failed.';
            showToast(err.message || 'Nomination failed.', 'error');
        } finally {
            submitBtn.disabled = false;
            submitBtn.textContent = 'Submit Nomination';
        }
    });
}

async function loadNominationScreen(payload) {
    const select = document.getElementById('apply-election-select');

    try {
        const dashboard = await api.get('/api/student/dashboard');
        const elections = dashboard.elections || [];
        if (elections.length > 0) {
            select.innerHTML = '<option value="">Select an election...</option>';
            elections.forEach((el) => {
                const opt = document.createElement('option');
                opt.value = el.id;
                opt.textContent = `${el.name} (${el.badge})`;
                select.appendChild(opt);
            });
        }

        if (payload && payload.electionId) {
            select.value = payload.electionId;
        }
    } catch (err) {
        console.warn('Failed to refresh nomination elections:', err);
    }
}

// ============================================================
// 4. My Applications View
// ============================================================
async function loadMyApplications() {
    const tbody = document.getElementById('my-applications-tbody');
    tbody.innerHTML = '<tr><td colspan="7" style="text-align:center;">Loading applications...</td></tr>';

    try {
        const apps = await api.get('/api/student/applications');
        tbody.innerHTML = '';

        if (!apps || apps.length === 0) {
            tbody.innerHTML = '<tr><td colspan="7" style="text-align:center; padding: 24px; color: var(--text-muted);">You have not filed any candidate nominations yet.</td></tr>';
            return;
        }

        apps.forEach((app) => {
            const tr = document.createElement('tr');

            const manifestoTd = document.createElement('td');
            manifestoTd.style.maxWidth = '180px';
            manifestoTd.style.whiteSpace = 'nowrap';
            manifestoTd.style.overflow = 'hidden';
            manifestoTd.style.textOverflow = 'ellipsis';
            manifestoTd.textContent = app.manifesto;
            manifestoTd.title = app.manifesto;
            manifestoTd.style.cursor = 'pointer';
            manifestoTd.onclick = () => {
                showModal({
                    title: `Your Manifesto for ${app.post}`,
                    message: app.manifesto,
                    confirmText: 'Close',
                    confirmClass: 'btn-primary',
                });
            };

            tr.innerHTML = `
                <td>#${app.id}</td>
                <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(app.election_name || 'Election #' + app.election_id)}</td>
                <td><strong>${escapeHtml(app.post)}</strong></td>
                <td>${escapeHtml(app.department || '—')}</td>
            `;
            tr.appendChild(manifestoTd);
            tr.innerHTML += `
                <td><span class="badge ${app.status === 'Approved' ? 'badge-approved' : app.status === 'Rejected' ? 'badge-rejected' : 'badge-pending'}">${app.status}</span></td>
                <td>${formatDate(app.applied_at)}</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        showToast('Failed to load applications: ' + err.message, 'error');
    }
}

// ============================================================
// 5. Profile View
// ============================================================
async function loadProfileView() {
    const fullNameEl = document.getElementById('profile-fullname');
    const studentIdEl = document.getElementById('profile-studentid');
    const usernameEl = document.getElementById('profile-username');
    const registeredAtEl = document.getElementById('profile-registered-at');
    const historyTbody = document.getElementById('profile-history-tbody');

    try {
        const profile = await api.get('/api/student/profile');
        fullNameEl.textContent = profile.full_name;
        studentIdEl.textContent = profile.student_id;
        usernameEl.textContent = profile.username;
        registeredAtEl.textContent = formatDate(profile.created_at);

        const history = await api.get('/api/student/history');
        historyTbody.innerHTML = '';

        if (!history || history.length === 0) {
            historyTbody.innerHTML = '<tr><td colspan="2" style="text-align:center; padding: 20px; color: var(--text-muted);">No voting participation recorded yet.</td></tr>';
            return;
        }

        history.forEach((h) => {
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(h.election_name)}</td>
                <td>${formatDate(h.voted_at)}</td>
            `;
            historyTbody.appendChild(tr);
        });
    } catch (err) {
        showToast('Failed to load profile: ' + err.message, 'error');
    }
}

// ============================================================
// Sign Out
// ============================================================
function setupLogout() {
    btnLogout.onclick = () => {
        showModal({
            title: 'Sign Out',
            message: 'Are you sure you want to end your student voting session?',
            confirmText: 'Sign Out',
            confirmClass: 'btn-danger',
            onConfirm: async () => {
                try {
                    await api.post('/api/auth/logout');
                } catch {
                    // Ignore
                }
                window.location.href = '/index.html';
            },
        });
    };
}

// Initialize on DOM ready
document.addEventListener('DOMContentLoaded', () => {
    initStudentApp();
});
