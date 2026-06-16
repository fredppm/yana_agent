from __future__ import annotations

import logging
import uuid

from sqlalchemy.orm import Session

from .engine import _get_engine
from .models import Owner

log = logging.getLogger(__name__)


def add_owner_sync(name: str = "") -> str:
    """Create a new owner. Returns owner UUID."""
    owner_id = str(uuid.uuid4())
    try:
        with Session(_get_engine()) as session:
            session.add(Owner(id=owner_id, name=name or None))
            session.commit()
    except Exception as e:
        log.debug("store: add_owner failed: %s", e)
    return owner_id
