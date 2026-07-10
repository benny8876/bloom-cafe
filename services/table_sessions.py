"""VIP room session timer and hourly billing."""

from datetime import datetime
from typing import Optional, Tuple

from sqlalchemy.orm import Session

import models


def elapsed_minutes(started_at: datetime, as_of: Optional[datetime] = None) -> int:
    end = as_of or models.get_yangon_now()
    delta = end - started_at
    return max(0, int(delta.total_seconds() // 60))


def fee_per_block(hourly_rate: float, minimum_minutes: int) -> int:
    """Kyat charge for one billing block (e.g. 30 min at 20,000/hr → 10,000 Ks)."""
    block_mins = max(1, int(minimum_minutes or 30))
    return int(round(hourly_rate * block_mins / 60.0))


# First tier lasts until minimum_minutes + this grace (30 + 20 = 50 min).
FIRST_TIER_GRACE_MINUTES = 20


def tier_boundaries(minimum_minutes: int) -> tuple[int, int, int, int]:
    """Return (first_until, second_until, third_until, fourth_starts) in minutes."""
    block_mins = max(1, int(minimum_minutes or 30))
    first_until = block_mins + FIRST_TIER_GRACE_MINUTES
    second_until = 3 * block_mins
    third_until = 3 * block_mins + 19
    fourth_starts = 3 * block_mins + 20
    return first_until, second_until, third_until, fourth_starts


def billing_blocks(chargeable_minutes: int, minimum_minutes: int) -> int:
    """Fixed kyat tiers (when minimum_minutes = 30, hourly_rate = 20,000):

    1–50 min → 10,000 Ks | 51–90 → 20,000 | 91–109 → 30,000
    110+ → 40,000 Ks, then +10,000 every 30 minutes (140 → 50,000, …).
    """
    if chargeable_minutes <= 0:
        return 0

    block_mins = max(1, int(minimum_minutes or 30))
    first_until, second_until, third_until, fourth_starts = tier_boundaries(block_mins)

    if chargeable_minutes <= first_until:
        return 1
    if chargeable_minutes <= second_until:
        return 2
    if chargeable_minutes <= third_until:
        return 3

    extra = chargeable_minutes - fourth_starts
    return 4 + (extra // block_mins)


def calculate_session_fee(
    started_at: datetime,
    hourly_rate: float,
    minimum_minutes: int,
    free_minutes: int,
    as_of: Optional[datetime] = None,
) -> Tuple[float, int, int]:
    """Return (fee_amount, billable_minutes, elapsed_minutes).

    Fixed tiers at 20,000 Ks/hr with 30-min minimum (10,000 Ks per block):
    1–50 min → 10,000 | 51–90 → 20,000 | 91–109 → 30,000
    110+ → 40,000, then +10,000 every 30 minutes.
    """
    if hourly_rate <= 0:
        return 0.0, 0, elapsed_minutes(started_at, as_of)

    block_mins = max(1, int(minimum_minutes or 30))
    total_elapsed = elapsed_minutes(started_at, as_of)
    chargeable = max(0, total_elapsed - int(free_minutes or 0))
    if chargeable <= 0:
        return 0.0, 0, total_elapsed

    blocks = billing_blocks(chargeable, minimum_minutes)
    per_block = fee_per_block(hourly_rate, block_mins)
    fee = blocks * per_block
    billable = blocks * block_mins
    return float(fee), billable, total_elapsed


def format_duration(minutes: int) -> str:
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h {mins}m"
    return f"{mins}m"


def get_active_session(db: Session, table_id: int) -> Optional[models.TableSession]:
    return (
        db.query(models.TableSession)
        .filter(
            models.TableSession.table_id == table_id,
            models.TableSession.status == models.TableSessionStatus.ACTIVE,
        )
        .first()
    )


def ensure_vip_session_started(db: Session, table: models.RestaurantTable) -> Tuple[Optional[models.TableSession], bool]:
    """Start a VIP visit session for VIP tables (hourly rate optional)."""
    if not table.is_vip_room:
        return None, False
    existing = get_active_session(db, table.id)
    if existing:
        return existing, False

    session = models.TableSession(
        table_id=table.id,
        started_at=models.get_yangon_now(),
        hourly_rate_snapshot=float(table.hourly_rate or 0),
        minimum_minutes_snapshot=int(table.minimum_minutes or 30),
        free_minutes_snapshot=int(table.free_minutes or 0),
        entry_fee_per_guest_snapshot=float(table.entry_fee_per_guest or 0),
        guest_count=0,
        status=models.TableSessionStatus.ACTIVE,
    )
    db.add(session)
    db.flush()
    return session, True


def entry_fee_amount(guest_count: int, entry_fee_per_guest: float) -> float:
    guests = max(0, int(guest_count or 0))
    rate = float(entry_fee_per_guest or 0)
    if guests <= 0 or rate <= 0:
        return 0.0
    return float(guests * rate)


def set_session_guest_count(session: models.TableSession, guest_count: int) -> models.TableSession:
    session.guest_count = max(0, int(guest_count or 0))
    return session


def end_table_session(
    db: Session,
    table_id: int,
    status: models.TableSessionStatus,
    as_of: Optional[datetime] = None,
) -> Optional[models.TableSession]:
    session = get_active_session(db, table_id)
    if not session:
        return None

    now = as_of or models.get_yangon_now()
    session.ended_at = now
    session.status = status

    if status == models.TableSessionStatus.SETTLED:
        fee, billable, _ = calculate_session_fee(
            session.started_at,
            session.hourly_rate_snapshot,
            session.minimum_minutes_snapshot,
            session.free_minutes_snapshot,
            as_of=now,
        )
        session.session_fee_charged = fee
        session.billable_minutes = billable
        session.entry_fee_charged = entry_fee_amount(
            session.guest_count,
            session.entry_fee_per_guest_snapshot,
        )
    else:
        session.session_fee_charged = 0.0
        session.billable_minutes = 0
        session.entry_fee_charged = 0.0

    db.flush()
    return session


def get_settled_session_at(
    db: Session, table_id: int, settled_at: datetime
) -> Optional[models.TableSession]:
    return (
        db.query(models.TableSession)
        .filter(
            models.TableSession.table_id == table_id,
            models.TableSession.status == models.TableSessionStatus.SETTLED,
            models.TableSession.ended_at == settled_at,
        )
        .first()
    )


def session_fee_line_item(session: models.TableSession) -> dict:
    elapsed = elapsed_minutes(session.started_at, session.ended_at)
    billed = int(session.billable_minutes or 0)
    label = (
        f"VIP Room Session ({format_duration(elapsed)}, "
        f"billed {format_duration(billed)})"
    )
    fee = float(int(session.session_fee_charged or 0))
    return {
        "name": label,
        "quantity": 1,
        "unit_price": fee,
        "modifiers": [],
        "is_session_fee": True,
    }


def entry_fee_line_item(session: models.TableSession, *, use_charged: bool = False) -> Optional[dict]:
    guests = int(session.guest_count or 0)
    rate = float(session.entry_fee_per_guest_snapshot or 0)
    fee = (
        float(session.entry_fee_charged or 0)
        if use_charged
        else entry_fee_amount(guests, rate)
    )
    if fee <= 0 and guests <= 0:
        return None
    if fee <= 0:
        return None
    display_guests = guests if guests > 0 else 1
    unit = rate if guests > 0 and rate > 0 else fee
    return {
        "name": f"VIP Entry × {display_guests}",
        "quantity": display_guests,
        "unit_price": unit,
        "subtotal": fee,
        "modifiers": [],
        "is_entry_fee": True,
    }


def session_summary(session: models.TableSession, as_of: Optional[datetime] = None) -> dict:
    fee, billable, total_elapsed = calculate_session_fee(
        session.started_at,
        session.hourly_rate_snapshot,
        session.minimum_minutes_snapshot,
        session.free_minutes_snapshot,
        as_of=as_of,
    )
    guests = int(session.guest_count or 0)
    entry_rate = float(session.entry_fee_per_guest_snapshot or 0)
    entry_fee = entry_fee_amount(guests, entry_rate)
    return {
        "session_id": session.id,
        "started_at": session.started_at.isoformat(),
        "elapsed_minutes": total_elapsed,
        "elapsed_label": format_duration(total_elapsed),
        "billable_minutes": billable,
        "billing_blocks": billing_blocks(
            max(0, total_elapsed - int(session.free_minutes_snapshot or 0)),
            session.minimum_minutes_snapshot,
        ),
        "fee_per_block": fee_per_block(
            session.hourly_rate_snapshot, session.minimum_minutes_snapshot
        ),
        "current_fee": fee,
        "hourly_rate": session.hourly_rate_snapshot,
        "minimum_minutes": session.minimum_minutes_snapshot,
        "free_minutes": session.free_minutes_snapshot,
        "guest_count": guests,
        "entry_fee_per_guest": entry_rate,
        "entry_fee": entry_fee,
    }
