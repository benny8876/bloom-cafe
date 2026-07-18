"""Shared order creation logic for customer menu and manager counter sales."""

from datetime import timedelta
from typing import List, Optional, Sequence

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

import models
from models import get_yangon_now
from schemas import OrderItemCreate

# Unpaid drafts can be reused longer; paid retries are usually seconds.
MENU_AWAITING_DEDUP_MINUTES = 30
MENU_PAID_DEDUP_MINUTES = 10


def order_item_unit_price(order_item: models.OrderItem) -> float:
    unit_price = float(order_item.menu_item.price)
    for mod_assoc in order_item.selected_modifiers:
        unit_price += float(mod_assoc.modifier.price)
    return unit_price


def order_item_line_total(order_item: models.OrderItem) -> float:
    return order_item_unit_price(order_item) * order_item.quantity


def recalculate_order_total(order: models.Order) -> float:
    total_price = sum(order_item_line_total(item) for item in order.items)
    order.total_price = round(total_price, 2)
    return order.total_price


def restore_order_item_stock(
    order_item: models.OrderItem, quantity: int, db: Session
) -> None:
    if quantity <= 0:
        return

    menu_item = order_item.menu_item
    if menu_item.stock is not None:
        menu_item.stock += quantity
        if not menu_item.is_available and menu_item.stock > 0:
            menu_item.is_available = True


def cart_fingerprint_from_payload(items: Sequence[OrderItemCreate]) -> str:
    lines = []
    for item in items:
        mods = tuple(sorted(int(m) for m in (item.modifier_ids or [])))
        notes = (item.notes or "").strip()
        lines.append(f"{item.menu_item_id}:{item.quantity}:{notes}:{mods}")
    return "|".join(sorted(lines))


def cart_fingerprint_from_order(order: models.Order) -> str:
    lines = []
    for oi in order.items or []:
        mods = tuple(sorted(int(m.modifier_id) for m in (oi.selected_modifiers or [])))
        notes = (oi.notes or "").strip()
        lines.append(f"{oi.menu_item_id}:{oi.quantity}:{notes}:{mods}")
    return "|".join(sorted(lines))


def find_recent_matching_menu_order(
    db: Session,
    table_id: int,
    items: Sequence[OrderItemCreate],
) -> Optional[models.Order]:
    """Return a recent same-cart order so retries do not create duplicates."""
    fingerprint = cart_fingerprint_from_payload(items)
    if not fingerprint:
        return None

    now = get_yangon_now()
    awaiting_cutoff = now - timedelta(minutes=MENU_AWAITING_DEDUP_MINUTES)
    paid_cutoff = now - timedelta(minutes=MENU_PAID_DEDUP_MINUTES)

    candidates = (
        db.query(models.Order)
        .options(
            joinedload(models.Order.items).joinedload(
                models.OrderItem.selected_modifiers
            ),
            joinedload(models.Order.items).joinedload(models.OrderItem.menu_item),
            joinedload(models.Order.table),
        )
        .filter(
            models.Order.table_id == table_id,
            models.Order.created_at >= awaiting_cutoff,
            models.Order.status.in_(
                [
                    models.OrderStatus.AWAITING_PAYMENT,
                    models.OrderStatus.PENDING,
                    models.OrderStatus.PREPARING,
                    models.OrderStatus.SERVED,
                    models.OrderStatus.COMPLETED,
                ]
            ),
        )
        .order_by(models.Order.created_at.desc())
        .all()
    )
    for order in candidates:
        if cart_fingerprint_from_order(order) != fingerprint:
            continue
        if order.status == models.OrderStatus.AWAITING_PAYMENT:
            return order
        # Already in kitchen — only block immediate cancel/retry duplicates
        if order.created_at >= paid_cutoff:
            return order
    return None


def cancel_awaiting_orders_for_table(
    db: Session, table_id: int, *, keep_order_id: Optional[int] = None
) -> None:
    """Drop unpaid drafts so a changed cart can place a fresh order."""
    from security import restore_order_stock

    awaitings = (
        db.query(models.Order)
        .options(
            joinedload(models.Order.items).joinedload(models.OrderItem.menu_item),
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.selected_modifiers)
            .joinedload(models.OrderItemModifier.modifier),
        )
        .filter(
            models.Order.table_id == table_id,
            models.Order.status == models.OrderStatus.AWAITING_PAYMENT,
        )
        .all()
    )
    for order in awaitings:
        if keep_order_id is not None and order.id == keep_order_id:
            continue
        restore_order_stock(order, db)
        order.status = models.OrderStatus.CANCELLED


def create_order_from_items(
    db: Session,
    table_id: int,
    items: List[OrderItemCreate],
    initial_status: models.OrderStatus = models.OrderStatus.AWAITING_PAYMENT,
) -> models.Order:
    if not items:
        raise HTTPException(status_code=400, detail="Order must include at least one item.")

    total_price = 0.0
    db_order = models.Order(table_id=table_id, status=initial_status)
    db.add(db_order)
    db.flush()

    for item in items:
        menu_item = (
            db.query(models.MenuItem)
            .filter(models.MenuItem.id == item.menu_item_id)
            .first()
        )
        if not menu_item or not menu_item.is_available:
            db.rollback()
            raise HTTPException(
                status_code=400,
                detail=f"Item {item.menu_item_id} is unavailable.",
            )

        if menu_item.stock is not None:
            if menu_item.stock < item.quantity:
                db.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=f"Insufficient stock for {menu_item.name}. (Only {menu_item.stock} left).",
                )
            menu_item.stock -= item.quantity
            if menu_item.stock == 0:
                menu_item.is_available = False

        base_item_price = menu_item.price
        db_order_item = models.OrderItem(
            order_id=db_order.id,
            menu_item_id=item.menu_item_id,
            quantity=item.quantity,
            notes=item.notes,
        )
        db.add(db_order_item)
        db.flush()

        modifier_price_accumulator = 0.0
        for mod_id in item.modifier_ids or []:
            modifier = (
                db.query(models.MenuItemModifier)
                .filter(
                    models.MenuItemModifier.id == mod_id,
                    models.MenuItemModifier.menu_item_id == menu_item.id,
                )
                .first()
            )
            if not modifier:
                db.rollback()
                raise HTTPException(
                    status_code=400,
                    detail=f"Selected modifier ID {mod_id} is invalid for {menu_item.name}.",
                )

            modifier_price_accumulator += modifier.price
            db_item_mod = models.OrderItemModifier(
                order_item_id=db_order_item.id, modifier_id=modifier.id
            )
            db.add(db_item_mod)

        total_price += (base_item_price + modifier_price_accumulator) * item.quantity

    db_order.total_price = total_price
    db.flush()
    return db_order
