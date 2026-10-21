/**
 * Campus Ballot — API Helper Module
 * Wraps fetch() with credentials, JSON parsing, global 401 handling, and loading states.
 *
 * SECURITY: credentials='same-origin' ensures the HttpOnly cookie is sent only
 * to the same origin. User data is NEVER injected via innerHTML.
 */

/**
 * Escape HTML entities to prevent XSS when rendering user content.
 * @param {string} str - Raw string
 * @returns {string} Escaped string
 */
export function escapeHtml(str) {
    if (!str) return '';
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

/**
 * Core fetch wrapper.
 * @param {string} url - API endpoint
 * @param {object} options - fetch options
 * @returns {Promise<any>} Parsed JSON response
 */
async function request(url, options = {}) {
    const defaults = {
        credentials: 'same-origin',
        headers: {
            'Content-Type': 'application/json',
            ...(options.headers || {}),
        },
    };

    // Merge but remove Content-Type for FormData.
    if (options.body instanceof FormData) {
        delete defaults.headers['Content-Type'];
    }

    const config = { ...defaults, ...options, headers: { ...defaults.headers, ...options.headers } };

    const response = await fetch(url, config);

    // Global 401 handler: redirect to login page.
    if (response.status === 401) {
        // Don't redirect if we're already on the login page.
        if (!window.location.pathname.endsWith('index.html') && window.location.pathname !== '/') {
            window.location.href = '/index.html';
        }
        const data = await response.json().catch(() => ({ detail: 'Session expired.' }));
        throw new ApiError(data.detail || 'Not authenticated.', response.status);
    }

    // For file downloads, return the response blob.
    if (options.responseType === 'blob') {
        if (!response.ok) {
            const data = await response.json().catch(() => ({ detail: 'Download failed.' }));
            throw new ApiError(data.detail || 'Download failed.', response.status);
        }
        return response;
    }

    const data = await response.json().catch(() => null);

    if (!response.ok) {
        const message = data?.detail || `Request failed (${response.status})`;
        throw new ApiError(message, response.status);
    }

    return data;
}

/**
 * Custom error class with status code.
 */
export class ApiError extends Error {
    constructor(message, status) {
        super(message);
        this.status = status;
    }
}

// Convenience methods.
export const api = {
    get: (url) => request(url, { method: 'GET' }),
    post: (url, body) => request(url, { method: 'POST', body: JSON.stringify(body) }),
    delete: (url) => request(url, { method: 'DELETE' }),
    download: (url) => request(url, { method: 'GET', responseType: 'blob' }),
};
