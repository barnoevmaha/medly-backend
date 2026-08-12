"""Read database content in the caller's language, translating and caching
on first use.

Every translatable model follows the same shape: an English column (`title`,
`description`, `name`, `prompt`, ...) plus a `<field>_ru` and `<field>_uz`
sibling that starts empty. `read()` returns the column for the requested
language, and `ensure_fields()` fills in whichever siblings are still empty
by calling out to translate.py — in parallel, since a cold cache on a list
page can mean a few dozen strings at once and doing them one at a time would
make the first visit in a language feel broken.

This is what makes translation "automatic" rather than hand-maintained: a
community a student created ten seconds ago and a community seeded on day one
go through the exact same path the first time anyone views either in Uzbek or
Russian. Nothing about content translation is authored by hand.
"""
from __future__ import annotations

from contextvars import ContextVar
from typing import Sequence

from sqlmodel import Session

from app.services import medical_translate

SUPPORTED_TARGETS = {"ru", "uz"}

# One (object, field-name) pair awaiting translation.
FieldRef = tuple[object, str]

# --------------------------------------------------------------------------
# Fallback reporting
#
# Falling back to English is the correct behaviour — a blank field would be
# worse — but doing it *silently* means a viewer cannot tell "Medly has no
# Russian for this" from "this article happens to be about an English term".
# The middleware in app/main.py turns this flag into a response header, and
# the frontend renders one small line.
#
# A dict rather than a bool because FastAPI runs sync endpoints in a worker
# thread with a *copy* of the context: a `.set()` inside the endpoint would
# not be visible to the middleware afterwards, but a mutation of the object
# the middleware already put there is, because both hold the same reference.
# --------------------------------------------------------------------------
_fallback: ContextVar[dict | None] = ContextVar("medly_translation_fallback", default=None)

# Below this, "the translation is identical to the English" means nothing:
# "ECG", "Email" and "3" are the same string in every language.
_MEANINGFUL_LENGTH = 12


def begin_request() -> dict:
    """Install a fresh flag for one request and return it."""
    state = {"fallback": False}
    _fallback.set(state)
    return state


def note_fallback() -> None:
    state = _fallback.get()
    if state is not None:
        state["fallback"] = True


def read(obj: object, field: str, lang: str) -> str:
    """The value of `field` on `obj` in `lang`, falling back to English (the
    canonical column) if no translation has been cached yet or the object has
    none — this is what guarantees a viewer never sees a blank field."""
    if lang not in SUPPORTED_TARGETS:
        return getattr(obj, field, "") or ""
    translated = getattr(obj, f"{field}_{lang}", "")
    if translated:
        return translated
    english = getattr(obj, field, "") or ""
    if english:
        note_fallback()
    return english


def ensure_fields(session: Session, refs: Sequence[FieldRef], lang: str) -> None:
    """Fill every `<field>_<lang>` in `refs` that is still empty, then commit
    once. No-op for English (nothing to translate) and for fields that are
    already cached from a previous view.

    `refs` may reference the same underlying rows a caller already loaded —
    this only ever mutates the `_ru`/`_uz` columns, so it is safe to call
    right before building a response from those same rows.
    """
    if lang not in SUPPORTED_TARGETS:
        return

    pending: list[tuple[object, str, str]] = []
    for obj, field in refs:
        source_text = (getattr(obj, field, "") or "").strip()
        if not source_text:
            continue
        target_attr = f"{field}_{lang}"
        if getattr(obj, target_attr, ""):
            continue
        pending.append((obj, target_attr, source_text))

    if not pending:
        return

    # One batched call rather than a thread pool of one-string requests. The
    # strings on a page belong to the same case, so translating them together
    # is cheaper *and* more consistent — the model sees that "the patient" in
    # the prompt and "the patient" in the option label are the same patient.
    # medical_translate never raises and always returns the same number of
    # strings; anything it could not do safely comes back as the English.
    translated_values = medical_translate.translate_batch(
        [source for _obj, _attr, source in pending], lang
    )

    for (obj, target_attr, source), translated in zip(pending, translated_values):
        # A long phrase that comes back byte-identical is a translation that
        # was refused or failed. Writing it would be worse than not caching at
        # all: the column stops being empty, so every later view skips it and
        # the text is stuck in English permanently — one throttled request on
        # the first view in a language and that case never translates again.
        # Leave the column empty so the next view retries, and tell the viewer
        # this page is partly English in the meantime.
        if translated == source and len(source) >= _MEANINGFUL_LENGTH:
            note_fallback()
            continue
        setattr(obj, target_attr, translated)
        session.add(obj)
    session.commit()


def fields_for(objs: Sequence[object], field_names: Sequence[str]) -> list[FieldRef]:
    """`[(obj, field) for obj in objs for field in field_names]`, spelled out
    because that comprehension shows up at every call site otherwise."""
    return [(obj, field) for obj in objs for field in field_names]
