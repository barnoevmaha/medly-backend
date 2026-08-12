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


logger = logging.getLogger("medly.startup")

# Providers that reach a real model, and the setting each one needs a key in.
_LIVE_PROVIDERS = {
    "gemini": "GEMINI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def _report_assistant_provider() -> None:
    """Say plainly, once, at boot, which brain the assistant is running on.

    `rules` is a legitimate zero-config default and stays the default — this
    does not fail startup or change behaviour. But a deployment that *meant*
    to run Gemini and quietly fell back to keyword matching looks fine in the
    UI and fine in the logs, and the only symptom is answers that feel oddly
    shallow. That is an expensive thing to discover during a demo, so it is
    stated out loud here.

    The key itself is never logged — only whether one is present.
    """
    provider = settings.assistant_provider
    key_env = _LIVE_PROVIDERS.get(provider)

    if key_env is None:
        logger.warning(
            "assistant_provider is %r — the offline keyword-based fallback is "
            "active, not a live model. Set MEDLY_ASSISTANT_PROVIDER=gemini and "
            "GEMINI_API_KEY to use one.",
            provider,
        )
        return

    key = {
        "gemini": settings.gemini_api_key,
        "anthropic": settings.anthropic_api_key,
        "openai": settings.openai_api_key,
    }[provider]

    if not key.strip():
        logger.warning(
            "assistant_provider is %r but %s is empty — every request will "
            "fail its provider call and degrade to the offline fallback. "
            "Set %s, or set MEDLY_ASSISTANT_PROVIDER=rules to make the "
            "fallback deliberate.",
            provider,
            key_env,
            key_env,
        )
        return

    logger.info(
        "assistant_provider=%s model=%s — live model configured",
        provider,
        settings.gemini_model if provider == "gemini" else "(provider default)",
    )


@asynccontextmanager
async def lifespan(_: FastAPI):
    # Replaces @app.on_event("startup"), which is deprecated in current FastAPI.
    init_db()
    _report_assistant_provider()
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
    # A cross-origin browser can only read the headers named here. Without
    # this the translation-fallback header arrives and is invisible to JS.
    expose_headers=["X-Medly-Translation"],
)

class TranslationFallbackMiddleware:
    """Tell the client when part of this response is English by necessity.

    `localize.read()` falls back to the English column when no translation is
    cached, which is the right behaviour and the wrong silence: a student
    reading Russian cannot tell a missing translation from an article that is
    simply about an English term. One header, one small line in the UI.

    Written as raw ASGI rather than `@app.middleware("http")` on purpose.
    That decorator installs a `BaseHTTPMiddleware`, which pumps the response
    body through an internal queue — fine for JSON, and a real hazard for the
    assistant's SSE endpoint, where anything that buffers the body turns a
    working stream back into the delayed lump this project already spent a
    day fixing. Touching only the `http.response.start` message leaves every
    body byte on its original path.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        from starlette.datastructures import MutableHeaders

        from app.services import localize

        state = localize.begin_request()

        async def send_with_header(message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["X-Medly-Translation"] = (
                    "partial" if state["fallback"] else "complete"
                )
            await send(message)

        await self.app(scope, receive, send_with_header)


app.add_middleware(TranslationFallbackMiddleware)

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
        # A boolean, never the key. "provider says gemini, key is missing" is
        # the failure that looks identical to a working deployment from the
        # outside, so it is answerable without shell access to the container.
        "assistant_key_configured": bool(
            {
                "gemini": settings.gemini_api_key,
                "anthropic": settings.anthropic_api_key,
                "openai": settings.openai_api_key,
            }
            .get(settings.assistant_provider, "")
            .strip()
        ),
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
