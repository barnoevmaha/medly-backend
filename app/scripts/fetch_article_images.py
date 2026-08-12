"""Resolve stock photos for articles, offline.

Run once after setting PEXELS_API_KEY. Idempotent: articles that already have a
photo are skipped unless --force is given.

    python -m app.scripts.fetch_article_images
    python -m app.scripts.fetch_article_images --force
"""
from __future__ import annotations

import argparse
import logging

from sqlmodel import Session

from app.config import settings
from app.db import engine
from app.services.article_images import backfill


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true",
                        help="refetch articles that already have a photo")
    parser.add_argument("--limit", type=int, default=0,
                        help="stop after this many articles")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")
    if not settings.pexels_api_key:
        print("PEXELS_API_KEY is not set — nothing to do.")
        print("Set it in backend/.env and run this again.")
        return 1

    with Session(engine) as session:
        changed = backfill(session, force=args.force, limit=args.limit)
    print(f"{changed} article image(s) updated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
