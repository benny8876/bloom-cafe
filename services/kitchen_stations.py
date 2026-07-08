"""Kitchen station routing: coffee bar vs food kitchen."""

import os
from typing import Iterable, List, Optional, Set

import models
from schemas import OrderResponse

DEFAULT_COFFEE_CATEGORIES = frozenset(
    {
        "coffee",
        "drinks",
        "drink",
        "milkshakes",
        "milkshake",
        "tea",
        "beverages",
        "beverage",
    }
)

VALID_STATIONS = frozenset({"coffee", "food"})


def coffee_categories() -> Set[str]:
    raw = os.getenv("KITCHEN_COFFEE_CATEGORIES", "")
    if raw.strip():
        return {part.strip().lower() for part in raw.split(",") if part.strip()}
    return set(DEFAULT_COFFEE_CATEGORIES)


def station_for_category(category: Optional[str]) -> str:
    name = (category or "").strip().lower()
    if name in coffee_categories():
        return "coffee"
    return "food"


def normalize_station(station: str) -> str:
    value = (station or "").strip().lower()
    if value not in VALID_STATIONS:
        raise ValueError(f"Invalid kitchen station: {station}")
    return value


def station_for_menu_item(menu_item: Optional[models.MenuItem]) -> str:
    if menu_item is None:
        return "food"
    if menu_item.kitchen_station:
        try:
            return normalize_station(menu_item.kitchen_station)
        except ValueError:
            pass
    return station_for_category(menu_item.category)


def order_item_station(order_item: models.OrderItem) -> str:
    return station_for_menu_item(order_item.menu_item)


def order_has_station_items(order: models.Order, station: str) -> bool:
    target = normalize_station(station)
    return any(order_item_station(item) == target for item in order.items)


def filter_order_for_station(order: models.Order, station: str) -> Optional[OrderResponse]:
    target = normalize_station(station)
    station_items = [item for item in order.items if order_item_station(item) == target]
    if not station_items:
        return None

    payload = OrderResponse.model_validate(order).model_dump(mode="python")
    station_item_ids = {item.id for item in station_items}
    payload["items"] = [item for item in payload["items"] if item["id"] in station_item_ids]
    return OrderResponse.model_validate(payload)


def filter_orders_for_station(
    orders: Iterable[models.Order], station: str
) -> List[OrderResponse]:
    filtered: List[OrderResponse] = []
    for order in orders:
        station_order = filter_order_for_station(order, station)
        if station_order is not None:
            filtered.append(station_order)
    return filtered
