from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from .engine import _get_engine
from .models import Connector


def save_connector_sync(profile_id: str, instance_id: str, config_json_str: str) -> None:
    with Session(_get_engine()) as db:
        connector = db.get(Connector, (profile_id, instance_id))
        if connector is None:
            connector = Connector(profile_id=profile_id, instance_id=instance_id)
            db.add(connector)
        connector.config_json = config_json_str
        db.commit()


def list_connectors_sync(profile_id: str) -> list[dict]:
    with Session(_get_engine()) as db:
        connectors = db.scalars(
            select(Connector).where(Connector.profile_id == profile_id)
        ).all()
        return [
            {"instance_id": c.instance_id, "config_json": c.config_json} for c in connectors
        ]
