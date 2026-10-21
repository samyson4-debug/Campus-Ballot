"""
Campus Ballot — Audit Service
Append-only audit log writer. No update or delete operations ever.

PRIVACY: The audit log must NEVER contain password hashes or vote choices
(which candidate a student voted for).
"""

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import settings
from ..database import DATE_FORMAT, get_connection

logger = logging.getLogger("campus_ballot")


def write_audit(
    action: str,
    actor_type: str = "system",
    actor_id: str = "",
    details: str = "",
) -> None:
    """
    Write a single append-only audit log entry.
    This should NEVER raise — audit failures must not break business operations.
    """
    try:
        tz = ZoneInfo(settings.APP_TIMEZONE)
        now_str = datetime.now(tz).strftime(DATE_FORMAT)
        conn = get_connection()
        try:
            conn.execute(
                "INSERT INTO audit_log (action, actor_type, actor_id, details, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (action, actor_type, str(actor_id), details, now_str),
            )
            conn.commit()
        finally:
            conn.close()
    except Exception:
        # SECURITY: audit failure must never propagate and must never
        # make a successful business operation look failed.
        logger.exception("Failed to write audit log entry: action=%s", action)
