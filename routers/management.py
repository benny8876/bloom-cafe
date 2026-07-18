"""Management dashboard: finance features for managers + Coffee/Food item sales."""

from datetime import datetime
from typing import Optional, List
import io

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib import colors

from database import get_db
import models, schemas, security
from table_labels import RESTAURANT_NAME
from services.analytics import (
    parse_target_date,
    day_bounds,
    resolve_range_bounds,
    item_sales_by_station_for_range,
)
from services.pdf_fonts import bilingual_category_paragraph, mixed_text_paragraph
from routers.finance import (
    _normalize_category,
    _all_expense_categories,
    _build_finance_summary,
)

router = APIRouter(prefix="/management", tags=["Management"])


@router.get("/categories")
def get_expense_categories(
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_manager_token),
):
    presets = list(schemas.EXPENSE_CATEGORIES)
    all_categories = _all_expense_categories(db)
    custom = [c for c in all_categories if c not in presets]
    return {"presets": presets, "custom": custom, "all": all_categories}


@router.get("/summary", response_model=schemas.FinanceSummary)
def get_management_summary(
    date: Optional[str] = None,
    range: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_manager_token),
):
    try:
        range_start, range_end, label = resolve_range_bounds(
            date, range, from_date, to_date
        )
        target_date = parse_target_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return _build_finance_summary(db, range_start, range_end, label, target_date)


@router.get("/item-sales", response_model=schemas.ItemSalesByStation)
def get_item_sales(
    date: Optional[str] = None,
    range: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_manager_token),
):
    try:
        range_start, range_end, label = resolve_range_bounds(
            date, range, from_date, to_date
        )
        target_date = parse_target_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    payload = item_sales_by_station_for_range(
        db, range_start, range_end, exclude_categories=["_pos_entry"]
    )
    return schemas.ItemSalesByStation(
        date=target_date.strftime("%Y-%m-%d"),
        date_from=range_start.strftime("%Y-%m-%d"),
        date_to=range_end.strftime("%Y-%m-%d"),
        period_label=label,
        coffee=schemas.StationSalesSummary(**payload["coffee"]),
        food=schemas.StationSalesSummary(**payload["food"]),
        total_qty=payload["total_qty"],
        total_revenue=payload["total_revenue"],
    )


@router.get("/expenses", response_model=List[schemas.ExpenseResponse])
def list_expenses(
    date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_manager_token),
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
    authenticated: bool = Depends(security.verify_manager_token),
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
    authenticated: bool = Depends(security.verify_manager_token),
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
    authenticated: bool = Depends(security.verify_manager_token),
):
    expense = db.query(models.Expense).filter(models.Expense.id == expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found.")
    db.delete(expense)
    db.commit()
    return {"message": "Expense deleted."}


@router.get("/export")
def export_management_report(
    date: Optional[str] = None,
    range: Optional[str] = None,
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    db: Session = Depends(get_db),
    authenticated: bool = Depends(security.verify_manager_token),
):
    try:
        range_start, range_end, label = resolve_range_bounds(
            date, range, from_date, to_date
        )
        target_date = parse_target_date(date)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    summary = _build_finance_summary(db, range_start, range_end, label, target_date)
    sales = item_sales_by_station_for_range(
        db, range_start, range_end, exclude_categories=["_pos_entry"]
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
    coffee_color = colors.HexColor("#92400e")
    food_color = colors.HexColor("#0f766e")

    title_style = ParagraphStyle(
        "MgrTitle",
        parent=styles["Heading1"],
        fontSize=18,
        textColor=primary,
        spaceAfter=6,
    )
    subtitle_style = ParagraphStyle(
        "MgrSub",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#64748b"),
        spaceAfter=14,
    )

    story = [
        Paragraph(RESTAURANT_NAME, title_style),
        Paragraph(f"Management Report — {label}", subtitle_style),
        Paragraph(
            f"Income: <b>{summary.income_total:,.0f} Ks</b> &nbsp;|&nbsp; "
            f"Outcome: <b>{summary.outcome_total:,.0f} Ks</b> &nbsp;|&nbsp; "
            f"Net: <b>{summary.net_profit:,.0f} Ks</b> &nbsp;|&nbsp; "
            f"Bills: <b>{summary.order_count}</b>"
            + (
                f" &nbsp;|&nbsp; Refunds: <b>-{summary.refunds_total:,.0f} Ks</b>"
                if summary.refunds_total > 0
                else ""
            ),
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
        inc_data.append(["TOTAL", "", "", f"{summary.income_total:,.0f}"])
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

    story.extend([Spacer(1, 16), Paragraph("Refunds", styles["Heading2"])])
    if summary.refunds:
        refund_data = [["Time", "Type", "Reference", "Reason", "By", "Amount (Ks)"]]
        for refund in summary.refunds:
            refund_data.append(
                [
                    refund.created_at.strftime("%Y-%m-%d %H:%M"),
                    refund.kind,
                    mixed_text_paragraph(refund.reference),
                    mixed_text_paragraph(refund.reason or "—"),
                    mixed_text_paragraph(refund.refunded_by or "—"),
                    f"{refund.amount:,.0f}",
                ]
            )
        refund_data.append(["TOTAL", "", "", "", "", f"{summary.refunds_total:,.0f}"])
        refund_table = Table(refund_data, colWidths=[75, 45, 110, 90, 55, 65])
        refund_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#be123c")),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 8),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("ALIGN", (-1, 1), (-1, -1), "RIGHT"),
                    ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#fff1f2")),
                    ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
                ]
            )
        )
        story.append(refund_table)
    else:
        story.append(Paragraph("No refunds in this period.", styles["Italic"]))

    def _append_station_section(title: str, station: dict, header_color):
        story.extend([Spacer(1, 16), Paragraph(title, styles["Heading2"])])
        story.append(
            Paragraph(
                f"Qty: <b>{station['total_qty']}</b> &nbsp;|&nbsp; "
                f"Revenue: <b>{station['total_revenue']:,.0f} Ks</b>",
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 8))
        items = station.get("items") or []
        if not items:
            story.append(Paragraph("No items sold.", styles["Italic"]))
            return
        rows = [["Item", "Qty", "Revenue (Ks)"]]
        for item in items:
            rows.append(
                [
                    mixed_text_paragraph(item["name"]),
                    str(item["qty"]),
                    f"{item['revenue']:,.0f}",
                ]
            )
        table = Table(rows, colWidths=[280, 60, 100])
        table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), header_color),
                    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                    ("FONTSIZE", (0, 0), (-1, -1), 9),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.lightgrey),
                    ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ]
            )
        )
        story.append(table)

    _append_station_section("Coffee bar — items sold", sales["coffee"], coffee_color)
    _append_station_section("Food kitchen — items sold", sales["food"], food_color)

    doc.build(story)
    buffer.seek(0)

    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={
            "Content-Disposition": (
                f'attachment; filename="management_{range_key}_{date_label}.pdf"'
            )
        },
    )
