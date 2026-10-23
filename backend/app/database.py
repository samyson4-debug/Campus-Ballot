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


def _migrate_postgres(conn) -> None:
    """
    Idempotent migration for PostgreSQL (Render, Supabase, Neon):
    - add results_declared to elections if missing
    - add post to candidates if missing
    - add post to candidate_applications if missing
    - add post to votes if missing (DEFAULT '')
    - drop obsolete UNIQUE(election_id, student_id) constraint on votes
    - add UNIQUE(election_id, student_id, post) constraint on votes
    - drop obsolete UNIQUE(election_id, student_id) on candidate_applications
    - add UNIQUE(election_id, student_id, post) on candidate_applications
    - backfill candidate posts
    - backfill votes posts
    - insert counterpart candidates for election 1
    - add performance indexes
    """
    logger.info("Running PostgreSQL migrations...")

    # 1. Add missing columns safely
    column_migrations = [
        "ALTER TABLE elections ADD COLUMN IF NOT EXISTS results_declared INTEGER DEFAULT 0",
        "ALTER TABLE candidates ADD COLUMN IF NOT EXISTS post TEXT",
        "ALTER TABLE candidate_applications ADD COLUMN IF NOT EXISTS post TEXT",
        "ALTER TABLE votes ADD COLUMN IF NOT EXISTS post TEXT NOT NULL DEFAULT ''",
    ]
    for sql in column_migrations:
        try:
            conn.execute(sql)
            conn.commit()
            logger.info("Postgres migration executed: %s", sql)
        except Exception as e:
            conn.rollback()
            logger.warning("Postgres column migration note (%s): %s", sql, e)

    # 2. Migrate votes unique constraint to support per-post voting
    try:
        cons = conn.execute("""
            SELECT con.conname, pg_get_constraintdef(con.oid) AS condef
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE rel.relname = 'votes' AND con.contype = 'u'
        """).fetchall()

        has_post_unique = False
        for c in cons:
            conname = c["conname"]
            condef = (c["condef"] or "").lower()
            if "election_id" in condef and "student_id" in condef:
                if "post" in condef:
                    has_post_unique = True
                else:
                    logger.info("Dropping obsolete unique constraint '%s' from votes", conname)
                    conn.execute(f'ALTER TABLE votes DROP CONSTRAINT IF EXISTS "{conname}"')
                    conn.commit()

        if not has_post_unique:
            try:
                conn.execute(
                    "ALTER TABLE votes ADD CONSTRAINT votes_election_student_post_key UNIQUE(election_id, student_id, post)"
                )
                conn.commit()
                logger.info("Added UNIQUE(election_id, student_id, post) constraint to votes.")
            except Exception as e:
                conn.rollback()
                logger.warning("Could not add votes_election_student_post_key: %s", e)
    except Exception as e:
        conn.rollback()
        logger.warning("Votes constraint migration inspection error: %s", e)

    # 3. Migrate candidate_applications unique constraint to support per-post nomination
    try:
        app_cons = conn.execute("""
            SELECT con.conname, pg_get_constraintdef(con.oid) AS condef
            FROM pg_constraint con
            JOIN pg_class rel ON rel.oid = con.conrelid
            JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
            WHERE rel.relname = 'candidate_applications' AND con.contype = 'u'
        """).fetchall()

        has_app_post_unique = False
        for c in app_cons:
            conname = c["conname"]
            condef = (c["condef"] or "").lower()
            if "election_id" in condef and "student_id" in condef:
                if "post" in condef:
                    has_app_post_unique = True
                else:
                    logger.info("Dropping obsolete unique constraint '%s' from candidate_applications", conname)
                    conn.execute(f'ALTER TABLE candidate_applications DROP CONSTRAINT IF EXISTS "{conname}"')
                    conn.commit()

        if not has_app_post_unique:
            try:
                conn.execute(
                    "ALTER TABLE candidate_applications ADD CONSTRAINT cand_apps_election_student_post_key UNIQUE(election_id, student_id, post)"
                )
                conn.commit()
                logger.info("Added UNIQUE(election_id, student_id, post) constraint to candidate_applications.")
            except Exception as e:
                conn.rollback()
                logger.warning("Could not add cand_apps_election_student_post_key: %s", e)
    except Exception as e:
        conn.rollback()
        logger.warning("Candidate applications constraint migration inspection error: %s", e)

    # 4. Performance indexes
    index_migrations = [
        "CREATE INDEX IF NOT EXISTS idx_votes_election ON votes(election_id)",
        "CREATE INDEX IF NOT EXISTS idx_votes_student ON votes(student_id)",
        "CREATE INDEX IF NOT EXISTS idx_votes_election_post ON votes(election_id, post)",
        "CREATE INDEX IF NOT EXISTS idx_candidates_election ON candidates(election_id)",
        "CREATE INDEX IF NOT EXISTS idx_candidates_election_post ON candidates(election_id, post)",
        "CREATE INDEX IF NOT EXISTS idx_applications_election_status ON candidate_applications(election_id, status)",
    ]
    for sql in index_migrations:
        try:
            conn.execute(sql)
            conn.commit()
        except Exception as e:
            conn.rollback()
            logger.warning("Postgres index migration note (%s): %s", sql, e)

    # 5. Sync candidate posts from approved candidate applications & defaults
    _sync_candidate_posts_from_applications(conn)

    logger.info("PostgreSQL migrations completed successfully.")


def _sync_candidate_posts_from_applications(conn) -> None:
    """
    Sync candidate positions from approved candidate_applications.
    Ensures candidates nominated by students (e.g. Dancing committe nominees)
    reflect the actual post they applied for (President, Vice President, Secretary, etc.),
    rather than a generic default, and syncs votes.post to match.
    """
    try:
        approved_apps = conn.execute("""
            SELECT ca.id, ca.election_id, ca.post, ca.department, s.full_name
            FROM candidate_applications ca
            JOIN students s ON ca.student_id = s.id
            WHERE ca.status = 'Approved' AND ca.post IS NOT NULL AND ca.post != ''
            ORDER BY ca.id ASC
        """).fetchall()

        apps_by_cand = {}
        for app in approved_apps:
            key = (app["election_id"], app["full_name"])
            if key not in apps_by_cand:
                apps_by_cand[key] = []
            apps_by_cand[key].append(app)

        for (eid, name), app_list in apps_by_cand.items():
            cands = conn.execute(
                "SELECT id, post, department FROM candidates WHERE election_id = ? AND name = ? ORDER BY id ASC",
                (eid, name),
            ).fetchall()

            for i, app in enumerate(app_list):
                if i < len(cands):
                    conn.execute(
                        "UPDATE candidates SET post = ?, department = COALESCE(?, department) WHERE id = ?",
                        (app["post"], app["department"], cands[i]["id"]),
                    )
                else:
                    conn.execute(
                        "INSERT INTO candidates (election_id, name, department, post) VALUES (?, ?, ?, ?)",
                        (eid, name, app["department"], app["post"]),
                    )

        # Sync known sample candidate posts
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
                "UPDATE candidates SET post = ? WHERE name = ? AND (post IS NULL OR post = '' OR post = 'General')",
                (default_post, name),
            )

        # Any candidate remaining with empty or null post gets a sensible default
        conn.execute(
            "UPDATE candidates SET post = 'President' WHERE post IS NULL OR post = ''"
        )

        # Counterpart candidates for election 1 (Student Council General Elections 2026)
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

        # Sync votes.post from candidates table
        conn.execute("""
            UPDATE votes
            SET post = (SELECT COALESCE(c.post, '') FROM candidates c WHERE c.id = votes.candidate_id)
            WHERE candidate_id IS NOT NULL
        """)

        conn.commit()
        logger.info("Candidate posts successfully synchronized from applications and defaults.")
    except Exception as e:
        conn.rollback()
        logger.warning("Candidate post synchronization note: %s", e)


def _migrate(conn) -> None:
    """
    Idempotent migration:
    - add results_declared to elections if older schema.
    - add post to candidates if older schema.
    - migrate votes table to support per-post voting with UNIQUE(election_id, student_id, post).
    - backfill candidate posts if missing.
    """
    if is_postgres():
        _migrate_postgres(conn)
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

    # 4. Sync candidate posts from approved candidate applications & defaults
    _sync_candidate_posts_from_applications(conn)


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
            _migrate_postgres(conn)
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
