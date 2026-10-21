"""
Campus Ballot — Auth Router
POST /api/auth/register, /login, /logout, GET /me

SECURITY:
- Login checks admins first, then students (by Student ID OR username).
- Error messages are intentionally generic to prevent user enumeration.
- In-memory rate limiting: 5 failed attempts per 10 min per (IP + identifier).
"""

import time
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request, Response, Depends

from ..config import settings
from ..database import DATE_FORMAT, get_connection
from ..deps import get_current_user
from ..schemas import LoginRequest, RegisterRequest, ChangePasswordRequest
from ..security import (
    create_access_token,
    hash_password,
    validate_password,
    verify_password,
)
from ..services.audit import write_audit

router = APIRouter(prefix="/api/auth", tags=["auth"])

# ---------------------------------------------------------------------------
# In-memory rate limiter (single-worker process, so this is safe)
# ---------------------------------------------------------------------------
_rate_lock = threading.Lock()
_failed_attempts: dict[str, list[float]] = {}  # key → list of timestamps
RATE_LIMIT_MAX = 5
RATE_LIMIT_WINDOW = 600  # 10 minutes


def _check_rate_limit(key: str) -> None:
    """Raise 429 if the key has exceeded RATE_LIMIT_MAX failures in the window."""
    now = time.time()
    with _rate_lock:
        attempts = _failed_attempts.get(key, [])
        # Prune old entries.
        attempts = [t for t in attempts if now - t < RATE_LIMIT_WINDOW]
        _failed_attempts[key] = attempts
        if len(attempts) >= RATE_LIMIT_MAX:
            raise HTTPException(
                status_code=429,
                detail="Too many failed login attempts. Please try again later.",
            )


def _record_failure(key: str) -> None:
    with _rate_lock:
        _failed_attempts.setdefault(key, []).append(time.time())


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------
@router.post("/register")
def register(body: RegisterRequest):
    """Register a new student. Returns the generated Student ID."""
    # Validate password policy.
    errors = validate_password(body.password)
    if errors:
        raise HTTPException(status_code=400, detail=errors[0])

    if body.password != body.confirm_password:
        raise HTTPException(status_code=400, detail="Passwords do not match.")

    if len(body.username) < 4:
        raise HTTPException(
            status_code=400, detail="Username must be at least 4 characters."
        )

    hashed = hash_password(body.password)
    tz = ZoneInfo(settings.APP_TIMEZONE)
    now = datetime.now(tz)
    now_str = now.strftime(DATE_FORMAT)
    year = now.year

    conn = get_connection()
    try:
        # Check username uniqueness (case-insensitive via COLLATE NOCASE).
        existing = conn.execute(
            "SELECT id FROM students WHERE username = ?", (body.username,)
        ).fetchone()
        if existing:
            raise HTTPException(status_code=409, detail="Username already exists.")

        # Generate Student ID: STU<year><4-digit serial> inside a transaction.
        conn.execute("BEGIN IMMEDIATE")
        prefix = f"STU{year}"
        row = conn.execute(
            "SELECT student_id FROM students WHERE student_id LIKE ? ORDER BY student_id DESC LIMIT 1",
            (f"{prefix}%",),
        ).fetchone()

        if row:
            last_serial = int(row["student_id"][len(prefix):])
            serial = last_serial + 1
        else:
            serial = 1

        student_id = f"{prefix}{serial:04d}"

        conn.execute(
            "INSERT INTO students (student_id, username, full_name, password, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (student_id, body.username, body.full_name, hashed, now_str),
        )
        conn.commit()
    except HTTPException:
        conn.rollback()
        raise
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    write_audit(
        action="register",
        actor_type="student",
        actor_id=student_id,
        details=f"Student registered: {body.username}",
    )

    return {"student_id": student_id, "message": f"Registration successful! Your Student ID is {student_id}"}


# ---------------------------------------------------------------------------
# Login (unified: admin + student)
# ---------------------------------------------------------------------------
@router.post("/login")
def login(body: LoginRequest, request: Request, response: Response):
    """
    Unified login for admins and students.
    Checks admins table first, then students (by Student ID or username).
    """
    identifier = body.identifier.strip()
    password = body.password

    if not identifier or not password:
        raise HTTPException(
            status_code=400,
            detail="Please enter your ID/Username and password.",
        )

    # Rate limiting key: IP + lowered identifier.
    client_ip = request.client.host if request.client else "unknown"
    rate_key = f"{client_ip}:{identifier.lower()}"
    _check_rate_limit(rate_key)

    conn = get_connection()
    try:
        # --- Try admins first ---
        admin = conn.execute(
            "SELECT id, username, password, must_change_password FROM admins WHERE username = ?",
            (identifier,),
        ).fetchone()

        if admin:
            if verify_password(password, admin["password"]):
                token = create_access_token(
                    subject=admin["id"],
                    role="admin",
                    extra={"username": admin["username"]},
                )
                _set_cookie(response, token)
                write_audit(
                    action="login_success",
                    actor_type="admin",
                    actor_id=str(admin["id"]),
                    details=f"Admin login: {admin['username']}",
                )
                return {
                    "role": "admin",
                    "username": admin["username"],
                    "must_change_password": bool(admin["must_change_password"]),
                }
            else:
                _record_failure(rate_key)
                write_audit(
                    action="login_failure",
                    actor_type="admin",
                    actor_id=identifier,
                    details="Wrong password",
                )
                raise HTTPException(
                    status_code=401,
                    detail="Invalid ID/Username or password.",
                )

        # --- Try students (by student_id or username, case-insensitive) ---
        student = conn.execute(
            "SELECT id, student_id, username, full_name, password FROM students "
            "WHERE student_id = ? OR username = ? COLLATE NOCASE",
            (identifier, identifier),
        ).fetchone()

        if student:
            if verify_password(password, student["password"]):
                token = create_access_token(
                    subject=student["id"],
                    role="student",
                    extra={
                        "username": student["username"],
                        "student_id": student["student_id"],
                    },
                )
                _set_cookie(response, token)
                write_audit(
                    action="login_success",
                    actor_type="student",
                    actor_id=str(student["id"]),
                    details=f"Student login: {student['username']}",
                )
                return {
                    "role": "student",
                    "username": student["username"],
                    "student_id": student["student_id"],
                    "full_name": student["full_name"],
                }
            else:
                _record_failure(rate_key)
                write_audit(
                    action="login_failure",
                    actor_type="student",
                    actor_id=identifier,
                    details="Wrong password",
                )
                raise HTTPException(
                    status_code=401,
                    detail="Invalid ID/Username or password.",
                )

        # No user found — same generic message.
        _record_failure(rate_key)
        write_audit(
            action="login_failure",
            actor_type="unknown",
            actor_id=identifier,
            details="User not found",
        )
        raise HTTPException(
            status_code=401,
            detail="Invalid ID/Username or password.",
        )
    finally:
        conn.close()


def _set_cookie(response: Response, token: str) -> None:
    """Set the session JWT in an HttpOnly, SameSite=Lax cookie."""
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=settings.COOKIE_SECURE,
        max_age=settings.SESSION_HOURS * 3600,
        path="/",
    )


# ---------------------------------------------------------------------------
# Logout
# ---------------------------------------------------------------------------
@router.post("/logout")
def logout(request: Request, response: Response):
    """Clear the session cookie and record logout event."""
    token = request.cookies.get("session_token")
    if token:
        try:
            from ..security import decode_access_token
            payload = decode_access_token(token)
            write_audit(
                action="logout",
                actor_type=payload.get("role", "user"),
                actor_id=str(payload.get("sub", "")),
                details=f"User logged out ({payload.get('role', 'user')})",
            )
        except Exception:
            pass
    response.delete_cookie("session_token", path="/")
    return {"message": "Logged out."}


# ---------------------------------------------------------------------------
# Current user
# ---------------------------------------------------------------------------
@router.get("/me")
def me(user: dict = Depends(get_current_user)):
    """Return the current user's profile (no sensitive fields)."""
    return user
