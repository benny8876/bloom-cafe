from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Header, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from sqlalchemy import func
from datetime import datetime, time, timezone, timedelta
from typing import Optional, List
import csv, io, shutil, uuid
import os
from database import get_db, SessionLocal
import models, schemas
import security
from services.passwords import hash_password, verify_password, needs_rehash
from services.sessions import create_session, revoke_user_sessions, ROLE_OWNER, ROLE_MANAGER, MANAGER_ROLES
from websocket import manager_ws
from table_labels import RESTAURANT_NAME, get_table_label, COUNTER_TABLE_NUMBER, is_counter_table
from services.analytics import (
    parse_target_date,
    day_bounds,
    month_bounds,
    completed_orders_for_range,
    top_selling_items_for_range,
    bill_amounts,
    income_timestamp,
    resolve_range_bounds,
    add_settled_session_fees,
    add_fee_only_settled_sessions,
    fee_only_settled_sessions_for_range,
    MYANMAR_TZ,
)
from services.orders import (
    create_order_from_items,
    order_item_unit_price,
    recalculate_order_total,
    restore_order_item_stock,
)
from services.table_sessions import (
    ensure_vip_session_started,
    end_table_session,
    format_duration,
    get_active_session,
    get_settled_session_at,
    session_fee_line_item,
    entry_fee_line_item,
    session_summary,
    set_session_guest_count,
)
from services.dining_sessions import close_dining_sessions_for_table
from services.menu_categories import list_menu_categories, move_menu_category, sync_menu_categories
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors

router = APIRouter(prefix="/manager", tags=["Manager Panel"])

verify_manager_token = security.verify_manager_token


@router.post("/login", response_model=schemas.LoginResponse)
def manager_login(credentials: schemas.LoginRequest, db: Session = Depends(get_db)):
    admin = (
        db.query(models.AdminCredential)
        .filter(models.AdminCredential.username == credentials.username)
        .first()
    )
    if not admin or not verify_password(credentials.password, admin.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password.")

    if needs_rehash(admin.password_hash):
        admin.password_hash = hash_password(credentials.password)
        db.commit()

    role = admin.role or ROLE_MANAGER
    if role == "staff":
        role = ROLE_MANAGER
    if role not in (ROLE_OWNER, ROLE_MANAGER):
        role = ROLE_MANAGER

    token = create_session(db, role=role, username=admin.username)
    return schemas.LoginResponse(token=token, role=role, username=admin.username)


@router.post("/logout")
def manager_logout(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    security.logout_token(db, authorization)
    return {"message": "Logged out."}


@router.post("/change-password")
def change_password(
    data: schemas.PasswordChangeRequest,
    db: Session = Depends(get_db),
    session: models.AuthSession = Depends(verify_manager_token),
):
    admin = (
        db.query(models.AdminCredential)
        .filter(models.AdminCredential.username == session.username)
        .first()
    )
    if not admin:
        raise HTTPException(status_code=404, detail="Admin configuration missing.")

    if not verify_password(data.old_password, admin.password_hash):
        raise HTTPException(status_code=400, detail="Incorrect old password.")

    admin.password_hash = hash_password(data.new_password)
    revoke_user_sessions(db, admin.username)
    db.commit()

    return {"message": "Password changed successfully. Please log in again."}


# Create static directories if they don't exist on system startup
UPLOAD_DIR = "static/uploads"
os.makedirs(UPLOAD_DIR, exist_ok=True)


# --- IMAGE UPLOADS ---
@router.post("/upload-image")
def upload_menu_image(
    file: UploadFile = File(...), authenticated: bool = Depends(verify_manager_token)
):
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in [".jpg", ".jpeg", ".png", ".webp"]:
        raise HTTPException(status_code=400, detail="Unsupported file format.")

    unique_filename = f"{uuid.uuid4()}{file_ext}"
    destination_path = os.path.join(UPLOAD_DIR, unique_filename)

    with open(destination_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    return {"image_url": f"/static/uploads/{unique_filename}"}


# --- SECURE TABLE QR GENERATOR ---
@router.get("/generate-token/{table_id}")
def generate_table_qr_token(
    table_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    table = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.id == table_id)
        .first()
    )
    if not table:
        raise HTTPException(status_code=404, detail="Table does not exist.")

    token = security.generate_table_token(table.id)
    return {
        "table_id": table.id,
        "table_number": get_table_label(table),
        "secure_token": token,
        "qr_link": f"/menu?table={table.id}&token={token}",
    }


@router.get("/tables/qr-links")
def get_all_table_qr_links(
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    tables = (
        db.query(models.RestaurantTable)
        .filter(
            models.RestaurantTable.is_active == True,
            models.RestaurantTable.number != COUNTER_TABLE_NUMBER,
        )
        .order_by(models.RestaurantTable.number.asc())
        .all()
    )
    return [
        {
            "table_id": table.id,
            "table_number": get_table_label(table),
            "secure_token": security.generate_table_token(table.id),
            "qr_link": f"/menu?table={table.id}&token={security.generate_table_token(table.id)}",
        }
        for table in tables
    ]


OPEN_TABLE_SESSION_STATUSES = [
    models.OrderStatus.AWAITING_PAYMENT,
    models.OrderStatus.PENDING,
    models.OrderStatus.PREPARING,
    models.OrderStatus.SERVED,
]


def _active_order_table_ids(db: Session) -> set:
    rows = (
        db.query(models.Order.table_id)
        .filter(models.Order.status.in_(OPEN_TABLE_SESSION_STATUSES))
        .distinct()
        .all()
    )
    return {row[0] for row in rows}


def _table_management_payload(table: models.RestaurantTable, active_table_ids: set, db: Session) -> dict:
    active_session = get_active_session(db, table.id)
    payload = {
        "id": table.id,
        "number": table.number,
        "label": get_table_label(table),
        "is_active": table.is_active,
        "has_active_orders": table.id in active_table_ids,
        "is_vip_room": bool(table.is_vip_room),
        "hourly_rate": float(table.hourly_rate or 0),
        "entry_fee_per_guest": float(table.entry_fee_per_guest or 0),
        "minimum_minutes": int(table.minimum_minutes or 30),
        "free_minutes": int(table.free_minutes or 0),
        "active_session": session_summary(active_session) if active_session else None,
    }
    return payload


def _apply_vip_settings(table: models.RestaurantTable, data: schemas.TableCreate | schemas.TableUpdate) -> None:
    fields = data.model_dump(exclude_unset=True)
    if "is_vip_room" in fields:
        table.is_vip_room = fields["is_vip_room"]
    if "hourly_rate" in fields:
        table.hourly_rate = fields["hourly_rate"]
    if "entry_fee_per_guest" in fields:
        table.entry_fee_per_guest = fields["entry_fee_per_guest"]
    if "minimum_minutes" in fields:
        table.minimum_minutes = fields["minimum_minutes"]
    if "free_minutes" in fields:
        table.free_minutes = fields["free_minutes"]


def _append_vip_fee_lines(items_list: list, grand_total: float, session, *, use_charged: bool = False):
    """Insert VIP session/entry fee lines and return (items, grand_total, session_fee, entry_fee, vip_session)."""
    session_fee = 0.0
    entry_fee = 0.0
    vip_session = None
    if not session:
        return items_list, grand_total, session_fee, entry_fee, vip_session

    if use_charged:
        if (session.session_fee_charged or 0) > 0:
            line = session_fee_line_item(session)
            session_fee = float(line["unit_price"])
            items_list.insert(0, line)
            grand_total += session_fee
        entry_line = entry_fee_line_item(session, use_charged=True)
        if entry_line:
            entry_fee = float(entry_line.get("subtotal") or entry_line["unit_price"] * entry_line["quantity"])
            items_list.insert(0, entry_line)
            grand_total += entry_fee
    else:
        vip_session = session_summary(session)
        session_fee = float(vip_session["current_fee"] or 0)
        if session_fee > 0:
            items_list.insert(
                0,
                {
                    "name": (
                        f"VIP Room Session ({vip_session['elapsed_label']}, "
                        f"billed {format_duration(vip_session['billable_minutes'])})"
                    ),
                    "quantity": 1,
                    "unit_price": session_fee,
                    "modifiers": [],
                    "is_session_fee": True,
                },
            )
            grand_total += session_fee
        entry_line = entry_fee_line_item(session, use_charged=False)
        if entry_line:
            entry_fee = float(entry_line.get("subtotal") or 0)
            items_list.insert(0, entry_line)
            grand_total += entry_fee

    return items_list, grand_total, session_fee, entry_fee, vip_session


@router.get("/tables", response_model=List[schemas.TableManagementResponse])
def list_managed_tables(
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    tables = (
        db.query(models.RestaurantTable)
        .filter(
            models.RestaurantTable.is_active == True,
            models.RestaurantTable.number != COUNTER_TABLE_NUMBER,
        )
        .order_by(models.RestaurantTable.number.asc())
        .all()
    )
    active_table_ids = _active_order_table_ids(db)
    return [_table_management_payload(table, active_table_ids, db) for table in tables]


@router.post("/tables", response_model=schemas.TableManagementResponse)
def create_table(
    data: schemas.TableCreate,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    label = data.label.strip()
    if not label:
        raise HTTPException(status_code=400, detail="Table label is required.")

    existing = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.label == label)
        .first()
    )
    if existing:
        raise HTTPException(status_code=400, detail=f"Table label '{label}' already exists.")

    max_number = (
        db.query(func.max(models.RestaurantTable.number))
        .filter(models.RestaurantTable.number != COUNTER_TABLE_NUMBER)
        .scalar()
        or 0
    )

    table = models.RestaurantTable(
        number=max_number + 1,
        label=label,
        is_active=True,
        is_vip_room=data.is_vip_room,
        hourly_rate=data.hourly_rate,
        entry_fee_per_guest=data.entry_fee_per_guest,
        minimum_minutes=data.minimum_minutes,
        free_minutes=data.free_minutes,
    )
    db.add(table)
    db.commit()
    db.refresh(table)
    return _table_management_payload(table, set(), db)


@router.put("/tables/{table_id}", response_model=schemas.TableManagementResponse)
def update_table(
    table_id: int,
    data: schemas.TableUpdate,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    table = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.id == table_id)
        .first()
    )
    if not table or is_counter_table(table):
        raise HTTPException(status_code=404, detail="Table does not exist.")
    if not table.is_active:
        raise HTTPException(status_code=404, detail="Table is not active.")

    label = (data.label or "").strip() if data.label is not None else None
    if data.label is not None:
        if not label:
            raise HTTPException(status_code=400, detail="Table label is required.")
        duplicate = (
            db.query(models.RestaurantTable)
            .filter(
                models.RestaurantTable.label == label,
                models.RestaurantTable.id != table_id,
            )
            .first()
        )
        if duplicate:
            raise HTTPException(status_code=400, detail=f"Table label '{label}' already exists.")
        table.label = label

    _apply_vip_settings(table, data)
    db.commit()
    db.refresh(table)
    active_table_ids = _active_order_table_ids(db)
    return _table_management_payload(table, active_table_ids, db)


def _get_dining_table(db: Session, table_id: int) -> models.RestaurantTable:
    table = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.id == table_id)
        .first()
    )
    if not table or is_counter_table(table) or not table.is_active:
        raise HTTPException(status_code=404, detail="Table does not exist.")
    return table


@router.post("/tables/{table_id}/start-visit")
async def start_vip_visit(
    table_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    table = _get_dining_table(db, table_id)
    if not table.is_vip_room:
        raise HTTPException(
            status_code=400, detail="Start Visit is only available for VIP rooms."
        )

    if _load_active_table_orders(db, table_id):
        raise HTTPException(
            status_code=400,
            detail="Table already has active orders. Open Bill from the floor plan.",
        )

    if get_active_session(db, table_id):
        raise HTTPException(status_code=400, detail="A visit is already in progress.")

    session, started = ensure_vip_session_started(db, table)
    if not session:
        raise HTTPException(status_code=400, detail="Could not start VIP visit.")

    db.commit()
    db.refresh(session)

    if started:
        await manager_ws.broadcast(
            {
                "event": "table_session_started",
                "table_id": table.id,
                "table_number": get_table_label(table),
            }
        )

    return session_summary(session)


@router.patch("/tables/{table_id}/guests")
def update_table_guest_count(
    table_id: int,
    payload: schemas.TableGuestCountUpdate,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    table = _get_dining_table(db, table_id)
    if not table.is_vip_room:
        raise HTTPException(status_code=400, detail="Guest count is only for VIP tables.")

    session = get_active_session(db, table_id)
    if not session:
        session, _ = ensure_vip_session_started(db, table)
    if not session:
        raise HTTPException(
            status_code=400,
            detail="No active VIP visit. Use Start Visit on the floor plan first.",
        )

    # Keep entry fee rate in sync with current table setting for open visits
    session.entry_fee_per_guest_snapshot = float(table.entry_fee_per_guest or 0)
    set_session_guest_count(session, payload.guest_count)
    db.commit()
    db.refresh(session)
    return session_summary(session)


@router.delete("/tables/{table_id}")
def delete_table(
    table_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    table = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.id == table_id)
        .first()
    )
    if not table or is_counter_table(table):
        raise HTTPException(status_code=404, detail="Table does not exist.")
    if not table.is_active:
        raise HTTPException(status_code=404, detail="Table is already removed.")

    active_orders = (
        db.query(models.Order)
        .filter(
            models.Order.table_id == table_id,
            models.Order.status.in_(OPEN_TABLE_SESSION_STATUSES),
        )
        .count()
    )
    if active_orders:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove a table with active orders. Settle or cancel the session first.",
        )

    table.is_active = False
    db.commit()
    return {"message": f"Table {get_table_label(table)} removed."}


# --- INVENTORY LIST (manager panel) ---
@router.get("/menu", response_model=List[schemas.MenuItemResponse])
def list_menu_items(
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    return (
        db.query(models.MenuItem)
        .options(joinedload(models.MenuItem.modifiers))
        .order_by(models.MenuItem.order_index.asc())
        .all()
    )


@router.get("/menu/categories", response_model=List[schemas.MenuCategoryResponse])
def get_manager_menu_categories(
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    return list_menu_categories(db)


@router.post("/menu/categories/move")
def move_manager_menu_category(
    payload: schemas.MenuCategoryMoveRequest,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    if not move_menu_category(db, payload.category, payload.direction):
        raise HTTPException(status_code=400, detail="Could not move category.")
    return {"status": "success"}


# --- INVENTORY CREATION ---
@router.post("/menu", response_model=schemas.MenuItemResponse)
def create_menu_item(
    item: schemas.MenuItemCreate,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    # ၁။ လက်ရှိ Database ထဲမှာ အကြီးဆုံး order_index ကို ရှာမယ်
    # အကယ်၍ Item တစ်ခုမှ မရှိသေးရင် 0 ကို ယူမယ်
    max_index = db.query(func.max(models.MenuItem.order_index)).scalar() or 0
    
    # ၂။ အသစ်ထည့်မယ့် Item ရဲ့ order_index ကို max_index + 1 လို့ သတ်မှတ်လိုက်မယ်
    db_item = models.MenuItem(
        name=item.name,
        description=item.description,
        price=item.price,
        category=item.category,
        kitchen_station=item.kitchen_station,
        is_available=item.is_available,
        stock=item.stock,
        image_url=item.image_url,
        order_index=max_index + 1  # 🔥 ဒီနေရာလေးပဲ အဓိက ပြင်ရတာပါ
    )
    db.add(db_item)
    db.flush() # ID ရဖို့အတွက် flush ခံမယ်

    for mod in item.modifiers:
        db_mod = models.MenuItemModifier(
            menu_item_id=db_item.id, name=mod.name, price=mod.price
        )
        db.add(db_mod)

    sync_menu_categories(db)
    db.commit()
    db.refresh(db_item)
    return db_item


# --- INVENTORY UPDATES ---
@router.put("/menu/{item_id}", response_model=schemas.MenuItemResponse)
def update_menu_item(
    item_id: int,
    updated_item: schemas.MenuItemUpdate,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    db_item = db.query(models.MenuItem).filter(models.MenuItem.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    update_data = updated_item.model_dump(exclude_unset=True)
    modifiers_data = update_data.pop("modifiers", None)

    for key, value in update_data.items():
        setattr(db_item, key, value)

    if modifiers_data is not None:
        db.query(models.MenuItemModifier).filter(
            models.MenuItemModifier.menu_item_id == item_id
        ).delete()
        for mod in modifiers_data:
            db.add(
                models.MenuItemModifier(
                    menu_item_id=item_id,
                    name=mod["name"],
                    price=mod["price"],
                )
            )

    sync_menu_categories(db)
    db.commit()
    db.refresh(db_item)
    return db_item


@router.delete("/menu/{item_id}")
def delete_menu_item(
    item_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    db_item = db.query(models.MenuItem).filter(models.MenuItem.id == item_id).first()
    if not db_item:
        raise HTTPException(status_code=404, detail="Item not found")

    order_refs = (
        db.query(models.OrderItem)
        .filter(models.OrderItem.menu_item_id == item_id)
        .count()
    )
    if order_refs:
        raise HTTPException(
            status_code=400,
            detail="Cannot remove this item because it appears in past orders. Mark it as Sold Out instead.",
        )

    image_url = db_item.image_url
    item_name = db_item.name
    db.delete(db_item)
    db.commit()

    if image_url and image_url.startswith("/static/uploads/"):
        image_path = image_url.lstrip("/")
        if os.path.isfile(image_path):
            os.remove(image_path)

    return {"message": f"Menu item '{item_name}' removed."}


# --- Updated: Category-Aware & Sequential Index Swapping ---
@router.post("/menu/items/{item_id}/move")
async def move_menu_item(
    item_id: int, 
    direction: str, 
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token)
):
    # 1. Locate the current item
    current_item = db.query(models.MenuItem).filter(models.MenuItem.id == item_id).first()
    if not current_item:
        raise HTTPException(status_code=404, detail="Item not found")

    # 2. Fetch all items in the SAME category, sorted by their index and database ID
    items_in_category = db.query(models.MenuItem).filter(
        models.MenuItem.category == current_item.category
    ).order_by(models.MenuItem.order_index.asc(), models.MenuItem.id.asc()).all()

    # 3. Automatically assign sequential order_indices to fix default 0 values and duplicates
    for idx, item in enumerate(items_in_category):
        item.order_index = idx
    db.flush()

    # 4. Find the position of the current item in the sequential list
    current_idx = items_in_category.index(current_item)

    # 5. Determine the target index to swap with based on direction
    if direction == "up" and current_idx > 0:
        target_idx = current_idx - 1
    elif direction == "down" and current_idx < len(items_in_category) - 1:
        target_idx = current_idx + 1
    else:
        # Prevent moving up past the top item or down past the bottom item
        return {"status": "no_change"}

    # 6. Swap indices of current and target items
    target_item = items_in_category[target_idx]
    current_item.order_index, target_item.order_index = target_item.order_index, current_item.order_index

    db.commit()
    return {"status": "success"}


# --- ALL ORDERS LOG ---
@router.get("/orders", response_model=List[schemas.OrderResponse])
def get_all_orders(
    date: Optional[str] = None,
    status: Optional[str] = None,
    table_id: Optional[int] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    query = db.query(models.Order)

    if date:
        try:
            target_date = parse_target_date(date)
        except ValueError:
            raise HTTPException(
                status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
            )
        day_start, day_end = day_bounds(target_date)
        query = query.filter(models.Order.created_at.between(day_start, day_end))

    if status:
        try:
            order_status = models.OrderStatus(status.lower())
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid order status filter.")
        query = query.filter(models.Order.status == order_status)

    if table_id is not None:
        query = query.filter(models.Order.table_id == table_id)

    return query.order_by(models.Order.created_at.desc()).all()


# --- PRINT VOUCHER DOCKET ---
@router.get("/orders/{order_id}/voucher")
def print_voucher(
    order_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    amounts = bill_amounts(order.total_price)
    voucher_data = {
        "restaurant_name": RESTAURANT_NAME,
        "voucher_id": f"REC-{order.id:06d}",
        "timestamp": order.created_at.strftime("%Y-%m-%d %H:%M:%S"),
        "table_number": get_table_label(order.table),
        "items": [
            {
                "name": item.menu_item.name,
                "quantity": item.quantity,
                "unit_price": item.menu_item.price,
                "subtotal": item.quantity * item.menu_item.price,
            }
            for item in order.items
        ],
        **amounts,
        "status": order.status.value,
    }
    return voucher_data


# --- GET LIST OF LIVE TABLES ---
@router.get("/tables/active")
def get_active_tables(
    db: Session = Depends(get_db), authenticated: bool = Depends(verify_manager_token)
):
    active_orders = (
        db.query(models.Order)
        .filter(models.Order.status.in_(OPEN_TABLE_SESSION_STATUSES))
        .all()
    )

    tables_map = {}
    for order in active_orders:
        if is_counter_table(order.table):
            continue
        t_id = order.table.id
        if t_id not in tables_map:
            tables_map[t_id] = {
                "table_id": t_id,
                "table_number": get_table_label(order.table),
                "active_orders_count": 0,
                "total_price": 0.0,
            }
        tables_map[t_id]["active_orders_count"] += 1
        tables_map[t_id]["total_price"] += order.total_price

    return list(tables_map.values())


@router.get("/tables/floor")
def get_table_floor(
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    tables = (
        db.query(models.RestaurantTable)
        .filter(
            models.RestaurantTable.is_active == True,
            models.RestaurantTable.number != COUNTER_TABLE_NUMBER,
        )
        .order_by(models.RestaurantTable.number.asc())
        .all()
    )

    active_orders = (
        db.query(models.Order)
        .filter(models.Order.status.in_(OPEN_TABLE_SESSION_STATUSES))
        .all()
    )

    live_map = {}
    for order in active_orders:
        if is_counter_table(order.table):
            continue
        t_id = order.table_id
        if t_id not in live_map:
            live_map[t_id] = {
                "active_orders_count": 0,
                "total_price": 0.0,
            }
        live_map[t_id]["active_orders_count"] += 1
        live_map[t_id]["total_price"] += order.total_price

    floor = []
    for table in tables:
        live = live_map.get(table.id)
        active_session = get_active_session(db, table.id)
        session_fee = 0.0
        entry_fee = 0.0
        vip_session = None
        if active_session:
            vip_session = session_summary(active_session)
            session_fee = float(vip_session["current_fee"] or 0)
            entry_fee = float(vip_session.get("entry_fee") or 0)

        if live or active_session:
            orders_total = live["total_price"] if live else 0.0
            orders_count = live["active_orders_count"] if live else 0
            entry = {
                "table_id": table.id,
                "table_number": get_table_label(table),
                "status": "live",
                "active_orders_count": orders_count,
                "total_price": orders_total,
                "is_vip_room": bool(table.is_vip_room),
                "visit_only": bool(active_session and not live),
                "session_fee": session_fee,
                "entry_fee": entry_fee,
                "total_with_session": orders_total + session_fee + entry_fee,
                "vip_session": vip_session,
            }
            floor.append(entry)
        else:
            floor.append(
                {
                    "table_id": table.id,
                    "table_number": get_table_label(table),
                    "status": "empty",
                    "active_orders_count": 0,
                    "total_price": 0.0,
                    "is_vip_room": bool(table.is_vip_room),
                    "session_fee": 0.0,
                    "total_with_session": 0.0,
                    "vip_session": None,
                }
            )
    return floor


# --- WALK-IN / COUNTER SALE ---
@router.post("/counter/sale", response_model=schemas.OrderResponse)
async def create_counter_sale(
    data: schemas.CounterSaleCreate,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
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

    order = create_order_from_items(
        db,
        table_id=counter_table.id,
        items=data.items,
        initial_status=models.OrderStatus.PENDING,
    )
    now_settled = datetime.now(MYANMAR_TZ).replace(tzinfo=None)
    order.settled_at = now_settled
    db.commit()
    order = (
        db.query(models.Order)
        .options(
            joinedload(models.Order.table),
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.menu_item),
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.selected_modifiers)
            .joinedload(models.OrderItemModifier.modifier),
        )
        .filter(models.Order.id == order.id)
        .first()
    )

    response_payload = schemas.OrderResponse.model_validate(order).model_dump(mode="json")
    await manager_ws.broadcast({"event": "new_order", "order": response_payload})

    return order


def _load_active_table_orders(db: Session, table_id: int) -> List[models.Order]:
    return (
        db.query(models.Order)
        .options(
            joinedload(models.Order.table),
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.menu_item),
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.selected_modifiers)
            .joinedload(models.OrderItemModifier.modifier),
        )
        .filter(
            models.Order.table_id == table_id,
            models.Order.status.in_(OPEN_TABLE_SESSION_STATUSES),
        )
        .order_by(models.Order.id.asc())
        .all()
    )


def _order_item_payload(item: models.OrderItem) -> dict:
    unit_price = order_item_unit_price(item)
    quantity = item.quantity
    return {
        "order_item_id": item.id,
        "order_id": item.order_id,
        "name": item.menu_item.name,
        "quantity": quantity,
        "unit_price": unit_price,
        "modifiers": [m.modifier.name for m in item.selected_modifiers],
        "subtotal": round(unit_price * quantity, 2),
    }


def _build_adjustable_items(active_orders: List[models.Order]) -> List[dict]:
    adjustable_items = []
    for order in active_orders:
        for item in order.items:
            adjustable_items.append(_order_item_payload(item))
    return adjustable_items


# --- ADJUST ORDER ITEM QTY (before settle) ---
@router.patch("/order-items/{order_item_id}/quantity", response_model=schemas.OrderResponse)
async def adjust_order_item_quantity(
    order_item_id: int,
    data: schemas.OrderItemQuantityAdjust,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    order_item = (
        db.query(models.OrderItem)
        .options(
            joinedload(models.OrderItem.menu_item),
            joinedload(models.OrderItem.selected_modifiers)
            .joinedload(models.OrderItemModifier.modifier),
            joinedload(models.OrderItem.order).joinedload(models.Order.table),
        )
        .filter(models.OrderItem.id == order_item_id)
        .first()
    )
    if not order_item:
        raise HTTPException(status_code=404, detail="Order item not found.")

    order = order_item.order
    if order.status not in OPEN_TABLE_SESSION_STATUSES:
        raise HTTPException(
            status_code=400,
            detail="Can only adjust items on active table orders before settle.",
        )
    if is_counter_table(order.table):
        raise HTTPException(
            status_code=400,
            detail="Counter sales cannot be adjusted here. Use order refund instead.",
        )

    current_qty = order_item.quantity
    new_qty = data.quantity
    if new_qty > current_qty:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot increase quantity before settle. Current quantity is {current_qty}.",
        )

    if new_qty == current_qty:
        return (
            db.query(models.Order)
            .options(
                joinedload(models.Order.table),
                joinedload(models.Order.items)
                .joinedload(models.OrderItem.menu_item),
                joinedload(models.Order.items)
                .joinedload(models.OrderItem.selected_modifiers)
                .joinedload(models.OrderItemModifier.modifier),
            )
            .filter(models.Order.id == order.id)
            .first()
        )

    removed_qty = current_qty - new_qty
    restore_order_item_stock(order_item, removed_qty, db)

    if new_qty == 0:
        db.delete(order_item)
    else:
        order_item.quantity = new_qty

    db.flush()

    remaining_items = (
        db.query(models.OrderItem)
        .filter(models.OrderItem.order_id == order.id)
        .count()
    )
    if remaining_items == 0:
        order.status = models.OrderStatus.CANCELLED
        order.total_price = 0.0
    else:
        recalculate_order_total(order)

    db.commit()

    order = (
        db.query(models.Order)
        .options(
            joinedload(models.Order.table),
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.menu_item),
            joinedload(models.Order.items)
            .joinedload(models.OrderItem.selected_modifiers)
            .joinedload(models.OrderItemModifier.modifier),
        )
        .filter(models.Order.id == order.id)
        .first()
    )

    response_payload = schemas.OrderResponse.model_validate(order).model_dump(mode="json")
    await manager_ws.broadcast({"event": "status_update", "order": response_payload})

    return order


# --- GENERATE UNIFIED MASTER BILL ---
@router.get("/tables/{table_id}/bill")
def get_consolidated_table_bill(
    table_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    active_orders = _load_active_table_orders(db, table_id)
    active_session = get_active_session(db, table_id)

    if active_orders:
        table = active_orders[0].table
    else:
        table = (
            db.query(models.RestaurantTable)
            .filter(models.RestaurantTable.id == table_id)
            .first()
        )
        if not table or is_counter_table(table) or not table.is_active:
            raise HTTPException(status_code=404, detail="Table does not exist.")
        if not (table.is_vip_room and active_session):
            raise HTTPException(status_code=404, detail="No active dining sessions found.")

    consolidated_items = {}
    grand_total = 0.0
    order_ids = []

    for order in active_orders:
        order_ids.append(order.id)
        for item in order.items:
            item_unit_price = order_item_unit_price(item)

            mod_key = "-".join(
                sorted([str(m.modifier_id) for m in item.selected_modifiers])
            )
            item_key = f"{item.menu_item.id}_{mod_key}"

            if item_key not in consolidated_items:
                consolidated_items[item_key] = {
                    "name": item.menu_item.name,
                    "quantity": 0,
                    "unit_price": item_unit_price,
                    "modifiers": [m.modifier.name for m in item.selected_modifiers],
                }

            consolidated_items[item_key]["quantity"] += item.quantity
            grand_total += item_unit_price * item.quantity

    table_num = get_table_label(table)
    items_list = list(consolidated_items.values())

    if table.is_vip_room and active_orders:
        ensure_vip_session_started(db, table)
        db.commit()
        active_session = get_active_session(db, table_id)

    items_list, grand_total, session_fee, entry_fee, vip_session = _append_vip_fee_lines(
        items_list, grand_total, active_session, use_charged=False
    )

    return {
        "restaurant_name": RESTAURANT_NAME,
        "table_id": table_id,
        "table_number": table_num,
        "order_ids": order_ids,
        "timestamp": datetime.now(MYANMAR_TZ).strftime("%Y-%m-%d %H:%M:%S"),
        "items": items_list,
        "adjustable_items": _build_adjustable_items(active_orders),
        "session_fee": session_fee,
        "entry_fee": entry_fee,
        "is_vip_room": bool(table.is_vip_room),
        "visit_only": not active_orders,
        "entry_fee_per_guest": float(
            (vip_session or {}).get("entry_fee_per_guest")
            or (table.entry_fee_per_guest or 0)
        ),
        "guest_count": int((vip_session or {}).get("guest_count") or 0),
        "vip_session": vip_session,
        **bill_amounts(grand_total),
    }


# --- SETTLE TABLE BILL ---
@router.post("/tables/{table_id}/settle")
async def settle_table_bill(
    table_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    active_orders = (
        db.query(models.Order)
        .filter(
            models.Order.table_id == table_id,
            models.Order.status.in_(OPEN_TABLE_SESSION_STATUSES),
        )
        .all()
    )
    active_session = get_active_session(db, table_id)

    if not active_orders and not active_session:
        raise HTTPException(
            status_code=400,
            detail="No active visit or orders found to settle.",
        )

    table = active_orders[0].table if active_orders else _get_dining_table(db, table_id)

    if not active_orders and active_session:
        entry_rate = float(active_session.entry_fee_per_guest_snapshot or 0)
        guests = int(active_session.guest_count or 0)
        if entry_rate > 0 and guests <= 0:
            raise HTTPException(
                status_code=400,
                detail="Set guest count before settling this visit.",
            )

    now_settled_time = datetime.now(MYANMAR_TZ).replace(tzinfo=None)

    for order in active_orders:
        order.status = models.OrderStatus.COMPLETED
        order.settled_at = now_settled_time

    end_table_session(db, table_id, models.TableSessionStatus.SETTLED, as_of=now_settled_time)
    close_dining_sessions_for_table(db, table_id, as_of=now_settled_time)

    db.commit()
    table_label = get_table_label(table)
    await manager_ws.broadcast(
        {"event": "table_settled", "table_id": table_id, "table_number": table_label}
    )
    return {"message": f"Table {table_label} settled."}


@router.post("/tables/{table_id}/cancel")
async def cancel_table_session(
    table_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    active_orders = (
        db.query(models.Order)
        .filter(
            models.Order.table_id == table_id,
            models.Order.status.in_(OPEN_TABLE_SESSION_STATUSES),
        )
        .all()
    )
    active_session = get_active_session(db, table_id)

    if not active_orders and not active_session:
        raise HTTPException(
            status_code=400,
            detail="No active visit or orders found to cancel.",
        )

    table = active_orders[0].table if active_orders else _get_dining_table(db, table_id)
    table_label = get_table_label(table)

    for order in active_orders:
        security.restore_order_stock(order, db)
        order.status = models.OrderStatus.CANCELLED

    end_table_session(db, table_id, models.TableSessionStatus.CANCELLED)
    close_dining_sessions_for_table(db, table_id)

    db.commit()

    for order in active_orders:
        db.refresh(order)
        response_payload = schemas.OrderResponse.model_validate(order).model_dump(mode="json")
        await manager_ws.broadcast({"event": "status_update", "order": response_payload})

    return {"message": f"Table {table_label} session cancelled."}


# --- GET TABLE BILLS HISTORY (daily total per table) ---
@router.get("/tables/settled-history")
def get_settled_tables_history(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    try:
        target_date = parse_target_date(date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )

    range_start, range_end = day_bounds(target_date)

    settled_orders = (
        db.query(models.Order)
        .options(joinedload(models.Order.table))
        .filter(
            models.Order.settled_at.isnot(None),
            models.Order.settled_at.between(range_start, range_end),
            models.Order.status != models.OrderStatus.CANCELLED,
        )
        .order_by(models.Order.settled_at.desc())
        .all()
    )

    table_map: dict = {}
    session_fee_keys: set = set()
    counter_rows: list = []
    target_date_str = target_date.strftime("%Y-%m-%d")

    for order in settled_orders:
        if is_counter_table(order.table):
            counter_rows.append(
                {
                    "table_id": order.table_id,
                    "table_number": f"{get_table_label(order.table)} #{order.id}",
                    "order_count": 1,
                    "total_amount": order.total_price,
                    "order_ids": [order.id],
                    "order_id": order.id,
                    "is_counter_sale": True,
                    "date": target_date_str,
                    "settled_at": order.settled_at.isoformat(),
                }
            )
            continue

        if order.status != models.OrderStatus.COMPLETED:
            continue

        t_id = order.table_id
        if t_id not in table_map:
            table_map[t_id] = {
                "table_id": t_id,
                "table_number": get_table_label(order.table),
                "order_count": 0,
                "total_amount": 0.0,
                "order_ids": [],
                "order_id": None,
                "is_counter_sale": False,
                "date": target_date_str,
            }
        row = table_map[t_id]
        row["order_count"] += 1
        row["total_amount"] += order.total_price
        row["order_ids"].append(order.id)

        fee_key = (t_id, order.settled_at.isoformat())
        if fee_key not in session_fee_keys:
            session_fee_keys.add(fee_key)
            table_session = get_settled_session_at(db, t_id, order.settled_at)
            if table_session:
                row["total_amount"] += float(table_session.session_fee_charged or 0)
                row["total_amount"] += float(table_session.entry_fee_charged or 0)

    dining_rows = sorted(
        table_map.values(),
        key=lambda row: (-row["total_amount"], row["table_number"]),
    )

    for session in fee_only_settled_sessions_for_range(db, range_start, range_end):
        table = (
            db.query(models.RestaurantTable)
            .filter(models.RestaurantTable.id == session.table_id)
            .first()
        )
        if not table or is_counter_table(table):
            continue
        total_amount = float(session.session_fee_charged or 0) + float(
            session.entry_fee_charged or 0
        )
        dining_rows.append(
            {
                "table_id": session.table_id,
                "table_number": get_table_label(table),
                "order_count": 0,
                "total_amount": total_amount,
                "order_ids": [],
                "order_id": None,
                "is_counter_sale": False,
                "is_visit_only": True,
                "date": target_date_str,
                "settled_at": session.ended_at.isoformat(),
            }
        )

    dining_rows.sort(key=lambda row: (-row["total_amount"], row["table_number"]))
    counter_rows.sort(key=lambda row: row["settled_at"], reverse=True)

    return counter_rows + dining_rows


# --- DYNAMICALLY RECONSTRUCT COMPLETED TABLE BILLS ---
@router.get("/tables/{table_id}/historical-bill")
def get_historical_table_bill(
    table_id: int,
    settled_at: str,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    try:
        settled_datetime = datetime.fromisoformat(settled_at)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid ISO date format.")

    orders = (
        db.query(models.Order)
        .filter(
            models.Order.table_id == table_id,
            models.Order.status == models.OrderStatus.COMPLETED,
            models.Order.settled_at == settled_datetime,
        )
        .all()
    )

    table_session = get_settled_session_at(db, table_id, settled_datetime)
    if not orders:
        if not table_session:
            raise HTTPException(status_code=404, detail="No historical records found.")
        table = (
            db.query(models.RestaurantTable)
            .filter(models.RestaurantTable.id == table_id)
            .first()
        )
        if not table:
            raise HTTPException(status_code=404, detail="Table does not exist.")
        table_num = get_table_label(table)
        items_list: list = []
        grand_total = 0.0
        order_ids: list = []
    else:
        consolidated_items = {}
        grand_total = 0.0
        order_ids = []

        for order in orders:
            order_ids.append(order.id)
            for item in order.items:
                item_unit_price = item.menu_item.price
                for mod_assoc in item.selected_modifiers:
                    item_unit_price += mod_assoc.modifier.price

                mod_key = "-".join(
                    sorted([str(m.modifier_id) for m in item.selected_modifiers])
                )
                item_key = f"{item.menu_item.id}_{mod_key}"

                if item_key not in consolidated_items:
                    consolidated_items[item_key] = {
                        "name": item.menu_item.name,
                        "quantity": 0,
                        "unit_price": item_unit_price,
                        "modifiers": [m.modifier.name for m in item.selected_modifiers],
                    }

                consolidated_items[item_key]["quantity"] += item.quantity
                grand_total += item_unit_price * item.quantity

        table_num = get_table_label(orders[0].table)
        items_list = list(consolidated_items.values())

    items_list, grand_total, session_fee, entry_fee, _vip = _append_vip_fee_lines(
        items_list, grand_total, table_session, use_charged=True
    )

    return {
        "restaurant_name": RESTAURANT_NAME,
        "table_id": table_id,
        "table_number": table_num,
        "order_ids": order_ids,
        "timestamp": settled_datetime.strftime("%Y-%m-%d %H:%M:%S"),
        "items": items_list,
        "session_fee": session_fee,
        "entry_fee": entry_fee,
        **bill_amounts(grand_total),
    }


@router.get("/tables/{table_id}/daily-bill")
def get_daily_table_bill(
    table_id: int,
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    try:
        target_date = parse_target_date(date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )

    range_start, range_end = day_bounds(target_date)
    orders = (
        db.query(models.Order)
        .options(joinedload(models.Order.table))
        .filter(
            models.Order.table_id == table_id,
            models.Order.status == models.OrderStatus.COMPLETED,
            models.Order.settled_at.isnot(None),
            models.Order.settled_at.between(range_start, range_end),
        )
        .order_by(models.Order.settled_at.asc())
        .all()
    )

    if not orders:
        raise HTTPException(status_code=404, detail="No settled sales for this table on that date.")

    consolidated_items = {}
    grand_total = 0.0
    order_ids = []
    session_fee_keys: set = set()
    session_fee_total = 0.0
    items_list = []

    for order in orders:
        order_ids.append(order.id)
        for item in order.items:
            item_unit_price = item.menu_item.price
            for mod_assoc in item.selected_modifiers:
                item_unit_price += mod_assoc.modifier.price

            mod_key = "-".join(
                sorted([str(m.modifier_id) for m in item.selected_modifiers])
            )
            item_key = f"{item.menu_item.id}_{mod_key}"

            if item_key not in consolidated_items:
                consolidated_items[item_key] = {
                    "name": item.menu_item.name,
                    "quantity": 0,
                    "unit_price": item_unit_price,
                    "modifiers": [m.modifier.name for m in item.selected_modifiers],
                }

            consolidated_items[item_key]["quantity"] += item.quantity
            grand_total += item_unit_price * item.quantity

        fee_key = order.settled_at.isoformat()
        if fee_key not in session_fee_keys:
            session_fee_keys.add(fee_key)
            table_session = get_settled_session_at(db, table_id, order.settled_at)
            if table_session:
                if (table_session.session_fee_charged or 0) > 0:
                    session_line = session_fee_line_item(table_session)
                    items_list.append(session_line)
                    session_fee_total += session_line["unit_price"]
                    grand_total += session_line["unit_price"]
                entry_line = entry_fee_line_item(table_session, use_charged=True)
                if entry_line:
                    fee = float(entry_line.get("subtotal") or 0)
                    items_list.append(entry_line)
                    grand_total += fee

    table_num = get_table_label(orders[0].table)
    items_list.extend(consolidated_items.values())

    return {
        "restaurant_name": RESTAURANT_NAME,
        "table_id": table_id,
        "table_number": table_num,
        "order_ids": order_ids,
        "timestamp": target_date.strftime("%Y-%m-%d"),
        "items": items_list,
        "session_fee": session_fee_total,
        **bill_amounts(grand_total),
    }


# --- DAILY FINANCIAL ANALYTICS ---
@router.get("/analytics/daily", response_model=schemas.DailyAnalytics)
def get_daily_analytics(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    try:
        target_date = parse_target_date(date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )

    day_start, day_end = day_bounds(target_date)
    month_start, month_end = month_bounds(target_date)

    completed_orders = completed_orders_for_range(db, day_start, day_end)
    monthly_orders = completed_orders_for_range(db, month_start, month_end)

    revenue_orders = sum(order.total_price for order in completed_orders)
    revenue_monthly_orders = sum(order.total_price for order in monthly_orders)
    session_fees_day = add_settled_session_fees(db, completed_orders)
    session_fees_month = add_settled_session_fees(db, monthly_orders)
    session_fees_day += add_fee_only_settled_sessions(db, day_start, day_end)
    session_fees_month += add_fee_only_settled_sessions(db, month_start, month_end)
    total_revenue = revenue_orders + session_fees_day
    total_monthly_revenue = revenue_monthly_orders + session_fees_month

    popular_items = top_selling_items_for_range(db, day_start, day_end, limit=5)
    top_selling = [{"name": item[0], "sold_qty": item[1]} for item in popular_items]

    return schemas.DailyAnalytics(
        date=target_date.strftime("%Y-%m-%d"),
        total_revenue=round(total_revenue, 2),
        total_monthly_revenue=round(total_monthly_revenue, 2),
        total_orders_completed=len(completed_orders),
        top_selling_items=top_selling,
    )


# --- PDF Business Summary Exporter ---
@router.get("/analytics/export")
def export_daily_report(
    date: Optional[str] = None,
    range: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(verify_manager_token),
):
    try:
        range_start, range_end, label = resolve_range_bounds(date, range)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    range_key = (range or "day").lower()
    period_orders = completed_orders_for_range(db, range_start, range_end)
    revenue_orders = sum(order.total_price for order in period_orders)
    session_fees = add_settled_session_fees(db, period_orders)
    session_fees += add_fee_only_settled_sessions(db, range_start, range_end)
    total_revenue = revenue_orders + session_fees
    total_transactions = len(period_orders)
    show_date_column = range_key != "day"

    popular_items = top_selling_items_for_range(
        db, range_start, range_end, limit=5
    )

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()
    primary_color = colors.HexColor("#301f16")
    secondary_color = colors.HexColor("#6f8a38")

    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontName="Helvetica-Bold",
        fontSize=18,
        textColor=primary_color,
        spaceAfter=4,
    )
    subtitle_style = ParagraphStyle(
        "DocSubtitle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#666666"),
        spaceAfter=12,
    )
    section_style = ParagraphStyle(
        "Section",
        parent=styles["Heading2"],
        fontName="Helvetica-Bold",
        fontSize=11,
        textColor=secondary_color,
        spaceBefore=10,
        spaceAfter=6,
    )

    story = [
        Paragraph("Operations Report", title_style),
        Paragraph(label, subtitle_style),
        Paragraph("Summary", section_style),
    ]

    summary_rows = [
        ["Total revenue", f"{total_revenue:,.0f} Ks"],
        ["Bills", str(total_transactions)],
    ]

    summary_table = Table(summary_rows, colWidths=[200, 120])
    summary_table.setStyle(
        TableStyle(
            [
                ("FONTNAME", (0, 0), (0, -1), "Helvetica"),
                ("FONTNAME", (1, 0), (1, -1), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 10),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                ("TOPPADDING", (0, 0), (-1, -1), 6),
                ("LINEBELOW", (0, 0), (-1, -2), 0.25, colors.lightgrey),
            ]
        )
    )
    story.extend([summary_table, Spacer(1, 12), Paragraph("Bills", section_style)])

    if show_date_column:
        bill_header = ["Date", "Order", "Table", "Amount (Ks)"]
        col_widths = [70, 55, 90, 95]
    else:
        bill_header = ["Time", "Order", "Table", "Amount (Ks)"]
        col_widths = [55, 55, 90, 95]

    bill_data = [bill_header]
    if not period_orders:
        bill_data.append(["—", "—", "—", "0"])
    else:
        for order in period_orders:
            when = income_timestamp(order)
            bill_data.append(
                [
                    when.strftime("%Y-%m-%d") if show_date_column else when.strftime("%H:%M"),
                    f"#{order.id}",
                    get_table_label(order.table),
                    f"{order.total_price:,.0f}",
                ]
            )
        bill_data.append(["TOTAL", "", "", f"{total_revenue:,.0f}"])

    bill_table = Table(bill_data, colWidths=col_widths)
    bill_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), primary_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
                ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f3f4f6")),
                ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ]
        )
    )
    story.extend([bill_table, Spacer(1, 12), Paragraph("Top items", section_style)])

    if popular_items:
        items_data = [["Item", "Qty"]] + [
            [name, str(qty)] for name, qty in popular_items
        ]
    else:
        items_data = [["Item", "Qty"], ["No sales in this period", "0"]]

    items_table = Table(items_data, colWidths=[250, 80])
    items_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), secondary_color),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, -1), 9),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ]
        )
    )
    story.append(items_table)

    doc.build(story)
    buffer.seek(0)

    safe_label = label.replace(" ", "_").replace("→", "to")
    filename = f"operations_{range_key}_{safe_label}.pdf"
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(buffer, media_type="application/pdf", headers=headers)


@router.websocket("/ws")
async def manager_websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    db = SessionLocal()
    try:
        if not security.verify_ws_token(db, token, MANAGER_ROLES):
            await security.reject_unauthorized_ws(
                websocket, "Manager authentication required"
            )
            return

        await manager_ws.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"LOG: [Manager WebSocket] Unexpected connection break: {e}")
        finally:
            manager_ws.disconnect(websocket)
    finally:
        db.close()