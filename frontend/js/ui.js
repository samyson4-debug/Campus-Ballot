/**
 * Campus Ballot — UI Utilities
 * Toast notifications, modal management, and DOM helpers.
 *
 * SECURITY: All user-facing text uses textContent, never innerHTML.
 */

// ============================================================
// Toast Notifications
// ============================================================
let toastContainer = null;

function ensureToastContainer() {
    if (!toastContainer) {
        toastContainer = document.createElement('div');
        toastContainer.className = 'toast-container';
        toastContainer.setAttribute('role', 'alert');
        toastContainer.setAttribute('aria-live', 'polite');
        document.body.appendChild(toastContainer);
    }
    return toastContainer;
}

const TOAST_ICONS = {
    success: '✓',
    error: '✕',
    warning: '⚠',
    info: 'ℹ',
};

/**
 * Show a toast notification.
 * @param {string} message - The message to display
 * @param {'success'|'error'|'warning'|'info'} type - Toast type
 * @param {number} duration - Duration in ms (default 4000)
 */
export function showToast(message, type = 'info', duration = 4000) {
    const container = ensureToastContainer();

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;

    const icon = document.createElement('span');
    icon.className = 'toast-icon';
    icon.textContent = TOAST_ICONS[type] || 'ℹ';

    const msg = document.createElement('span');
    msg.className = 'toast-message';
    msg.textContent = message;

    const close = document.createElement('button');
    close.className = 'toast-close';
    close.textContent = '×';
    close.setAttribute('aria-label', 'Close notification');
    close.onclick = () => removeToast(toast);

    const progress = document.createElement('div');
    progress.className = 'toast-progress';
    progress.style.animationDuration = `${duration}ms`;

    toast.appendChild(icon);
    toast.appendChild(msg);
    toast.appendChild(close);
    toast.appendChild(progress);
    container.appendChild(toast);

    setTimeout(() => removeToast(toast), duration);
}

function removeToast(toast) {
    if (!toast.parentNode) return;
    toast.classList.add('removing');
    setTimeout(() => toast.remove(), 300);
}


// ============================================================
// Modal Management
// ============================================================

/**
 * Show a confirmation modal.
 * @param {object} options
 * @param {string} options.title - Modal title
 * @param {string} options.message - Modal body text
 * @param {string} [options.confirmText='Confirm'] - Confirm button text
 * @param {string} [options.confirmClass='btn-primary'] - Confirm button CSS class
 * @param {Function} options.onConfirm - Callback on confirm
 */
export function showModal({ title, message, confirmText = 'Confirm', confirmClass = 'btn-primary', onConfirm }) {
    const overlay = document.createElement('div');
    overlay.className = 'modal-overlay';

    overlay.innerHTML = `
        <div class="modal" role="dialog" aria-modal="true" aria-label="${title}">
            <div class="modal-header">
                <h3 class="modal-title"></h3>
                <button class="modal-close" aria-label="Close modal">×</button>
            </div>
            <div class="modal-body"></div>
            <div class="modal-footer">
                <button class="btn btn-ghost modal-cancel-btn">Cancel</button>
                <button class="btn ${confirmClass} modal-confirm-btn"></button>
            </div>
        </div>
    `;

    // Use textContent for user-supplied strings (XSS safe).
    overlay.querySelector('.modal-title').textContent = title;
    overlay.querySelector('.modal-body').textContent = message;
    overlay.querySelector('.modal-confirm-btn').textContent = confirmText;

    const close = () => {
        overlay.classList.remove('active');
        setTimeout(() => overlay.remove(), 300);
    };

    overlay.querySelector('.modal-close').addEventListener('click', close);
    overlay.querySelector('.modal-cancel-btn').addEventListener('click', close);
    overlay.querySelector('.modal-confirm-btn').addEventListener('click', () => {
        close();
        if (onConfirm) onConfirm();
    });

    // Close on overlay click.
    overlay.addEventListener('click', (e) => {
        if (e.target === overlay) close();
    });

    // Close on Escape.
    const escHandler = (e) => {
        if (e.key === 'Escape') {
            close();
            document.removeEventListener('keydown', escHandler);
        }
    };
    document.addEventListener('keydown', escHandler);

    document.body.appendChild(overlay);
    // Force reflow then activate for transition.
    requestAnimationFrame(() => overlay.classList.add('active'));
}


// ============================================================
// Loading State
// ============================================================

/**
 * Show a loading spinner inside a container.
 * @param {HTMLElement} container
 */
export function showLoading(container) {
    container.innerHTML = `
        <div class="loading-overlay">
            <div class="loading-spinner"></div>
        </div>
    `;
}

/**
 * Show an empty state inside a container.
 * @param {HTMLElement} container
 * @param {string} icon
 * @param {string} text
 * @param {string} [subtext]
 */
export function showEmpty(container, icon, text, subtext = '') {
    const div = document.createElement('div');
    div.className = 'empty-state';

    const iconEl = document.createElement('div');
    iconEl.className = 'empty-icon';
    iconEl.textContent = icon;

    const textEl = document.createElement('div');
    textEl.className = 'empty-text';
    textEl.textContent = text;

    div.appendChild(iconEl);
    div.appendChild(textEl);

    if (subtext) {
        const subEl = document.createElement('div');
        subEl.className = 'empty-sub';
        subEl.textContent = subtext;
        div.appendChild(subEl);
    }

    container.innerHTML = '';
    container.appendChild(div);
}


// ============================================================
// DOM Helpers
// ============================================================

/**
 * Safely set text content (never innerHTML for user data).
 * @param {string} selector
 * @param {string} text
 */
export function setText(selector, text) {
    const el = document.querySelector(selector);
    if (el) el.textContent = text;
}

/**
 * Get a badge CSS class for a given state/badge string.
 * @param {string} badge
 * @returns {string}
 */
export function getBadgeClass(badge) {
    const map = {
        'Voting Open': 'badge-open',
        'OPEN': 'badge-open',
        'Closed': 'badge-closed',
        'CLOSED': 'badge-closed',
        'Upcoming': 'badge-upcoming',
        'NOT_STARTED': 'badge-not-started',
        'Vote Submitted': 'badge-vote-submitted',
        'Results Available': 'badge-results-available',
        'Pending': 'badge-pending',
        'Approved': 'badge-approved',
        'Rejected': 'badge-rejected',
        'ON': 'badge-on',
        'OFF': 'badge-off',
    };
    return map[badge] || 'badge-pending';
}

/**
 * Format a datetime string for display.
 * @param {string} dateStr
 * @returns {string}
 */
export function formatDate(dateStr) {
    if (!dateStr) return '—';
    try {
        // Handle both "YYYY-MM-DD HH:MM" and ISO formats.
        const parts = dateStr.split(' ');
        if (parts.length === 2) {
            const [date, time] = parts;
            const [y, m, d] = date.split('-');
            return `${d}/${m}/${y} ${time}`;
        }
        return dateStr;
    } catch {
        return dateStr;
    }
}

/**
 * Create a badge element.
 * @param {string} text
 * @returns {HTMLElement}
 */
export function createBadge(text) {
    const span = document.createElement('span');
    span.className = `badge ${getBadgeClass(text)}`;
    span.textContent = text;
    return span;
}
