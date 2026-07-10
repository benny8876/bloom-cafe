import enum
from sqlalchemy import Column, Integer, String, Float, Boolean, ForeignKey, DateTime, Enum
from sqlalchemy.orm import relationship
from datetime import datetime, timezone, timedelta
from database import Base




MYANMAR_TZ = timezone(timedelta(hours=6, minutes=30))

def get_yangon_now():
    
    return datetime.now(MYANMAR_TZ).replace(tzinfo=None)

class OrderStatus(str, enum.Enum):
    AWAITING_PAYMENT = "awaiting_payment" 
    PENDING = "pending"                  
    PREPARING = "preparing"               
    SERVED = "served"                     
    COMPLETED = "completed"               
    CANCELLED = "cancelled"

class RestaurantTable(Base):
    __tablename__ = "tables"
    id = Column(Integer, primary_key=True, index=True)
    number = Column(Integer, unique=True, nullable=False)
    label = Column(String, unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    is_vip_room = Column(Boolean, default=False)
    hourly_rate = Column(Float, nullable=False, default=0.0)
    minimum_minutes = Column(Integer, nullable=False, default=30)
    free_minutes = Column(Integer, nullable=False, default=0)

    sessions = relationship("TableSession", back_populates="table")


class TableSessionStatus(str, enum.Enum):
    ACTIVE = "active"
    SETTLED = "settled"
    CANCELLED = "cancelled"


class TableSession(Base):
    __tablename__ = "table_sessions"
    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(Integer, ForeignKey("tables.id"), nullable=False, index=True)
    started_at = Column(DateTime, default=get_yangon_now, nullable=False)
    ended_at = Column(DateTime, nullable=True)
    status = Column(
        Enum(
            TableSessionStatus,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=TableSessionStatus.ACTIVE,
    )
    hourly_rate_snapshot = Column(Float, nullable=False, default=0.0)
    minimum_minutes_snapshot = Column(Integer, nullable=False, default=30)
    free_minutes_snapshot = Column(Integer, nullable=False, default=0)
    billable_minutes = Column(Integer, nullable=True)
    session_fee_charged = Column(Float, nullable=True)

    table = relationship("RestaurantTable", back_populates="sessions")


class DiningSessionStatus(str, enum.Enum):
    ACTIVE = "active"
    CLOSED = "closed"


class DiningSession(Base):
    """Short-lived customer access after scanning a table QR (2h, closed on settle)."""
    __tablename__ = "dining_sessions"
    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(Integer, ForeignKey("tables.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    started_at = Column(DateTime, default=get_yangon_now, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    status = Column(
        Enum(
            DiningSessionStatus,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=DiningSessionStatus.ACTIVE,
    )
    closed_at = Column(DateTime, nullable=True)

    table = relationship("RestaurantTable")

class MenuItem(Base):
    __tablename__ = "menu_items"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(String, nullable=True)
    price = Column(Float, nullable=False)
    category = Column(String, nullable=False)
    kitchen_station = Column(String, nullable=False, default="food")
    is_available = Column(Boolean, default=True)
    stock = Column(Integer, nullable=True)
    order_index = Column(Integer, default=0 , index=True)
    
    
    image_url = Column(String, nullable=True) 

    modifiers = relationship("MenuItemModifier", back_populates="menu_item", cascade="all, delete-orphan")

class MenuCategory(Base):
    __tablename__ = "menu_categories"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, unique=True, nullable=False, index=True)
    order_index = Column(Integer, default=0, index=True)

class MenuItemModifier(Base):
    __tablename__ = "menu_item_modifiers"
    id = Column(Integer, primary_key=True, index=True)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=False)
    name = Column(String, nullable=False)
    price = Column(Float, nullable=False, default=0.0)

    menu_item = relationship("MenuItem", back_populates="modifiers")



class Order(Base):
    __tablename__ = "orders"
    id = Column(Integer, primary_key=True, index=True)
    table_id = Column(Integer, ForeignKey("tables.id"), nullable=False)
    status = Column(
        Enum(
            OrderStatus,
            values_callable=lambda statuses: [status.value for status in statuses],
        ),
        default=OrderStatus.AWAITING_PAYMENT,
    )
    total_price = Column(Float, default=0.0)
    created_at = Column(DateTime, default=get_yangon_now)
    
    
    settled_at = Column(DateTime, nullable=True)
    payment_method = Column(String, nullable=True)

    table = relationship("RestaurantTable")
    items = relationship("OrderItem", back_populates="order", cascade="all, delete-orphan")



class OrderItem(Base):
    __tablename__ = "order_items"
    id = Column(Integer, primary_key=True, index=True)
    order_id = Column(Integer, ForeignKey("orders.id"), nullable=False)
    menu_item_id = Column(Integer, ForeignKey("menu_items.id"), nullable=False)
    quantity = Column(Integer, nullable=False)
    notes = Column(String, nullable=True)

    order = relationship("Order", back_populates="items")
    menu_item = relationship("MenuItem")
    selected_modifiers = relationship("OrderItemModifier", back_populates="order_item", cascade="all, delete-orphan")

class OrderItemModifier(Base):
    __tablename__ = "order_item_modifiers"
    id = Column(Integer, primary_key=True, index=True)
    order_item_id = Column(Integer, ForeignKey("order_items.id"), nullable=False)
    modifier_id = Column(Integer, ForeignKey("menu_item_modifiers.id"), nullable=False)

    order_item = relationship("OrderItem", back_populates="selected_modifiers")
    modifier = relationship("MenuItemModifier")


class AdminCredential(Base):
    __tablename__ = "admin_credentials"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, nullable=False, default="manager")


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    id = Column(Integer, primary_key=True, index=True)
    token_hash = Column(String, unique=True, nullable=False, index=True)
    role = Column(String, nullable=False)
    username = Column(String, nullable=True)
    created_at = Column(DateTime, default=get_yangon_now, nullable=False)
    expires_at = Column(DateTime, nullable=False)


class Expense(Base):
    __tablename__ = "expenses"
    id = Column(Integer, primary_key=True, index=True)
    category = Column(String, nullable=False)
    amount = Column(Float, nullable=False)
    description = Column(String, nullable=True)
    recorded_at = Column(DateTime, default=get_yangon_now, index=True)