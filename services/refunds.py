"""Refund completed counter sales, entry checkouts, and settled table bills."""

from datetime import datetime
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

import models
import security
from services.analytics import bill_amounts, settlement_discount_amount
from table_labels import is_counter_table
from services.table_sessions import get_settled_session_at


def _is_entry_checkout(order: models.Order) -> bool:
    return order.payment_method == "entry_checkout"


def _is_refundable_order(order: models.Order) -> bool:
    if not order.settled_at:
        return False
    if order.status == models.OrderStatus.REFUNDED:
        return False
    if order.status == models.OrderStatus.CANCELLED:
        return False
    if _is_entry_checkout(order):
        return True
    if is_counter_table(order.table):
        return True
    return False


def order_refund_amount(order: models.Order) -> float:
    return round(float(order.total_price or 0) - float(order.discount_amount or 0), 2)


def table_settlement_refund_amount(
    db: Session,
    table_id: int,
    settled_at: datetime,
    orders: list[models.Order],
    table_session: Optional[models.TableSession],
) -> float:
    subtotal = sum(float(order.total_price or 0) for order in orders)
    if table_session:
        subtotal += float(table_session.session_fee_charged or 0)
        subtotal += float(table_session.entry_fee_charged or 0)
        discount_percent = float(table_session.discount_percent or 0)
    elif orders:
        discount_percent = float(orders[0].discount_percent or 0)
        if discount_percent <= 0:
            discount_amount = settlement_discount_amount(db, table_id, settled_at)
            return round(subtotal - discount_amount, 2)
    else:
        discount_percent = 0.0

    return bill_amounts(subtotal, discount_percent)["grand_total"]


def refund_order(
    db: Session,
    order_id: int,
    *,
    reason: Optional[str] = None,
    restore_stock: bool = False,
    refunded_by: Optional[str] = None,
) -> models.Refund:
    order = (
        db.query(models.Order)
        .options(
            joinedload(models.Order.table),
            joinedload(models.Order.items).joinedload(models.OrderItem.menu_item),
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.selected_modifiers)
            .joinedload(models.OrderItemModifier.modifier),
        )
        .filter(models.Order.id == order_id)
        .first()
    )
    if not order:
        raise HTTPException(status_code=404, detail="Order not found.")
    if not _is_refundable_order(order):
        raise HTTPException(
            status_code=400,
            detail="Only completed counter sales or entry checkouts can be refunded.",
        )

    amount = order_refund_amount(order)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Nothing to refund for this order.")

    if restore_stock and not _is_entry_checkout(order):
        security.restore_order_stock(order, db)

    order.status = models.OrderStatus.REFUNDED
    refund = models.Refund(
        refund_type=models.RefundType.ORDER,
        order_id=order.id,
        table_id=order.table_id,
        settled_at_ref=order.settled_at,
        amount=amount,
        reason=(reason or "").strip() or None,
        refunded_by=refunded_by,
        restore_stock=bool(restore_stock),
    )
    db.add(refund)
    db.flush()
    return refund


def refund_table_settlement(
    db: Session,
    table_id: int,
    settled_at: datetime,
    *,
    reason: Optional[str] = None,
    restore_stock: bool = False,
    refunded_by: Optional[str] = None,
) -> models.Refund:
    table = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.id == table_id)
        .first()
    )
    if not table:
        raise HTTPException(status_code=404, detail="Table not found.")
    if is_counter_table(table):
        raise HTTPException(
            status_code=400,
            detail="Use order refund for counter sales.",
        )

    table_session = get_settled_session_at(db, table_id, settled_at)
    if table_session and table_session.refunded_at:
        raise HTTPException(status_code=400, detail="This table settlement was already refunded.")

    orders = (
        db.query(models.Order)
        .options(
            joinedload(models.Order.items).joinedload(models.OrderItem.menu_item),
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.selected_modifiers)
            .joinedload(models.OrderItemModifier.modifier),
        )
        .filter(
            models.Order.table_id == table_id,
            models.Order.settled_at == settled_at,
            models.Order.status.in_(
                [
                    models.OrderStatus.COMPLETED,
                    models.OrderStatus.PENDING,
                ]
            ),
        )
        .all()
    )

    if not orders and not table_session:
        raise HTTPException(status_code=404, detail="No settled bill found for this table and time.")

    if any(order.status == models.OrderStatus.REFUNDED for order in orders):
        raise HTTPException(status_code=400, detail="This table settlement was already refunded.")

    amount = table_settlement_refund_amount(db, table_id, settled_at, orders, table_session)
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Nothing to refund for this settlement.")

    if restore_stock:
        for order in orders:
            if not _is_entry_checkout(order):
                security.restore_order_stock(order, db)

    now = models.get_yangon_now()
    for order in orders:
        order.status = models.OrderStatus.REFUNDED

    if table_session:
        table_session.refunded_at = now

    refund = models.Refund(
        refund_type=models.RefundType.TABLE_SETTLE,
        order_id=None,
        table_id=table_id,
        settled_at_ref=settled_at,
        amount=amount,
        reason=(reason or "").strip() or None,
        refunded_by=refunded_by,
        restore_stock=bool(restore_stock),
    )
    db.add(refund)
    db.flush()
    return refund


def refunds_for_range(
    db: Session, start: datetime, end: datetime
) -> list[models.Refund]:
    return (
        db.query(models.Refund)
        .options(
            joinedload(models.Refund.order).joinedload(models.Order.table),
            joinedload(models.Refund.table),
        )
        .filter(models.Refund.created_at.between(start, end))
        .order_by(models.Refund.created_at.desc())
        .all()
    )


def refunds_total_for_range(db: Session, start: datetime, end: datetime) -> float:
    rows = (
        db.query(models.Refund)
        .filter(models.Refund.created_at.between(start, end))
        .with_entities(models.Refund.amount)
        .all()
    )
    return round(sum(float(row[0] or 0) for row in rows), 2)


def refund_original_settled_at(refund: models.Refund) -> Optional[datetime]:
    if refund.settled_at_ref:
        return refund.settled_at_ref
    if refund.order:
        return refund.order.settled_at
    return None


def refunds_revenue_adjustment_for_range(
    db: Session, start: datetime, end: datetime
) -> float:
    """Subtract refunds processed in range when the original sale was in another period."""
    total = 0.0
    for refund in refunds_for_range(db, start, end):
        settled = refund_original_settled_at(refund)
        if settled and start <= settled <= end:
            continue
        total += float(refund.amount or 0)
    return round(total, 2)


def refund_kind_code(refund: models.Refund) -> str:
    if refund.refund_type == models.RefundType.TABLE_SETTLE:
        return "table"
    order = refund.order
    if order and order.payment_method == "entry_checkout":
        return "entry"
    return "counter"


def refund_reference_label(refund: models.Refund) -> str:
    from table_labels import get_table_label

    if refund.refund_type == models.RefundType.TABLE_SETTLE:
        table = refund.table
        label = get_table_label(table) if table else f"Table #{refund.table_id}"
        if refund.settled_at_ref:
            return f"{label} · {refund.settled_at_ref.strftime('%Y-%m-%d %H:%M')}"
        return label
    if refund.order_id:
        order = refund.order
        if order and order.payment_method == "entry_checkout":
            return f"Photo Entry #{refund.order_id}"
        return f"Order #{refund.order_id}"
    return f"Refund #{refund.id}"


def is_order_refunded(order: models.Order) -> bool:
    return order.status == models.OrderStatus.REFUNDED


def is_table_settlement_refunded(
    db: Session, table_id: int, settled_at: datetime
) -> bool:
    session = get_settled_session_at(db, table_id, settled_at)
    if session and session.refunded_at:
        return True
    refunded_order = (
        db.query(models.Order.id)
        .filter(
            models.Order.table_id == table_id,
            models.Order.settled_at == settled_at,
            models.Order.status == models.OrderStatus.REFUNDED,
        )
        .first()
    )
    return refunded_order is not None


def refundable_order_kind(order: models.Order) -> Optional[str]:
    if not _is_refundable_order(order):
        return None
    if _is_entry_checkout(order):
        return "entry"
    if is_counter_table(order.table):
        return "counter"
    return None
