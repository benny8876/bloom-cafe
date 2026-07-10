from typing import List

from sqlalchemy import func
from sqlalchemy.orm import Session

import models


def sync_menu_categories(db: Session) -> None:
    """Ensure every menu item category has a row in menu_categories."""
    item_categories = (
        db.query(
            models.MenuItem.category,
            func.min(models.MenuItem.order_index).label("min_order"),
        )
        .group_by(models.MenuItem.category)
        .all()
    )
    if not item_categories:
        return

    existing = {row.name: row for row in db.query(models.MenuCategory).all()}
    max_index = db.query(func.max(models.MenuCategory.order_index)).scalar()
    next_index = max_index if max_index is not None else -1

    for category_name, _min_order in sorted(
        item_categories, key=lambda row: (row.min_order or 0, row.category)
    ):
        if category_name in existing:
            continue
        next_index += 1
        db.add(models.MenuCategory(name=category_name, order_index=next_index))

    db.commit()


def _categories_with_items(db: Session) -> List[models.MenuCategory]:
    item_categories = {
        row[0]
        for row in db.query(models.MenuItem.category).distinct().all()
        if row[0]
    }
    rows = (
        db.query(models.MenuCategory)
        .filter(models.MenuCategory.name.in_(item_categories))
        .order_by(models.MenuCategory.order_index.asc(), models.MenuCategory.id.asc())
        .all()
    )
    for idx, row in enumerate(rows):
        row.order_index = idx
    db.flush()
    return rows


def list_menu_categories(db: Session) -> List[models.MenuCategory]:
    sync_menu_categories(db)
    return _categories_with_items(db)


def get_category_order_map(db: Session) -> dict[str, int]:
    return {row.name: row.order_index for row in list_menu_categories(db)}


def move_menu_category(db: Session, category_name: str, direction: str) -> bool:
    sync_menu_categories(db)
    rows = _categories_with_items(db)

    try:
        current_idx = next(i for i, row in enumerate(rows) if row.name == category_name)
    except StopIteration:
        return False

    if direction == "up" and current_idx > 0:
        target_idx = current_idx - 1
    elif direction == "down" and current_idx < len(rows) - 1:
        target_idx = current_idx + 1
    else:
        return False

    rows[current_idx].order_index, rows[target_idx].order_index = (
        rows[target_idx].order_index,
        rows[current_idx].order_index,
    )
    db.commit()
    return True
