"""SQLAlchemy model: one flat ``clients`` table.

The primary key ``client_id`` is the number the system assigns; it is what
the QR code / membership card encodes (as ``RGFP-000123``).
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from functools import lru_cache
from typing import Iterator

from sqlalchemy import (
    JSON, Boolean, Date, DateTime, Index, Integer, LargeBinary, String, Text, create_engine, event,
)
from sqlalchemy.engine import Engine
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from .config import DB_URL, MEMBER_PREFIX


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class UTCDateTime(TypeDecorator):
    """Stores UTC; always returns tz-aware UTC (SQLite drops tzinfo otherwise)."""

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):  # noqa: ANN001
        if value is not None:
            if value.tzinfo is None:
                raise ValueError("naive datetime; pass a tz-aware value")
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):  # noqa: ANN001
        return value.replace(tzinfo=timezone.utc) if value is not None and value.tzinfo is None else value


class Base(DeclarativeBase):
    pass


class Client(Base):
    __tablename__ = "clients"

    client_id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)
    source: Mapped[str] = mapped_column(String(80), default="intake")  # intake | seed | csv:<file>
    legacy_id: Mapped[str | None] = mapped_column(String(64))

    # Page 1 — registration
    intake_date: Mapped[date | None] = mapped_column(Date)
    first_name: Mapped[str] = mapped_column(String(60))
    middle_initial: Mapped[str | None] = mapped_column(String(1))
    last_name: Mapped[str] = mapped_column(String(60))
    age: Mapped[int | None] = mapped_column(Integer)
    is_senior: Mapped[bool | None] = mapped_column(Boolean)
    is_18_59: Mapped[bool | None] = mapped_column(Boolean)
    household_others: Mapped[int | None] = mapped_column(Integer)
    seniors_in_hh: Mapped[int | None] = mapped_column(Integer)
    adults_in_hh: Mapped[int | None] = mapped_column(Integer)
    children_in_hh: Mapped[int | None] = mapped_column(Integer)
    others_pickup: Mapped[bool | None] = mapped_column(Boolean)
    pickup_persons: Mapped[list] = mapped_column(JSON, default=list)  # [{"name":..,"phone":..}]
    simc_number: Mapped[str | None] = mapped_column(String(40))

    # Page 2 — TEFAP
    state: Mapped[str | None] = mapped_column(String(2))
    zip: Mapped[str | None] = mapped_column(String(10))
    county: Mapped[str | None] = mapped_column(String(60))
    phone: Mapped[str | None] = mapped_column(String(12))
    tefap_auto_eligible: Mapped[bool | None] = mapped_column(Boolean)
    tefap_household_size: Mapped[int | None] = mapped_column(Integer)
    tefap_income_period: Mapped[str | None] = mapped_column(String(10))
    tefap_income_limit: Mapped[int | None] = mapped_column(Integer)
    tefap_income_at_or_below: Mapped[bool | None] = mapped_column(Boolean)
    signature_png: Mapped[bytes | None] = mapped_column(LargeBinary)
    signature_date: Mapped[date | None] = mapped_column(Date)

    # Card / QR
    qr_png: Mapped[bytes | None] = mapped_column(LargeBinary)

    notes: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_clients_name", "last_name", "first_name"),
        Index("ix_clients_phone", "phone"),
        Index("ix_clients_simc", "simc_number"),
        Index("ix_clients_created", "created_at"),
    )

    @property
    def member_code(self) -> str:
        return format_member_code(self.client_id)

    @property
    def household_size(self) -> int | None:
        return None if self.household_others is None else self.household_others + 1

    @property
    def full_name(self) -> str:
        mi = f" {self.middle_initial}." if self.middle_initial else ""
        return f"{self.first_name}{mi} {self.last_name}"


def format_member_code(client_id: int) -> str:
    return f"{MEMBER_PREFIX}-{client_id:06d}"


# ---------------------------------------------------------------- engine --
@lru_cache(maxsize=4)
def get_engine(url: str = DB_URL) -> Engine:
    is_sqlite = url.startswith("sqlite")
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if is_sqlite else {},
        pool_pre_ping=True,
    )
    if is_sqlite:
        @event.listens_for(engine, "connect")
        def _pragmas(dbapi_conn, _):  # noqa: ANN001
            cur = dbapi_conn.cursor()
            cur.execute("PRAGMA journal_mode=WAL")      # readers don't block the writer
            cur.execute("PRAGMA synchronous=NORMAL")
            cur.execute("PRAGMA foreign_keys=ON")
            cur.close()
    Base.metadata.create_all(engine)
    return engine


@lru_cache(maxsize=4)
def _sessionmaker(url: str) -> sessionmaker[Session]:
    return sessionmaker(get_engine(url), expire_on_commit=False)


@contextmanager
def session_scope(url: str = DB_URL) -> Iterator[Session]:
    s = _sessionmaker(url)()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
