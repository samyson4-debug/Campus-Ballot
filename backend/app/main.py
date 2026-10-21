"""
Campus Ballot — FastAPI Application Entry Point

Startup sequence:
1. Create/migrate the database and bootstrap the default admin.
2. Mount API routers.
3. Mount the frontend as static files with index.html fallback.
4. Add security headers middleware.

SECURITY:
- Security headers (X-Content-Type-Options, X-Frame-Options, Referrer-Policy, CSP).
- Single origin: no CORS needed because FastAPI serves the frontend.
- Single Uvicorn worker (required for SQLite + in-memory rate limiter).
"""

import logging
import os
from pathlib import Path

from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .database import create_database
from .routers import auth, admin, student, public

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("campus_ballot")

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
app = FastAPI(
    title="Campus Ballot",
    description="College Election Voting System",
    version="1.0.0",
    docs_url="/api/docs",
    redoc_url=None,
)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------
@app.on_event("startup")
def on_startup():
    logger.info("Starting Campus Ballot...")
    create_database()
    logger.info("Campus Ballot is ready.")


# ---------------------------------------------------------------------------
# Security Headers Middleware
# ---------------------------------------------------------------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response: Response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self'; "
        "style-src 'self' https://fonts.googleapis.com 'unsafe-inline'; "
        "font-src 'self' https://fonts.gstatic.com; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "frame-ancestors 'none';"
    )
    return response


# ---------------------------------------------------------------------------
# API Routers
# ---------------------------------------------------------------------------
app.include_router(public.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(student.router)


# ---------------------------------------------------------------------------
# Frontend Static Files + SPA Fallback
# ---------------------------------------------------------------------------
FRONTEND_DIR = Path(__file__).resolve().parent.parent.parent / "frontend"


# Serve known frontend files (CSS, JS, HTML, images).
if FRONTEND_DIR.exists():
    app.mount(
        "/css",
        StaticFiles(directory=str(FRONTEND_DIR / "css")),
        name="css",
    )
    app.mount(
        "/js",
        StaticFiles(directory=str(FRONTEND_DIR / "js")),
        name="js",
    )

    @app.get("/admin.html")
    async def serve_admin():
        return FileResponse(str(FRONTEND_DIR / "admin.html"))

    @app.get("/student.html")
    async def serve_student():
        return FileResponse(str(FRONTEND_DIR / "student.html"))

    # Catch-all: serve index.html for the root and any unmatched paths.
    @app.get("/{full_path:path}")
    async def serve_frontend(full_path: str):
        # Try to serve the exact file first.
        file_path = FRONTEND_DIR / full_path
        if full_path and file_path.exists() and file_path.is_file():
            return FileResponse(str(file_path))
        # Fallback to index.html (SPA routing).
        return FileResponse(str(FRONTEND_DIR / "index.html"))
