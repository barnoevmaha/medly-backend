"""The active display language for a request.

The frontend's language switcher (Settings, see src/lib/i18n.tsx) sends the
selected language on every API call as the `X-Medly-Lang` header, set once in
the shared request() wrapper in src/lib/api.ts rather than threaded through
every call site. Routes that serve translatable content depend on `get_lang`
to read it.
"""
from __future__ import annotations

from fastapi import Header

SUPPORTED_LANGS = {"en", "ru", "uz"}


def get_lang(x_medly_lang: str = Header(default="en", alias="X-Medly-Lang")) -> str:
    return x_medly_lang if x_medly_lang in SUPPORTED_LANGS else "en"
