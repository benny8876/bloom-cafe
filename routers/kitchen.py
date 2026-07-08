from fastapi import APIRouter, Depends, HTTPException, WebSocket, WebSocketDisconnect, Header
from sqlalchemy.orm import Session, joinedload
from database import get_db, SessionLocal
import models, schemas
from websocket import manager_ws
from typing import List, Optional
import security
from services.sessions import create_session, ROLE_KITCHEN
from table_labels import is_counter_table
from services.kitchen_stations import (
    coffee_categories,
    filter_orders_for_station,
    normalize_station,
    VALID_STATIONS,
)

router = APIRouter(prefix="/kitchen", tags=["Kitchen Panel"])


def _active_orders_query(db: Session):
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
            models.Order.status.in_(
                [
                    models.OrderStatus.PENDING,
                    models.OrderStatus.PREPARING,
                    models.OrderStatus.SERVED,
                ]
            )
        )
        .order_by(models.Order.created_at.asc())
    )


def _resolve_station(station: str) -> str:
    try:
        return normalize_station(station)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/login", response_model=schemas.KitchenLoginResponse)
def kitchen_login(credentials: schemas.KitchenLoginRequest, db: Session = Depends(get_db)):
    if credentials.pin != security.KITCHEN_PIN:
        raise HTTPException(status_code=401, detail="Invalid kitchen PIN.")
    token = create_session(db, role=ROLE_KITCHEN)
    return schemas.KitchenLoginResponse(token=token)


@router.post("/logout")
def kitchen_logout(
    authorization: Optional[str] = Header(None),
    db: Session = Depends(get_db),
):
    security.logout_token(db, authorization)
    return {"message": "Logged out."}


@router.get("/stations/config")
def kitchen_stations_config():
    return {
        "stations": sorted(VALID_STATIONS),
        "coffee_categories": sorted(coffee_categories()),
    }


@router.get("/{station}/orders", response_model=List[schemas.OrderResponse])
def get_active_orders_for_station(
    station: str,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_kitchen_token),
):
    resolved_station = _resolve_station(station)
    orders = _active_orders_query(db).all()
    return filter_orders_for_station(orders, resolved_station)


@router.patch("/orders/{order_id}/status", response_model=schemas.OrderResponse)
async def update_order_status(
    order_id: int,
    status: models.OrderStatus,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_kitchen_token),
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    security.validate_kitchen_status_transition(order.status, status)

    if status == models.OrderStatus.CANCELLED:
        security.restore_order_stock(order, db)

    order.status = status
    if status == models.OrderStatus.SERVED and is_counter_table(order.table):
        order.status = models.OrderStatus.COMPLETED

    db.commit()
    db.refresh(order)

    response_payload = schemas.OrderResponse.model_validate(order).model_dump(mode="json")
    await manager_ws.broadcast({"event": "status_update", "order": response_payload})

    return order


@router.post("/orders/{order_id}/cancel", response_model=schemas.OrderResponse)
async def cancel_order(
    order_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_kitchen_token),
):
    order = db.query(models.Order).filter(models.Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    security.validate_kitchen_status_transition(order.status, models.OrderStatus.CANCELLED)
    security.restore_order_stock(order, db)
    order.status = models.OrderStatus.CANCELLED
    db.commit()
    db.refresh(order)

    response_payload = schemas.OrderResponse.model_validate(order).model_dump(mode="json")
    await manager_ws.broadcast({"event": "status_update", "order": response_payload})

    return order


@router.websocket("/ws")
async def kitchen_websocket_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token")
    db = SessionLocal()
    try:
        if not security.verify_ws_token(db, token, {ROLE_KITCHEN}):
            await security.reject_unauthorized_ws(
                websocket, "Kitchen authentication required"
            )
            return

        await manager_ws.connect(websocket)
        try:
            while True:
                await websocket.receive_text()
        except WebSocketDisconnect:
            pass
        except Exception as e:
            print(f"LOG: [WebSocket] Unexpected connection break: {e}")
        finally:
            manager_ws.disconnect(websocket)
    finally:
        db.close()
