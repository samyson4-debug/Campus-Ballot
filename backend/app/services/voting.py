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

try:
    import psycopg2
    PG_INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg2.IntegrityError)
except ImportError:
    PG_INTEGRITY_ERRORS = (sqlite3.IntegrityError,)



class VoteError(Exception):
    """Raised when a vote cannot be cast.  ``code`` is a machine-readable tag."""

    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def save_vote(election_id: int, student_id: int, candidate_id: int) -> list[str]:
    """
    Atomically record a vote for a single candidate.
    Maintains full backward compatibility.
    """
    return save_votes(election_id, student_id, [candidate_id])


def save_votes(election_id: int, student_id: int, candidate_ids: list[int]) -> list[str]:
    """
    Atomically record one or more votes across different posts for a student.

    Raises ``VoteError`` with one of these codes on failure:
    NOT_STARTED, CLOSED, ALREADY_VOTED, INVALID_CANDIDATE, RESULTS_DECLARED
    """
    if not candidate_ids:
        raise VoteError("No candidates selected to vote for.", "INVALID_CANDIDATE")

    # Remove duplicates if any
    unique_candidate_ids = list(dict.fromkeys(candidate_ids))

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

        # 4. Fetch and validate each candidate belongs to this election
        placeholders = ",".join("?" for _ in unique_candidate_ids)
        rows = conn.execute(
            f"SELECT id, name, department, post FROM candidates "
            f"WHERE election_id = ? AND id IN ({placeholders})",
            [election_id] + unique_candidate_ids,
        ).fetchall()

        cand_map = {r["id"]: dict(r) for r in rows}
        for cid in unique_candidate_ids:
            if cid not in cand_map:
                conn.rollback()
                raise VoteError(f"Invalid candidate #{cid} for this election.", "INVALID_CANDIDATE")

        # 5. Check duplicate posts in current submission batch
        seen_posts = set()
        posts_to_vote = []
        for cid in unique_candidate_ids:
            c = cand_map[cid]
            raw_post = c.get("post")
            post = (raw_post or "").strip()
            if post in seen_posts:
                post_label = f"the post of {post}" if post else "this election"
                conn.rollback()
                raise VoteError(f"Cannot cast multiple votes for {post_label} at the same time.", "ALREADY_VOTED")
            seen_posts.add(post)
            posts_to_vote.append((cid, post))

        # 6. Check if student already voted for ANY of these posts
        for cid, post in posts_to_vote:
            if post:
                existing = conn.execute(
                    "SELECT id FROM votes WHERE election_id = ? AND student_id = ? AND post = ?",
                    (election_id, student_id, post),
                ).fetchone()
            else:
                existing = conn.execute(
                    "SELECT id FROM votes WHERE election_id = ? AND student_id = ? AND (post = '' OR post IS NULL)",
                    (election_id, student_id),
                ).fetchone()

            if existing:
                conn.rollback()
                post_label = f" for the post of {post}" if post else ""
                raise VoteError(f"You have already voted{post_label} in this election.", "ALREADY_VOTED")

        # 7. INSERT the votes
        for cid, post in posts_to_vote:
            try:
                conn.execute(
                    "INSERT INTO votes (election_id, student_id, candidate_id, post, voted_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (election_id, student_id, cid, post, now_str),
                )
            except PG_INTEGRITY_ERRORS:
                # UNIQUE(election_id, student_id, post) — safety net.
                conn.rollback()
                post_label = f" for the post of {post}" if post else ""
                raise VoteError(f"You have already voted{post_label} in this election.", "ALREADY_VOTED")

        # 8. COMMIT — all votes are now durable.
        conn.commit()

    except VoteError:
        raise  # re-raise business errors
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    # 9. Audit AFTER the commit.
    # PRIVACY: we log that votes were cast for the posts, NEVER which candidate.
    from ..services.audit import write_audit

    posts_desc = ", ".join(p if p else "General" for _, p in posts_to_vote)
    write_audit(
        action="vote_cast",
        actor_type="student",
        actor_id=str(student_id),
        details=f"Voted in election {election_id} for: {posts_desc}",
    )
    return [p for _, p in posts_to_vote]
