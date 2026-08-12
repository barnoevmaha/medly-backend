"""Medly API — AI safety training for medical education."""
from __future__ import annotations

import logging
import sys
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db

# --------------------------------------------------------------------------
# Logging
#
# uvicorn configures only its own `uvicorn*` loggers. It never calls
# basicConfig and never touches the root logger, so an application logger like
# `medly.gemini` inherits root's WARNING with no handler attached — and every
# logger.info() in this codebase is discarded before it reaches stdout.
#
# Configuring just the `medly` namespace turns our own logs on without making
# SQLAlchemy and friends verbose. propagate=False keeps a single copy of each
# line even if something else configures root later.
# --------------------------------------------------------------------------
_medly_log = logging.getLogger("medly")
if not _medly_log.handlers:
    _handler = logging.StreamHandler(sys.stdout)
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    _medly_log.addHandler(_handler)
_medly_log.setLevel(logging.DEBUG if settings.stream_debug else logging.INFO)
_medly_log.propagate = False
from app.routers import (
    analysis,
    assistant,
    auth,
    casebook,
    challenges,
    communities,
    courses,
    feed,
    governance,
    profile,
    quizzes,
    saved,
    virtual_patient,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Replaces @app.on_event("startup"), which is deprecated in current FastAPI.
    init_db()
    if settings.seed_on_startup:
        # Containers get an empty volume on first boot; without this a fresh
        # deploy has no courses, no exam and no demo accounts to sign in with.
        from app.seed import run as run_seed

        run_seed()
    yield


app = FastAPI(
    title="Medly API",
    description=(
        "Teaching platform for safe use of AI in medical imaging. "
        "Every AI interaction passes a guardrail layer and is written to an audit log."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    # Lets any Railway/Vercel preview URL through without redeploying the API
    # every time the frontend gets a new hostname.
    allow_origin_regex=settings.cors_origin_regex or None,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(courses.router)
app.include_router(quizzes.router)
app.include_router(assistant.router)
app.include_router(analysis.router)
app.include_router(governance.router)
app.include_router(feed.router)
app.include_router(saved.router)
app.include_router(communities.router)
app.include_router(challenges.router)
app.include_router(casebook.router)
app.include_router(profile.router)
app.include_router(virtual_patient.router)


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    # `commit` answers "is Railway actually running the code I just pushed?"
    # without guessing — Railway injects RAILWAY_GIT_COMMIT_SHA at build time.
    # `streaming` says whether the SSE endpoint exists in this build at all.
    import os

    return {
        "status": "ok",
        "commit": (os.getenv("RAILWAY_GIT_COMMIT_SHA") or "unknown")[:7],
        "assistant_provider": settings.assistant_provider,
        # Listing the assistant routes rather than asserting one exact string:
        # the previous exact-match version reported false while the endpoint
        # was demonstrably serving, which cost a debugging round. A list cannot
        # be wrong in that way — you can see what is actually registered.
        "assistant_routes": sorted(
            getattr(route, "path", "")
            for route in app.routes
            if getattr(route, "path", "").startswith("/api/assistant")
        ),
        "stream_debug": settings.stream_debug,
        "inference_engine": settings.inference_engine,
        "confidence_threshold": settings.low_confidence_threshold,
    }
