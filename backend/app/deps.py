"""
Campus Ballot — Dependency Injection
FastAPI dependencies for authentication and role-based access control.

SECURITY-CRITICAL:
- Every protected route MUST use either ``require_admin`` or ``require_student``.
- The JWT token is read from an HttpOnly cookie, never from a header.
- 401 clears the cookie to force re-login on the client side.
"""

from fastapi import Cookie, HTTPException, Request, Response

from .database import get_connection
from .security import decode_access_token


def _get_token(request: Request) -> str | None:
    """Extract the session token from the HttpOnly cookie."""
    return request.cookies.get("session_token")


def get_current_user(request: Request) -> dict:
    """
    Decode the JWT and return a dict with ``id``, ``role``, ``username``,
    and optionally ``full_name``, ``student_id``, ``must_change_password``.
    Raises 401 if the token is missing, expired, or the user no longer exists.
    """
    token = _get_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Not authenticated.")

    payload = decode_access_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Session expired or invalid.")

    role = payload.get("role")
    user_id = payload.get("sub")

    conn = get_connection()
    try:
        if role == "admin":
            row = conn.execute(
                "SELECT id, username, must_change_password FROM admins WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="User no longer exists.")
            return {
                "id": row["id"],
                "role": "admin",
                "username": row["username"],
                "must_change_password": bool(row["must_change_password"]),
            }
        elif role == "student":
            row = conn.execute(
                "SELECT id, student_id, username, full_name FROM students WHERE id = ?",
                (user_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=401, detail="User no longer exists.")
            return {
                "id": row["id"],
                "role": "student",
                "username": row["username"],
                "full_name": row["full_name"],
                "student_id": row["student_id"],
            }
        else:
            raise HTTPException(status_code=401, detail="Invalid role.")
    finally:
        conn.close()


def require_admin(request: Request) -> dict:
    """Dependency: the request MUST come from an admin."""
    user = get_current_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admin access required.")
    return user


def require_student(request: Request) -> dict:
    """Dependency: the request MUST come from a student."""
    user = get_current_user(request)
    if user["role"] != "student":
        raise HTTPException(status_code=403, detail="Student access required.")
    return user
