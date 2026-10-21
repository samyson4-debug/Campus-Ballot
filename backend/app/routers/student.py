"""
Campus Ballot — Student Router
All endpoints require ``require_student`` dependency.
"""

from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException

from ..config import settings
from ..database import DATE_FORMAT, get_connection
from ..deps import require_student
from ..schemas import CandidateApplicationRequest, VoteRequest
from ..services.audit import write_audit
from ..services.elections import get_election_state
from ..services.voting import VoteError, save_vote

router = APIRouter(prefix="/api/student", tags=["student"])


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@router.get("/dashboard")
def student_dashboard(user: dict = Depends(require_student)):
    conn = get_connection()
    try:
        # Personal stats.
        total_elections = conn.execute("SELECT COUNT(*) AS c FROM elections").fetchone()["c"]
        apps_count = conn.execute(
            "SELECT COUNT(*) AS c FROM candidate_applications WHERE student_id = ?",
            (user["id"],),
        ).fetchone()["c"]
        votes_cast = conn.execute(
            "SELECT COUNT(*) AS c FROM votes WHERE student_id = ?", (user["id"],)
        ).fetchone()["c"]
        approved = conn.execute(
            "SELECT COUNT(*) AS c FROM candidate_applications WHERE student_id = ? AND status='Approved'",
            (user["id"],),
        ).fetchone()["c"]

        # Elections with badge and candidate info.
        rows = conn.execute(
            "SELECT id, name, start_time, end_time, status, results_declared "
            "FROM elections ORDER BY id DESC"
        ).fetchall()

        elections = []
        for r in rows:
            state = get_election_state(r["start_time"], r["end_time"], r["status"])

            # Has this student voted?
            voted = conn.execute(
                "SELECT id FROM votes WHERE election_id = ? AND student_id = ?",
                (r["id"], user["id"]),
            ).fetchone()

            # Compute badge.
            if voted:
                badge = "Vote Submitted"
            elif r["results_declared"]:
                badge = "Results Available"
            elif state == "OPEN":
                badge = "Voting Open"
            elif state == "NOT_STARTED":
                badge = "Upcoming"
            else:
                badge = "Closed"

            # Candidates for this election.
            candidates = conn.execute(
                "SELECT id, name, department FROM candidates WHERE election_id = ?",
                (r["id"],),
            ).fetchall()

            elections.append({
                "id": r["id"],
                "name": r["name"],
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "status": r["status"],
                "results_declared": bool(r["results_declared"]),
                "state": state,
                "badge": badge,
                "has_voted": bool(voted),
                "candidates": [dict(c) for c in candidates],
            })
        open_elections_count = sum(1 for e in elections if e["badge"] == "Voting Open")
    finally:
        conn.close()

    return {
        "full_name": user.get("full_name", ""),
        "student_id": user.get("student_id", ""),
        "total_elections": total_elections,
        "open_elections_count": open_elections_count,
        "applications_count": apps_count,
        "my_applications_count": apps_count,
        "votes_cast": votes_cast,
        "my_votes_count": votes_cast,
        "approved_applications": approved,
        "approved_candidacies_count": approved,
        "elections": elections,
    }


# ---------------------------------------------------------------------------
# All available elections for student
# ---------------------------------------------------------------------------
@router.get("/elections")
def get_student_elections(user: dict = Depends(require_student)):
    """Return all elections with their live status and badges."""
    dash = student_dashboard(user)
    return dash["elections"]


# ---------------------------------------------------------------------------
# Candidates for an election
# ---------------------------------------------------------------------------
@router.get("/elections/{election_id}/candidates")
def get_candidates(election_id: int, user: dict = Depends(require_student)):
    conn = get_connection()
    try:
        election = conn.execute(
            "SELECT id FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        if not election:
            raise HTTPException(status_code=404, detail="Election not found.")

        rows = conn.execute(
            "SELECT id, name, department FROM candidates WHERE election_id = ?",
            (election_id,),
        ).fetchall()
        candidates = [dict(r) for r in rows]
    finally:
        conn.close()
    return candidates


# ---------------------------------------------------------------------------
# Candidate Application
# ---------------------------------------------------------------------------
@router.post("/applications")
def submit_application(
    body: CandidateApplicationRequest, user: dict = Depends(require_student)
):
    conn = get_connection()
    try:
        # Validate election exists.
        election = conn.execute(
            "SELECT id FROM elections WHERE id = ?", (body.election_id,)
        ).fetchone()
        if not election:
            raise HTTPException(status_code=404, detail="Election not found.")

        tz = ZoneInfo(settings.APP_TIMEZONE)
        now_str = datetime.now(tz).strftime(DATE_FORMAT)

        conn.execute("BEGIN IMMEDIATE")
        try:
            conn.execute(
                "INSERT INTO candidate_applications "
                "(election_id, student_id, post, department, manifesto, status, applied_at) "
                "VALUES (?, ?, ?, ?, ?, 'Pending', ?)",
                (body.election_id, user["id"], body.post, body.department,
                 body.manifesto, now_str),
            )
            conn.commit()
        except Exception as e:
            conn.rollback()
            if "UNIQUE constraint" in str(e):
                raise HTTPException(
                    status_code=409, detail="Already applied for this post in this election."
                )
            raise
    finally:
        conn.close()

    write_audit(
        action="application_submit",
        actor_type="student",
        actor_id=str(user["id"]),
        details=f"Applied for {body.post} in election {body.election_id}",
    )
    return {"message": "Application submitted successfully."}


@router.get("/applications")
def my_applications(user: dict = Depends(require_student)):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT ca.id, ca.election_id, ca.post, ca.department, ca.manifesto, "
            "ca.status, ca.applied_at, e.name AS election_name "
            "FROM candidate_applications ca "
            "JOIN elections e ON ca.election_id = e.id "
            "WHERE ca.student_id = ? "
            "ORDER BY ca.id DESC",
            (user["id"],),
        ).fetchall()
        apps = [dict(r) for r in rows]
    finally:
        conn.close()
    return apps


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------
@router.post("/elections/{election_id}/vote")
def cast_vote(
    election_id: int, body: VoteRequest, user: dict = Depends(require_student)
):
    try:
        save_vote(election_id, user["id"], body.candidate_id)
    except VoteError as e:
        code_to_status = {
            "NOT_STARTED": 400,
            "CLOSED": 400,
            "ALREADY_VOTED": 409,
            "INVALID_CANDIDATE": 400,
            "RESULTS_DECLARED": 400,
        }
        raise HTTPException(
            status_code=code_to_status.get(e.code, 400), detail=str(e)
        )
    return {"message": "Your vote has been recorded successfully."}


# ---------------------------------------------------------------------------
# Profile
# ---------------------------------------------------------------------------
@router.get("/profile")
def profile(user: dict = Depends(require_student)):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, student_id, username, full_name, created_at FROM students WHERE id = ?",
            (user["id"],),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Student not found.")
    finally:
        conn.close()

    return {
        "id": row["id"],
        "student_id": row["student_id"],
        "username": row["username"],
        "full_name": row["full_name"],
        "created_at": row["created_at"],
    }


# ---------------------------------------------------------------------------
# Voting History
# PRIVACY: shows when/where a student voted, NEVER whom.
# ---------------------------------------------------------------------------
@router.get("/history")
def voting_history(user: dict = Depends(require_student)):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT v.id, v.election_id, e.name AS election_name, v.voted_at "
            "FROM votes v "
            "JOIN elections e ON v.election_id = e.id "
            "WHERE v.student_id = ? "
            "ORDER BY v.id DESC",
            (user["id"],),
        ).fetchall()
        history = [dict(r) for r in rows]
    finally:
        conn.close()
    return history
