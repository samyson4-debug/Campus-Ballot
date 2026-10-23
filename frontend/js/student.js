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
let nominationElectionsCache = [];

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
        setupResultsModal();

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

        // Personal Stats with fallback attributes
        document.getElementById('stat-open-elections').textContent = dashboardData.open_elections_count ?? dashboardData.active_elections ?? 0;
        document.getElementById('stat-votes-cast').textContent = dashboardData.my_votes_count ?? dashboardData.votes_cast ?? 0;
        document.getElementById('stat-my-applications').textContent = dashboardData.my_applications_count ?? dashboardData.applications_count ?? 0;
        document.getElementById('stat-approved-candidacies').textContent = dashboardData.approved_candidacies_count ?? dashboardData.approved_candidates ?? 0;

        // Elections Cards
        cardGrid.innerHTML = '';
        if (!dashboardData.elections || dashboardData.elections.length === 0) {
            cardGrid.innerHTML = '<div class="empty-state" style="grid-column: 1 / -1;"><div class="empty-icon">🗳️</div><div class="empty-text">No elections scheduled currently.</div></div>';
        } else {
            dashboardData.elections.forEach((el) => {
                const card = document.createElement('div');
                card.className = 'card';

                const badgeClass = getBadgeCss(el.badge);
                const canVote = el.badge === 'Voting Open' && !el.has_voted;
                const isDeclared = el.results_declared || el.badge === 'Results Available';

                // Group candidates by post
                const cands = el.candidates || [];
                const postGroups = {};
                cands.forEach(c => {
                    const p = (c.post || 'General').trim();
                    if (!postGroups[p]) postGroups[p] = [];
                    postGroups[p].push(c);
                });
                const postGroupHtml = Object.entries(postGroups).map(([post, cs]) =>
                    `<div style="margin-bottom:8px;">
                        <div class="cand-badge-post" style="margin-bottom:6px;">🏷️ ${escapeHtml(post)}</div>
                        <div class="election-candidates-preview">${cs.map(c =>
                            `<div class="election-candidate-chip">
                                <span class="chip-name">${escapeHtml(c.name)}</span>
                                <span class="cand-badge-branch">🎓 ${escapeHtml(c.department || 'N/A')}</span>
                            </div>`).join('')}
                        </div>
                    </div>`
                ).join('');

                card.innerHTML = `
                    <div class="card-header">
                        <span class="badge ${badgeClass}">${el.badge}</span>
                        <span style="font-size: 0.8rem; color: var(--text-muted);">${formatDate(el.start_time)}</span>
                    </div>
                    <h3 style="font-size: 1.15rem; font-weight: 700; color: var(--text-primary); margin-bottom: 8px;">
                        ${escapeHtml(el.name)}
                    </h3>
                    <p style="font-size: 0.85rem; color: var(--text-secondary); margin-bottom: 10px;">
                        Closes: <strong>${formatDate(el.end_time)}</strong>
                    </p>
                    ${cands.length > 0 ? postGroupHtml : `<div style="margin-bottom:14px;"><span class="form-help">No candidates yet.</span></div>`}
                `;

                const footerDiv = document.createElement('div');
                footerDiv.style.display = 'flex';
                footerDiv.style.flexDirection = 'column';
                footerDiv.style.gap = '8px';

                if (isDeclared) {
                    const btnResults = document.createElement('button');
                    btnResults.className = 'btn btn-primary btn-sm';
                    btnResults.style.width = '100%';
                    btnResults.textContent = '🏆 View Results & Winner';
                    btnResults.onclick = () => showStudentResultsModal(el.id);
                    footerDiv.appendChild(btnResults);
                } else if (canVote) {
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
                    votedSpan.style.textAlign = 'center';
                    votedSpan.style.padding = '4px';
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
            historyTbody.innerHTML = '<tr><td colspan="4" style="text-align:center; padding: 20px; color: var(--text-muted);">No votes cast yet.</td></tr>';
        } else {
            dashboardData.participation_history.forEach((item) => {
                const tr = document.createElement('tr');
                const postLabel = item.post ? escapeHtml(item.post) : '<span style="color:var(--text-muted)">—</span>';
                tr.innerHTML = `
                    <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(item.election_name)}</td>
                    <td><span class="cand-badge-post">${postLabel}</span></td>
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

        // Collect one selected candidate per post
        const postSections = document.querySelectorAll('.ballot-post-section:not(.already-voted)');
        const selectedCandidates = [];
        const selectedNames = [];
        let allOk = true;

        if (postSections.length > 0) {
            postSections.forEach((section) => {
                const postName = section.getAttribute('data-post');
                const checked = section.querySelector('input[type="radio"]:checked');
                if (checked) {
                    selectedCandidates.push(parseInt(checked.value, 10));
                    selectedNames.push(`${checked.getAttribute('data-name')} (${postName})`);
                }
                // Voting for a post is optional — students can skip some posts
            });
        } else {
            // Fallback: single radio list
            const selectedRadio = document.querySelector('input[name="candidate_choice"]:checked');
            if (!selectedRadio) {
                votingError.textContent = 'Please select at least one candidate.';
                showToast('Please select at least one candidate.', 'warning');
                allOk = false;
            } else {
                selectedCandidates.push(parseInt(selectedRadio.value, 10));
                selectedNames.push(selectedRadio.getAttribute('data-name'));
            }
        }

        if (!allOk || selectedCandidates.length === 0) {
            if (selectedCandidates.length === 0) {
                votingError.textContent = 'Please select at least one candidate before submitting.';
                showToast('Please select at least one candidate.', 'warning');
            }
            return;
        }

        const namesList = selectedNames.map(n => `• ${n}`).join('\n');
        showModal({
            title: 'Confirm Your Vote',
            message: `You are about to cast your official vote(s) for:\n\n${namesList}\n\nIMPORTANT: Once submitted, your vote is final and cannot be changed.`,
            confirmText: 'Yes, Submit My Votes',
            confirmClass: 'btn-primary',
            onConfirm: async () => {
                await submitVote(electionId, selectedCandidates);
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
    const subtitleEl = document.getElementById('voting-ballot-subtitle');

    successCard.classList.add('hidden');
    emptyState.classList.add('hidden');
    votingError.textContent = '';
    candidatesList.innerHTML = '<div class="loading-overlay"><div class="loading-spinner"></div></div>';
    ballotCard.classList.remove('hidden');

    try {
        const data = await api.get(`/api/student/elections/${electionId}/candidates`);
        titleEl.textContent = `${data.election_name || 'Election'} — Ballot`;

        const candidates = Array.isArray(data) ? data : (data.candidates || []);
        const votedPosts = data.voted_posts || [];
        const votedCids = data.voted_candidate_ids || [];

        candidatesList.innerHTML = '';
        if (!candidates || candidates.length === 0) {
            candidatesList.innerHTML = '<p class="form-help" style="padding: 20px; text-align: center;">No approved candidates registered for this election yet.</p>';
            return;
        }

        // Group candidates by post
        const postGroups = {};
        candidates.forEach((c) => {
            const p = (c.post || 'General').trim();
            if (!postGroups[p]) postGroups[p] = [];
            postGroups[p].push(c);
        });
        const posts = Object.keys(postGroups);
        const hasMultiplePosts = posts.length > 1;

        if (subtitleEl) {
            if (hasMultiplePosts) {
                subtitleEl.textContent = `This election has ${posts.length} posts. You can vote for one candidate per post. Select your choices below and submit.`;
            } else {
                subtitleEl.textContent = 'Select one candidate below to cast your ballot.';
            }
        }

        posts.forEach((post) => {
            const isVoted = votedPosts.includes(post);
            const section = document.createElement('div');
            section.className = 'ballot-post-section' + (isVoted ? ' already-voted' : '');
            section.setAttribute('data-post', post);

            const header = document.createElement('div');
            header.className = 'ballot-post-header';
            header.innerHTML = `
                <div class="ballot-post-title">
                    <span class="cand-badge-post">🏷️ ${escapeHtml(post)}</span>
                </div>
                ${isVoted ? '<span class="ballot-voted-notice">✓ Voted</span>' : ''}
            `;
            section.appendChild(header);

            if (isVoted) {
                const notice = document.createElement('p');
                notice.className = 'form-help';
                notice.style.color = 'var(--text-muted)';
                notice.textContent = 'You have already cast your vote for this post.';
                section.appendChild(notice);
            } else {
                const radioList = document.createElement('div');
                radioList.className = 'radio-list';
                radioList.style.marginTop = '0';

                postGroups[post].forEach((cand) => {
                    const label = document.createElement('label');
                    label.className = 'radio-item';
                    const candName = cand.name || `Candidate #${cand.id}`;
                    const candDept = cand.department || 'N/A';

                    label.innerHTML = `
                        <input
                            type="radio"
                            name="candidate_post_${CSS.escape(post)}"
                            value="${cand.id}"
                            data-name="${escapeHtml(candName)}"
                            data-post="${escapeHtml(post)}"
                        >
                        <div class="radio-item-info">
                            <div class="radio-item-name">${escapeHtml(candName)}</div>
                            <div class="radio-item-dept">
                                <span class="cand-badge-branch">🎓 ${escapeHtml(candDept)}</span>
                            </div>
                        </div>
                    `;

                    label.addEventListener('click', () => {
                        // Deselect others within same post section
                        radioList.querySelectorAll('.radio-item').forEach(i => i.classList.remove('selected'));
                        label.classList.add('selected');
                    });

                    radioList.appendChild(label);
                });

                section.appendChild(radioList);
            }

            candidatesList.appendChild(section);
        });

        // Check if all posts already voted
        const unvotedPosts = posts.filter(p => !votedPosts.includes(p));
        if (unvotedPosts.length === 0 && posts.length > 0) {
            const doneNote = document.createElement('div');
            doneNote.className = 'ballot-voted-notice';
            doneNote.style.marginTop = '16px';
            doneNote.innerHTML = '✓ You have voted for all posts in this election.';
            candidatesList.appendChild(doneNote);
        }

    } catch (err) {
        ballotCard.classList.add('hidden');
        emptyState.classList.remove('hidden');
        showToast(err.message, 'error');
    }
}

async function submitVote(electionId, candidateIds) {
    const submitBtn = document.getElementById('btn-submit-ballot');
    const votingError = document.getElementById('voting-error');
    const ballotCard = document.getElementById('voting-ballot-card');
    const successCard = document.getElementById('voting-success-card');

    submitBtn.disabled = true;
    submitBtn.innerHTML = '<span class="spinner"></span> Securing Ballot...';
    votingError.textContent = '';

    // Support both single id (number) and array of ids
    const ids = Array.isArray(candidateIds) ? candidateIds : [candidateIds];
    const body = ids.length === 1
        ? { candidate_id: ids[0] }
        : { candidate_ids: ids };

    try {
        const resp = await api.post(`/api/student/elections/${electionId}/vote`, body);
        const posts = resp.posts_voted || [];
        const msg = posts.length > 0
            ? `Vote recorded for: ${posts.join(', ')}!`
            : 'Your vote has been officially recorded!';

        // Reload ballot to show updated voted state
        await loadBallot(electionId);
        showToast(msg, 'success');

        // Check if all posts are now voted
        const remaining = document.querySelectorAll('.ballot-post-section:not(.already-voted)');
        if (remaining.length === 0) {
            ballotCard.classList.add('hidden');
            successCard.classList.remove('hidden');
        }
    } catch (err) {
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
function updateNominationSchedule(selectedId) {
    const scheduleCard = document.getElementById('nomination-election-schedule');
    const nameEl = document.getElementById('nomination-election-name');
    const startEl = document.getElementById('nomination-start-date');
    const endEl = document.getElementById('nomination-end-date');
    const badgeEl = document.getElementById('nomination-status-badge');

    if (!scheduleCard) return;

    if (!selectedId) {
        scheduleCard.style.display = 'none';
        return;
    }

    const el = (nominationElectionsCache || []).find((e) => String(e.id) === String(selectedId));
    if (el) {
        if (nameEl) nameEl.textContent = el.name;
        if (startEl) startEl.textContent = formatDate(el.start_time);
        if (endEl) endEl.textContent = formatDate(el.end_time);
        if (badgeEl) {
            const badgeClass = getBadgeCss(el.badge);
            badgeEl.innerHTML = `<span class="badge ${badgeClass}">${el.badge || el.state || 'Scheduled'}</span>`;
        }
        scheduleCard.style.display = 'block';
    } else {
        scheduleCard.style.display = 'none';
    }
}

function setupNominationForm() {
    const form = document.getElementById('form-candidate-apply');
    const select = document.getElementById('apply-election-select');
    const manifestoInput = document.getElementById('apply-manifesto');
    const countEl = document.getElementById('manifesto-count');
    const errorEl = document.getElementById('apply-error');
    const submitBtn = document.getElementById('btn-submit-nomination');

    select.addEventListener('change', () => {
        updateNominationSchedule(select.value);
    });

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
            updateNominationSchedule('');
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
        nominationElectionsCache = dashboard.elections || [];

        select.innerHTML = '<option value="">Select an election...</option>';
        if (nominationElectionsCache.length > 0) {
            nominationElectionsCache.forEach((el) => {
                const opt = document.createElement('option');
                opt.value = el.id;
                opt.textContent = `${el.name} (${el.badge})`;
                select.appendChild(opt);
            });
        }

        if (payload && payload.electionId) {
            select.value = payload.electionId;
        }

        updateNominationSchedule(select.value);
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
            historyTbody.innerHTML = '<tr><td colspan="3" style="text-align:center; padding: 20px; color: var(--text-muted);">No voting participation recorded yet.</td></tr>';
            return;
        }

        history.forEach((h) => {
            const tr = document.createElement('tr');
            const postLabel = h.post ? `<span class="cand-badge-post">${escapeHtml(h.post)}</span>` : '<span style="color:var(--text-muted)">—</span>';
            tr.innerHTML = `
                <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(h.election_name)}</td>
                <td>${postLabel}</td>
                <td>${formatDate(h.voted_at)}</td>
            `;
            historyTbody.appendChild(tr);
        });
    } catch (err) {
        showToast('Failed to load profile: ' + err.message, 'error');
    }
}

// ============================================================
// 6. Results & Winner Modal
// ============================================================
function setupResultsModal() {
    const modal = document.getElementById('modal-student-results');
    document.getElementById('btn-close-results-modal')?.addEventListener('click', () => {
        modal?.classList.remove('active');
    });
    document.getElementById('btn-done-results-modal')?.addEventListener('click', () => {
        modal?.classList.remove('active');
    });
    modal?.addEventListener('click', (e) => {
        if (e.target === modal) {
            modal.classList.remove('active');
        }
    });
}

async function showStudentResultsModal(electionId) {
    const modal = document.getElementById('modal-student-results');
    const titleEl = document.getElementById('student-results-title');
    const metaEl = document.getElementById('student-results-meta');
    const winnerBanner = document.getElementById('student-results-winner-banner');
    const winnerNameEl = document.getElementById('student-results-winner-name');
    const winnerMetaEl = document.getElementById('student-results-winner-meta');
    const chartEl = document.getElementById('student-results-chart');
    const tbody = document.getElementById('student-results-tbody');

    if (!modal) return;

    chartEl.innerHTML = '<div class="loading-overlay" style="min-height: 80px;"><div class="loading-spinner"></div></div>';
    tbody.innerHTML = '';
    winnerBanner.style.display = 'none';
    modal.classList.add('active');

    try {
        const results = await api.get(`/api/student/results/${electionId}`);
        const totalVotes = results.total_votes ?? 0;
        titleEl.textContent = `${results.election_name || 'Election'} — Final Tally`;
        metaEl.textContent = `Total votes cast: ${totalVotes}`;

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

        chartEl.innerHTML = '';
        tbody.innerHTML = '';

        if (!results.results || results.results.length === 0) {
            chartEl.innerHTML = '<p class="form-help" style="text-align: center; padding: 12px;">No candidates were registered for this election.</p>';
            return;
        }

        const sorted = [...results.results].sort((a, b) => b.vote_count - a.vote_count);
        const maxVotes = Math.max(...sorted.map((c) => c.vote_count), 1);

        // Post winners section
        if (results.post_winners && Object.keys(results.post_winners).length > 0) {
            const winnersGrid = document.createElement('div');
            winnersGrid.className = 'post-winners-grid';
            Object.entries(results.post_winners).forEach(([post, w]) => {
                const card = document.createElement('div');
                card.className = 'post-winner-card';
                const pct = totalVotes > 0 ? ((w.vote_count / totalVotes) * 100).toFixed(1) : '0.0';
                card.innerHTML = `
                    <div class="pw-post">🏷️ ${escapeHtml(post)}</div>
                    <div class="pw-name">👑 ${escapeHtml(w.candidate_name)}</div>
                    <div class="pw-meta">${escapeHtml(w.department || 'N/A')} • ${w.vote_count} votes (${pct}%)</div>
                `;
                winnersGrid.appendChild(card);
            });
            chartEl.appendChild(winnersGrid);
        }

        // Group results by post
        const postGrouped = {};
        sorted.forEach(item => {
            const p = (item.post || 'General').trim();
            if (!postGrouped[p]) postGrouped[p] = [];
            postGrouped[p].push(item);
        });

        Object.entries(postGrouped).forEach(([post, items]) => {
            // Post separator bar chart
            const postLabel = document.createElement('div');
            postLabel.style.cssText = 'margin: 16px 0 8px; font-size:0.82rem; font-weight:700; text-transform:uppercase; letter-spacing:.06em; color:var(--accent-light);';
            postLabel.textContent = `🏷️ ${post}`;
            chartEl.appendChild(postLabel);

            items.forEach((item, index) => {
                const pct = totalVotes > 0 ? ((item.vote_count / totalVotes) * 100).toFixed(1) : '0.0';
                const barWidth = Math.max((item.vote_count / maxVotes) * 100, item.vote_count > 0 ? 5 : 2);
                const isWinner = index === 0 && item.vote_count > 0;

                const barBox = document.createElement('div');
                barBox.className = 'result-bar-container';
                barBox.innerHTML = `
                    <div class="result-bar-label">
                        <span class="result-bar-name">${isWinner ? '👑 ' : ''}${escapeHtml(item.candidate_name)}
                            <span class="cand-badge-branch" style="margin-left:6px;">🎓 ${escapeHtml(item.department || 'N/A')}</span>
                        </span>
                        <span class="result-bar-count">${item.vote_count} votes (${pct}%)</span>
                    </div>
                    <div class="result-bar-track">
                        <div class="result-bar-fill" style="width: ${barWidth}%;"></div>
                    </div>
                `;
                chartEl.appendChild(barBox);
            });
        });

        let rank = 1;
        sorted.forEach((item) => {
            const pct = totalVotes > 0 ? ((item.vote_count / totalVotes) * 100).toFixed(1) : '0.0';
            const tr = document.createElement('tr');
            tr.innerHTML = `
                <td style="font-weight: 700;">#${rank++}</td>
                <td style="font-weight: 600; color: var(--text-primary);">${escapeHtml(item.candidate_name)}</td>
                <td><span class="cand-badge-post">${escapeHtml(item.post || 'General')}</span></td>
                <td>${escapeHtml(item.department || '—')}</td>
                <td style="font-weight: 700; color: var(--accent-light);">${item.vote_count}</td>
                <td>${pct}%</td>
            `;
            tbody.appendChild(tr);
        });
    } catch (err) {
        showToast('Failed to load results: ' + err.message, 'error');
        modal.classList.remove('active');
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
