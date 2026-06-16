from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from sqlalchemy import create_engine

load_dotenv(Path(__file__).parent.parent / ".env")

_engine_cache: Any = None


def _load_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise ValueError("DATABASE_URL env var not set (check .env)")
    return url


def _get_engine():
    import store as _store

    if _store._engine_cache is None:
        _store._engine_cache = create_engine(_store._load_url(), pool_pre_ping=True)
    return _store._engine_cache
