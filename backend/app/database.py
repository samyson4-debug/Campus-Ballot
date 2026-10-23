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
from .security import hash_password, verify_password

logger = logging.getLogger("campus_ballot")

DATE_FORMAT = "%Y-%m-%d %H:%M"


def _now_str() -> str:
    """Current timestamp in the app timezone, formatted as ``DATE_FORMAT``."""
    tz = ZoneInfo(settings.APP_TIMEZONE)
    return datetime.now(tz).strftime(DATE_FORMAT)


def is_postgres() -> bool:
    """Return True if DATABASE_URL is set for PostgreSQL."""
    return bool(settings.DATABASE_URL)


def get_connection():
    """
    Open a database connection.
    - If settings.DATABASE_URL is set, connects to PostgreSQL (Render Postgres, Supabase, etc.).
    - Otherwise, opens a SQLite connection with WAL mode and foreign keys enabled.
    """
    if is_postgres():
        from .postgres_adapter import PostgresConnectionWrapper, PSYCOPG2_AVAILABLE
        if not PSYCOPG2_AVAILABLE:
            raise RuntimeError(
                "psycopg2-binary is required for PostgreSQL. Run: pip install psycopg2-binary"
            )
        import psycopg2
        raw_conn = psycopg2.connect(settings.DATABASE_URL)
        return PostgresConnectionWrapper(raw_conn)

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
    department    TEXT,
    post          TEXT
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
    post          TEXT    NOT NULL DEFAULT '',
    voted_at      TEXT,
    UNIQUE(election_id, student_id, post)
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


def _migrate(conn) -> None:
    """
    Idempotent migration:
    - add results_declared to elections if older schema.
    - add post to candidates if older schema.
    - migrate votes table to support per-post voting with UNIQUE(election_id, student_id, post).
    - backfill candidate posts if missing.
    """
    if is_postgres():
        return

    # 1. results_declared on elections
    cursor = conn.execute("PRAGMA table_info(elections)")
    columns = {row["name"] for row in cursor.fetchall()}
    if "results_declared" not in columns:
        conn.execute(
            "ALTER TABLE elections ADD COLUMN results_declared INTEGER DEFAULT 0"
        )
        logger.info("Migration: added results_declared column to elections.")

    # 2. post on candidates
    cursor = conn.execute("PRAGMA table_info(candidates)")
    c_columns = {row["name"] for row in cursor.fetchall()}
    if "post" not in c_columns:
        conn.execute("ALTER TABLE candidates ADD COLUMN post TEXT")
        logger.info("Migration: added post column to candidates.")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_candidates_election_post ON candidates(election_id, post)")

    # 3. votes table migration for per-post voting
    cursor = conn.execute("PRAGMA table_info(votes)")
    v_columns = {row["name"] for row in cursor.fetchall()}
    if "post" not in v_columns:
        conn.execute("PRAGMA foreign_keys=OFF")
        conn.execute("""
            CREATE TABLE IF NOT EXISTS votes_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                election_id   INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
                student_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
                candidate_id  INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
                post          TEXT    NOT NULL DEFAULT '',
                voted_at      TEXT,
                UNIQUE(election_id, student_id, post)
            )
        """)
        conn.execute("""
            INSERT INTO votes_new (id, election_id, student_id, candidate_id, post, voted_at)
            SELECT v.id, v.election_id, v.student_id, v.candidate_id, COALESCE(c.post, ''), v.voted_at
            FROM votes v
            LEFT JOIN candidates c ON v.candidate_id = c.id
        """)
        conn.execute("DROP TABLE votes")
        conn.execute("ALTER TABLE votes_new RENAME TO votes")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_votes_election ON votes(election_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_votes_student ON votes(student_id)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_votes_election_post ON votes(election_id, post)")
        conn.execute("PRAGMA foreign_keys=ON")
        logger.info("Migration: migrated votes table to support per-post voting.")
    else:
        conn.execute("CREATE INDEX IF NOT EXISTS idx_votes_election_post ON votes(election_id, post)")

    # 4. Backfill default posts for candidates if empty
    post_defaults = {
        "Alex Rivera": "President",
        "Jordan Lee": "President",
        "Samantha Chen": "Vice President",
        "Rahul Patel": "Vice President",
        "Marcus Johnson": "Secretary",
        "Elena Gomez": "Secretary",
        "Priya Sharma": "Class Representative",
        "Liam Davies": "Class Representative",
        "Aisha Khan": "Cultural Secretary",
        "Lucas Martin": "Sports Secretary",
    }
    for name, default_post in post_defaults.items():
        conn.execute(
            "UPDATE candidates SET post = ? WHERE name = ? AND (post IS NULL OR post = '')",
            (default_post, name),
        )
    conn.execute(
        "UPDATE candidates SET post = 'President' WHERE post IS NULL OR post = ''"
    )

    # 5. For existing seeded election 1, add counterpart candidates if not present so each post has options
    row_e1 = conn.execute("SELECT id FROM elections WHERE id = 1").fetchone()
    if row_e1:
        e1_cands = {r["name"] for r in conn.execute("SELECT name FROM candidates WHERE election_id = 1").fetchall()}
        needed = [
            ("Jordan Lee", "Mechanical Engineering", "President"),
            ("Rahul Patel", "Civil Engineering", "Vice President"),
            ("Elena Gomez", "Information Technology", "Secretary"),
        ]
        for name, dept, post in needed:
            if name not in e1_cands:
                conn.execute(
                    "INSERT INTO candidates (election_id, name, department, post) VALUES (1, ?, ?, ?)",
                    (name, dept, post),
                )
    # Sync vote post from candidate if vote post is empty
    conn.execute("""
        UPDATE votes
        SET post = (SELECT COALESCE(c.post, '') FROM candidates c WHERE c.id = votes.candidate_id)
        WHERE post = '' OR post IS NULL
    """)
    conn.commit()


def _bootstrap_admin(conn: sqlite3.Connection) -> None:
    """
    Create the default admin on first startup.
    Ensures that if the initial admin has must_change_password=1 and an unverified
    random password, it is synchronized with settings.ADMIN_PASSWORD so administrators
    can always log in.
    """
    row = conn.execute(
        "SELECT id, password, must_change_password FROM admins WHERE username = ?",
        (settings.ADMIN_USERNAME,),
    ).fetchone()

    if row:
        # If the admin hasn't customized their password yet (must_change_password == 1),
        # ensure it matches settings.ADMIN_PASSWORD.
        if row["must_change_password"] == 1 and settings.ADMIN_PASSWORD:
            if not verify_password(settings.ADMIN_PASSWORD, row["password"]):
                hashed = hash_password(settings.ADMIN_PASSWORD)
                conn.execute(
                    "UPDATE admins SET password = ? WHERE id = ?",
                    (hashed, row["id"]),
                )
                conn.commit()
                logger.info("Synchronized initial password for admin '%s'.", settings.ADMIN_USERNAME)
        return

    password = settings.ADMIN_PASSWORD or "Admin@Campus2026!"
    hashed = hash_password(password)
    conn.execute(
        "INSERT INTO admins (username, password, must_change_password) VALUES (?, ?, 1)",
        (settings.ADMIN_USERNAME, hashed),
    )
    conn.commit()
    logger.info("Default admin '%s' initialized with configured password.", settings.ADMIN_USERNAME)


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
        ("Alex Rivera", "Computer Science", "President"),
        ("Jordan Lee", "Mechanical Engineering", "President"),
        ("Samantha Chen", "Electrical Engineering", "Vice President"),
        ("Rahul Patel", "Civil Engineering", "Vice President"),
        ("Marcus Johnson", "Business Administration", "Secretary"),
        ("Elena Gomez", "Information Technology", "Secretary"),
    ]
    for name, dept, post in sample_candidates_1:
        conn.execute(
            "INSERT INTO candidates (election_id, name, department, post) VALUES (?, ?, ?, ?)",
            (eid_1, name, dept, post),
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
        ("Priya Sharma", "Information Technology", "Class Representative"),
        ("Liam Davies", "Mechanical Engineering", "Class Representative"),
        ("Aisha Khan", "Computer Science", "Cultural Secretary"),
        ("Lucas Martin", "Physical Education", "Sports Secretary"),
    ]
    for name, dept, post in sample_candidates_2:
        conn.execute(
            "INSERT INTO candidates (election_id, name, department, post) VALUES (?, ?, ?, ?)",
            (eid_2, name, dept, post),
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


def _seed_default_students(conn: sqlite3.Connection) -> None:
    """
    Seed a default student account 'student' if it doesn't already exist.
    """
    row = conn.execute("SELECT id FROM students WHERE username = 'student'").fetchone()
    if row:
        return

    tz = ZoneInfo(settings.APP_TIMEZONE)
    now = datetime.now(tz)
    now_str = now.strftime(DATE_FORMAT)
    hashed = hash_password("Student@2026!")

    prefix = f"STU{now.year}"
    last = conn.execute(
        "SELECT student_id FROM students WHERE student_id LIKE ? ORDER BY student_id DESC LIMIT 1",
        (f"{prefix}%",),
    ).fetchone()
    serial = (int(last["student_id"][len(prefix):]) + 1) if last else 1
    sid = f"{prefix}{serial:04d}"

    conn.execute(
        "INSERT INTO students (student_id, username, full_name, password, created_at) "
        "VALUES (?, 'student', 'Demo Student', ?, ?)",
        (sid, hashed, now_str),
    )
    conn.commit()
    logger.info("Default student 'student' (%s) seeded successfully.", sid)


def create_database() -> None:
    """
    Ensure the database file and all tables exist, run migrations,
    bootstrap default admin, and seed initial elections and demo student.
    """
    if is_postgres():
        from .postgres_adapter import POSTGRES_SCHEMA_SQL
        conn = get_connection()
        try:
            conn.execute(POSTGRES_SCHEMA_SQL)
            conn.commit()
            _bootstrap_admin(conn)
            _seed_default_students(conn)
            _seed_default_elections(conn)
            conn.commit()
        finally:
            conn.close()
        logger.info("PostgreSQL database initialized successfully via DATABASE_URL.")
        return

    # Ensure parent directory exists.
    db_dir = os.path.dirname(settings.DATABASE_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = get_connection()
    try:
        conn.executescript(_SCHEMA_SQL)
        _migrate(conn)
        _bootstrap_admin(conn)
        _seed_default_students(conn)
        _seed_default_elections(conn)
    finally:
        conn.close()

    logger.info("Database ready at %s", settings.DATABASE_PATH)
