"""Counter photo-entry checkout (per-guest fee before table dining)."""

from datetime import datetime

from fastapi import HTTPException
from sqlalchemy.orm import Session, joinedload

import models
from schemas import OrderItemCreate
from services.analytics import bill_amounts
from services.orders import create_order_from_items
from table_labels import COUNTER_TABLE_NUMBER, RESTAURANT_NAME, get_table_label

ENTRY_ITEM_CATEGORY = "_pos_entry"
ENTRY_ITEM_NAME = "Photo Entry"
MYANMAR_TZ = models.MYANMAR_TZ


def is_pos_only_menu_item(item: models.MenuItem) -> bool:
    return (item.category or "").startswith("_pos")


def get_shop_settings(db: Session) -> models.ShopSettings:
    row = db.query(models.ShopSettings).filter(models.ShopSettings.id == 1).first()
    if not row:
        row = models.ShopSettings(id=1, entry_fee_per_guest=0.0)
        db.add(row)
        db.flush()
    return row


def ensure_entry_menu_item(db: Session) -> models.MenuItem:
    settings = get_shop_settings(db)
    rate = float(settings.entry_fee_per_guest or 0)
    item = (
        db.query(models.MenuItem)
        .filter(
            models.MenuItem.category == ENTRY_ITEM_CATEGORY,
            models.MenuItem.name == ENTRY_ITEM_NAME,
        )
        .first()
    )
    price = max(rate, 1.0)
    if not item:
        item = models.MenuItem(
            name=ENTRY_ITEM_NAME,
            price=price,
            category=ENTRY_ITEM_CATEGORY,
            kitchen_station="coffee",
            is_available=True,
            description="Counter photo entry (manager POS only)",
        )
        db.add(item)
    elif rate > 0 and float(item.price) != rate:
        item.price = rate
    db.flush()
    return item


def sync_entry_menu_price(db: Session, entry_fee_per_guest: float) -> models.MenuItem:
    settings = get_shop_settings(db)
    settings.entry_fee_per_guest = float(entry_fee_per_guest or 0)
    item = ensure_entry_menu_item(db)
    if settings.entry_fee_per_guest > 0:
        item.price = settings.entry_fee_per_guest
    db.flush()
    return item


def entry_checkout_receipt(order: models.Order, guest_count: int) -> dict:
    amounts = bill_amounts(order.total_price)
    item = order.items[0] if order.items else None
    line_name = f"{ENTRY_ITEM_NAME} × {guest_count}"
    unit_price = float(item.menu_item.price) if item else order.total_price / max(guest_count, 1)
    return {
        "restaurant_name": RESTAURANT_NAME,
        "voucher_id": f"ENT-{order.id:06d}",
        "timestamp": (order.settled_at or order.created_at).strftime("%Y-%m-%d %H:%M:%S"),
        "table_number": "Photo Entry",
        "items": [
            {
                "name": line_name,
                "quantity": guest_count,
                "unit_price": unit_price,
                "subtotal": float(order.total_price),
            }
        ],
        **amounts,
        "status": order.status.value,
        "is_entry_checkout": True,
    }


def create_entry_checkout(db: Session, guest_count: int) -> tuple[models.Order, dict]:
    guests = int(guest_count or 0)
    if guests < 1:
        raise HTTPException(status_code=400, detail="At least 1 guest is required.")

    settings = get_shop_settings(db)
    rate = float(settings.entry_fee_per_guest or 0)
    if rate <= 0:
        raise HTTPException(
            status_code=400,
            detail="Entry fee per guest is not set. Enter a rate and save first.",
        )

    counter_table = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.number == COUNTER_TABLE_NUMBER)
        .first()
    )
    if not counter_table:
        raise HTTPException(
            status_code=500,
            detail="Counter table is not configured. Restart the server to seed it.",
        )

    menu_item = sync_entry_menu_price(db, rate)
    order = create_order_from_items(
        db,
        table_id=counter_table.id,
        items=[OrderItemCreate(menu_item_id=menu_item.id, quantity=guests)],
        initial_status=models.OrderStatus.COMPLETED,
    )
    now = datetime.now(MYANMAR_TZ).replace(tzinfo=None)
    order.settled_at = now
    order.payment_method = "entry_checkout"
    db.commit()

    order = (
        db.query(models.Order)
        .options(
            joinedload(models.Order.table),
            joinedload(models.Order.items).joinedload(models.OrderItem.menu_item),
        )
        .filter(models.Order.id == order.id)
        .first()
    )
    return order, entry_checkout_receipt(order, guests)


def entry_checkout_stats_for_range(
    db: Session, start: datetime, end: datetime
) -> tuple[int, int]:
    """Return (checkout_count, total_guests) for entry checkouts in range."""
    from sqlalchemy.orm import joinedload

    orders = (
        db.query(models.Order)
        .options(joinedload(models.Order.items))
        .filter(
            models.Order.payment_method == "entry_checkout",
            models.Order.status.notin_(
                [models.OrderStatus.CANCELLED, models.OrderStatus.REFUNDED]
            ),
            models.Order.settled_at.isnot(None),
            models.Order.settled_at.between(start, end),
        )
        .all()
    )
    guests = sum(
        int(item.quantity or 0) for order in orders for item in (order.items or [])
    )
    return len(orders), guests
