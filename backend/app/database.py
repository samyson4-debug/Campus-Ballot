"""
Campus Ballot — Database Module
SQLite connection helper, schema creation (7 tables), idempotent migration,
and default-admin bootstrap.

SECURITY-CRITICAL:
- PRAGMA foreign_keys=ON enforced on every connection.
- WAL mode for concurrent reads.
- busy_timeout to avoid immediate SQLITE_BUSY errors.
- All queries use parameterized SQL (no string interpolation).
"""

import logging
import os
import sqlite3
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .config import settings
from .security import hash_password

logger = logging.getLogger("campus_ballot")

DATE_FORMAT = "%Y-%m-%d %H:%M"


def _now_str() -> str:
    """Current timestamp in the app timezone, formatted as ``DATE_FORMAT``."""
    tz = ZoneInfo(settings.APP_TIMEZONE)
    return datetime.now(tz).strftime(DATE_FORMAT)


def get_connection() -> sqlite3.Connection:
    """
    Open a new SQLite connection with safety pragmas.
    Callers are responsible for closing it (use as a context manager).
    """
    conn = sqlite3.connect(settings.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=5000")
    return conn


# ---------------------------------------------------------------------------
# Schema DDL
# ---------------------------------------------------------------------------
_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS students (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id  TEXT    UNIQUE NOT NULL,
    username    TEXT    UNIQUE NOT NULL COLLATE NOCASE,
    full_name   TEXT    NOT NULL,
    password    TEXT    NOT NULL,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    username            TEXT    UNIQUE NOT NULL,
    password            TEXT    NOT NULL,
    must_change_password INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS elections (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    name              TEXT    NOT NULL,
    start_time        TEXT    NOT NULL,
    end_time          TEXT    NOT NULL,
    status            TEXT    DEFAULT 'OFF' CHECK(status IN ('ON','OFF')),
    results_declared  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS candidates (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    election_id   INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    department    TEXT
);

CREATE TABLE IF NOT EXISTS candidate_applications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    election_id   INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    post          TEXT,
    department    TEXT,
    manifesto     TEXT,
    status        TEXT    DEFAULT 'Pending' CHECK(status IN ('Pending','Approved','Rejected')),
    applied_at    TEXT,
    UNIQUE(election_id, student_id, post)
);

CREATE TABLE IF NOT EXISTS votes (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    election_id   INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    candidate_id  INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    voted_at      TEXT,
    UNIQUE(election_id, student_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    action      TEXT,
    actor_type  TEXT,
    actor_id    TEXT,
    details     TEXT,
    created_at  TEXT
);

-- Performance indexes
CREATE INDEX IF NOT EXISTS idx_votes_election   ON votes(election_id);
CREATE INDEX IF NOT EXISTS idx_votes_student    ON votes(student_id);
CREATE INDEX IF NOT EXISTS idx_candidates_election ON candidates(election_id);
CREATE INDEX IF NOT EXISTS idx_applications_election_status
    ON candidate_applications(election_id, status);
"""


def _migrate(conn: sqlite3.Connection) -> None:
    """
    Idempotent migration: add ``results_declared`` to elections if it was
    created by an older schema version.
    """
    cursor = conn.execute("PRAGMA table_info(elections)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "results_declared" not in columns:
        conn.execute(
            "ALTER TABLE elections ADD COLUMN results_declared INTEGER DEFAULT 0"
        )
        logger.info("Migration: added results_declared column to elections.")


def _bootstrap_admin(conn: sqlite3.Connection) -> None:
    """
    Create the default admin on first startup only.
    NEVER overwrites an existing admin on restart.
    """
    row = conn.execute(
        "SELECT id FROM admins WHERE username = ?", (settings.ADMIN_USERNAME,)
    ).fetchone()
    if row:
        logger.info("Default admin '%s' already exists — skipping.", settings.ADMIN_USERNAME)
        return

    password = settings.ADMIN_PASSWORD
    generated = False
    if not password:
        import secrets as _secrets
        password = _secrets.token_urlsafe(16)
        generated = True

    hashed = hash_password(password)
    conn.execute(
        "INSERT INTO admins (username, password, must_change_password) VALUES (?, ?, 1)",
        (settings.ADMIN_USERNAME, hashed),
    )
    conn.commit()

    if generated:
        # Print once so the deployer can see it in the logs.
        logger.warning(
            "========================================\n"
            "  DEFAULT ADMIN CREATED\n"
            "  Username : %s\n"
            "  Password : %s\n"
            "  (change immediately after first login)\n"
            "========================================",
            settings.ADMIN_USERNAME,
            password,
        )
    else:
        logger.info("Default admin '%s' created from env.", settings.ADMIN_USERNAME)


def _seed_default_elections(conn: sqlite3.Connection) -> None:
    """
    Seed initial elections if the elections table is empty,
    so that students and administrators immediately have elections available.
    """
    count = conn.execute("SELECT COUNT(*) AS c FROM elections").fetchone()["c"]
    if count > 0:
        return

    tz = ZoneInfo(settings.APP_TIMEZONE)
    now = datetime.now(tz)

    # 1. Active general election (Open for voting & nominations)
    start_1 = (now - timedelta(days=2)).strftime(DATE_FORMAT)
    end_1 = (now + timedelta(days=14)).strftime(DATE_FORMAT)
    cursor = conn.execute(
        "INSERT INTO elections (name, start_time, end_time, status, results_declared) "
        "VALUES (?, ?, ?, 'ON', 0)",
        ("Student Council General Elections 2026", start_1, end_1),
    )
    eid_1 = cursor.lastrowid

    sample_candidates_1 = [
        ("Alex Rivera", "Computer Science"),
        ("Samantha Chen", "Electrical Engineering"),
        ("Marcus Johnson", "Business Administration"),
    ]
    for name, dept in sample_candidates_1:
        conn.execute(
            "INSERT INTO candidates (election_id, name, department) VALUES (?, ?, ?)",
            (eid_1, name, dept),
        )

    # 2. Department Representative Election (Open for voting & nominations)
    start_2 = (now - timedelta(days=1)).strftime(DATE_FORMAT)
    end_2 = (now + timedelta(days=21)).strftime(DATE_FORMAT)
    cursor = conn.execute(
        "INSERT INTO elections (name, start_time, end_time, status, results_declared) "
        "VALUES (?, ?, ?, 'ON', 0)",
        ("Department Representative Election 2026", start_2, end_2),
    )
    eid_2 = cursor.lastrowid

    sample_candidates_2 = [
        ("Priya Sharma", "Information Technology"),
        ("Liam Davies", "Mechanical Engineering"),
    ]
    for name, dept in sample_candidates_2:
        conn.execute(
            "INSERT INTO candidates (election_id, name, department) VALUES (?, ?, ?)",
            (eid_2, name, dept),
        )

    # 3. Cultural & Sports Committee Elections (Upcoming)
    start_3 = (now + timedelta(days=3)).strftime(DATE_FORMAT)
    end_3 = (now + timedelta(days=25)).strftime(DATE_FORMAT)
    conn.execute(
        "INSERT INTO elections (name, start_time, end_time, status, results_declared) "
        "VALUES (?, ?, ?, 'ON', 0)",
        ("Cultural & Sports Committee Elections 2026", start_3, end_3),
    )

    conn.commit()
    logger.info("Default sample elections seeded successfully.")


def create_database() -> None:
    """
    Ensure the database file and all tables exist, run migrations,
    bootstrap default admin, and seed initial elections.
    """
    # Ensure parent directory exists.
    db_dir = os.path.dirname(settings.DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = get_connection()
    try:
        conn.executescript(_SCHEMA_SQL)
        _migrate(conn)
        _bootstrap_admin(conn)
        _seed_default_elections(conn)
    finally:
        conn.close()

    logger.info("Database ready at %s", settings.DATABASE_PATH)
