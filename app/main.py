"""Medly API — AI safety training for medical education."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.db import init_db
from app.routers import analysis, assistant, auth, courses, governance, quizzes


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


@app.get("/api/health", tags=["meta"])
def health() -> dict:
    return {
        "status": "ok",
        "assistant_provider": settings.assistant_provider,
        "inference_engine": settings.inference_engine,
        "confidence_threshold": settings.low_confidence_threshold,
    }
