"""Data access: everything the UI does to the clients table goes through here."""
from __future__ import annotations

from datetime import datetime
from typing import Iterable, Sequence

import pandas as pd
from sqlalchemy import Select, delete, func, or_, select
from sqlalchemy.orm import Session

from .config import TZ
from .db import CheckIn, Client, format_member_code, session_scope
from .qr import make_qr_png, parse_member_code
from .schemas import ClientIn

# Columns written from a ClientIn onto the ORM row.
_FIELDS = [f for f in ClientIn.model_fields if f != "pickup_persons"]


def _apply(row: Client, data: ClientIn) -> None:
    for f in _FIELDS:
        setattr(row, f, getattr(data, f))
    row.pickup_persons = [p.model_dump() for p in data.pickup_persons]


def to_client_in(row: Client) -> ClientIn:
    d = {f: getattr(row, f) for f in _FIELDS}
    d["pickup_persons"] = row.pickup_persons or []
    return ClientIn.model_validate(d)


def ensure_qr(s: Session, row: Client) -> bytes:
    """QR PNG is stored on the record; generated on first need (bulk imports skip it)."""
    if not row.qr_png:
        row.qr_png = make_qr_png(format_member_code(row.client_id))
        s.flush()
    return row.qr_png


# ------------------------------------------------------------------ writes --
def create_client(data: ClientIn, signature_png: bytes | None = None, source: str = "intake") -> Client:
    with session_scope() as s:
        row = Client(source=source)
        _apply(row, data)
        row.signature_png = signature_png
        s.add(row)
        s.flush()  # assigns client_id
        ensure_qr(s, row)
        return row


def update_client(client_id: int, data: ClientIn, signature_png: bytes | None = None) -> Client:
    """signature_png=None keeps the existing signature."""
    with session_scope() as s:
        row = s.get(Client, client_id)
        if row is None:
            raise KeyError(client_id)
        _apply(row, data)
        if signature_png is not None:
            row.signature_png = signature_png
        ensure_qr(s, row)
        return row


def bulk_create(items: Iterable[ClientIn], source: str, with_qr: bool = True,
                progress=None) -> list[int]:  # noqa: ANN001
    items = list(items)
    ids: list[int] = []
    with session_scope() as s:
        rows = []
        for it in items:
            r = Client(source=source)
            _apply(r, it)
            rows.append(r)
        s.add_all(rows)
        s.flush()
        for i, r in enumerate(rows):
            if with_qr:
                r.qr_png = make_qr_png(format_member_code(r.client_id))
            ids.append(r.client_id)
            if progress and (i % 25 == 0 or i == len(rows) - 1):
                progress((i + 1) / len(rows))
    return ids


def delete_all() -> int:
    with session_scope() as s:
        n = s.scalar(select(func.count()).select_from(Client)) or 0
        s.execute(delete(CheckIn))
        s.execute(delete(Client))
        return n


# ------------------------------------------------------------------- reads --
def get_client(client_id: int) -> Client | None:
    with session_scope() as s:
        row = s.get(Client, client_id)
        if row is not None:
            ensure_qr(s, row)
        return row


def lookup(scanned: str) -> Client | None:
    cid = parse_member_code(scanned)
    return get_client(cid) if cid is not None else None


def _light(q: Select) -> Select:
    return q.with_only_columns(
        Client.client_id, Client.first_name, Client.middle_initial, Client.last_name,
        Client.age, Client.phone, Client.simc_number, Client.household_others, Client.created_at,
        Client.source,
    )


def _rows_to_df(rows: Sequence) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=[
        "client_id", "first_name", "middle_initial", "last_name", "age", "phone",
        "simc_number", "household_others", "created_at", "source",
    ])
    if not df.empty:
        df.insert(0, "member", df["client_id"].map(format_member_code))
        df["household"] = df["household_others"].map(lambda v: None if pd.isna(v) else int(v) + 1)
        df = df.drop(columns=["household_others"])
    return df


def search(text: str, limit: int = 50) -> pd.DataFrame:
    """Every whitespace token must match name, phone, SIMC # or member code."""
    q = select(Client)
    tokens = [t for t in (text or "").split() if t]
    for t in tokens:
        cid = parse_member_code(t)
        like = f"%{t}%"
        digits = "".join(ch for ch in t if ch.isdigit())
        conds = [Client.first_name.ilike(like), Client.last_name.ilike(like), Client.simc_number.ilike(like)]
        if len(digits) >= 3:
            conds.append(func.replace(Client.phone, "-", "").like(f"%{digits}%"))
        if cid is not None:
            conds.append(Client.client_id == cid)
        q = q.where(or_(*conds))
    q = _light(q.order_by(Client.last_name, Client.first_name).limit(limit))
    with session_scope() as s:
        return _rows_to_df(s.execute(q).all())


def recent(since: datetime, limit: int = 25) -> pd.DataFrame:
    q = _light(select(Client).where(Client.created_at >= since)
               .order_by(Client.created_at.desc()).limit(limit))
    with session_scope() as s:
        return _rows_to_df(s.execute(q).all())


def possible_duplicates(data: ClientIn, exclude_id: int | None = None) -> pd.DataFrame:
    """Same first+last name and (same phone or same age), case-insensitive."""
    q = select(Client).where(
        func.lower(Client.first_name) == data.first_name.lower(),
        func.lower(Client.last_name) == data.last_name.lower(),
    )
    alts = []
    if data.phone:
        alts.append(Client.phone == data.phone)
    if data.age is not None:
        alts.append(Client.age == data.age)
    if not alts:
        return _rows_to_df([])
    q = q.where(or_(*alts))
    if exclude_id is not None:
        q = q.where(Client.client_id != exclude_id)
    with session_scope() as s:
        return _rows_to_df(s.execute(_light(q.limit(10))).all())


def existing_keys() -> set[tuple[str, str, str]]:
    """(first, last, phone) for duplicate-skipping during CSV import."""
    with session_scope() as s:
        rows = s.execute(select(Client.first_name, Client.last_name, Client.phone)).all()
    return {(f.lower(), l.lower(), p or "") for f, l, p in rows}


def stats() -> dict:
    with session_scope() as s:
        total = s.scalar(select(func.count()).select_from(Client)) or 0
        people = s.scalar(select(func.coalesce(func.sum(Client.household_others + 1), 0))) or 0
        by_source = dict(s.execute(select(Client.source, func.count()).group_by(Client.source)).all())
        auto = s.scalar(select(func.count()).where(Client.tefap_auto_eligible.is_(True))) or 0
    return {"clients": total, "people": int(people), "by_source": by_source, "auto_eligible": auto}


def export_df() -> pd.DataFrame:
    """Everything except binary columns (signature / QR), plus member code."""
    cols = [c for c in Client.__table__.columns if not c.name.endswith("_png")]
    with session_scope() as s:
        rows = s.execute(select(*cols).order_by(Client.client_id)).all()
    df = pd.DataFrame(rows, columns=[c.name for c in cols])
    if not df.empty:
        df.insert(1, "member_code", df["client_id"].map(format_member_code))
        df["pickup_persons"] = df["pickup_persons"].map(
            lambda v: "; ".join(f"{p.get('name')} {p.get('phone') or ''}".strip() for p in (v or []))
        )
    return df


# ------------------------------------------------------------- browse all --
def all_clients_df(now: datetime | None = None) -> pd.DataFrame:
    """Every client (no images) with visit status, for the All Clients page. ~10k rows is fine."""
    from .config import MONTHLY_VISITS
    from .visits import period_of

    period = period_of(now)
    last_ci = (select(CheckIn.client_id, func.max(CheckIn.checked_in_at).label("last_checkin"))
               .group_by(CheckIn.client_id).subquery())
    flagged = (select(CheckIn.client_id, func.count().label("flagged_month"))
               .where(CheckIn.flagged.is_(True), CheckIn.period == period)
               .group_by(CheckIn.client_id).subquery())
    q = (select(Client.client_id, Client.first_name, Client.middle_initial, Client.last_name, Client.age,
                Client.phone, Client.household_others, Client.county, Client.zip, Client.simc_number,
                Client.tefap_auto_eligible, Client.created_at, Client.source,
                Client.visits_remaining, Client.visits_period,
                last_ci.c.last_checkin, func.coalesce(flagged.c.flagged_month, 0).label("flagged_month"))
         .outerjoin(last_ci, last_ci.c.client_id == Client.client_id)
         .outerjoin(flagged, flagged.c.client_id == Client.client_id)
         .order_by(Client.last_name, Client.first_name, Client.client_id))
    with session_scope() as s:
        rows = s.execute(q).all()
    df = pd.DataFrame(rows, columns=[c for c in rows[0]._fields] if rows else [
        "client_id", "first_name", "middle_initial", "last_name", "age", "phone", "household_others",
        "county", "zip", "simc_number", "tefap_auto_eligible", "created_at", "source", "visits_remaining",
        "visits_period", "last_checkin", "flagged_month"])
    df.insert(0, "member", df["client_id"].map(format_member_code))
    df["name"] = (df["first_name"].fillna("") + " "
                  + df["middle_initial"].fillna("").map(lambda m: f"{m}. " if m else "")
                  + df["last_name"].fillna(""))
    df["household"] = df["household_others"].map(lambda v: None if pd.isna(v) else int(v) + 1).astype("Int64")
    current = df["visits_period"] == period
    df["visits_left"] = df["visits_remaining"].where(current & df["visits_remaining"].notna(),
                                                     MONTHLY_VISITS).astype("Int64")
    for col in ("created_at", "last_checkin"):
        df[col] = pd.to_datetime(df[col], utc=True).dt.tz_convert(TZ)
    return df


def filter_clients(df: pd.DataFrame, text: str = "") -> pd.DataFrame:
    """Keep rows where every word matches name, member #, phone, SIMC #, ZIP or county."""
    words = [w.lower() for w in (text or "").split()]
    if not words or df.empty:
        return df
    hay = (df["member"] + " " + df["name"] + " " + df["phone"].fillna("") + " "
           + df["phone"].fillna("").str.replace("-", "", regex=False) + " " + df["simc_number"].fillna("")
           + " " + df["zip"].fillna("") + " " + df["county"].fillna("")).str.lower()
    mask = pd.Series(True, index=df.index)
    for w in words:
        cid = parse_member_code(w)
        m = hay.str.contains(w, regex=False)
        if cid is not None:
            m |= df["client_id"] == cid
        mask &= m
    return df[mask]
