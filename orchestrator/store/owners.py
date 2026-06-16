from __future__ import annotations

import uuid

from sqlalchemy.orm import Session

from .engine import _get_engine
from .models import Owner


def add_owner_sync(name: str = "") -> str:
    """Create a new owner. Returns owner UUID. Raises on DB failure."""
    owner_id = str(uuid.uuid4())
    with Session(_get_engine()) as session:
        session.add(Owner(id=owner_id, name=name or None))
        session.commit()
    return owner_id
