"""Fill the translation cache ahead of time, so no one waits for it live.

    python -m app.scripts.warm_translations                # ru and uz
    python -m app.scripts.warm_translations --lang ru      # one language
    python -m app.scripts.warm_translations --dry-run      # count, call nothing
    python -m app.scripts.warm_translations --retry-identical

Translation is normally lazy: the first person to open a page in Uzbek pays
for every string on it (see app/services/localize.py). That is the right
default and a bad thing to discover on stage — a cold cache on the Library
page is a few dozen sequential HTTP calls to a free endpoint. This walks the
same code path in advance so the cache is warm before anyone looks.

Idempotent. `ensure_fields` skips any field that is already cached, so running
this twice does nothing the second time, and running it after adding one new
article translates one new article.

WHAT `--retry-identical` IS FOR

`translate_text` never raises: if both providers fail it returns the source
text unchanged, and `ensure_fields` then caches that English string in the
`_ru` column, where it is indistinguishable from a real translation and will
never be retried. That is the one way this cache goes quietly wrong.

So this script counts fields whose cached "translation" is byte-identical to
the English, and `--retry-identical` clears those and asks again. Short
strings are excluded from the count, because "ECG" really is "ECG" in all
three languages.
"""
from __future__ import annotations

import argparse
import sys
from typing import Iterable, Sequence

from sqlmodel import Session, select

from app.db import engine, init_db
from app.models.challenge import Challenge, ChallengeChoice, ChallengeQuestion
from app.models.community import Community
from app.models.course import Course, Lesson
from app.models.quiz import Choice, Question, Quiz
from app.models.social import Article, Resource
from app.models.virtual_patient import (
    VirtualPatientCase,
    VirtualPatientOption,
    VirtualPatientStage,
)
from app.services import localize

# Every model with `_ru`/`_uz` columns, and the fields the routers actually
# translate. Questions and choices are here even though they are not on the
# brief: they are the strings a live demo hits the moment someone opens a
# challenge in Uzbek, which is exactly the wait this script exists to remove.
TARGETS: Sequence[tuple[type, tuple[str, ...]]] = (
    (Article, ("title", "excerpt", "body_md")),
    (Community, ("name", "description")),
    (Challenge, ("title", "description", "topic")),
    (ChallengeQuestion, ("prompt", "explanation")),
    (ChallengeChoice, ("text",)),
    (Resource, ("description",)),
    # Virtual Patient. A case has more translatable text than anything else
    # on the platform — brief, every stage, every option, every teaching
    # point — and it is read mid-simulation, where a pause is worst.
    (
        VirtualPatientCase,
        (
            "title",
            "summary",
            "presenting_complaint",
            "patient_brief",
            "correct_diagnosis",
            "learning_objectives",
            "debrief_md",
        ),
    ),
    (
        VirtualPatientStage,
        ("title", "narrative", "patient_line", "clinical_note", "prompt"),
    ),
    (VirtualPatientOption, ("label", "detail", "feedback")),
    # Curriculum.
    (Course, ("title", "summary")),
    (Lesson, ("title", "body_md", "key_point")),
    (Quiz, ("title", "description")),
    (Question, ("prompt", "explanation")),
    (Choice, ("text",)),
)

# Matches localize._MEANINGFUL_LENGTH: below this, identical is not evidence.
MEANINGFUL_LENGTH = 12


def _rows(session: Session, model: type) -> list:
    return list(session.exec(select(model)).all())


def _pending(rows: Iterable, fields: Sequence[str], lang: str) -> int:
    """Fields that have English text and no cached translation yet."""
    total = 0
    for row in rows:
        for field in fields:
            if (getattr(row, field, "") or "").strip() and not getattr(
                row, f"{field}_{lang}", ""
            ):
                total += 1
    return total


def _identical(rows: Iterable, fields: Sequence[str], lang: str) -> list[tuple[object, str]]:
    """Cached translations byte-identical to their English source."""
    out: list[tuple[object, str]] = []
    for row in rows:
        for field in fields:
            source = (getattr(row, field, "") or "").strip()
            cached = getattr(row, f"{field}_{lang}", "")
            if cached and cached == source and len(source) >= MEANINGFUL_LENGTH:
                out.append((row, f"{field}_{lang}"))
    return out


def warm(langs: Sequence[str], dry_run: bool, retry_identical: bool) -> int:
    init_db()

    problems = 0
    for lang in langs:
        print(f"\n=== {lang} ===")
        with Session(engine) as session:
            for model, fields in TARGETS:
                rows = _rows(session, model)
                if not rows:
                    print(f"  {model.__name__:<18} no rows")
                    continue

                if retry_identical:
                    stale = _identical(rows, fields, lang)
                    for row, attr in stale:
                        setattr(row, attr, "")
                        session.add(row)
                    if stale:
                        session.commit()
                        print(f"  {model.__name__:<18} cleared {len(stale)} identical-to-English")

                todo = _pending(rows, fields, lang)
                if not todo:
                    print(f"  {model.__name__:<18} {len(rows):>4} rows · already warm")
                    continue

                if dry_run:
                    print(f"  {model.__name__:<18} {len(rows):>4} rows · {todo} field(s) would be translated")
                    continue

                print(f"  {model.__name__:<18} {len(rows):>4} rows · translating {todo} field(s)…", end=" ", flush=True)
                localize.ensure_fields(session, localize.fields_for(rows, fields), lang)

                left = _pending(rows, fields, lang)
                same = len(_identical(rows, fields, lang))
                if left:
                    problems += left
                    print(f"{left} still empty")
                elif same:
                    problems += same
                    print(f"done, but {same} came back identical to English")
                else:
                    print("done")

    return problems


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument(
        "--lang",
        action="append",
        choices=sorted(localize.SUPPORTED_TARGETS),
        help="Language to warm; repeatable. Defaults to every supported target.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Report what is missing, translate nothing.")
    parser.add_argument(
        "--retry-identical",
        action="store_true",
        help="Clear cached values identical to their English source and ask again.",
    )
    args = parser.parse_args(argv)

    langs = args.lang or sorted(localize.SUPPORTED_TARGETS)
    problems = warm(langs, args.dry_run, args.retry_identical)

    if args.dry_run:
        print("\nDry run — nothing was written.")
        return 0
    if problems:
        # Non-zero so CI or a deploy hook notices, but this is a warning about
        # an external free endpoint, not a broken build: every one of these
        # fields still renders, in English.
        print(f"\n{problems} field(s) did not translate. Re-run, or check network access to the providers.")
        return 1
    print("\nCache is warm.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
