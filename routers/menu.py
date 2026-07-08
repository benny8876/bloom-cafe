from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List
from database import get_db
import models, schemas
from websocket import manager_ws
import security
from table_labels import get_table_label
from services.orders import create_order_from_items
from services.table_sessions import ensure_vip_session_started

router = APIRouter(prefix="/menu", tags=["Menu (Client)"])


@router.get("/", response_model=List[schemas.MenuItemResponse])
def get_available_menu(db: Session = Depends(get_db)):
    return (
        db.query(models.MenuItem)
        .filter(models.MenuItem.is_available == True)
        .order_by(models.MenuItem.order_index.asc())
        .all()
    )


@router.post("/order", response_model=schemas.OrderResponse, status_code=status.HTTP_201_CREATED)
async def place_order(order_data: schemas.OrderCreate, db: Session = Depends(get_db)):
    if not security.verify_table_token(order_data.table_id, order_data.token):
        raise HTTPException(
            status_code=403, detail="Invalid table token. Table verification failed."
        )

    table = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.id == order_data.table_id)
        .first()
    )
    if not table or not table.is_active:
        raise HTTPException(status_code=404, detail="Selected table is inactive or missing.")

    db_order = create_order_from_items(
        db,
        table_id=order_data.table_id,
        items=order_data.items,
        initial_status=models.OrderStatus.AWAITING_PAYMENT,
    )
    _, session_started = ensure_vip_session_started(db, table)
    db.commit()
    db.refresh(db_order)

    if session_started:
        await manager_ws.broadcast(
            {
                "event": "table_session_started",
                "table_id": table.id,
                "table_number": get_table_label(table),
            }
        )

    return db_order


@router.post("/order/{order_id}/mock-pay", response_model=schemas.OrderResponse)
async def process_mock_payment(
    order_id: int,
    payment_data: schemas.MockPayRequest,
    db: Session = Depends(get_db),
):
    if not security.verify_table_token(payment_data.table_id, payment_data.token):
        raise HTTPException(status_code=403, detail="Invalid table token.")

    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Target order does not exist.")
    if order.table_id != payment_data.table_id:
        raise HTTPException(status_code=403, detail="Order does not belong to this table.")
    if order.status != models.OrderStatus.AWAITING_PAYMENT:
        raise HTTPException(status_code=400, detail="Order has already been processed/paid.")

    order.status = models.OrderStatus.PENDING
    db.commit()
    db.refresh(order)

    response_payload = schemas.OrderResponse.model_validate(order).model_dump(mode="json")
    await manager_ws.broadcast({"event": "new_order", "order": response_payload})

    return order


@router.post("/call-waiter")
async def call_waiter(
    table_id: int,
    request_type: str,
    token: str,
    db: Session = Depends(get_db),
):
    if not security.verify_table_token(table_id, token):
        raise HTTPException(status_code=403, detail="Invalid table token.")

    table = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.id == table_id)
        .first()
    )
    if not table:
        raise HTTPException(status_code=404, detail="Table not found.")

    await manager_ws.broadcast(
        {
            "event": "service_request",
            "table_number": get_table_label(table),
            "request": request_type,
        }
    )
    return {"message": "Service alert successfully dispatched."}
