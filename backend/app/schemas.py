"""
Campus Ballot — Pydantic v2 Schemas
Request/response models with validation for every endpoint.
"""

from pydantic import BaseModel, Field, field_validator, model_validator


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class RegisterRequest(BaseModel):
    full_name: str = Field(..., min_length=1, max_length=200)
    username: str = Field(..., min_length=4, max_length=50)
    password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    identifier: str = Field(..., min_length=1, max_length=100)
    password: str = Field(..., min_length=1, max_length=128)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(..., min_length=1, max_length=128)
    new_password: str = Field(..., min_length=8, max_length=128)
    confirm_password: str = Field(..., min_length=8, max_length=128)


# ---------------------------------------------------------------------------
# Elections
# ---------------------------------------------------------------------------
class ElectionCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    start_time: str = Field(..., max_length=20)
    end_time: str = Field(..., max_length=20)


# ---------------------------------------------------------------------------
# Candidate Applications
# ---------------------------------------------------------------------------
VALID_POSTS = [
    "President",
    "Vice President",
    "Secretary",
    "Treasurer",
    "Class Representative",
    "Cultural Secretary",
    "Sports Secretary",
    "Other",
]


class CandidateApplicationRequest(BaseModel):
    election_id: int
    post: str = Field(..., min_length=1, max_length=100)
    department: str = Field(..., min_length=1, max_length=200)
    manifesto: str = Field("", max_length=2000)

    @field_validator("post")
    @classmethod
    def validate_post(cls, v: str) -> str:
        if v not in VALID_POSTS:
            raise ValueError(f"Invalid post. Must be one of: {', '.join(VALID_POSTS)}")
        return v


# ---------------------------------------------------------------------------
# Voting
# ---------------------------------------------------------------------------
class VoteRequest(BaseModel):
    candidate_id: int | None = None
    candidate_ids: list[int] | None = None

    @model_validator(mode="after")
    def validate_vote_targets(self):
        if self.candidate_id is None and not self.candidate_ids:
            raise ValueError("Either candidate_id or candidate_ids must be provided.")
        return self


# ---------------------------------------------------------------------------
# Responses (selected)
# ---------------------------------------------------------------------------
class UserOut(BaseModel):
    id: int
    role: str
    username: str
    full_name: str | None = None
    student_id: str | None = None
    must_change_password: bool = False


class ElectionOut(BaseModel):
    id: int
    name: str
    start_time: str
    end_time: str
    status: str
    results_declared: bool
    state: str | None = None  # computed: OPEN / CLOSED / NOT_STARTED / INVALID


class CandidateOut(BaseModel):
    id: int
    name: str
    department: str | None = None
    post: str | None = None


class ApplicationOut(BaseModel):
    id: int
    election_id: int
    election_name: str | None = None
    student_id: int | None = None
    student_display_id: str | None = None
    student_name: str | None = None
    post: str | None = None
    department: str | None = None
    manifesto: str | None = None
    status: str
    applied_at: str | None = None


class AuditLogEntry(BaseModel):
    id: int
    action: str | None = None
    actor_type: str | None = None
    actor_id: str | None = None
    details: str | None = None
    created_at: str | None = None


class DashboardStats(BaseModel):
    total_elections: int = 0
    active_elections: int = 0
    total_candidates: int = 0
    registered_students: int = 0
    total_votes: int = 0
    recent_elections: list[ElectionOut] = []


class StudentDashboard(BaseModel):
    full_name: str
    student_id: str
    total_elections: int = 0
    applications_count: int = 0
    votes_cast: int = 0
    approved_applications: int = 0
    elections: list[dict] = []


class ResultRow(BaseModel):
    candidate_id: int
    candidate_name: str
    department: str | None = None
    post: str | None = None
    vote_count: int = 0
