#!/usr/bin/env python3
"""
Campus Ballot — Database Management & Diagnostics CLI
100% Free of Cost | Zero-Dependency SQLite Tool

Usage:
    python db_cli.py test       # Check connection health and database file status
    python db_cli.py tables     # List all tables and record counts
    python db_cli.py logins     # View all logged login and authentication events
    python db_cli.py events     # View recent audit events (votes, elections, nominations)
    python db_cli.py backup     # Create an instant live snapshot backup of the database
"""

import os
import sys
import sqlite3
from datetime import datetime
from pathlib import Path

# Add backend directory to sys.path
backend_dir = Path(__file__).resolve().parent / "backend"
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.config import settings
from app.database import get_connection, create_database


def format_size(bytes_val: int) -> str:
    """Format bytes into readable units."""
    for unit in ["B", "KB", "MB", "GB"]:
        if bytes_val < 1024:
            return f"{bytes_val:.1f} {unit}"
        bytes_val /= 1024
    return f"{bytes_val:.1f} TB"


def cmd_test():
    """Verify database connection and integrity."""
    print("=" * 60)
    print("  CAMPUS BALLOT — DATABASE CONNECTION TEST")
    print("=" * 60)

    from app.database import is_postgres

    if is_postgres():
        print("Engine:          PostgreSQL (Render Postgres / Hosted DB)")
        import re
        masked_url = re.sub(r':([^@]+)@', ':****@', settings.DATABASE_URL)
        print(f"Connection URL:  {masked_url}")
        try:
            conn = get_connection()
            ver = conn.execute("SELECT version()").fetchone()[0]
            db_name = conn.execute("SELECT current_database()").fetchone()[0]
            conn.close()
            print(f"Database Name:   {db_name}")
            print(f"Server Version:  {ver.split(',')[0]}")
            print("\n[SUCCESS] PostgreSQL database connection is HEALTHY and active!")
        except Exception as e:
            print(f"\n[ERROR] PostgreSQL connection failed: {e}")
            sys.exit(1)
        return

    db_path = Path(settings.DATABASE_PATH).resolve()
    print("Engine:          SQLite (Built-in Local DB)")
    print(f"Target Database: {db_path}")
    print(f"File Exists:     {db_path.exists()}")

    if db_path.exists():
        size = db_path.stat().st_size
        print(f"Database Size:   {format_size(size)}")

    try:
        conn = get_connection()
        wal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        fk_status = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        sqlite_version = conn.execute("SELECT sqlite_version()").fetchone()[0]
        conn.close()

        print(f"SQLite Version:  {sqlite_version}")
        print(f"Journal Mode:    {wal_mode.upper()} (High-concurrency WAL)")
        print(f"Foreign Keys:    {'ENABLED' if fk_status else 'DISABLED'}")
        print("\n[SUCCESS] Database connection is HEALTHY and active!")
        print("Cost:            $0.00 (100% free built-in local database)")
    except Exception as e:
        print(f"\n[ERROR] Connection failed: {e}")
        sys.exit(1)


def cmd_tables():
    """List all database tables and current row counts."""
    cmd_test()
    print("\n" + "=" * 60)
    print("  TABLE INVENTORY & RECORD COUNTS")
    print("=" * 60)

    tables = [
        ("students", "Registered student voter accounts"),
        ("admins", "System administrator credentials"),
        ("elections", "Scheduled campus elections"),
        ("candidates", "Approved official candidates on ballots"),
        ("candidate_applications", "Student nomination applications"),
        ("votes", "Cast secret ballots (one-per-student)"),
        ("audit_log", "Immutable security & audit event trail"),
    ]

    conn = get_connection()
    try:
        for tbl, desc in tables:
            try:
                count = conn.execute(f"SELECT COUNT(*) AS c FROM {tbl}").fetchone()["c"]
                print(f" * {tbl:<24} {count:>5} records  ({desc})")
            except Exception:
                print(f" * {tbl:<24} [NOT FOUND]")
    finally:
        conn.close()


def cmd_logins(limit: int = 20):
    """View saved login and authentication events."""
    print("=" * 60)
    print("  SAVED LOGIN & AUTHENTICATION EVENTS")
    print("=" * 60)

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, action, actor_type, actor_id, details, created_at
            FROM audit_log
            WHERE action LIKE '%login%' OR action = 'register' OR action = 'logout'
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

        if not rows:
            print("No login events recorded yet. Log in via web interface to record.")
            return

        for r in rows:
            symbol = "[OK]  " if "success" in r["action"] or r["action"] == "register" else "[FAIL]" if "failure" in r["action"] else "[INFO]"
            print(f"[{r['created_at']}] {symbol} {r['action'].upper():<14} | User: {r['actor_id']:<14} ({r['actor_type']}) | {r['details']}")
    finally:
        conn.close()


def cmd_events(limit: int = 25):
    """View recent election lifecycle events."""
    print("=" * 60)
    print("  ALL AUDIT & LIFECYCLE EVENTS (FREE & PERMANENT)")
    print("=" * 60)

    conn = get_connection()
    try:
        rows = conn.execute(
            """
            SELECT id, action, actor_type, actor_id, details, created_at
            FROM audit_log
            ORDER BY id DESC LIMIT ?
            """,
            (limit,),
        ).fetchall()

        if not rows:
            print("No audit events recorded yet.")
            return

        for r in rows:
            print(f"#{r['id']:<4} | {r['created_at']} | {r['action']:<18} | Actor: {r['actor_id']:<10} ({r['actor_type']:<7}) | {r['details']}")
    finally:
        conn.close()


def cmd_backup():
    """Create a live snapshot backup using SQLite Online Backup API."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = Path(f"campus_ballot_backup_{timestamp}.db").resolve()

    print(f"Creating live database backup to: {backup_file.name} ...")
    source = sqlite3.connect(settings.DATABASE_PATH)
    dest = sqlite3.connect(str(backup_file))
    try:
        source.backup(dest)
        print(f"[SUCCESS] Live backup completed! File size: {format_size(backup_file.stat().st_size)}")
    finally:
        source.close()
        dest.close()


def main():
    if len(sys.argv) < 2:
        cmd_test()
        print("\nAvailable commands:")
        print("  python db_cli.py test     — Test connection & health")
        print("  python db_cli.py tables   — Show tables & counts")
        print("  python db_cli.py logins   — View login events")
        print("  python db_cli.py events   — View all election events")
        print("  python db_cli.py backup   — Create snapshot backup")
        return

    cmd = sys.argv[1].lower()
    if cmd == "test":
        cmd_test()
    elif cmd == "tables":
        cmd_tables()
    elif cmd == "logins":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 20
        cmd_logins(limit)
    elif cmd == "events":
        limit = int(sys.argv[2]) if len(sys.argv) > 2 else 25
        cmd_events(limit)
    elif cmd == "backup":
        cmd_backup()
    else:
        print(f"Unknown command: {cmd}")
        print("Usage: python db_cli.py [test|tables|logins|events|backup]")


if __name__ == "__main__":
    main()
