"""
Campus Ballot — Voting Service
Atomic one-vote-per-student save with all safety checks.

SECURITY-CRITICAL:
- Uses BEGIN IMMEDIATE to acquire a write lock before reads.
- Re-reads the election inside the transaction for consistency.
- Catches UNIQUE constraint violation as a second safety net.
- Audit entry is written AFTER the commit so a logging failure
  never makes a recorded vote look failed.
"""

import logging
import sqlite3
from datetime import datetime
from zoneinfo import ZoneInfo

from ..config import settings
from ..database import DATE_FORMAT, get_connection
from ..services.elections import get_election_state, STATE_OPEN

logger = logging.getLogger("campus_ballot")


class VoteError(Exception):
    """Raised when a vote cannot be cast.  ``code`` is a machine-readable tag."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def save_vote(election_id: int, student_id: int, candidate_id: int) -> None:
    """
    Atomically record a vote.

    Raises ``VoteError`` with one of these codes on failure:
    NOT_STARTED, CLOSED, ALREADY_VOTED, INVALID_CANDIDATE, RESULTS_DECLARED
    """
    tz = ZoneInfo(settings.APP_TIMEZONE)
    now_str = datetime.now(tz).strftime(DATE_FORMAT)

    conn = get_connection()
    try:
        # BEGIN IMMEDIATE: acquire the write lock up front so all reads
        # inside this transaction see a consistent snapshot.
        conn.execute("BEGIN IMMEDIATE")

        # 1. Re-read the election inside the transaction.
        election = conn.execute(
            "SELECT id, start_time, end_time, status, results_declared "
            "FROM elections WHERE id = ?",
            (election_id,),
        ).fetchone()

        if not election:
            conn.rollback()
            raise VoteError("Election not found.", "CLOSED")

        # 2. Results already declared?
        if election["results_declared"]:
            conn.rollback()
            raise VoteError("Results have already been declared for this election.", "RESULTS_DECLARED")

        # 3. Check computed state.
        state = get_election_state(
            election["start_time"], election["end_time"], election["status"]
        )
        if state == "NOT_STARTED":
            conn.rollback()
            raise VoteError("Voting has not started yet.", "NOT_STARTED")
        if state != STATE_OPEN:
            conn.rollback()
            raise VoteError("Voting is closed.", "CLOSED")

        # 4. Has this student already voted in this election?
        existing = conn.execute(
            "SELECT id FROM votes WHERE election_id = ? AND student_id = ?",
            (election_id, student_id),
        ).fetchone()
        if existing:
            conn.rollback()
            raise VoteError("You have already voted in this election.", "ALREADY_VOTED")

        # 5. Does the candidate belong to this election?
        candidate = conn.execute(
            "SELECT id FROM candidates WHERE id = ? AND election_id = ?",
            (candidate_id, election_id),
        ).fetchone()
        if not candidate:
            conn.rollback()
            raise VoteError("Invalid candidate for this election.", "INVALID_CANDIDATE")

        # 6. INSERT the vote.
        try:
            conn.execute(
                "INSERT INTO votes (election_id, student_id, candidate_id, voted_at) "
                "VALUES (?, ?, ?, ?)",
                (election_id, student_id, candidate_id, now_str),
            )
        except sqlite3.IntegrityError:
            # UNIQUE(election_id, student_id) — second safety net.
            conn.rollback()
            raise VoteError("You have already voted in this election.", "ALREADY_VOTED")

        # 7. COMMIT — the vote is now durable.
        conn.commit()

    except VoteError:
        raise  # re-raise business errors
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # 8. Audit AFTER the commit.
    # PRIVACY: we log that a vote was cast but NEVER which candidate.
    from ..services.audit import write_audit

    write_audit(
        action="vote_cast",
        actor_type="student",
        actor_id=str(student_id),
        details=f"Voted in election {election_id}",
    )
