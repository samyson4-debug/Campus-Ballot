"""
Campus Ballot — PostgreSQL Database Adapter
Enables seamless connection to Render PostgreSQL, Supabase, Neon, or any hosted Postgres.
Translates SQLite parameterized queries and provides an interface compatible with sqlite3.
"""

import re
import logging

try:
    import psycopg2
    import psycopg2.extras
    PSYCOPG2_AVAILABLE = True
except ImportError:
    PSYCOPG2_AVAILABLE = False

logger = logging.getLogger("campus_ballot")


class PostgresRowWrapper(dict):
    """Row wrapper that supports dictionary access by column name and index."""
    def __init__(self, d):
        super().__init__(d)
        self._keys = list(d.keys())
        self._values = list(d.values())

    def __getitem__(self, item):
        if isinstance(item, int):
            return self._values[item]
        return super().__getitem__(item)


class PostgresCursorWrapper:
    def __init__(self, raw_cursor, conn):
        self._raw_cursor = raw_cursor
        self._conn = conn

    def fetchone(self):
        row = self._raw_cursor.fetchone()
        if row is None:
            return None
        return PostgresRowWrapper(row)

    def fetchall(self):
        rows = self._raw_cursor.fetchall()
        return [PostgresRowWrapper(r) for r in rows]

    @property
    def lastrowid(self):
        try:
            cur = self._conn.cursor()
            cur.execute("SELECT lastval()")
            res = cur.fetchone()
            cur.close()
            return res[0] if res else None
        except Exception:
            return None

    def __iter__(self):
        for r in self._raw_cursor:
            yield PostgresRowWrapper(r)


def translate_sql_for_postgres(sql: str) -> str:
    """Translate SQLite-specific syntax into PostgreSQL syntax."""
    # 1. Handle last_insert_rowid()
    if "last_insert_rowid()" in sql.lower():
        return "SELECT lastval() AS id"

    # 2. Handle BEGIN IMMEDIATE (PostgreSQL transactions are managed automatically)
    if sql.strip().upper() == "BEGIN IMMEDIATE":
        return "SELECT 1"

    # 3. Handle COLLATE NOCASE -> remove keyword (case handling managed via NOCASE/LOWER)
    sql = re.sub(r'\s+COLLATE\s+NOCASE', '', sql, flags=re.IGNORECASE)

    # 4. Handle ? parameter markers -> %s for psycopg2
    sql = sql.replace("?", "%s")

    return sql


class PostgresConnectionWrapper:
    """Connection wrapper mimicking sqlite3.Connection."""
    def __init__(self, raw_conn):
        self._raw_conn = raw_conn

    def execute(self, sql: str, params=None):
        cur = self._raw_conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        trans_sql = translate_sql_for_postgres(sql)
        if params is not None:
            cur.execute(trans_sql, tuple(params))
        else:
            cur.execute(trans_sql)
        return PostgresCursorWrapper(cur, self._raw_conn)

    def commit(self):
        self._raw_conn.commit()

    def rollback(self):
        self._raw_conn.rollback()

    def close(self):
        self._raw_conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type:
            self.rollback()
        else:
            self.commit()
        self.close()


POSTGRES_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS students (
    id          SERIAL PRIMARY KEY,
    student_id  TEXT    UNIQUE NOT NULL,
    username    TEXT    UNIQUE NOT NULL,
    full_name   TEXT    NOT NULL,
    password    TEXT    NOT NULL,
    created_at  TEXT
);

CREATE TABLE IF NOT EXISTS admins (
    id                  SERIAL PRIMARY KEY,
    username            TEXT    UNIQUE NOT NULL,
    password            TEXT    NOT NULL,
    must_change_password INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS elections (
    id                SERIAL PRIMARY KEY,
    name              TEXT    NOT NULL,
    start_time        TEXT    NOT NULL,
    end_time          TEXT    NOT NULL,
    status            TEXT    DEFAULT 'OFF' CHECK(status IN ('ON','OFF')),
    results_declared  INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS candidates (
    id            SERIAL PRIMARY KEY,
    election_id   INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    name          TEXT    NOT NULL,
    department    TEXT
);

CREATE TABLE IF NOT EXISTS candidate_applications (
    id            SERIAL PRIMARY KEY,
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
    id            SERIAL PRIMARY KEY,
    election_id   INTEGER NOT NULL REFERENCES elections(id) ON DELETE CASCADE,
    student_id    INTEGER NOT NULL REFERENCES students(id) ON DELETE CASCADE,
    candidate_id  INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    voted_at      TEXT,
    UNIQUE(election_id, student_id)
);

CREATE TABLE IF NOT EXISTS audit_log (
    id          SERIAL PRIMARY KEY,
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
