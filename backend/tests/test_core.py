"""
Campus Ballot — Test Suite
Covers the 24+ checks from the original report plus API-level access-control
and concurrency tests.

Uses a temporary SQLite database for isolation.
"""

import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

# Set env vars BEFORE importing the app.
_tmp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
_tmp_db.close()
os.environ["DATABASE_PATH"] = _tmp_db.name
os.environ["SECRET_KEY"] = "test-secret-key-not-for-production"
os.environ["ADMIN_USERNAME"] = "testadmin"
os.environ["ADMIN_PASSWORD"] = "Admin@1234"
os.environ["APP_TIMEZONE"] = "Asia/Kolkata"
os.environ["COOKIE_SECURE"] = "false"
os.environ["PBKDF2_ITERATIONS"] = "1000"  # Fast iterations for testing

# Reload config so it picks up env vars.
# We need to re-instantiate Settings.
import importlib
from app import config as config_module
importlib.reload(config_module)
from app.config import settings as _s
_s.DATABASE_PATH = _tmp_db.name
_s.SECRET_KEY = "test-secret-key-not-for-production"
_s.ADMIN_USERNAME = "testadmin"
_s.ADMIN_PASSWORD = "Admin@1234"
_s.COOKIE_SECURE = False
_s.PBKDF2_ITERATIONS = 1000

from app.main import app
from app.database import get_connection, create_database
from app.security import hash_password, verify_password, validate_password

client = TestClient(app)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module", autouse=True)
def setup_db():
    """Ensure the DB is created before tests run."""
    create_database()
    yield
    # Cleanup
    try:
        os.unlink(_tmp_db.name)
    except OSError:
        pass


def _admin_login() -> dict:
    """Helper: login as the default admin. Returns cookies dict."""
    resp = client.post("/api/auth/login", json={
        "identifier": "testadmin",
        "password": "Admin@1234",
    })
    assert resp.status_code == 200
    return dict(resp.cookies)


def _register_student(username: str = "teststudent", full_name: str = "Test Student",
                       password: str = "Test@1234") -> str:
    """Helper: register a student. Returns student_id."""
    resp = client.post("/api/auth/register", json={
        "full_name": full_name,
        "username": username,
        "password": password,
        "confirm_password": password,
    })
    assert resp.status_code == 200, resp.json()
    return resp.json()["student_id"]


def _student_login(identifier: str, password: str = "Test@1234") -> dict:
    """Helper: login as a student. Returns cookies dict."""
    resp = client.post("/api/auth/login", json={
        "identifier": identifier,
        "password": password,
    })
    assert resp.status_code == 200
    return dict(resp.cookies)


# ===========================================================================
# 1. Seven tables created
# ===========================================================================
def test_seven_tables_created():
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
        ).fetchall()
        tables = {r["name"] for r in rows}
    finally:
        conn.close()

    expected = {"students", "admins", "elections", "candidates",
                "candidate_applications", "votes", "audit_log"}
    assert expected.issubset(tables), f"Missing tables: {expected - tables}"


# ===========================================================================
# 2. Default admin created
# ===========================================================================
def test_default_admin_created():
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT id, username, must_change_password FROM admins WHERE username = ?",
            ("testadmin",),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["must_change_password"] == 1


# ===========================================================================
# 3. Default admin not overwritten on restart
# ===========================================================================
def test_admin_not_overwritten_on_restart():
    conn = get_connection()
    try:
        original = conn.execute(
            "SELECT password FROM admins WHERE username = ?", ("testadmin",)
        ).fetchone()["password"]
    finally:
        conn.close()

    # Call create_database again (simulating restart).
    create_database()

    conn = get_connection()
    try:
        after = conn.execute(
            "SELECT password FROM admins WHERE username = ?", ("testadmin",)
        ).fetchone()["password"]
    finally:
        conn.close()

    assert original == after


# ===========================================================================
# 4. Hash format salt:hash
# ===========================================================================
def test_hash_format():
    h = hash_password("SomePass@123")
    parts = h.split(":")
    assert len(parts) == 2, f"Expected salt:hash, got {h}"
    # Both parts should be hex.
    bytes.fromhex(parts[0])
    bytes.fromhex(parts[1])


# ===========================================================================
# 5. Correct password verifies
# ===========================================================================
def test_correct_password_verifies():
    h = hash_password("MyPass@789")
    assert verify_password("MyPass@789", h) is True


# ===========================================================================
# 6. Wrong password fails
# ===========================================================================
def test_wrong_password_fails():
    h = hash_password("MyPass@789")
    assert verify_password("WrongPass@1", h) is False


# ===========================================================================
# 7. Same password gives different hashes (random salt)
# ===========================================================================
def test_same_password_different_hashes():
    h1 = hash_password("Same@Pass1")
    h2 = hash_password("Same@Pass1")
    assert h1 != h2, "Same password must produce different hashes due to random salt."


# ===========================================================================
# 8. Malformed hash fails safely
# ===========================================================================
def test_malformed_hash_fails_safely():
    assert verify_password("anything", "") is False
    assert verify_password("anything", "nocolon") is False
    assert verify_password("anything", "not:hex!") is False
    assert verify_password("anything", "abc:def:ghi") is False
    assert verify_password("anything", None) is False  # type: ignore


# ===========================================================================
# 9-13. Password policy rejections and acceptance
# ===========================================================================
def test_password_too_short():
    errors = validate_password("Ab1@")
    assert any("8 characters" in e for e in errors)


def test_password_no_uppercase():
    errors = validate_password("abcdefg1@")
    assert any("uppercase" in e for e in errors)


def test_password_no_lowercase():
    errors = validate_password("ABCDEFG1@")
    assert any("lowercase" in e for e in errors)


def test_password_no_digit():
    errors = validate_password("Abcdefgh@")
    assert any("digit" in e for e in errors)


def test_password_no_special():
    errors = validate_password("Abcdefg1")
    assert any("special" in e for e in errors)


def test_password_valid():
    errors = validate_password("Valid@Pass1")
    assert errors == []


# ===========================================================================
# 14-17. Election state
# ===========================================================================
def test_election_state_open():
    from app.services.elections import get_election_state
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)
    start = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    end = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    assert get_election_state(start, end, "ON") == "OPEN"


def test_election_state_not_started():
    from app.services.elections import get_election_state
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)
    start = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    end = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    assert get_election_state(start, end, "ON") == "NOT_STARTED"


def test_election_state_closed_by_time():
    from app.services.elections import get_election_state
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)
    start = (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")
    end = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    assert get_election_state(start, end, "ON") == "CLOSED"


def test_election_state_closed_by_off():
    from app.services.elections import get_election_state
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)
    start = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    end = (now + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    assert get_election_state(start, end, "OFF") == "CLOSED"


def test_election_state_invalid():
    from app.services.elections import get_election_state
    assert get_election_state("bad-date", "bad-date", "ON") == "INVALID"


# ===========================================================================
# 18. Student ID format
# ===========================================================================
def test_student_id_format():
    import re
    sid = _register_student(username="stufmt1")
    assert re.match(r"^STU\d{4}\d{4}$", sid), f"Student ID doesn't match format: {sid}"


# ===========================================================================
# 19. Duplicate username rejected
# ===========================================================================
def test_duplicate_username_rejected():
    _register_student(username="dupuser1")
    resp = client.post("/api/auth/register", json={
        "full_name": "Dup User",
        "username": "dupuser1",
        "password": "Test@1234",
        "confirm_password": "Test@1234",
    })
    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"].lower()


# ===========================================================================
# 20. Second vote rejected
# ===========================================================================
def test_second_vote_rejected():
    cookies = _admin_login()
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)
    start = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M")
    end = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M")

    # Create an election.
    resp = client.post("/api/admin/elections", json={
        "name": "Vote Test Election",
        "start_time": start,
        "end_time": end,
    }, cookies=cookies)
    assert resp.status_code == 200
    eid = resp.json()["id"]

    # Add a candidate directly.
    conn = get_connection()
    conn.execute("INSERT INTO candidates (election_id, name, department) VALUES (?, 'C1', 'CS')", (eid,))
    conn.commit()
    cid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()

    # Turn on.
    client.post(f"/api/admin/elections/{eid}/on", cookies=cookies)

    # Register and login a student.
    sid = _register_student(username="voter1")
    scookies = _student_login(sid)

    # First vote — should succeed.
    resp = client.post(f"/api/student/elections/{eid}/vote",
                       json={"candidate_id": cid}, cookies=scookies)
    assert resp.status_code == 200

    # Second vote — should fail.
    resp = client.post(f"/api/student/elections/{eid}/vote",
                       json={"candidate_id": cid}, cookies=scookies)
    assert resp.status_code == 409
    assert "already voted" in resp.json()["detail"].lower()


# ===========================================================================
# 21. Duplicate application rejected
# ===========================================================================
def test_duplicate_application_rejected():
    cookies = _admin_login()
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)

    resp = client.post("/api/admin/elections", json={
        "name": "App Test Election",
        "start_time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "end_time": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
    }, cookies=cookies)
    eid = resp.json()["id"]

    sid = _register_student(username="appdup1")
    scookies = _student_login(sid)

    # First application.
    resp = client.post("/api/student/applications", json={
        "election_id": eid,
        "post": "President",
        "department": "CS",
        "manifesto": "My manifesto",
    }, cookies=scookies)
    assert resp.status_code == 200

    # Duplicate.
    resp = client.post("/api/student/applications", json={
        "election_id": eid,
        "post": "President",
        "department": "CS",
        "manifesto": "My manifesto again",
    }, cookies=scookies)
    assert resp.status_code == 409
    assert "already applied" in resp.json()["detail"].lower()


# ===========================================================================
# 22. Cascade delete election → candidates and votes
# ===========================================================================
def test_cascade_delete():
    cookies = _admin_login()
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)

    resp = client.post("/api/admin/elections", json={
        "name": "Cascade Test",
        "start_time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "end_time": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
    }, cookies=cookies)
    eid = resp.json()["id"]

    conn = get_connection()
    conn.execute("INSERT INTO candidates (election_id, name, department) VALUES (?, 'C1', 'CS')", (eid,))
    conn.commit()
    cid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()

    client.post(f"/api/admin/elections/{eid}/on", cookies=cookies)

    sid = _register_student(username="cascadestu")
    scookies = _student_login(sid)
    client.post(f"/api/student/elections/{eid}/vote",
                json={"candidate_id": cid}, cookies=scookies)

    # Delete election.
    resp = client.delete(f"/api/admin/elections/{eid}", cookies=cookies)
    assert resp.status_code == 200

    # Verify cascaded.
    conn = get_connection()
    c_count = conn.execute("SELECT COUNT(*) AS c FROM candidates WHERE election_id = ?", (eid,)).fetchone()["c"]
    v_count = conn.execute("SELECT COUNT(*) AS c FROM votes WHERE election_id = ?", (eid,)).fetchone()["c"]
    conn.close()
    assert c_count == 0
    assert v_count == 0


# ===========================================================================
# 23. Audit entry written
# ===========================================================================
def test_audit_entry_written():
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COUNT(*) AS c FROM audit_log WHERE action = 'register'"
        ).fetchone()
    finally:
        conn.close()
    assert row["c"] > 0, "Expected audit entries for registration."


# ===========================================================================
# API-level: Student cannot access admin routes
# ===========================================================================
def test_student_cannot_access_admin():
    sid = _register_student(username="noaccess1")
    scookies = _student_login(sid)
    resp = client.get("/api/admin/dashboard", cookies=scookies)
    assert resp.status_code == 403


# ===========================================================================
# API-level: Results hidden until declared
# ===========================================================================
def test_results_hidden_until_declared():
    cookies = _admin_login()
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)

    resp = client.post("/api/admin/elections", json={
        "name": "Results Test",
        "start_time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "end_time": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
    }, cookies=cookies)
    eid = resp.json()["id"]

    resp = client.get(f"/api/admin/results/{eid}", cookies=cookies)
    assert resp.status_code == 400
    assert "not been declared" in resp.json()["detail"].lower()


# ===========================================================================
# API-level: Voting after close rejected
# ===========================================================================
def test_voting_after_close_rejected():
    cookies = _admin_login()
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)

    # Create an election that's already ended.
    resp = client.post("/api/admin/elections", json={
        "name": "Closed Vote Test",
        "start_time": (now - timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
        "end_time": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
    }, cookies=cookies)
    eid = resp.json()["id"]

    conn = get_connection()
    conn.execute("INSERT INTO candidates (election_id, name, department) VALUES (?, 'C1', 'CS')", (eid,))
    conn.commit()
    cid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()

    # Do NOT turn on — election stays OFF → state = CLOSED.
    sid = _register_student(username="closedvoter")
    scookies = _student_login(sid)

    resp = client.post(f"/api/student/elections/{eid}/vote",
                       json={"candidate_id": cid}, cookies=scookies)
    assert resp.status_code == 400
    assert "closed" in resp.json()["detail"].lower()


# ===========================================================================
# API-level: Concurrent double-vote → exactly one vote
# ===========================================================================
def test_concurrent_double_vote():
    cookies = _admin_login()
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)

    resp = client.post("/api/admin/elections", json={
        "name": "Concurrent Vote Test",
        "start_time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "end_time": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
    }, cookies=cookies)
    eid = resp.json()["id"]

    conn = get_connection()
    conn.execute("INSERT INTO candidates (election_id, name, department) VALUES (?, 'C1', 'CS')", (eid,))
    conn.commit()
    cid = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.close()

    client.post(f"/api/admin/elections/{eid}/on", cookies=cookies)

    sid = _register_student(username="concvoter")
    scookies = _student_login(sid)

    results = []

    def vote():
        r = client.post(
            f"/api/student/elections/{eid}/vote",
            json={"candidate_id": cid},
            cookies=scookies,
        )
        results.append(r.status_code)

    threads = [threading.Thread(target=vote) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # Exactly one should succeed (200), rest should fail (409).
    assert results.count(200) == 1, f"Expected exactly 1 success, got: {results}"

    # Verify only one vote in the DB.
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) AS c FROM votes WHERE election_id = ? AND student_id = (SELECT id FROM students WHERE student_id = ?)",
        (eid, sid),
    ).fetchone()["c"]
    conn.close()
    assert count == 1


# ===========================================================================
# Verifications for Fixes: Ballot Candidates, Dashboard Stats, Winner Counting
# ===========================================================================
def test_student_candidates_ballot_endpoint():
    cookies = _admin_login()
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)

    resp = client.post("/api/admin/elections", json={
        "name": "Ballot Candidates Test",
        "start_time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "end_time": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
    }, cookies=cookies)
    eid = resp.json()["id"]

    conn = get_connection()
    conn.execute("INSERT INTO candidates (election_id, name, department) VALUES (?, 'Member Alice', 'IT')", (eid,))
    conn.execute("INSERT INTO candidates (election_id, name, department) VALUES (?, 'Member Bob', 'Mech')", (eid,))
    conn.commit()
    conn.close()

    sid = _register_student(username="ballotvoter")
    scookies = _student_login(sid)

    # Fetch candidates as student
    cand_resp = client.get(f"/api/student/elections/{eid}/candidates", cookies=scookies)
    assert cand_resp.status_code == 200
    data = cand_resp.json()
    assert "candidates" in data
    assert len(data["candidates"]) == 2
    assert data["election_name"] == "Ballot Candidates Test"
    assert data["candidates"][0]["name"] in ["Member Alice", "Member Bob"]


def test_dashboard_stats_and_participation():
    cookies = _admin_login()
    adm_dash = client.get("/api/admin/dashboard", cookies=cookies).json()
    assert "counts" in adm_dash
    assert "active_elections" in adm_dash["counts"]
    assert "total_candidates" in adm_dash["counts"]
    assert "registered_students" in adm_dash["counts"]
    assert "total_votes" in adm_dash["counts"]

    sid = _register_student(username="statsstudent")
    scookies = _student_login(sid)
    stu_dash = client.get("/api/student/dashboard", cookies=scookies).json()
    assert "open_elections_count" in stu_dash
    assert "active_elections" in stu_dash
    assert "approved_candidacies_count" in stu_dash
    assert "participation_history" in stu_dash
    assert isinstance(stu_dash["elections"], list)


def test_results_winner_counting():
    cookies = _admin_login()
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)

    resp = client.post("/api/admin/elections", json={
        "name": "Winner Count Test",
        "start_time": (now - timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
        "end_time": (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M"),
    }, cookies=cookies)
    eid = resp.json()["id"]

    conn = get_connection()
    conn.execute("INSERT INTO candidates (election_id, name, department) VALUES (?, 'Winner Charlie', 'CSE')", (eid,))
    conn.execute("INSERT INTO candidates (election_id, name, department) VALUES (?, 'Runner Dave', 'ECE')", (eid,))
    conn.commit()
    c_winner = conn.execute("SELECT id FROM candidates WHERE election_id = ? AND name = 'Winner Charlie'", (eid,)).fetchone()["id"]
    conn.close()

    client.post(f"/api/admin/elections/{eid}/on", cookies=cookies)

    # Student 1 votes for Winner Charlie
    sid1 = _register_student(username="winnervoter1")
    scookies1 = _student_login(sid1)
    client.post(f"/api/student/elections/{eid}/vote", json={"candidate_id": c_winner}, cookies=scookies1)

    # Stop election and declare results
    client.post(f"/api/admin/elections/{eid}/off", cookies=cookies)
    client.post(f"/api/admin/elections/{eid}/declare", cookies=cookies)

    # Check Admin Results
    adm_res = client.get(f"/api/admin/results/{eid}", cookies=cookies).json()
    assert adm_res["total_votes"] == 1
    assert adm_res["winner"] is not None
    assert adm_res["winner"]["candidate_name"] == "Winner Charlie"
    assert adm_res["winner"]["vote_count"] == 1

    # Check Student Results
    stu_res = client.get(f"/api/student/results/{eid}", cookies=scookies1).json()
    assert stu_res["total_votes"] == 1
    assert stu_res["winner"] is not None
    assert stu_res["winner"]["candidate_name"] == "Winner Charlie"


# 33. Multi-post voting: separate votes and batch votes for different posts
def test_multi_post_voting():
    cookies = _admin_login()
    tz = ZoneInfo("Asia/Kolkata")
    now = datetime.now(tz)

    resp = client.post("/api/admin/elections", json={
        "name": "Multi-Post Council Election",
        "start_time": (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M"),
        "end_time": (now + timedelta(hours=3)).strftime("%Y-%m-%d %H:%M"),
    }, cookies=cookies)
    eid = resp.json()["id"]

    conn = get_connection()
    conn.execute("INSERT INTO candidates (election_id, name, department, post) VALUES (?, 'Alice Pres', 'CSE', 'President')", (eid,))
    conn.execute("INSERT INTO candidates (election_id, name, department, post) VALUES (?, 'Bob Pres', 'ECE', 'President')", (eid,))
    conn.execute("INSERT INTO candidates (election_id, name, department, post) VALUES (?, 'Charlie VP', 'ME', 'Vice President')", (eid,))
    conn.execute("INSERT INTO candidates (election_id, name, department, post) VALUES (?, 'Dave VP', 'CE', 'Vice President')", (eid,))
    conn.execute("INSERT INTO candidates (election_id, name, department, post) VALUES (?, 'Eve Sec', 'IT', 'Secretary')", (eid,))
    conn.commit()

    c_alice = conn.execute("SELECT id FROM candidates WHERE election_id = ? AND name = 'Alice Pres'", (eid,)).fetchone()["id"]
    c_bob = conn.execute("SELECT id FROM candidates WHERE election_id = ? AND name = 'Bob Pres'", (eid,)).fetchone()["id"]
    c_charlie = conn.execute("SELECT id FROM candidates WHERE election_id = ? AND name = 'Charlie VP'", (eid,)).fetchone()["id"]
    c_dave = conn.execute("SELECT id FROM candidates WHERE election_id = ? AND name = 'Dave VP'", (eid,)).fetchone()["id"]
    c_eve = conn.execute("SELECT id FROM candidates WHERE election_id = ? AND name = 'Eve Sec'", (eid,)).fetchone()["id"]
    conn.close()

    # Turn ON election
    client.post(f"/api/admin/elections/{eid}/on", cookies=cookies)

    # Student 1 tests separate votes for different posts
    sid1 = _register_student(username="multipost_voter1")
    scookies1 = _student_login(sid1)

    # Verify candidates list includes post
    cands_resp = client.get(f"/api/student/elections/{eid}/candidates", cookies=scookies1).json()
    assert "candidates" in cands_resp
    assert any(c["post"] == "President" for c in cands_resp["candidates"])
    assert any(c["post"] == "Vice President" for c in cands_resp["candidates"])

    # Vote for President
    v1 = client.post(f"/api/student/elections/{eid}/vote", json={"candidate_id": c_alice}, cookies=scookies1)
    assert v1.status_code == 200, v1.json()

    # Second vote for President should fail with ALREADY_VOTED
    v1_dup = client.post(f"/api/student/elections/{eid}/vote", json={"candidate_id": c_bob}, cookies=scookies1)
    assert v1_dup.status_code == 409
    assert "already voted" in v1_dup.json()["detail"].lower()

    # Vote for Vice President should succeed!
    v2 = client.post(f"/api/student/elections/{eid}/vote", json={"candidate_id": c_charlie}, cookies=scookies1)
    assert v2.status_code == 200, v2.json()

    # Student 2 tests voting for multiple posts at a time (batch vote)
    sid2 = _register_student(username="multipost_voter2")
    scookies2 = _student_login(sid2)

    batch_vote = client.post(
        f"/api/student/elections/{eid}/vote",
        json={"candidate_ids": [c_bob, c_dave, c_eve]},
        cookies=scookies2,
    )
    assert batch_vote.status_code == 200, batch_vote.json()

    # Turn OFF and declare results
    client.post(f"/api/admin/elections/{eid}/off", cookies=cookies)
    client.post(f"/api/admin/elections/{eid}/declare", cookies=cookies)

    # Check results have post_winners and post per candidate
    res = client.get(f"/api/student/results/{eid}", cookies=scookies1).json()
    assert "post_winners" in res
    assert "President" in res["post_winners"]
    assert "Vice President" in res["post_winners"]
    assert all("post" in r for r in res["results"])


