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
from ..services.voting import VoteError, save_vote, save_votes

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

            # Candidates for this election with post
            candidates = conn.execute(
                "SELECT id, name, department, post FROM candidates WHERE election_id = ? ORDER BY post, name",
                (r["id"],),
            ).fetchall()

            # Student votes in this election
            voted_rows = conn.execute(
                "SELECT candidate_id, post FROM votes WHERE election_id = ? AND student_id = ?",
                (r["id"], user["id"]),
            ).fetchall()
            voted_posts = [v["post"] for v in voted_rows]
            cand_posts = {(c["post"] or "").strip() for c in candidates if (c["post"] or "").strip()}
            fully_voted = bool(cand_posts and cand_posts.issubset(set(voted_posts)))
            has_voted = bool(voted_rows)

            # Compute badge.
            if r["results_declared"]:
                badge = "Results Available"
            elif fully_voted:
                badge = "Vote Submitted"
            elif state == "OPEN":
                badge = "Voting Open"
            elif state == "NOT_STARTED":
                badge = "Upcoming"
            else:
                badge = "Closed"

            elections.append({
                "id": r["id"],
                "name": r["name"],
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "status": r["status"],
                "results_declared": bool(r["results_declared"]),
                "state": state,
                "badge": badge,
                "has_voted": has_voted,
                "fully_voted": fully_voted,
                "voted_posts": voted_posts,
                "candidates": [dict(c) for c in candidates],
                "candidate_count": len(candidates),
            })
        history_rows = conn.execute(
            "SELECT v.id, v.voted_at, v.post, e.name AS election_name, c.name AS candidate_name "
            "FROM votes v "
            "JOIN elections e ON v.election_id = e.id "
            "LEFT JOIN candidates c ON v.candidate_id = c.id "
            "WHERE v.student_id = ? ORDER BY v.id DESC LIMIT 10",
            (user["id"],),
        ).fetchall()
        participation_history = [dict(h) for h in history_rows]
        open_elections_count = sum(1 for e in elections if e["badge"] == "Voting Open")
    finally:
        conn.close()

    return {
        "full_name": user.get("full_name", ""),
        "student_id": user.get("student_id", ""),
        "total_elections": total_elections,
        "open_elections_count": open_elections_count,
        "active_elections": open_elections_count,
        "applications_count": apps_count,
        "my_applications_count": apps_count,
        "votes_cast": votes_cast,
        "my_votes_count": votes_cast,
        "registered_votes": votes_cast,
        "approved_applications": approved,
        "approved_candidacies_count": approved,
        "approved_candidates": approved,
        "elections": elections,
        "participation_history": participation_history,
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
# Candidates for an election (returns both dict with metadata and candidates list)
# ---------------------------------------------------------------------------
@router.get("/elections/{election_id}/candidates")
def get_candidates(election_id: int, user: dict = Depends(require_student)):
    conn = get_connection()
    try:
        election = conn.execute(
            "SELECT id, name, start_time, end_time, status, results_declared FROM elections WHERE id = ?",
            (election_id,),
        ).fetchone()
        if not election:
            raise HTTPException(status_code=404, detail="Election not found.")

        rows = conn.execute(
            "SELECT id, name, department, post FROM candidates WHERE election_id = ? ORDER BY post, name",
            (election_id,),
        ).fetchall()
        candidates = [dict(r) for r in rows]

        # Voted posts for this student in this election
        voted_rows = conn.execute(
            "SELECT candidate_id, post FROM votes WHERE election_id = ? AND student_id = ?",
            (election_id, user["id"]),
        ).fetchall()
        voted_posts = [r["post"] for r in voted_rows]
        voted_cids = [r["candidate_id"] for r in voted_rows]
        posts = list(dict.fromkeys([(c.get("post") or "").strip() for c in candidates if (c.get("post") or "").strip()]))
    finally:
        conn.close()

    return {
        "election_id": election["id"],
        "election_name": election["name"],
        "start_time": election["start_time"],
        "end_time": election["end_time"],
        "status": election["status"],
        "candidates": candidates,
        "posts": posts,
        "voted_posts": voted_posts,
        "voted_candidate_ids": voted_cids,
    }


# ---------------------------------------------------------------------------
# Declared Results for Student View
# ---------------------------------------------------------------------------
@router.get("/results/{election_id}")
def get_student_results(election_id: int, user: dict = Depends(require_student)):
    conn = get_connection()
    try:
        election = conn.execute(
            "SELECT id, name, results_declared FROM elections WHERE id = ?",
            (election_id,),
        ).fetchone()
        if not election:
            raise HTTPException(status_code=404, detail="Election not found.")
        if not election["results_declared"]:
            raise HTTPException(status_code=400, detail="Results have not been declared yet.")

        rows = conn.execute(
            "SELECT c.id AS candidate_id, c.name AS candidate_name, c.department, c.post, "
            "COUNT(v.id) AS vote_count "
            "FROM candidates c "
            "LEFT JOIN votes v ON c.id = v.candidate_id AND v.election_id = c.election_id "
            "WHERE c.election_id = ? "
            "GROUP BY c.id "
            "ORDER BY c.post, vote_count DESC",
            (election_id,),
        ).fetchall()

        results = [dict(r) for r in rows]
        total_votes = sum(r["vote_count"] for r in results)
        winner = results[0] if (results and results[0]["vote_count"] > 0) else None

        # Calculate winners per post
        post_winners = {}
        for r in results:
            p = r.get("post") or "General"
            if p not in post_winners and r["vote_count"] > 0:
                post_winners[p] = r
    finally:
        conn.close()

    return {
        "election_name": election["name"],
        "total_votes": total_votes,
        "winner": winner,
        "post_winners": post_winners,
        "results": results,
    }


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
        if body.candidate_ids:
            posts_voted = save_votes(election_id, user["id"], body.candidate_ids)
        else:
            posts_voted = save_vote(election_id, user["id"], body.candidate_id)
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
    return {
        "message": "Your vote has been recorded successfully.",
        "posts_voted": posts_voted,
    }


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
