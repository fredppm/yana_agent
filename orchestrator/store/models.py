from __future__ import annotations

import json  # noqa: F401 — used by helpers in store/contacts.py

from sqlalchemy import Integer, PrimaryKeyConstraint, String, Text
from sqlalchemy.orm import DeclarativeBase, MappedColumn, mapped_column

# Maps LLM write-protocol names → ORM attribute names
_OWNER_FIELDS: dict[str, str] = {
    "PERSONA": "persona",
    "CREED": "creed",
    "BOND": "bond",
}
_PROFILE_FIELDS: dict[str, str] = {
    "CAPABILITIES": "capabilities",
    "PULSE": "pulse",
    "PULSE_CONFIG": "pulse_config",
}


class Base(DeclarativeBase):
    pass


class Owner(Base):
    __tablename__ = "owners"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)  # UUID
    name: MappedColumn[str | None] = mapped_column(
        String, nullable=True
    )  # apelido — mutable free text
    persona: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    creed: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    bond: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    updated_at: MappedColumn[str | None] = mapped_column(String, nullable=True)


class Profile(Base):
    __tablename__ = "profiles"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    owner_id: MappedColumn[str] = mapped_column(String, nullable=False)
    label: MappedColumn[str] = mapped_column(String, nullable=False)
    capabilities: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    pulse: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    pulse_config: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    created_at: MappedColumn[str] = mapped_column(String, nullable=False)


class Connector(Base):
    __tablename__ = "connectors"
    __table_args__ = (PrimaryKeyConstraint("profile_id", "instance_id"),)

    profile_id: MappedColumn[str] = mapped_column(String, nullable=False)
    instance_id: MappedColumn[str] = mapped_column(String, nullable=False)
    config_json: MappedColumn[str] = mapped_column(Text, nullable=False, default="{}")
    enabled: MappedColumn[int] = mapped_column(Integer, nullable=False, default=1)


class SessionRecord(Base):
    __tablename__ = "sessions"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    profile_id: MappedColumn[str] = mapped_column(String, nullable=False)
    started_at: MappedColumn[str] = mapped_column(String, nullable=False)
    title: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    summary: MappedColumn[str | None] = mapped_column(Text, nullable=True)
    messages_json: MappedColumn[str | None] = mapped_column(Text, nullable=True)


class PersonaRecord(Base):
    __tablename__ = "personas"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    name: MappedColumn[str] = mapped_column(String, nullable=False)
    type: MappedColumn[str] = mapped_column(String, nullable=False, default="person")
    owner: MappedColumn[str] = mapped_column(String, nullable=False, default="")
    aliases_json: MappedColumn[str] = mapped_column(Text, nullable=False, default="[]")
    context: MappedColumn[str] = mapped_column(Text, nullable=False, default="")
    tags_json: MappedColumn[str] = mapped_column(Text, nullable=False, default="[]")
    sources_json: MappedColumn[str] = mapped_column(Text, nullable=False, default="[]")
    vip: MappedColumn[int] = mapped_column(Integer, nullable=False, default=0)


class ContactRecord(Base):
    __tablename__ = "contacts"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    persona_id: MappedColumn[str] = mapped_column(String, nullable=False)
    channel: MappedColumn[str] = mapped_column(String, nullable=False)
    address: MappedColumn[str] = mapped_column(String, nullable=False)
    preferred: MappedColumn[int] = mapped_column(Integer, nullable=False, default=0)
    sources_json: MappedColumn[str] = mapped_column(Text, nullable=False, default="[]")


class NamedChannelRecord(Base):
    __tablename__ = "named_channels"

    id: MappedColumn[str] = mapped_column(String, primary_key=True)
    name: MappedColumn[str] = mapped_column(String, nullable=False)
    channel: MappedColumn[str] = mapped_column(String, nullable=False)
    address: MappedColumn[str] = mapped_column(String, nullable=False)
    via_connector: MappedColumn[str] = mapped_column(String, nullable=False)
    aliases_json: MappedColumn[str] = mapped_column(Text, nullable=False, default="[]")
