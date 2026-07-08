"""Database-backed auth sessions with hashed tokens."""

import hashlib
import os
import secrets
from datetime import timedelta
from typing import Optional, Set

from sqlalchemy.orm import Session

import models

ROLE_OWNER = "owner"
ROLE_MANAGER = "manager"
ROLE_KITCHEN = "kitchen"
MANAGER_ROLES: Set[str] = {ROLE_OWNER, ROLE_MANAGER}


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _session_ttl_hours(role: str) -> int:
    if role == ROLE_KITCHEN:
        return int(os.getenv("SESSION_TTL_HOURS_KITCHEN", "24"))
    return int(os.getenv("SESSION_TTL_HOURS_MANAGER", "168"))


def create_session(
    db: Session,
    role: str,
    username: Optional[str] = None,
) -> str:
    raw_token = secrets.token_urlsafe(32)
    now = models.get_yangon_now()
    session = models.AuthSession(
        token_hash=_hash_token(raw_token),
        role=role,
        username=username,
        created_at=now,
        expires_at=now + timedelta(hours=_session_ttl_hours(role)),
    )
    db.add(session)
    db.commit()
    return raw_token


def resolve_session(db: Session, raw_token: Optional[str]) -> Optional[models.AuthSession]:
    if not raw_token:
        return None
    session = (
        db.query(models.AuthSession)
        .filter(models.AuthSession.token_hash == _hash_token(raw_token))
        .first()
    )
    if not session:
        return None
    if session.expires_at < models.get_yangon_now():
        db.delete(session)
        db.commit()
        return None
    return session


def revoke_session(db: Session, raw_token: Optional[str]) -> None:
    if not raw_token:
        return
    session = (
        db.query(models.AuthSession)
        .filter(models.AuthSession.token_hash == _hash_token(raw_token))
        .first()
    )
    if session:
        db.delete(session)
        db.commit()


def revoke_user_sessions(db: Session, username: str) -> None:
    db.query(models.AuthSession).filter(models.AuthSession.username == username).delete()
    db.commit()
