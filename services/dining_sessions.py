"""Table dining access sessions — opened on QR scan, closed on settle (2h max)."""

from datetime import datetime, timedelta
from typing import Optional, Tuple
import hashlib
import secrets

from sqlalchemy.orm import Session

import models

DINING_SESSION_HOURS = 2


def _hash_token(raw_token: str) -> str:
    return hashlib.sha256(raw_token.encode()).hexdigest()


def _expire_stale_sessions(db: Session, table_id: Optional[int] = None) -> None:
    now = models.get_yangon_now()
    query = db.query(models.DiningSession).filter(
        models.DiningSession.status == models.DiningSessionStatus.ACTIVE,
        models.DiningSession.expires_at <= now,
    )
    if table_id is not None:
        query = query.filter(models.DiningSession.table_id == table_id)
    for session in query.all():
        session.status = models.DiningSessionStatus.CLOSED
        session.closed_at = now
    db.flush()


def start_dining_session(db: Session, table_id: int) -> Tuple[str, models.DiningSession]:
    """Create a new 2-hour dining session for a table."""
    _expire_stale_sessions(db, table_id)
    now = models.get_yangon_now()
    raw_token = secrets.token_urlsafe(32)
    session = models.DiningSession(
        table_id=table_id,
        token_hash=_hash_token(raw_token),
        started_at=now,
        expires_at=now + timedelta(hours=DINING_SESSION_HOURS),
        status=models.DiningSessionStatus.ACTIVE,
    )
    db.add(session)
    db.flush()
    return raw_token, session


def verify_dining_session(
    db: Session, table_id: int, raw_token: Optional[str]
) -> Optional[models.DiningSession]:
    if not raw_token:
        return None
    _expire_stale_sessions(db, table_id)
    session = (
        db.query(models.DiningSession)
        .filter(
            models.DiningSession.token_hash == _hash_token(raw_token),
            models.DiningSession.table_id == table_id,
            models.DiningSession.status == models.DiningSessionStatus.ACTIVE,
        )
        .first()
    )
    if not session:
        return None
    if session.expires_at <= models.get_yangon_now():
        session.status = models.DiningSessionStatus.CLOSED
        session.closed_at = models.get_yangon_now()
        db.flush()
        return None
    return session


def close_dining_sessions_for_table(
    db: Session, table_id: int, as_of: Optional[datetime] = None
) -> int:
    """Close all active dining sessions when a table is settled or cancelled."""
    now = as_of or models.get_yangon_now()
    sessions = (
        db.query(models.DiningSession)
        .filter(
            models.DiningSession.table_id == table_id,
            models.DiningSession.status == models.DiningSessionStatus.ACTIVE,
        )
        .all()
    )
    for session in sessions:
        session.status = models.DiningSessionStatus.CLOSED
        session.closed_at = now
    db.flush()
    return len(sessions)
