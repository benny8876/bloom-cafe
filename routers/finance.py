from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from sqlalchemy import func
from datetime import datetime
from typing import Optional, List
import io

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from database import get_db
import models, schemas, security
from table_labels import RESTAURANT_NAME, get_table_label
from services.analytics import (
    parse_target_date,
    day_bounds,
    month_bounds,
    completed_orders_for_range,
    resolve_range_bounds,
    add_settled_session_fees,
    add_fee_only_settled_sessions,
    fee_only_settled_sessions_for_range,
    subtract_settlement_discounts,
    settlement_discount_amount,
    settlement_discounts_for_range,
)
from services.pdf_fonts import bilingual_category_paragraph, mixed_text_paragraph

router = APIRouter(prefix="/finance", tags=["Finance"])


def _normalize_category(category: str) -> str:
    cleaned = (category or "").strip()
    if not cleaned:
        raise HTTPException(status_code=400, detail="Category is required.")
    if len(cleaned) > 50:
        raise HTTPException(status_code=400, detail="Category must be 50 characters or fewer.")
    return cleaned


def _all_expense_categories(db: Session) -> List[str]:
    preset = list(schemas.EXPENSE_CATEGORIES)
    custom_rows = (
        db.query(models.Expense.category)
        .distinct()
        .order_by(models.Expense.category.asc())
        .all()
    )
    seen = set(preset)
    merged = list(preset)
    for (name,) in custom_rows:
        if name and name not in seen:
            seen.add(name)
            merged.append(name)
    return merged


def _build_finance_summary(
    db: Session,
    range_start: datetime,
    range_end: datetime,
    period_label: str,
    anchor_date=None,
) -> schemas.FinanceSummary:
    anchor = anchor_date or range_start.date()
    month_start, month_end = month_bounds(anchor)

    completed_orders = completed_orders_for_range(db, range_start, range_end)
    monthly_orders = completed_orders_for_range(db, month_start, month_end)

    period_expenses = (
        db.query(models.Expense)
        .filter(models.Expense.recorded_at.between(range_start, range_end))
        .order_by(models.Expense.recorded_at.desc())
        .all()
    )

    month_expenses = (
        db.query(models.Expense)
        .filter(models.Expense.recorded_at.between(month_start, month_end))
        .all()
    )

    income_total_orders = sum(order.total_price for order in completed_orders)
    outcome_total = sum(expense.amount for expense in period_expenses)
    monthly_income_orders = sum(order.total_price for order in monthly_orders)
    monthly_outcome = sum(expense.amount for expense in month_expenses)

    table_income: dict = {}
    for order in completed_orders:
        t_id = order.table_id
        if t_id not in table_income:
            table_income[t_id] = {
                "table_id": t_id,
                "table_label": get_table_label(order.table),
                "order_count": 0,
                "total_amount": 0.0,
                "order_ids": [],
                "last_settled_at": None,
            }
        row = table_income[t_id]
        row["order_count"] += 1
        row["total_amount"] += order.total_price
        row["order_ids"].append(order.id)
        settled = order.settled_at or order.created_at
        if row["last_settled_at"] is None or settled > row["last_settled_at"]:
            row["last_settled_at"] = settled

    session_fees_total = add_settled_session_fees(db, completed_orders, table_income)

    discount_keys: set = set()
    for order in completed_orders:
        if not order.settled_at:
            continue
        key = (order.table_id, order.settled_at.isoformat())
        if key in discount_keys:
            continue
        discount_keys.add(key)
        discount = settlement_discount_amount(db, order.table_id, order.settled_at)
        if discount > 0 and order.table_id in table_income:
            table_income[order.table_id]["total_amount"] -= discount

    for session in fee_only_settled_sessions_for_range(db, range_start, range_end):
        table = (
            db.query(models.RestaurantTable)
            .filter(models.RestaurantTable.id == session.table_id)
            .first()
        )
        if not table:
            continue
        fee = float(session.session_fee_charged or 0) + float(
            session.entry_fee_charged or 0
        )
        if fee <= 0:
            continue
        t_id = session.table_id
        if t_id not in table_income:
            table_income[t_id] = {
                "table_id": t_id,
                "table_label": get_table_label(table),
                "order_count": 0,
                "total_amount": 0.0,
                "order_ids": [],
                "last_settled_at": None,
            }
        row = table_income[t_id]
        row["total_amount"] += fee
        row["total_amount"] -= float(session.discount_amount or 0)
        if session.ended_at and (
            row["last_settled_at"] is None or session.ended_at > row["last_settled_at"]
        ):
            row["last_settled_at"] = session.ended_at

    session_fees_total += add_fee_only_settled_sessions(db, range_start, range_end)
    monthly_session_fees = add_settled_session_fees(db, monthly_orders)
    monthly_session_fees += add_fee_only_settled_sessions(db, month_start, month_end)
    period_discounts = settlement_discounts_for_range(db, range_start, range_end)
    monthly_discounts = settlement_discounts_for_range(db, month_start, month_end)
    income_total = income_total_orders + session_fees_total - period_discounts
    monthly_income = monthly_income_orders + monthly_session_fees - monthly_discounts

    income_entries = [
        schemas.FinanceTableIncomeEntry(**row)
        for row in sorted(
            table_income.values(),
            key=lambda r: (-r["total_amount"], r["table_label"]),
        )
    ]

    category_rows = (
        db.query(
            models.Expense.category,
            func.sum(models.Expense.amount).label("total"),
        )
        .filter(models.Expense.recorded_at.between(range_start, range_end))
        .group_by(models.Expense.category)
        .order_by(func.sum(models.Expense.amount).desc())
        .all()
    )

    return schemas.FinanceSummary(
        date=anchor.strftime("%Y-%m-%d") if hasattr(anchor, "strftime") else str(anchor),
        date_from=range_start.strftime("%Y-%m-%d"),
        date_to=range_end.strftime("%Y-%m-%d"),
        period_label=period_label,
        income_total=income_total,
        outcome_total=outcome_total,
        net_profit=income_total - outcome_total,
        monthly_income=monthly_income,
        monthly_outcome=monthly_outcome,
        monthly_net=monthly_income - monthly_outcome,
        order_count=len(completed_orders),
        expense_count=len(period_expenses),
        income_entries=income_entries,
        expenses=period_expenses,
        expenses_by_category=[
            {"category": row[0], "total": float(row[1])} for row in category_rows
        ],
    )


@router.get("/categories")
def get_expense_categories(
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_owner_token),
):
    presets = list(schemas.EXPENSE_CATEGORIES)
    all_categories = _all_expense_categories(db)
    custom = [c for c in all_categories if c not in presets]
    return {"presets": presets, "custom": custom, "all": all_categories}


@router.get("/summary", response_model=schemas.FinanceSummary)
def get_finance_summary(
    date: Optional[str] = None,
    range: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_owner_token),
):
    try:
        range_start, range_end, label = resolve_range_bounds(
            date, range, from_date, to_date
        )
        target_date = parse_target_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _build_finance_summary(
        db, range_start, range_end, label, target_date
    )


@router.get("/expenses", response_model=List[schemas.ExpenseResponse])
def list_expenses(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_owner_token),
):
    try:
        target_date = parse_target_date(date)
    except ValueError:
        raise HTTPException(
            status_code=400, detail="Invalid date format. Use YYYY-MM-DD."
        )
    day_start, day_end = day_bounds(target_date)

    return (
        db.query(models.Expense)
        .filter(models.Expense.recorded_at.between(day_start, day_end))
        .order_by(models.Expense.recorded_at.desc())
        .all()
    )


@router.post("/expenses", response_model=schemas.ExpenseResponse)
def create_expense(
    data: schemas.ExpenseCreate,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_owner_token),
):
    category = _normalize_category(data.category)

    recorded_at = data.recorded_at
    if recorded_at and isinstance(recorded_at, datetime):
        recorded_at = recorded_at.replace(tzinfo=None)

    expense = models.Expense(
        category=category,
        amount=data.amount,
        description=data.description,
        recorded_at=recorded_at or models.get_yangon_now(),
    )
    db.add(expense)
    db.commit()
    db.refresh(expense)
    return expense


@router.put("/expenses/{expense_id}", response_model=schemas.ExpenseResponse)
def update_expense(
    expense_id: int,
    data: schemas.ExpenseUpdate,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_owner_token),
):
    expense = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    if data.category is not None:
        expense.category = _normalize_category(data.category)
    if data.amount is not None:
        expense.amount = data.amount
    if data.description is not None:
        expense.description = data.description
    if data.recorded_at is not None:
        expense.recorded_at = data.recorded_at.replace(tzinfo=None)

    db.commit()
    db.refresh(expense)
    return expense


@router.delete("/expenses/{expense_id}")
def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_owner_token),
):
    expense = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")

    db.delete(expense)
    db.commit()
    return {"message": "Expense deleted."}


@router.get("/export")
def export_finance_report(
    date: Optional[str] = None,
    range: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_owner_token),
):
    try:
        range_start, range_end, label = resolve_range_bounds(
            date, range, from_date, to_date
        )
        target_date = parse_target_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    summary = _build_finance_summary(
        db, range_start, range_end, label, target_date
    )
    range_key = (range or "day").lower()
    show_date_column = range_key != "day"
    date_label = label.replace(" → ", "_to_").replace(" ", "_")

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
    primary = colors.HexColor("#0f172a")
    green = colors.HexColor("#059669")

    title_style = ParagraphStyle(
        "FinTitle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=primary,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "FinSub",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=14,
    )

    story = [
        Paragraph(RESTAURANT_NAME, title_style),
        Paragraph(f"Finance Report — {label}", subtitle_style),
        Paragraph(
            f"Income: <b>{summary.income_total:,.0f} Ks</b> &nbsp;|&nbsp; "
            f"Outcome: <b>{summary.outcome_total:,.0f} Ks</b> &nbsp;|&nbsp; "
            f"Net: <b>{summary.net_profit:,.0f} Ks</b> &nbsp;|&nbsp; "
            f"Bills: <b>{summary.order_count}</b>",
            styles["Normal"],
        ),
        Spacer(1, 16),
        Paragraph("Expenses", styles["Heading2"]),
    ]

    if summary.expenses:
        exp_data = [["Category", "Description", "Amount (Ks)"]]
        for exp in summary.expenses:
            exp_data.append(
                [
                    bilingual_category_paragraph(exp.category),
                    mixed_text_paragraph(exp.description or "—"),
                    f"{exp.amount:,.0f}",
                ]
            )
        exp_table = Table(exp_data, colWidths=[100, 280, 100])
        exp_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), primary),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTNAME", (2, 1), (2, -1), "Helvetica"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("ALIGN", (2, 1), (2, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(exp_table)
    else:
        story.append(Paragraph("No expenses in this period.", styles["Italic"]))

    story.extend([Spacer(1, 16), Paragraph("Bills", styles["Heading2"])])

    if summary.income_entries:
        inc_data = [["Table", "Orders", "Last settled", "Total (Ks)"]]
        col_widths = [100, 55, 90, 95]
        for entry in summary.income_entries:
            when = entry.last_settled_at
            time_label = (
                when.strftime("%Y-%m-%d %H:%M")
                if show_date_column and when
                else (when.strftime("%H:%M") if when else "—")
            )
            inc_data.append(
                [
                    entry.table_label,
                    str(entry.order_count),
                    time_label,
                    f"{entry.total_amount:,.0f}",
                ]
            )
        inc_data.append(
            ["TOTAL", "", "", f"{summary.income_total:,.0f}"]
        )
        inc_table = Table(inc_data, colWidths=col_widths)
        inc_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), green),
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
        story.append(inc_table)
    else:
        story.append(Paragraph("No settled bills in this period.", styles["Italic"]))

    doc.build(story)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="finance_{range_key}_{date_label}.pdf"'
            )
        },
    )
