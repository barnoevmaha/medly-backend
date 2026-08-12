"""Runtime configuration, read once from the environment.

`.env` is read into the environment before `Settings` is built. Every field
below calls `os.getenv` as its default, and dataclass defaults are evaluated
once when the class is defined — so anything that is going to set a variable
has to have done it by the time this module finishes importing. That is why
the loader is a module-level call and not something the app does at startup.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import List

# backend/.env — sits next to requirements.txt, two levels up from this file.
_ENV_FILE = Path(__file__).resolve().parent.parent / ".env"


def _load_env_file(path: Path = _ENV_FILE) -> None:
    """Fill in missing environment variables from a local `.env`.

    Hand-rolled rather than pulling in python-dotenv: it is a dozen lines of
    standard library, this is the only module that needs it, and the project
    already prefers a small amount of its own code over a dependency to pin
    and keep current (see the note about the Gemini SDK in requirements.txt).

    A real environment variable always wins. Railway, Vercel and
    `docker compose` set theirs for real, and a stale local `.env` must never
    silently override a deployment. A missing or unreadable file is a normal
    state — production has no `.env` at all — so it is not an error.

    Values are never logged. This function is the only thing that reads the
    file, and it writes straight into `os.environ`.
    """
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return

    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :].lstrip()
        name, separator, value = line.partition("=")
        name = name.strip()
        # No "=" is not a variable; already set means the real environment
        # has spoken and this line is ignored.
        if not separator or not name or name in os.environ:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        os.environ[name] = value


_load_env_file()


def _split(value: str) -> List[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


@dataclass(frozen=True)
class Settings:
    secret_key: str = os.getenv("MEDLY_SECRET_KEY", "dev-only-insecure-secret-change-me")
    algorithm: str = "HS256"
    access_token_minutes: int = int(os.getenv("MEDLY_ACCESS_TOKEN_MINUTES", "720"))

    database_url: str = os.getenv("MEDLY_DATABASE_URL", "sqlite:///./medly.db")

    # Teacher uploads (cover art, question images) land here and are served
    # back from /uploads. Use a persisted volume in production.
    upload_dir: str = os.getenv("MEDLY_UPLOAD_DIR", "./data/uploads")

    cors_origins: List[str] = field(
        default_factory=lambda: _split(
            os.getenv("MEDLY_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173")
        )
    )
    # Deploy platforms hand out a new hostname per preview. Matching by pattern
    # avoids redeploying the API to add each one. Replit previews use
    # *.replit.dev (production) and *.replit.app (classic), Railway uses
    # *.up.railway.app, Vercel uses *.vercel.app.
    cors_origin_regex: str = os.getenv(
        "MEDLY_CORS_ORIGIN_REGEX",
        r"https://.*\.(up\.railway\.app|vercel\.app|replit\.dev|replit\.app)",
    )

    # Containers start with an empty volume, so a fresh deploy has no curriculum
    # and no demo accounts unless the seed runs on boot. Idempotent either way —
    # every seed step skips rows that already exist, so leaving it on for every
    # boot is safe. The one thing it must NOT do is rotate MEDLY_SECRET_KEY,
    # because that would invalidate every stored session on restart.
    seed_on_startup: bool = os.getenv("MEDLY_SEED_ON_STARTUP", "false").lower() in {
        "1", "true", "yes",
    }

    assistant_provider: str = os.getenv("MEDLY_ASSISTANT_PROVIDER", "rules")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")

    # --- Gemini ------------------------------------------------------------
    # Server-side only. The key is never sent to the browser: the frontend
    # talks to /api/assistant/chat, and this process talks to Google.
    # Stock imagery. Server-side only — this value is never placed on a
    # response model, so it cannot reach the browser. Unset is a supported
    # state: lookups are skipped and callers keep their existing image.
    pexels_api_key: str = os.getenv("PEXELS_API_KEY", "")
    pexels_timeout_seconds: float = float(os.getenv("PEXELS_TIMEOUT_SECONDS", "10"))

    gemini_api_key: str = os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
    gemini_base_url: str = os.getenv(
        "GEMINI_BASE_URL", "https://generativelanguage.googleapis.com/v1beta"
    )
    gemini_timeout_seconds: float = float(os.getenv("GEMINI_TIMEOUT_SECONDS", "45"))

    # Gemini 3.x reasons before it answers. With thinking left at its default
    # the model emits nothing for several seconds and then delivers the answer
    # in a few large pieces — which is indistinguishable from "not streaming".
    # A chat surface wants first-token latency, not depth, so this is turned
    # down. Set to "high" for harder questions, or "" to send no preference.
    gemini_thinking_level: str = os.getenv("GEMINI_THINKING_LEVEL", "low")

    # Bytes of SSE comment padding sent before the first real frame. Proxies
    # that buffer a response until some minimum is buffered will hold an SSE
    # stream open but silent forever otherwise. Comments are ignored by every
    # SSE client, so this is invisible. Set to 0 to disable.
    sse_preamble_bytes: int = int(os.getenv("MEDLY_SSE_PREAMBLE_BYTES", "2048"))

    # --- Virtual Patient -----------------------------------------------
    # Its own credentials so the simulator can be pointed at a different key,
    # project or quota than the assistant, and so exhausting one does not take
    # the other down. Empty falls back to the assistant's key, which is what
    # you want in development and for a single-project deployment.
    vp_gemini_api_key: str = os.getenv("VIRTUAL_PATIENT_GEMINI_API_KEY", "")
    vp_gemini_model: str = os.getenv("VIRTUAL_PATIENT_GEMINI_MODEL", "gemini-3.5-flash")
    vp_gemini_timeout_seconds: float = float(
        os.getenv("VIRTUAL_PATIENT_GEMINI_TIMEOUT_SECONDS", "30")
    )
    # Patient dialogue is a couple of sentences; a large ceiling here would
    # only pay for a monologue nobody asked for.
    vp_max_output_tokens: int = int(os.getenv("VIRTUAL_PATIENT_MAX_OUTPUT_TOKENS", "400"))
    vp_debrief_max_output_tokens: int = int(
        os.getenv("VIRTUAL_PATIENT_DEBRIEF_MAX_OUTPUT_TOKENS", "1200")
    )

    # Timestamped per-stage stream logging, and the /debug-stream probe.
    # Off unless explicitly enabled.
    stream_debug: bool = os.getenv("MEDLY_STREAM_DEBUG", "false").lower() in {"1", "true", "yes"}

    # Cost and abuse ceilings. Every one of these is a real limit enforced in
    # code, not a suggestion — an unbounded context window on a paid API is a
    # billing incident waiting to happen.
    ai_max_message_chars: int = int(os.getenv("MEDLY_AI_MAX_MESSAGE_CHARS", "4000"))
    ai_max_output_tokens: int = int(os.getenv("MEDLY_AI_MAX_OUTPUT_TOKENS", "1600"))
    ai_history_turns: int = int(os.getenv("MEDLY_AI_HISTORY_TURNS", "6"))
    ai_max_context_chars: int = int(os.getenv("MEDLY_AI_MAX_CONTEXT_CHARS", "12000"))
    ai_article_context_chars: int = int(os.getenv("MEDLY_AI_ARTICLE_CONTEXT_CHARS", "6000"))
    ai_note_context_chars: int = int(os.getenv("MEDLY_AI_NOTE_CONTEXT_CHARS", "1500"))

    # Per-user request ceiling, counted in this process.
    ai_rate_limit_per_minute: int = int(os.getenv("MEDLY_AI_RATE_LIMIT_PER_MINUTE", "12"))
    ai_rate_limit_per_hour: int = int(os.getenv("MEDLY_AI_RATE_LIMIT_PER_HOUR", "120"))

    inference_engine: str = os.getenv("MEDLY_INFERENCE_ENGINE", "mock")
    onnx_model_path: str = os.getenv("MEDLY_ONNX_MODEL_PATH", "")

    low_confidence_threshold: float = float(os.getenv("MEDLY_LOW_CONFIDENCE_THRESHOLD", "0.70"))

    # Shown on every AI output in the product. Non-negotiable by design.
    disclaimer: str = (
        "Educational use only. This output is generated by a simulated model for "
        "training purposes and must not be used for clinical diagnosis or patient care. "
        "A qualified clinician is responsible for every decision."
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
