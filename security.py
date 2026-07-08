import os
from typing import Optional, Set

import hmac
import hashlib

from fastapi import Depends, Header, HTTPException, Query, WebSocket
from sqlalchemy.orm import Session

import models
from database import get_db
from services.sessions import (
    MANAGER_ROLES,
    ROLE_KITCHEN,
    ROLE_OWNER,
    resolve_session,
    revoke_session,
)

SECRET_KEY = os.getenv(
    "RESTAURANT_SECRET_KEY", "restaurant_super_secret_signing_key_2026"
).encode()
KITCHEN_PIN = os.getenv("KITCHEN_PIN", "kitchen2026")

KITCHEN_ALLOWED_TRANSITIONS = {
    models.OrderStatus.PENDING: {
        models.OrderStatus.PREPARING,
        models.OrderStatus.CANCELLED,
    },
    models.OrderStatus.PREPARING: {
        models.OrderStatus.SERVED,
        models.OrderStatus.CANCELLED,
    },
}


def generate_table_token(table_id: int) -> str:
    return hmac.new(SECRET_KEY, str(table_id).encode(), hashlib.sha256).hexdigest()


def verify_table_token(table_id: int, token: str) -> bool:
    expected = generate_table_token(table_id)
    return hmac.compare_digest(expected, token)


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        raise HTTPException(
            status_code=401, detail="Missing Authorization Header. Please login."
        )
    try:
        token_type, token = authorization.split(" ", 1)
        if token_type.lower() != "bearer" or not token.strip():
            raise ValueError()
        return token.strip()
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=401, detail="Unauthorized session. Please log in."
        )


def _require_session(
    db: Session,
    raw_token: str,
    allowed_roles: Set[str],
    login_hint: str = "Please log in.",
) -> models.AuthSession:
    session = resolve_session(db, raw_token)
    if not session or session.role not in allowed_roles:
        raise HTTPException(status_code=401, detail=f"Unauthorized. {login_hint}")
    return session


def get_current_session(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> models.AuthSession:
    token = _extract_bearer_token(authorization)
    return _require_session(db, token, MANAGER_ROLES)


def verify_manager_token(
    session: models.AuthSession = Depends(get_current_session),
) -> models.AuthSession:
    return session


def get_owner_session(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> models.AuthSession:
    token = _extract_bearer_token(authorization)
    return _require_session(
        db,
        token,
        {ROLE_OWNER},
        login_hint="Owner access required for finance.",
    )


def verify_owner_token(
    session: models.AuthSession = Depends(get_owner_session),
) -> models.AuthSession:
    return session


def get_kitchen_session(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
) -> models.AuthSession:
    token = _extract_bearer_token(authorization)
    return _require_session(
        db,
        token,
        {ROLE_KITCHEN},
        login_hint="Kitchen login required.",
    )


def verify_kitchen_token(
    session: models.AuthSession = Depends(get_kitchen_session),
) -> models.AuthSession:
    return session


def verify_ws_token(
    db: Session,
    token: Optional[str],
    allowed_roles: Set[str],
) -> bool:
    session = resolve_session(db, token)
    return bool(session and session.role in allowed_roles)


async def reject_unauthorized_ws(websocket: WebSocket, reason: str) -> None:
    await websocket.close(code=1008, reason=reason)


def logout_token(db: Session, authorization: Optional[str]) -> None:
    try:
        token = _extract_bearer_token(authorization)
    except HTTPException:
        return
    revoke_session(db, token)


def validate_kitchen_status_transition(
    current: models.OrderStatus, new_status: models.OrderStatus
) -> None:
    allowed = KITCHEN_ALLOWED_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot change order from '{current.value}' to '{new_status.value}'.",
        )


def restore_order_stock(order: models.Order, db: Session) -> None:
    for order_item in order.items:
        menu_item = order_item.menu_item
        if menu_item.stock is not None:
            menu_item.stock += order_item.quantity
            if not menu_item.is_available and menu_item.stock > 0:
                menu_item.is_available = True
