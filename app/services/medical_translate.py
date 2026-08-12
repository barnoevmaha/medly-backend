"""Translation for medical teaching content.

Why this exists on top of `translate.py`: that module calls Google's keyless
web endpoint, one HTTP request per string, with no way to say "this is a
clinical vignette, keep the dose". For an article title that is fine. For
"Give 500 mg amoxicillin PO TDS" it is not — a general-purpose translator
will happily reword a drug route, and a student cannot tell that it did.

So the order here is: Gemini with the glossary and an explicit instruction
never to alter a number, validated afterwards; then the old translator; then
the English. Every step down is logged, and a value that fails validation is
discarded rather than stored, because a translation that quietly changes
"5 mg" to "50 mg" is worse than no translation at all.

Batched on purpose. `localize.ensure_fields` can arrive with sixty strings for
one page; sixty model calls would be slow and expensive, and the strings share
a case, so translating them together also gives the model the context to keep
them consistent with each other.
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter
from typing import List, Optional, Sequence

from app.services import medical_glossary as glossary
from app.services.translate import translate_text

# `app.services.gemini` is imported inside the functions that call it, not at
# module scope. `localize` imports this module, and the virtual patient engine
# imports `localize` for its read-through fallback — a module-level import
# here would give the deterministic engine a transitive dependency on the
# model, which is exactly the coupling that module exists to avoid.

logger = logging.getLogger("medly.medical_translate")

LANGUAGE_NAMES = {"en": "English", "ru": "Russian", "uz": "Uzbek (Latin script)"}

# Big enough that a whole page is usually one call; small enough that one bad
# batch does not cost the entire page, and that the response stays well inside
# the output ceiling.
MAX_BATCH_ITEMS = 20
MAX_BATCH_CHARS = 12_000

# Generous: this is a batch of prose, and truncation would fail validation and
# throw the whole batch away.
MAX_OUTPUT_TOKENS = 8_192

SYSTEM_PROMPT = """You are a medical translator for a clinical education \
platform. You translate teaching material for medical students.

ABSOLUTE RULES — a breach makes the translation unusable:
- Never change a number. Ages, doses, vital signs, lab values, rates, volumes,
  percentages and dates must appear in the translation exactly as given.
- Never change a unit, a drug name, or a route of administration.
- Never add a finding, symptom, measurement or recommendation that is not in
  the source. Never remove one.
- Never answer the content, explain it, or comment on it. You are translating.
- Preserve Markdown, line breaks, and any {placeholder} tokens exactly.

STYLE:
- Translate meaning, not words. The result must read as though a clinician in
  the target language wrote it, not as though it came from English.
- Use the standard clinical register of the target language.

You will be given a JSON array of strings. Return a JSON array of the same
length, in the same order, containing only the translations. No commentary,
no code fences, no keys — just the array."""


# --------------------------------------------------------------------------
# Validation
# --------------------------------------------------------------------------

_DIGIT_RUN = re.compile(r"\d+")
_PLACEHOLDER = re.compile(r"\{[a-zA-Z0-9_]+\}")


def digit_signature(text: str) -> Counter:
    """Multiset of digit runs.

    Compared instead of parsed numbers so the check survives the decimal and
    thousands separators changing, which they legitimately do: "38.5" becomes
    "38,5" in Russian and "1,200" becomes "1 200". Both still contain the same
    runs of digits, while "5 mg" turned into "50 mg" does not.
    """
    return Counter(_DIGIT_RUN.findall(text))


def validation_error(source: str, translated: str, target: str) -> Optional[str]:
    """Why this translation must not be stored, or None if it is fine."""
    if not translated or not translated.strip():
        return "empty"

    if digit_signature(source) != digit_signature(translated):
        # The single most important check in this file.
        return (
            f"numbers changed: {sorted(digit_signature(source).elements())} -> "
            f"{sorted(digit_signature(translated).elements())}"
        )

    want = Counter(_PLACEHOLDER.findall(source))
    got = Counter(_PLACEHOLDER.findall(translated))
    if want != got:
        return f"placeholders changed: {sorted(want)} -> {sorted(got)}"

    for token in glossary.DO_NOT_TRANSLATE:
        if source.count(token) and token not in translated:
            return f"dropped {token!r}"

    # A long passage that comes back the same length in Cyrillic is plausible;
    # one that comes back a third of the length has been summarised.
    if len(source) > 200 and len(translated) < len(source) * 0.4:
        return f"suspiciously short: {len(source)} -> {len(translated)} chars"

    if target == "uz":
        # The straight apostrophe and the curly quotes are the wrong
        # characters for oʻ/gʻ and for the glottal stop. Cheap to detect,
        # invisible to a reviewer skimming, and it looks careless to a
        # native reader.
        if re.search(r"[‘’']", translated):
            return "non-standard Uzbek apostrophe"

    return None


# --------------------------------------------------------------------------
# Gemini path
# --------------------------------------------------------------------------

def _credentials():
    """Prefer the assistant's key; fall back to the simulator's.

    Translation is not conversational, so it belongs on whichever key exists
    rather than earning a third environment variable nobody sets.
    """
    from app.services import gemini

    primary = gemini.assistant_credentials()
    if primary.api_key:
        return primary
    return gemini.virtual_patient_credentials()


def _parse_array(raw: str, expected: int) -> Optional[List[str]]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        logger.warning("translator returned non-JSON (%d chars)", len(text))
        return None
    if not isinstance(parsed, list) or len(parsed) != expected:
        logger.warning(
            "translator returned %s of length %s, wanted a list of %d",
            type(parsed).__name__,
            len(parsed) if isinstance(parsed, list) else "n/a",
            expected,
        )
        return None
    if not all(isinstance(item, str) for item in parsed):
        logger.warning("translator returned a list containing non-strings")
        return None
    return parsed


def _gemini_batch(texts: Sequence[str], target: str) -> Optional[List[str]]:
    """One call for the whole chunk, or None if it cannot be trusted."""
    from app.services import gemini

    credentials = _credentials()
    if not credentials.api_key:
        return None

    joined = "\n".join(texts)
    sections = [
        f"Translate from English into {LANGUAGE_NAMES[target]}.",
        glossary.TONE.get(target, ""),
        glossary.prompt_section(target, joined),
        "Leave these exactly as they are: " + ", ".join(glossary.DO_NOT_TRANSLATE),
        "",
        json.dumps(list(texts), ensure_ascii=False, indent=1),
    ]

    try:
        result = gemini.generate(
            system_prompt=SYSTEM_PROMPT,
            history=[],
            message="\n\n".join(part for part in sections if part),
            max_output_tokens=MAX_OUTPUT_TOKENS,
            # Deterministic: this is a transformation, not a composition.
            temperature=0.0,
            credentials=credentials,
        )
    except gemini.GeminiError as error:
        logger.warning("medical translator unavailable (%s); using fallback", error.detail)
        return None
    except Exception:  # noqa: BLE001 — translation must never break a request
        logger.exception("medical translator crashed; using fallback")
        return None

    return _parse_array(result.text, len(texts))


def _chunks(texts: Sequence[str]) -> List[List[int]]:
    """Index groups small enough to translate in one call."""
    groups: List[List[int]] = []
    current: List[int] = []
    size = 0
    for index, text in enumerate(texts):
        if current and (len(current) >= MAX_BATCH_ITEMS or size + len(text) > MAX_BATCH_CHARS):
            groups.append(current)
            current, size = [], 0
        current.append(index)
        size += len(text)
    if current:
        groups.append(current)
    return groups


# --------------------------------------------------------------------------
# Public
# --------------------------------------------------------------------------

def translate_batch(texts: Sequence[str], target: str, source: str = "en") -> List[str]:
    """Translate every string, in order. Never raises, never returns fewer.

    A string that cannot be translated safely comes back as the English. The
    caller (localize.ensure_fields) treats an unchanged long string as a
    fallback and tells the reader the page is partly English, so degrading
    here is visible rather than silent.
    """
    if target == source or target not in LANGUAGE_NAMES:
        return list(texts)

    out = list(texts)
    needs_fallback: List[int] = []

    for group in _chunks(texts):
        candidate = _gemini_batch([texts[i] for i in group], target)
        if candidate is None:
            needs_fallback.extend(group)
            continue
        for position, index in enumerate(group):
            problem = validation_error(texts[index], candidate[position], target)
            if problem:
                logger.warning("rejected translation (%s): %.60s", problem, texts[index])
                needs_fallback.append(index)
            else:
                out[index] = candidate[position]

    # Whatever Gemini could not do safely goes to the general-purpose
    # translator, which is worse at clinical register but better than English.
    for index in needs_fallback:
        legacy = translate_text(texts[index], target, source)
        problem = validation_error(texts[index], legacy, target)
        if problem:
            logger.warning("fallback also rejected (%s): %.60s", problem, texts[index])
            continue  # leaves the English in place
        out[index] = legacy

    return out


def translate_one(text: str, target: str, source: str = "en") -> str:
    """Single-string convenience. Prefer `translate_batch`."""
    return translate_batch([text], target, source)[0]
