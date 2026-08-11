"""Automatic machine translation for dynamic, database-backed content.

Medly has no paid translation API configured (there is no
GOOGLE_TRANSLATE_API_KEY / DEEPL_API_KEY / etc. in .env.example, and nothing
in the codebase called one before this file existed). Rather than gating
localisation on someone signing up for a paid account, this calls Google
Translate's public, keyless web endpoint — the same one translate.google.com's
own page uses — with MyMemory (mymemory.translated.net, also free and keyless)
as a fallback if that request fails. Both were checked by hand against real
article and community copy before this was wired in, and both genuinely
support Uzbek, which several paid providers do not.

This is a stopgap, not a replacement for a real localisation pipeline: a
production deployment serving real traffic should move this to a paid,
rate-limited, SLA-backed provider (Google Cloud Translation, DeepL, Azure
Translator, or a self-hosted LibreTranslate instance) instead of an
undocumented endpoint that Google could change or throttle without notice.
Translations are cached in the database by the caller (see localize.py) so
each string is only ever sent to either endpoint once.
"""
from __future__ import annotations

import logging
from typing import Optional

import httpx

logger = logging.getLogger("medly.translate")

_GOOGLE_ENDPOINT = "https://translate.googleapis.com/translate_a/single"
_MYMEMORY_ENDPOINT = "https://api.mymemory.translated.net/get"

# Comfortably under both providers' practical request-size limits, and small
# enough that one oversized paragraph cannot stall a whole batch.
_MAX_CHUNK_CHARS = 1800

_TIMEOUT = httpx.Timeout(10.0, connect=5.0)


def _split_into_chunks(text: str) -> list[str]:
    """Split long text on paragraph breaks so markdown structure (headings,
    lists) survives translation as separate, correctly-ordered requests.

    Short text — the common case: titles, excerpts, descriptions — returns
    unchanged as a single chunk.
    """
    if len(text) <= _MAX_CHUNK_CHARS:
        return [text]

    paragraphs = text.split("\n\n")
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        candidate = f"{current}\n\n{paragraph}" if current else paragraph
        if len(candidate) > _MAX_CHUNK_CHARS and current:
            chunks.append(current)
            current = paragraph
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks or [text]


def _google_translate(text: str, target: str, source: str) -> Optional[str]:
    try:
        response = httpx.get(
            _GOOGLE_ENDPOINT,
            params={"client": "gtx", "sl": source, "tl": target, "dt": "t", "q": text},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        # data[0] is a list of [translated_segment, original_segment, ...].
        return "".join(segment[0] for segment in data[0] if segment[0])
    except Exception as error:  # noqa: BLE001 — network/parse errors, never fatal
        logger.warning("google translate failed (%s -> %s): %s", source, target, error)
        return None


def _mymemory_translate(text: str, target: str, source: str) -> Optional[str]:
    try:
        response = httpx.get(
            _MYMEMORY_ENDPOINT,
            params={"q": text, "langpair": f"{source}|{target}"},
            timeout=_TIMEOUT,
        )
        response.raise_for_status()
        translated = response.json().get("responseData", {}).get("translatedText", "")
        return translated or None
    except Exception as error:  # noqa: BLE001
        logger.warning("mymemory translate failed (%s -> %s): %s", source, target, error)
        return None


def translate_text(text: str, target: str, source: str = "en") -> str:
    """Best-effort translation. Never raises: a translation-service outage or
    an unexpected response degrades to the original text, not a broken page.
    """
    text = (text or "").strip()
    if not text or target == source:
        return text

    chunks = _split_into_chunks(text)
    translated: list[str] = []
    for chunk in chunks:
        result = _google_translate(chunk, target, source)
        if result is None:
            result = _mymemory_translate(chunk, target, source)
        translated.append(result if result is not None else chunk)

    return "\n\n".join(translated) if len(chunks) > 1 else translated[0]
