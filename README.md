# Campus Ballot — College Election Voting System (Web Edition)

[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Python](https://img.shields.io/badge/Python-3.12+-3776AB.svg?style=flat&logo=python&logoColor=white)](https://python.org)
[![SQLite](https://img.shields.io/badge/SQLite-WAL%20Mode-003B57.svg?style=flat&logo=sqlite&logoColor=white)](https://sqlite.org)
[![License](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

A complete, production-grade, secure web application designed to manage the full life cycle of collegiate elections: student registration, candidate application and administrative approval, election scheduling, atomic one-person-one-vote secret balloting, live result declaration, and tamper-evident audit logging.

---

## 1. Key Architectural Features

- **Zero-Build Vanilla Frontend**: Built entirely with standard HTML5, CSS3, and vanilla modern JavaScript (ES Modules, Fetch API). No React/Vue/Angular, no Node.js build step, and no CDN dependencies.
- **Single-Origin Deployment**: FastAPI serves both the REST API endpoints and static frontend files (with SPA fallback), eliminating CORS vulnerabilities and overhead.
- **Robust Security & Cryptography**:
  - Passwords hashed with standard library **PBKDF2-HMAC-SHA256** using a 16-byte cryptographically secure random salt and **600,000 iterations** (`salt_hex:hash_hex`). Constant-time comparison via `secrets.compare_digest`.
  - Strict password complexity policy enforced on registration and updates (≥8 chars, uppercase, lowercase, digit, special character).
  - Signed JWT session tokens stored in `HttpOnly`, `SameSite=Lax` cookies (`Secure` flag on HTTPS).
  - Defense-in-depth HTTP security headers (`Content-Security-Policy`, `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`, `Referrer-Policy`).
  - Parameterized SQL queries everywhere to prevent SQL injection.
  - In-memory rate limiting against brute-force login attacks (5 failed attempts per 10 minutes per IP+identifier).
  - XSS prevention via safe DOM property assignment (`textContent`) and HTML entity escaping.
- **Atomic One-Student-One-Vote Engine**:
  - Ballots are committed within a `BEGIN IMMEDIATE` SQLite transaction verifying live `OPEN` election status, non-voted status, and candidate eligibility.
  - An explicit SQLite `UNIQUE(election_id, student_id)` constraint provides an impenetrable hardware-level safety net against concurrent double-voting.
- **Voter Privacy**: Audit logs and student-facing endpoints never record or expose which candidate a student selected. Participation history records *that* a student voted, never *whom* they voted for.

---

## 2. System Architecture & Tech Stack

```
campus-ballot/
├── backend/
│   ├── app/
│   │   ├── main.py            # FastAPI startup, middleware, router mounts, SPA fallback
│   │   ├── config.py          # Environment settings with Pydantic
│   │   ├── database.py        # SQLite connection helper, schema creation, migrations, default admin
│   │   ├── security.py        # PBKDF2 hashing, policy enforcement, PyJWT session handling
│   │   ├── deps.py            # Auth dependencies (get_current_user, require_admin, require_student)
│   │   ├── schemas.py         # Pydantic v2 request/response models
│   │   ├── services/
│   │   │   ├── elections.py   # State machine (OPEN, CLOSED, NOT_STARTED), status changes, results
│   │   │   ├── voting.py      # Atomic vote persistence (save_vote)
│   │   │   └── audit.py       # Append-only audit trail logging
│   │   └── routers/
│   │       ├── auth.py        # Login, student registration, logout, session check
│   │       ├── admin.py       # Dashboard, election lifecycle, nominations, CSV, backup
│   │       ├── student.py     # Voter dashboard, ballots, candidate applications, profile
│   │       └── public.py      # Health check (/api/health)
│   ├── tests/
│   │   └── test_core.py       # Pytest suite with 29 comprehensive verification tests
│   └── requirements.txt
├── frontend/
│   ├── index.html             # Login & student registration with interactive canvas
│   ├── admin.html             # Admin Control Center SPA shell
│   ├── student.html           # Student Voting Portal SPA shell
│   ├── css/
│   │   ├── base.css           # CSS reset, typography, and utility classes
│   │   ├── theme.css          # Dark-mode color tokens & CSS custom properties
│   │   └── components.css     # Buttons, modals, cards, badges, tables, bars, toasts
│   └── js/
│       ├── api.js             # Fetch wrapper with same-origin credentials & 401 handling
│       ├── ui.js              # Toasts, confirmation modals, badges, empty states
│       ├── login-canvas.js    # 60fps particle constellation canvas animation
│       ├── auth.js            # Login/Register tab switching, strength meter, validation
│       ├── admin.js           # Admin SPA logic, 2s auto-refresh polling, results chart
│       └── student.js         # Student voting SPA logic, nomination form, ballot flow
├── Dockerfile                 # Non-root container with healthcheck and persistent volume
├── .dockerignore              # Clean build context definition
├── render.yaml                # Render Blueprint deployment definition with disk
├── .env.example               # Configuration template
├── .gitignore
└── README.md
```

---

## 3. SQLite Database Schema

The database uses SQLite WAL (Write-Ahead Logging) mode with `foreign_keys=ON` and a busy timeout. Seven core tables are initialized automatically on startup:

1. **`students`**: `id`, `student_id` (e.g. `STU20260001` UNIQUE), `username` (COLLATE NOCASE UNIQUE), `full_name`, `password`, `created_at`.
2. **`admins`**: `id`, `username` (UNIQUE), `password`, `must_change_password` (INTEGER DEFAULT 1).
3. **`elections`**: `id`, `name`, `start_time`, `end_time`, `status` (ON/OFF), `results_declared` (0/1).
4. **`candidates`**: `id`, `election_id` (FK CASCADE), `name`, `department`.
5. **`candidate_applications`**: `id`, `election_id` (FK CASCADE), `student_id` (FK CASCADE), `post`, `department`, `manifesto`, `status` (Pending/Approved/Rejected), `applied_at`, `UNIQUE(election_id, student_id, post)`.
6. **`votes`**: `id`, `election_id` (FK CASCADE), `student_id` (FK CASCADE), `candidate_id` (FK CASCADE), `voted_at`, **`UNIQUE(election_id, student_id)`**.
7. **`audit_log`**: `id`, `action`, `actor_type`, `actor_id`, `details`, `created_at` (Append-only).

---

## 4. Local Development Quickstart

### Prerequisites
- Python 3.12+ (or 3.10+)
- Git

### Step 1: Clone and Set Up Environment
```bash
git clone <repo-url> campus-ballot
cd campus-ballot

# Copy environment configuration
cp .env.example .env
```

### Step 2: Install Dependencies
```bash
# Create a virtual environment
python -m venv .venv

# Activate virtual environment
# Windows:
.venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

# Install dependencies
pip install -r backend/requirements.txt
```

### Step 3: Run the Application Locally
Run the server from the `backend` folder:
```bash
cd backend
uvicorn app.main:app --reload --host 0.0.0.0 --port 10000
```
Open your browser and navigate to:
**http://localhost:10000**

- **Default Administrator Credentials**:
  - Username: `admin`
  - Password: `Admin@Campus2026!` (or the value configured in your `.env`)
  - *On first login, you will be prompted to change the default password.*

### Step 4: Run Tests
Run the comprehensive verification test suite:
```bash
cd backend
python -m pytest tests -v
```
All 29 security, database, and business logic tests should pass cleanly.

---

## 5. Running with Docker

### Build the Docker Image
```bash
docker build -t campus-ballot .
```

### Run the Container
```bash
docker run -d \
  --name campus-ballot-app \
  -p 10000:10000 \
  -v campus_ballot_data:/data \
  --env-file .env \
  campus-ballot
```

Check logs and health status:
```bash
docker logs -f campus-ballot-app
```

---

## 6. Production Deployment on Render

### Method A: Deploy via Render Blueprint (`render.yaml`) — Recommended
1. Push this repository to GitHub or GitLab.
2. In the [Render Dashboard](https://dashboard.render.com), click **New +** and select **Blueprint**.
3. Connect your repository. Render will automatically parse `render.yaml`.
4. Enter the required secret values:
   - `ADMIN_PASSWORD`: A strong initial password for the admin account.
5. Click **Apply**. Render will automatically provision:
   - A Docker web service.
   - A 1 GB persistent disk mounted at `/data` ensuring SQLite data persists across redeployments.
   - An automated cryptographic `SECRET_KEY` generation.

### Method B: Manual Web Service Setup
1. In Render, select **New +** -> **Web Service**.
2. Connect your repository and select **Docker** as the runtime.
3. In **Advanced Settings**, configure:
   - **Health Check Path**: `/api/health`
   - **Environment Variables**:
     - `SECRET_KEY`: `<random-64-char-string>`
     - `ADMIN_USERNAME`: `admin`
     - `ADMIN_PASSWORD`: `<your-admin-password>`
     - `DATABASE_PATH`: `/data/campus_ballot.db`
     - `APP_TIMEZONE`: `Asia/Kolkata`
     - `COOKIE_SECURE`: `true`
     - `PORT`: `10000`
   - **Disks** (Requires Starter plan or higher):
     - Name: `campus-ballot-data`
     - Mount Path: `/data`
     - Size: `1 GB`

> [!IMPORTANT]
> **Persistent Disk Notice**: Persistent disks require a paid Render instance (Starter or higher). If deploying on Render's **Free Tier**, the filesystem is ephemeral and the database will reset when the instance spins down or redeploys.
>
> **Fallback Best Practice**: If running on the free tier, use the **💾 Database Backup** button in the Administrator Control Center (`GET /api/admin/backup`) to download a live snapshot before triggering redeployments!

---

## 7. Security Model & Business Rules Reference

| Rule | Specification |
| :--- | :--- |
| **Student ID** | Formatted as `STU<YYYY><0001>`. The 4-digit serial increments sequentially per year within a database lock. |
| **Election State** | Dynamically computed on demand via `get_election_state()`: returns `OPEN`, `NOT_STARTED`, `CLOSED` (due to time window or manual OFF switch), or `INVALID`. |
| **Switch ON/OFF** | Elections can be toggled by admins. An election with declared results can **never** be turned ON again. |
| **Declare Results** | Refused while election status is `ON` ("Stop Voting First"). Finalizes results (`results_declared = 1`). |
| **Candidate Nominations** | Students apply for a post with department and manifesto (≤2000 chars). Admins approve or reject. Approval automatically promotes the student into the official ballot candidates list. |
| **Atomic Voting** | Handled by `save_vote()` inside a `BEGIN IMMEDIATE` transaction. Checks election status, existing votes, candidate validity, inserts ballot, and commits. The `audit_log` entry is written strictly *after* commit so logging issues never invalidate cast ballots. |
| **Audit Log** | Append-only audit record of every critical operation (registration, logins, status changes, nominations, votes cast, exports, backups). |

---

## 8. Verification Checklist

- [x] Schema: 7 SQLite tables with WAL mode, foreign keys, and indexes.
- [x] Password security: 600,000 iteration PBKDF2 with 16-byte salt, constant-time compare.
- [x] Authentication: Rate-limited login (5 attempts / 10 min), HttpOnly cookies, forced password change on first admin login.
- [x] Election lifecycle: Scheduled start/end times, dynamic timezone-aware state evaluation, manual ON/OFF toggle, results declaration guard.
- [x] Candidate workflow: Nomination application with manifesto, duplicate application guard, administrative approval flow.
- [x] Atomic voting: Strict one-person-one-vote guarantee, concurrent double-vote rejection test passing.
- [x] Frontend UI: Responsive dark theme, animated particle canvas background, password strength meter, mobile navigation drawer, CSS bar chart results visualization.
- [x] Real-time updates: 2-second polling for applicants with tab visibility pausing.
- [x] Data portability: Live SQLite online backup API download and CSV nomination export.
- [x] Containerization: Non-root Dockerfile, automated healthcheck, Render Blueprint specification.
- [x] Automated Tests: 29/29 Pytest unit and integration tests passing.
#   C a m p u s - B a l l o t  
 #   C a m p u s - B a l l o t  
 #   C a m p u s - B a l l o t  
 