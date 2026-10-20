"""Monthly visit allowance and check-ins.

Each client gets ``MONTHLY_VISITS`` (default 3) per calendar month, in the food
bank's time zone. Nothing has to run on the 1st: the count is stored together
with the month it belongs to (``visits_period``), and a stored count from an
earlier month is treated as a full allowance. So the refill happens the moment
anyone looks at, or checks in, that client in the new month.

A check-in with visits left uses one. A check-in with none left is still
recorded, but flagged, so staff decide what to do rather than the software.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

import pandas as pd
from sqlalchemy import func, select, update

from .config import MONTHLY_VISITS, TZ
from .db import CheckIn, Client, format_member_code, session_scope


def period_of(now: datetime | None = None) -> str:
    """'2026-10' for the food bank's current month."""
    return (now or datetime.now(TZ)).astimezone(TZ).strftime("%Y-%m")


def effective_remaining(stored: int | None, stored_period: str | None, period: str) -> int:
    if stored is None or stored_period != period:
        return MONTHLY_VISITS
    return stored


@dataclass(frozen=True)
class VisitStatus:
    remaining: int
    allowance: int
    period: str
    used_this_month: int          # check-ins recorded this month (including flagged)
    flagged_this_month: int
    last_checkin: datetime | None

    @property
    def exhausted(self) -> bool:
        return self.remaining <= 0


@dataclass(frozen=True)
class CheckInResult:
    flagged: bool
    visit_number: int
    remaining: int
    allowance: int
    checkin_id: int


def status(client_id: int, now: datetime | None = None) -> VisitStatus:
    period = period_of(now)
    with session_scope() as s:
        row = s.get(Client, client_id)
        if row is None:
            raise KeyError(client_id)
        used, flagged, last = s.execute(
            select(func.count(), func.count().filter(CheckIn.flagged.is_(True)), func.max(CheckIn.checked_in_at))
            .where(CheckIn.client_id == client_id, CheckIn.period == period)
        ).one()
        if last is None:
            last = s.scalar(select(func.max(CheckIn.checked_in_at)).where(CheckIn.client_id == client_id))
        if last is not None and last.tzinfo is None:  # Postgres aggregate bypasses the column type
            last = last.replace(tzinfo=timezone.utc)
        return VisitStatus(
            remaining=effective_remaining(row.visits_remaining, row.visits_period, period),
            allowance=MONTHLY_VISITS, period=period, used_this_month=used or 0,
            flagged_this_month=flagged or 0, last_checkin=last,
        )


def check_in(client_id: int, now: datetime | None = None, note: str | None = None) -> CheckInResult:
    """Record a visit. Uses one visit if any are left; otherwise records it as flagged."""
    now = now or datetime.now(TZ)
    period = period_of(now)
    with session_scope() as s:
        # Lock the row so two stations scanning the same card can't both use the last visit.
        row = s.get(Client, client_id, with_for_update=True)
        if row is None:
            raise KeyError(client_id)
        remaining = effective_remaining(row.visits_remaining, row.visits_period, period)
        flagged = remaining <= 0
        remaining = max(remaining - 1, 0)
        row.visits_remaining, row.visits_period = remaining, period
        n_before = s.scalar(select(func.count()).where(CheckIn.client_id == client_id, CheckIn.period == period))
        ci = CheckIn(client_id=client_id, checked_in_at=now.astimezone(timezone.utc), period=period,
                     visit_number=(n_before or 0) + 1, remaining_after=remaining, flagged=flagged,
                     note=note)
        s.add(ci)
        s.flush()
        return CheckInResult(flagged, ci.visit_number, remaining, MONTHLY_VISITS, ci.checkin_id)


def set_remaining(client_id: int, remaining: int, now: datetime | None = None) -> None:
    """Admin override for the current month (e.g. 0 to test flagging)."""
    if remaining < 0:
        raise ValueError("remaining must be >= 0")
    with session_scope() as s:
        row = s.get(Client, client_id, with_for_update=True)
        if row is None:
            raise KeyError(client_id)
        row.visits_remaining, row.visits_period = remaining, period_of(now)


def reset_all(now: datetime | None = None) -> int:
    """Give every client the full allowance for the current month."""
    with session_scope() as s:
        res = s.execute(update(Client).values(visits_remaining=MONTHLY_VISITS, visits_period=period_of(now)))
        return res.rowcount or 0


def history(client_id: int | None = None, flagged_only: bool = False, period: str | None = None,
            limit: int = 200) -> pd.DataFrame:
    q = (select(CheckIn.checkin_id, CheckIn.checked_in_at, CheckIn.client_id, Client.first_name,
                Client.last_name, CheckIn.visit_number, CheckIn.remaining_after, CheckIn.flagged, CheckIn.note)
         .join(Client, Client.client_id == CheckIn.client_id)
         .order_by(CheckIn.checked_in_at.desc()).limit(limit))
    if client_id is not None:
        q = q.where(CheckIn.client_id == client_id)
    if flagged_only:
        q = q.where(CheckIn.flagged.is_(True))
    if period:
        q = q.where(CheckIn.period == period)
    with session_scope() as s:
        rows = s.execute(q).all()
    df = pd.DataFrame(rows, columns=["checkin_id", "checked_in_at", "client_id", "first_name", "last_name",
                                     "visit_number", "remaining_after", "flagged", "note"])
    if not df.empty:
        df.insert(2, "member", df["client_id"].map(format_member_code))
        df["checked_in_at"] = pd.to_datetime(df["checked_in_at"], utc=True).dt.tz_convert(TZ)
    return df
