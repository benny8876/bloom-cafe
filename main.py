from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import models, os
from sqlalchemy import inspect, text
from database import engine, SessionLocal
from table_labels import TABLE_LABELS, label_for_number, COUNTER_TABLE_NUMBER, COUNTER_TABLE_LABEL
from routers import menu, kitchen, manager, finance
from services.passwords import hash_password

models.Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="QR Restaurant Ordering System",
    description="Secure dynamic restaurant management operations engine with real-time analytics.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def add_printer_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["Permissions-Policy"] = "bluetooth=(self), usb=(self)"
    return response


app.mount("/static", StaticFiles(directory="static"), name="static")



app.include_router(menu.router, prefix="/api/v1")
app.include_router(kitchen.router, prefix="/api/v1")
app.include_router(manager.router, prefix="/api/v1")
app.include_router(finance.router, prefix="/api/v1")


@app.get("/menu")
def serve_menu():
    return FileResponse(os.path.join("static", "menu.html"))


@app.get("/kitchen")
def serve_kitchen():
    return FileResponse(os.path.join("static", "kitchen.html"))


@app.get("/kitchen/coffee")
def serve_coffee_kitchen():
    return FileResponse(os.path.join("static", "kitchen.html"))


@app.get("/kitchen/food")
def serve_food_kitchen():
    return FileResponse(os.path.join("static", "kitchen.html"))


@app.get("/manager")
def serve_manager():
    return FileResponse(os.path.join("static", "manager.html"))


@app.get("/sw-manager.js")
def serve_sw_manager():
    return FileResponse(
        os.path.join("static", "sw-manager.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/sw-finance.js")
def serve_sw_finance():
    return FileResponse(
        os.path.join("static", "sw-finance.js"),
        media_type="application/javascript",
        headers={"Service-Worker-Allowed": "/", "Cache-Control": "no-cache"},
    )


@app.get("/manifest-manager.json")
def serve_manifest_manager():
    return FileResponse(
        os.path.join("static", "manifest-manager.json"),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/manifest-finance.json")
def serve_manifest_finance():
    return FileResponse(
        os.path.join("static", "manifest-finance.json"),
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )


@app.get("/finance")
def serve_finance():
    return FileResponse(os.path.join("static", "finance.html"))


def migrate_table_labels():
    inspector = inspect(engine)
    if "tables" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("tables")]
    if "label" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE tables ADD COLUMN label VARCHAR"))

    db = SessionLocal()
    try:
        tables = db.query(models.RestaurantTable).all()
        for table in tables:
            if not table.label:
                table.label = label_for_number(table.number)
        db.commit()
    finally:
        db.close()


def migrate_orders_payment_method():
    inspector = inspect(engine)
    if "orders" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("orders")]
    if "payment_method" not in columns:
        with engine.begin() as conn:
            conn.execute(text("ALTER TABLE orders ADD COLUMN payment_method VARCHAR"))


def migrate_menu_kitchen_station():
    from services.kitchen_stations import station_for_category

    inspector = inspect(engine)
    if "menu_items" not in inspector.get_table_names():
        return

    columns = [col["name"] for col in inspector.get_columns("menu_items")]
    column_was_added = "kitchen_station" not in columns
    if column_was_added:
        with engine.begin() as conn:
            conn.execute(
                text(
                    "ALTER TABLE menu_items ADD COLUMN kitchen_station VARCHAR NOT NULL DEFAULT 'food'"
                )
            )

    if not column_was_added:
        return

    db = SessionLocal()
    try:
        items = db.query(models.MenuItem).all()
        for item in items:
            item.kitchen_station = station_for_category(item.category)
        db.commit()
    finally:
        db.close()


def migrate_vip_table_settings():
    inspector = inspect(engine)
    if "tables" not in inspector.get_table_names():
        return

    columns = {col["name"] for col in inspector.get_columns("tables")}
    bool_default = "0" if engine.dialect.name == "sqlite" else "FALSE"
    alters = []
    if "is_vip_room" not in columns:
        alters.append(
            f"ALTER TABLE tables ADD COLUMN is_vip_room BOOLEAN NOT NULL DEFAULT {bool_default}"
        )
    if "hourly_rate" not in columns:
        alters.append("ALTER TABLE tables ADD COLUMN hourly_rate FLOAT NOT NULL DEFAULT 0")
    if "minimum_minutes" not in columns:
        alters.append("ALTER TABLE tables ADD COLUMN minimum_minutes INTEGER NOT NULL DEFAULT 30")
    if "free_minutes" not in columns:
        alters.append("ALTER TABLE tables ADD COLUMN free_minutes INTEGER NOT NULL DEFAULT 0")

    if alters:
        with engine.begin() as conn:
            for stmt in alters:
                conn.execute(text(stmt))

    if "table_sessions" not in inspector.get_table_names():
        models.TableSession.__table__.create(bind=engine)


def migrate_dining_sessions():
    inspector = inspect(engine)
    if "dining_sessions" not in inspector.get_table_names():
        models.DiningSession.__table__.create(bind=engine)


LEGACY_MENU_PRICES_KS = {
    "Cheeseburger": (8.99, 4500),
    "French Fries": (3.49, 2500),
    "Iced Soda": (2.49, 1500),
    "Iced Coffee": (3.0, 2000),
}


def migrate_legacy_menu_prices():
    """Convert USD seed prices to Myanmar Kyat for legacy installs."""
    db = SessionLocal()
    try:
        updated = False
        for name, (legacy_price, ks_price) in LEGACY_MENU_PRICES_KS.items():
            item = (
                db.query(models.MenuItem)
                .filter(models.MenuItem.name == name, models.MenuItem.price == legacy_price)
                .first()
            )
            if item:
                item.price = ks_price
                updated = True
        if updated:
            db.commit()
    finally:
        db.close()


def migrate_order_status_values():
    """Normalize legacy uppercase enum names to lowercase values in SQLite."""
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if "orders" not in inspector.get_table_names():
        return

    legacy_to_value = {
        "AWAITING_PAYMENT": "awaiting_payment",
        "PENDING": "pending",
        "PREPARING": "preparing",
        "SERVED": "served",
        "COMPLETED": "completed",
        "CANCELLED": "cancelled",
    }

    with engine.begin() as conn:
        for legacy, value in legacy_to_value.items():
            conn.execute(
                text("UPDATE orders SET status = :value WHERE status = :legacy"),
                {"legacy": legacy, "value": value},
            )


def ensure_counter_table(db):
    counter = (
        db.query(models.RestaurantTable)
        .filter(models.RestaurantTable.number == COUNTER_TABLE_NUMBER)
        .first()
    )
    if not counter:
        db.add(
            models.RestaurantTable(
                number=COUNTER_TABLE_NUMBER,
                label=COUNTER_TABLE_LABEL,
                is_active=True,
            )
        )
        db.commit()
    elif counter.label != COUNTER_TABLE_LABEL:
        counter.label = COUNTER_TABLE_LABEL
        db.commit()


def migrate_auth_tables():
    inspector = inspect(engine)
    table_names = inspector.get_table_names()

    if "admin_credentials" in table_names:
        columns = {col["name"] for col in inspector.get_columns("admin_credentials")}
        if "role" not in columns:
            with engine.begin() as conn:
                conn.execute(
                    text(
                        "ALTER TABLE admin_credentials ADD COLUMN role VARCHAR NOT NULL DEFAULT 'staff'"
                    )
                )
            db = SessionLocal()
            try:
                first_admin = (
                    db.query(models.AdminCredential)
                    .order_by(models.AdminCredential.id.asc())
                    .first()
                )
                if first_admin and first_admin.role == "staff":
                    first_admin.role = "owner"
                    db.commit()
            finally:
                db.close()

    if "auth_sessions" not in table_names:
        models.AuthSession.__table__.create(bind=engine)

    db = SessionLocal()
    try:
        db.query(models.AdminCredential).filter(
            models.AdminCredential.role == "staff"
        ).update({models.AdminCredential.role: "manager"}, synchronize_session=False)
        db.query(models.AuthSession).filter(
            models.AuthSession.role == "staff"
        ).update({models.AuthSession.role: "manager"}, synchronize_session=False)
        db.commit()
    finally:
        db.close()


def migrate_menu_categories():
    from services.menu_categories import sync_menu_categories

    inspector = inspect(engine)
    if "menu_categories" not in inspector.get_table_names():
        models.MenuCategory.__table__.create(bind=engine)

    db = SessionLocal()
    try:
        sync_menu_categories(db)
    finally:
        db.close()


def ensure_default_accounts(db):
    """Owner (admin) + floor manager accounts."""
    owner_password = os.getenv("OWNER_DEFAULT_PASSWORD", "adminpassword123")
    manager_password = os.getenv("MANAGER_DEFAULT_PASSWORD", "manager2026")

    owner = (
        db.query(models.AdminCredential)
        .filter(models.AdminCredential.username == "admin")
        .first()
    )
    if not owner:
        db.add(
            models.AdminCredential(
                username="admin",
                password_hash=hash_password(owner_password),
                role="owner",
            )
        )

    manager = (
        db.query(models.AdminCredential)
        .filter(models.AdminCredential.username == "manager")
        .first()
    )
    if not manager:
        db.add(
            models.AdminCredential(
                username="manager",
                password_hash=hash_password(manager_password),
                role="manager",
            )
        )

    db.commit()


@app.on_event("startup")
def seed_initial_data():
    migrate_table_labels()
    migrate_orders_payment_method()
    migrate_menu_kitchen_station()
    migrate_vip_table_settings()
    migrate_dining_sessions()
    migrate_legacy_menu_prices()
    migrate_order_status_values()
    migrate_auth_tables()
    migrate_menu_categories()
    db = SessionLocal()

    ensure_default_accounts(db)

   
    if not db.query(models.RestaurantTable).first():
        tables = [
            models.RestaurantTable(number=i + 1, label=label)
            for i, label in enumerate(TABLE_LABELS)
        ]
        db.add_all(tables)
        db.commit()

    ensure_counter_table(db)


    if not db.query(models.MenuItem).first():
 
        burger = models.MenuItem(
            name="Cheeseburger", price=4500, category="Main", kitchen_station="food", stock=25
        )
        fries = models.MenuItem(
            name="French Fries", price=2500, category="Side", kitchen_station="food", stock=50
        )
        soda = models.MenuItem(
            name="Iced Soda", price=1500, category="Drink", kitchen_station="coffee", stock=10
        )
        coffee = models.MenuItem(
            name="Iced Coffee", price=2000, category="Drink", kitchen_station="coffee", stock=20
        )

        db.add_all([burger, fries, soda, coffee])
        db.flush()  
        db.commit()


@app.get("/")
def root():
    return {
        "message": "Dine Inn System backend is active. Load /menu, /kitchen/coffee, /kitchen/food, /manager, or /finance."
    }


if __name__ == "__main__":
    from run_https import main as run_https_main

    run_https_main()
