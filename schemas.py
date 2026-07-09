from pydantic import BaseModel, Field
from typing import List, Optional, Literal
from datetime import datetime
from models import OrderStatus

KitchenStation = Literal["coffee", "food"]


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    role: str
    username: str


class PasswordChangeRequest(BaseModel):
    old_password: str
    new_password: str

class KitchenLoginRequest(BaseModel):
    pin: str


class KitchenLoginResponse(BaseModel):
    token: str
    role: str = "kitchen"

class MockPayRequest(BaseModel):
    table_id: int
    token: str
    session_token: str


class DiningSessionStartRequest(BaseModel):
    table_id: int
    token: str


class DiningSessionStartResponse(BaseModel):
    session_token: str
    expires_at: datetime
    table_label: str
    duration_hours: int = 2


class ModifierBase(BaseModel):
    name: str
    price: float = Field(..., ge=0)

class ModifierCreate(ModifierBase):
    pass

class ModifierResponse(ModifierBase):
    id: int
    class Config:
        from_attributes = True


class MenuItemBase(BaseModel):
    name: str
    description: Optional[str] = None
    price: float = Field(..., gt=0)
    category: str
    kitchen_station: KitchenStation = "food"
    is_available: bool = True
    stock: Optional[int] = None
    image_url: Optional[str] = None
    order_index: Optional[int] = None 

class MenuItemCreate(MenuItemBase):
    modifiers: Optional[List[ModifierCreate]] = []

class MenuItemUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    price: Optional[float] = Field(None, gt=0)
    category: Optional[str] = None
    kitchen_station: Optional[KitchenStation] = None
    is_available: Optional[bool] = None
    stock: Optional[int] = None
    image_url: Optional[str] = None
    modifiers: Optional[List[ModifierCreate]] = None

class MenuItemResponse(MenuItemBase):
    id: int
    modifiers: List[ModifierResponse] = []
    class Config:
        from_attributes = True


class OrderItemModifierResponse(BaseModel):
    modifier: ModifierResponse
    class Config:
        from_attributes = True

class OrderItemCreate(BaseModel):
    menu_item_id: int
    quantity: int = Field(..., gt=0)
    notes: Optional[str] = None
    modifier_ids: Optional[List[int]] = []

class OrderCreate(BaseModel):
    table_id: int
    token: str
    session_token: str
    items: List[OrderItemCreate]

class CounterSaleCreate(BaseModel):
    items: List[OrderItemCreate]

class OrderItemResponse(BaseModel):
    id: int
    menu_item: MenuItemResponse
    quantity: int
    notes: Optional[str] = None
    selected_modifiers: List[OrderItemModifierResponse] = []
    class Config:
        from_attributes = True

class TableResponse(BaseModel):
    id: int
    number: int
    label: str
    class Config:
        from_attributes = True

class TableCreate(BaseModel):
    label: str = Field(..., min_length=1, max_length=50)
    is_vip_room: bool = False
    hourly_rate: float = Field(0, ge=0)
    minimum_minutes: int = Field(30, ge=0)
    free_minutes: int = Field(0, ge=0)

class TableUpdate(BaseModel):
    label: Optional[str] = Field(None, min_length=1, max_length=50)
    is_vip_room: Optional[bool] = None
    hourly_rate: Optional[float] = Field(None, ge=0)
    minimum_minutes: Optional[int] = Field(None, ge=0)
    free_minutes: Optional[int] = Field(None, ge=0)

class TableSessionSummary(BaseModel):
    session_id: int
    started_at: str
    elapsed_minutes: int
    elapsed_label: str
    billable_minutes: int
    current_fee: float
    hourly_rate: float
    minimum_minutes: int
    free_minutes: int

class TableManagementResponse(BaseModel):
    id: int
    number: int
    label: str
    is_active: bool
    has_active_orders: bool = False
    is_vip_room: bool = False
    hourly_rate: float = 0
    minimum_minutes: int = 30
    free_minutes: int = 0
    active_session: Optional[TableSessionSummary] = None
    class Config:
        from_attributes = True

class OrderResponse(BaseModel):
    id: int
    table: TableResponse
    status: OrderStatus
    total_price: float
    created_at: datetime
    settled_at: Optional[datetime] = None
    items: List[OrderItemResponse]
    class Config:
        from_attributes = True

class DailyAnalytics(BaseModel):
    date: str
    total_revenue: float
    total_monthly_revenue: float
    total_orders_completed: int
    top_selling_items: List[dict]



EXPENSE_CATEGORIES = [
    "Supplies",
    "Rent",
    "Utilities",
    "Staff",
    "Equipment",
    "Marketing",
    "Other",
]


EXPENSE_CATEGORY_MYANMAR = {
    "Supplies": "ပစ္စည်းများ",
    "Rent": "ငှားရမ်းခ",
    "Utilities": "အသုံးအဆောင်ခ",
    "Staff": "ဝန်ထမ်းစရိတ်",
    "Equipment": "စက်ပစ္စည်း",
    "Marketing": "ကြော်ငြာစရိတ်",
    "Other": "အခြား",
}


class ExpenseBase(BaseModel):
    category: str
    amount: float = Field(..., gt=0)
    description: Optional[str] = None
    recorded_at: Optional[datetime] = None


class ExpenseCreate(ExpenseBase):
    pass


class ExpenseUpdate(BaseModel):
    category: Optional[str] = None
    amount: Optional[float] = Field(None, gt=0)
    description: Optional[str] = None
    recorded_at: Optional[datetime] = None


class ExpenseResponse(ExpenseBase):
    id: int
    recorded_at: datetime

    class Config:
        from_attributes = True


class FinanceTableIncomeEntry(BaseModel):
    table_id: int
    table_label: str
    order_count: int
    total_amount: float
    order_ids: List[int]
    last_settled_at: Optional[datetime] = None


class FinanceSummary(BaseModel):
    date: str
    date_from: Optional[str] = None
    date_to: Optional[str] = None
    period_label: Optional[str] = None
    income_total: float
    outcome_total: float
    net_profit: float
    monthly_income: float
    monthly_outcome: float
    monthly_net: float
    order_count: int
    expense_count: int
    income_entries: List[FinanceTableIncomeEntry]
    expenses: List[ExpenseResponse]
    expenses_by_category: List[dict]