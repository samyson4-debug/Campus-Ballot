"""
Campus Ballot — Admin Router
All endpoints require ``require_admin`` dependency.
"""

import csv
import io
import sqlite3
import tempfile
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse, FileResponse

from ..config import settings
from ..database import DATE_FORMAT, get_connection
from ..deps import require_admin
from ..schemas import ChangePasswordRequest, ElectionCreate
from ..security import hash_password, validate_password, verify_password
from ..services.audit import write_audit
from ..services.elections import get_election_state

router = APIRouter(prefix="/api/admin", tags=["admin"])


# ---------------------------------------------------------------------------
# Dashboard
# ---------------------------------------------------------------------------
@router.get("/dashboard")
def dashboard(user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        total_elections = conn.execute("SELECT COUNT(*) AS c FROM elections").fetchone()["c"]
        active_elections = conn.execute(
            "SELECT COUNT(*) AS c FROM elections WHERE status='ON'"
        ).fetchone()["c"]
        total_candidates = conn.execute("SELECT COUNT(*) AS c FROM candidates").fetchone()["c"]
        registered_students = conn.execute("SELECT COUNT(*) AS c FROM students").fetchone()["c"]
        total_votes = conn.execute("SELECT COUNT(*) AS c FROM votes").fetchone()["c"]

        rows = conn.execute(
            "SELECT id, name, start_time, end_time, status, results_declared "
            "FROM elections ORDER BY id DESC LIMIT 5"
        ).fetchall()
        recent = []
        for r in rows:
            state = get_election_state(r["start_time"], r["end_time"], r["status"])
            recent.append({
                "id": r["id"],
                "name": r["name"],
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "status": r["status"],
                "results_declared": bool(r["results_declared"]),
                "state": state,
            })
    finally:
        conn.close()

    return {
        "total_elections": total_elections,
        "active_elections": active_elections,
        "total_candidates": total_candidates,
        "registered_students": registered_students,
        "total_votes": total_votes,
        "recent_elections": recent,
    }


# ---------------------------------------------------------------------------
# Elections CRUD
# ---------------------------------------------------------------------------
@router.get("/elections")
def list_elections(user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT id, name, start_time, end_time, status, results_declared "
            "FROM elections ORDER BY id DESC"
        ).fetchall()
        elections = []
        for r in rows:
            state = get_election_state(r["start_time"], r["end_time"], r["status"])
            elections.append({
                "id": r["id"],
                "name": r["name"],
                "start_time": r["start_time"],
                "end_time": r["end_time"],
                "status": r["status"],
                "results_declared": bool(r["results_declared"]),
                "state": state,
            })
    finally:
        conn.close()
    return elections


@router.post("/elections")
def create_election(body: ElectionCreate, user: dict = Depends(require_admin)):
    # Validate date format.
    try:
        start = datetime.strptime(body.start_time, DATE_FORMAT)
        end = datetime.strptime(body.end_time, DATE_FORMAT)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid date format. Use {DATE_FORMAT} (e.g. 2026-01-15 09:00).",
        )

    if end <= start:
        raise HTTPException(status_code=400, detail="End time must be after start time.")

    # End must be in the future.
    tz = ZoneInfo(settings.APP_TIMEZONE)
    now = datetime.now(tz)
    end_aware = end.replace(tzinfo=tz)
    if end_aware <= now:
        raise HTTPException(status_code=400, detail="End time must be in the future.")

    conn = get_connection()
    try:
        conn.execute(
            "INSERT INTO elections (name, start_time, end_time, status, results_declared) "
            "VALUES (?, ?, ?, 'OFF', 0)",
            (body.name, body.start_time, body.end_time),
        )
        conn.commit()
        election_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    finally:
        conn.close()

    write_audit(
        action="election_create",
        actor_type="admin",
        actor_id=str(user["id"]),
        details=f"Created election '{body.name}' (id={election_id})",
    )

    return {"id": election_id, "message": "Election created."}


@router.delete("/elections/{election_id}")
def delete_election(election_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        row = conn.execute("SELECT name FROM elections WHERE id = ?", (election_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Election not found.")
        conn.execute("DELETE FROM elections WHERE id = ?", (election_id,))
        conn.commit()
    finally:
        conn.close()

    write_audit(
        action="election_delete",
        actor_type="admin",
        actor_id=str(user["id"]),
        details=f"Deleted election '{row['name']}' (id={election_id})",
    )
    return {"message": "Election deleted."}


# ---------------------------------------------------------------------------
# Election ON / OFF / Declare
# ---------------------------------------------------------------------------
@router.post("/elections/{election_id}/on")
def election_on(election_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, name, results_declared FROM elections WHERE id = ?", (election_id,)
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Election not found.")
        if row["results_declared"]:
            raise HTTPException(
                status_code=400,
                detail="Cannot turn ON an election whose results have been declared.",
            )
        conn.execute("UPDATE elections SET status='ON' WHERE id = ?", (election_id,))
        conn.commit()
    finally:
        conn.close()

    write_audit(
        action="election_on",
        actor_type="admin",
        actor_id=str(user["id"]),
        details=f"Turned ON election id={election_id}",
    )
    return {"message": "Election turned ON."}


@router.post("/elections/{election_id}/off")
def election_off(election_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        row = conn.execute("SELECT id FROM elections WHERE id = ?", (election_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Election not found.")
        conn.execute("UPDATE elections SET status='OFF' WHERE id = ?", (election_id,))
        conn.commit()
    finally:
        conn.close()

    write_audit(
        action="election_off",
        actor_type="admin",
        actor_id=str(user["id"]),
        details=f"Turned OFF election id={election_id}",
    )
    return {"message": "Election turned OFF."}


@router.post("/elections/{election_id}/declare")
def declare_results(election_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, status, results_declared FROM elections WHERE id = ?",
            (election_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Election not found.")
        if row["status"] == "ON":
            raise HTTPException(status_code=400, detail="Stop Voting First")
        if row["results_declared"]:
            raise HTTPException(status_code=400, detail="Results already declared.")
        conn.execute(
            "UPDATE elections SET results_declared = 1 WHERE id = ?", (election_id,)
        )
        conn.commit()
    finally:
        conn.close()

    write_audit(
        action="election_declare",
        actor_type="admin",
        actor_id=str(user["id"]),
        details=f"Declared results for election id={election_id}",
    )
    return {"message": "Results declared."}


# ---------------------------------------------------------------------------
# Candidate Applications (admin view)
# ---------------------------------------------------------------------------
@router.get("/applications")
def list_applications(
    search: str = Query("", max_length=100),
    election_id: int | None = Query(None),
    status: str = Query("", max_length=20),
    user: dict = Depends(require_admin),
):
    conn = get_connection()
    try:
        query = (
            "SELECT ca.id, ca.election_id, ca.student_id, ca.post, ca.department, "
            "ca.manifesto, ca.status, ca.applied_at, "
            "s.full_name AS student_name, s.student_id AS student_display_id, "
            "e.name AS election_name "
            "FROM candidate_applications ca "
            "JOIN students s ON ca.student_id = s.id "
            "JOIN elections e ON ca.election_id = e.id "
            "WHERE 1=1 "
        )
        params: list = []

        if search:
            query += "AND (s.full_name LIKE ? OR s.student_id LIKE ? OR ca.post LIKE ?) "
            like = f"%{search}%"
            params.extend([like, like, like])
        if election_id is not None:
            query += "AND ca.election_id = ? "
            params.append(election_id)
        if status:
            query += "AND ca.status = ? "
            params.append(status)

        query += "ORDER BY ca.id DESC"
        rows = conn.execute(query, params).fetchall()
        apps = [dict(r) for r in rows]
    finally:
        conn.close()
    return apps


@router.post("/applications/{app_id}/approve")
def approve_application(app_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        conn.execute("BEGIN IMMEDIATE")
        app_row = conn.execute(
            "SELECT ca.id, ca.election_id, ca.student_id, ca.post, ca.department, ca.status, "
            "s.full_name "
            "FROM candidate_applications ca "
            "JOIN students s ON ca.student_id = s.id "
            "WHERE ca.id = ?",
            (app_id,),
        ).fetchone()

        if not app_row:
            conn.rollback()
            raise HTTPException(status_code=404, detail="Application not found.")
        if app_row["status"] != "Pending":
            conn.rollback()
            raise HTTPException(
                status_code=400, detail=f"Application already {app_row['status'].lower()}."
            )

        # Update application status.
        conn.execute(
            "UPDATE candidate_applications SET status = 'Approved' WHERE id = ?",
            (app_id,),
        )
        # Insert into candidates table.
        conn.execute(
            "INSERT INTO candidates (election_id, name, department) VALUES (?, ?, ?)",
            (app_row["election_id"], app_row["full_name"], app_row["department"]),
        )
        conn.commit()
    except HTTPException:
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    write_audit(
        action="application_approve",
        actor_type="admin",
        actor_id=str(user["id"]),
        details=f"Approved application id={app_id}, student={app_row['full_name']}",
    )
    return {"message": "Application approved."}


@router.post("/applications/{app_id}/reject")
def reject_application(app_id: int, user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        app_row = conn.execute(
            "SELECT id, status FROM candidate_applications WHERE id = ?", (app_id,)
        ).fetchone()
        if not app_row:
            raise HTTPException(status_code=404, detail="Application not found.")
        if app_row["status"] != "Pending":
            raise HTTPException(
                status_code=400, detail=f"Application already {app_row['status'].lower()}."
            )
        conn.execute(
            "UPDATE candidate_applications SET status = 'Rejected' WHERE id = ?",
            (app_id,),
        )
        conn.commit()
    finally:
        conn.close()

    write_audit(
        action="application_reject",
        actor_type="admin",
        actor_id=str(user["id"]),
        details=f"Rejected application id={app_id}",
    )
    return {"message": "Application rejected."}


# ---------------------------------------------------------------------------
# CSV Export
# ---------------------------------------------------------------------------
@router.get("/applications/export.csv")
def export_applications_csv(user: dict = Depends(require_admin)):
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT ca.id, e.name AS election_name, s.student_id AS student_display_id, "
            "s.full_name AS student_name, ca.post, ca.department, ca.status, ca.applied_at "
            "FROM candidate_applications ca "
            "JOIN students s ON ca.student_id = s.id "
            "JOIN elections e ON ca.election_id = e.id "
            "ORDER BY ca.id DESC"
        ).fetchall()
    finally:
        conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Election", "Student ID", "Student Name", "Post", "Department", "Status", "Applied At"])
    for r in rows:
        writer.writerow([r["id"], r["election_name"], r["student_display_id"],
                         r["student_name"], r["post"], r["department"], r["status"], r["applied_at"]])

    write_audit(
        action="csv_export",
        actor_type="admin",
        actor_id=str(user["id"]),
        details="Exported applications CSV",
    )

    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=applications.csv"},
    )


# ---------------------------------------------------------------------------
# Results
# ---------------------------------------------------------------------------
@router.get("/results/{election_id}")
def get_results(election_id: int, user: dict = Depends(require_admin)):
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

        # LEFT JOIN so candidates with zero votes still appear.
        rows = conn.execute(
            "SELECT c.id AS candidate_id, c.name AS candidate_name, c.department, "
            "COUNT(v.id) AS vote_count "
            "FROM candidates c "
            "LEFT JOIN votes v ON c.id = v.candidate_id AND v.election_id = c.election_id "
            "WHERE c.election_id = ? "
            "GROUP BY c.id "
            "ORDER BY vote_count DESC",
            (election_id,),
        ).fetchall()

        results = [dict(r) for r in rows]
    finally:
        conn.close()

    return {"election_name": election["name"], "results": results}


# ---------------------------------------------------------------------------
# Audit Log
# ---------------------------------------------------------------------------
@router.get("/audit-log")
def get_audit_log(
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: dict = Depends(require_admin),
):
    conn = get_connection()
    try:
        total = conn.execute("SELECT COUNT(*) AS c FROM audit_log").fetchone()["c"]
        rows = conn.execute(
            "SELECT id, action, actor_type, actor_id, details, created_at "
            "FROM audit_log ORDER BY id DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
        entries = [dict(r) for r in rows]
    finally:
        conn.close()
    return {"total": total, "entries": entries}


# ---------------------------------------------------------------------------
# Backup (SQLite online backup API)
# ---------------------------------------------------------------------------
@router.get("/backup")
def backup_database(user: dict = Depends(require_admin)):
    """
    Create a consistent snapshot of the database using the sqlite3 online
    backup API and return it as a downloadable file.
    """
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp_path = tmp.name
    tmp.close()

    source_conn = sqlite3.connect(settings.DATABASE_PATH)
    dest_conn = sqlite3.connect(tmp_path)
    try:
        source_conn.backup(dest_conn)
    finally:
        source_conn.close()
        dest_conn.close()

    write_audit(
        action="backup",
        actor_type="admin",
        actor_id=str(user["id"]),
        details="Database backup downloaded",
    )

    return FileResponse(
        tmp_path,
        media_type="application/octet-stream",
        filename="campus_ballot_backup.db",
    )


# ---------------------------------------------------------------------------
# Change Password (admin)
# ---------------------------------------------------------------------------
@router.post("/change-password")
def change_password(body: ChangePasswordRequest, user: dict = Depends(require_admin)):
    if body.new_password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")

    errors = validate_password(body.new_password)
    if errors:
        raise HTTPException(status_code=400, detail=errors[0])

    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT password FROM admins WHERE id = ?", (user["id"],)
        ).fetchone()
        if not row or not verify_password(body.current_password, row["password"]):
            raise HTTPException(status_code=400, detail="Current password is incorrect.")

        hashed = hash_password(body.new_password)
        conn.execute(
            "UPDATE admins SET password = ?, must_change_password = 0 WHERE id = ?",
            (hashed, user["id"]),
        )
        conn.commit()
    finally:
        conn.close()

    write_audit(
        action="admin_password_change",
        actor_type="admin",
        actor_id=str(user["id"]),
        details="Admin changed password",
    )
    return {"message": "Password changed successfully."}
