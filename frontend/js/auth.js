/**
 * Campus Ballot — Auth Module
 * Manages Login, Student Registration, Password Strength Meter, and Session Redirection.
 */

import { api, ApiError } from './api.js';
import { showToast, showModal } from './ui.js';
import { initCanvas } from './login-canvas.js';

// DOM Elements
const loginTabBtn = document.getElementById('tab-login-btn');
const registerTabBtn = document.getElementById('tab-register-btn');
const loginForm = document.getElementById('login-form');
const registerForm = document.getElementById('register-form');

const loginIdentifier = document.getElementById('login-identifier');
const loginPassword = document.getElementById('login-password');
const loginError = document.getElementById('login-error');
const loginSubmitBtn = document.getElementById('login-submit-btn');

const regFullName = document.getElementById('reg-fullname');
const regUsername = document.getElementById('reg-username');
const regPassword = document.getElementById('reg-password');
const regConfirmPassword = document.getElementById('reg-confirm-password');
const regError = document.getElementById('reg-error');
const regSubmitBtn = document.getElementById('reg-submit-btn');

const strengthFill = document.getElementById('strength-fill');
const strengthText = document.getElementById('strength-text');

// Initialize background canvas
initCanvas('bg-canvas');

// Check existing session
async function checkCurrentSession() {
    try {
        const user = await api.get('/api/auth/me');
        if (user && user.role === 'admin') {
            window.location.href = '/admin.html';
        } else if (user && user.role === 'student') {
            window.location.href = '/student.html';
        }
    } catch {
        // Not logged in; remain on login page
    }
}

// Tab Switching
function switchTab(target) {
    if (target === 'login') {
        loginTabBtn.classList.add('active');
        loginTabBtn.setAttribute('aria-selected', 'true');
        registerTabBtn.classList.remove('active');
        registerTabBtn.setAttribute('aria-selected', 'false');

        loginForm.classList.remove('hidden');
        registerForm.classList.add('hidden');
        loginError.textContent = '';
        loginIdentifier.focus();
    } else {
        registerTabBtn.classList.add('active');
        registerTabBtn.setAttribute('aria-selected', 'true');
        loginTabBtn.classList.remove('active');
        loginTabBtn.setAttribute('aria-selected', 'false');

        registerForm.classList.remove('hidden');
        loginForm.classList.add('hidden');
        regError.textContent = '';
        regFullName.focus();
    }
}

loginTabBtn.addEventListener('click', () => switchTab('login'));
registerTabBtn.addEventListener('click', () => switchTab('register'));

// Password Visibility Toggles
document.querySelectorAll('.password-toggle').forEach((btn) => {
    btn.addEventListener('click', () => {
        const targetId = btn.getAttribute('data-target');
        const input = document.getElementById(targetId);
        if (!input) return;

        if (input.type === 'password') {
            input.type = 'text';
            btn.setAttribute('aria-label', 'Hide password');
            btn.textContent = '👁';
        } else {
            input.type = 'password';
            btn.setAttribute('aria-label', 'Show password');
            btn.textContent = '👁‍🗨';
        }
    });
});

// Password Strength Evaluation
function evaluatePasswordStrength(password) {
    if (!password) {
        return { score: 0, label: '', cssClass: '' };
    }

    let score = 0;
    if (password.length >= 8) score++;
    if (/[A-Z]/.test(password)) score++;
    if (/[a-z]/.test(password)) score++;
    if (/[0-9]/.test(password)) score++;
    if (/[^A-Za-z0-9]/.test(password)) score++;

    if (password.length < 8) {
        return { score: 1, label: 'Weak (min 8 chars)', cssClass: 'weak' };
    }
    if (score <= 2) {
        return { score: 1, label: 'Weak', cssClass: 'weak' };
    }
    if (score === 3) {
        return { score: 2, label: 'Fair', cssClass: 'fair' };
    }
    if (score === 4) {
        return { score: 3, label: 'Good', cssClass: 'good' };
    }
    return { score: 4, label: 'Strong', cssClass: 'strong' };
}

regPassword.addEventListener('input', () => {
    const pwd = regPassword.value;
    const { label, cssClass } = evaluatePasswordStrength(pwd);

    strengthFill.className = `strength-fill ${cssClass}`;
    strengthText.className = `strength-text ${cssClass}`;
    strengthText.textContent = label;
});

// Login Form Submit
loginForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    loginError.textContent = '';

    const identifier = loginIdentifier.value.trim();
    const password = loginPassword.value;

    if (!identifier || !password) {
        loginError.textContent = 'Please enter your ID/Username and password.';
        return;
    }

    loginSubmitBtn.disabled = true;
    loginSubmitBtn.innerHTML = '<span class="spinner"></span> Signing In...';

    try {
        const response = await api.post('/api/auth/login', {
            identifier,
            password,
        });

        showToast(response.message || 'Login successful!', 'success');

        if (response.role === 'admin') {
            window.location.href = '/admin.html';
        } else {
            window.location.href = '/student.html';
        }
    } catch (err) {
        loginError.textContent = err.message || 'Invalid ID/Username or password.';
        showToast(loginError.textContent, 'error');
    } finally {
        loginSubmitBtn.disabled = false;
        loginSubmitBtn.textContent = 'Sign In';
    }
});

// Register Form Submit
registerForm.addEventListener('submit', async (e) => {
    e.preventDefault();
    regError.textContent = '';

    const fullName = regFullName.value.trim();
    const username = regUsername.value.trim();
    const password = regPassword.value;
    const confirmPassword = regConfirmPassword.value;

    // Client-side validations matching business rules
    if (!fullName || !username || !password || !confirmPassword) {
        regError.textContent = 'All fields are required.';
        return;
    }

    if (username.length < 4) {
        regError.textContent = 'Username must be at least 4 characters.';
        return;
    }

    if (password.length < 8) {
        regError.textContent = 'Password must be at least 8 characters long.';
        return;
    }

    if (!/[A-Z]/.test(password)) {
        regError.textContent = 'Password must contain at least one uppercase letter.';
        return;
    }

    if (!/[a-z]/.test(password)) {
        regError.textContent = 'Password must contain at least one lowercase letter.';
        return;
    }

    if (!/[0-9]/.test(password)) {
        regError.textContent = 'Password must contain at least one digit.';
        return;
    }

    if (!/[^A-Za-z0-9]/.test(password)) {
        regError.textContent = 'Password must contain at least one special character.';
        return;
    }

    if (password !== confirmPassword) {
        regError.textContent = 'Passwords do not match.';
        return;
    }

    regSubmitBtn.disabled = true;
    regSubmitBtn.innerHTML = '<span class="spinner"></span> Creating Account...';

    try {
        const res = await api.post('/api/auth/register', {
            full_name: fullName,
            username,
            password,
            confirm_password: confirmPassword,
        });

        const studentId = res.student_id;

        // Show prominent modal with generated Student ID
        showModal({
            title: 'Registration Successful!',
            message: `Welcome, ${fullName}! Your unique Student ID is:\n\n${studentId}\n\nPlease keep this ID safe. You can log in using either this Student ID or your username.`,
            confirmText: 'Go to Sign In',
            confirmClass: 'btn-success',
            onConfirm: () => {
                // Clear registration form and switch to login
                registerForm.reset();
                strengthFill.className = 'strength-fill';
                strengthText.textContent = '';
                switchTab('login');
                loginIdentifier.value = studentId;
                loginPassword.focus();
            },
        });
    } catch (err) {
        regError.textContent = err.message || 'Registration failed.';
        showToast(regError.textContent, 'error');
    } finally {
        regSubmitBtn.disabled = false;
        regSubmitBtn.textContent = 'Create Student Account';
    }
});

// Run session check on load
checkCurrentSession();
