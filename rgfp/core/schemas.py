"""The single source of truth for a client record's shape and rules.

Every way data gets in — the intake form, the returning-client editor, the
seeder and the CSV importer — goes through ``ClientIn``. The ``before``
validators are deliberately forgiving about *input format* ("Y", "yes", "1";
"(505) 555 1234"; "New Mexico") so the CSV importer can hand raw strings
straight to the model.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .reference import STATE_BY_NAME, US_STATES, IncomePeriod, tefap_limit

_TRUE = {"y", "yes", "true", "t", "1", "x", "✓", "checked", "on"}
_FALSE = {"n", "no", "false", "f", "0", "", "unchecked", "off"}
_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%Y/%m/%d", "%d-%b-%Y", "%b %d, %Y")


# ---------------------------------------------------------------- coercers --
def blank_to_none(v: Any) -> Any:
    if v is None:
        return None
    if isinstance(v, float) and v != v:  # NaN from pandas
        return None
    if isinstance(v, str) and v.strip() in {"", "-", "n/a", "N/A", "na", "NA", "null", "None", "nan"}:
        return None
    return v


def to_bool(v: Any) -> bool | None:
    v = blank_to_none(v)
    if v is None or isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    raise ValueError(f"not a yes/no value: {v!r}")


def to_int(v: Any) -> int | None:
    v = blank_to_none(v)
    if v is None or isinstance(v, bool):
        return None if v is None else int(v)
    if isinstance(v, (int, float)):
        if float(v) != int(v):
            raise ValueError(f"expected a whole number, got {v!r}")
        return int(v)
    s = str(v).strip().replace(",", "")
    f = float(s)  # raises ValueError on junk
    if f != int(f):
        raise ValueError(f"expected a whole number, got {v!r}")
    return int(f)


def to_date(v: Any) -> date | None:
    v = blank_to_none(v)
    if v is None or (isinstance(v, date) and not isinstance(v, datetime)):
        return v
    if isinstance(v, datetime):
        return v.date()
    s = str(v).strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        raise ValueError(f"unrecognized date: {v!r}") from None


def normalize_phone(v: Any) -> str | None:
    v = blank_to_none(v)
    if v is None:
        return None
    digits = re.sub(r"\D", "", str(v))
    if len(digits) == 11 and digits.startswith("1"):
        digits = digits[1:]
    if len(digits) != 10:
        raise ValueError(f"phone must have 10 digits (XXX-XXX-XXXX), got {v!r}")
    return f"{digits[:3]}-{digits[3:6]}-{digits[6:]}"


def normalize_state(v: Any) -> str | None:
    v = blank_to_none(v)
    if v is None:
        return None
    s = str(v).strip()
    if s.upper() in US_STATES:
        return s.upper()
    code = STATE_BY_NAME.get(s.lower())
    if code:
        return code
    raise ValueError(f"unknown state: {v!r}")


def normalize_zip(v: Any) -> str | None:
    v = blank_to_none(v)
    if v is None:
        return None
    s = str(v).strip()
    if re.fullmatch(r"\d{3,4}(\.0)?", s):  # Excel ate the leading zero(s)
        s = s.split(".")[0].zfill(5)
    if re.fullmatch(r"\d{9}", s):
        s = f"{s[:5]}-{s[5:]}"
    if not re.fullmatch(r"\d{5}(-\d{4})?", s):
        raise ValueError(f"ZIP must be 5 digits (or ZIP+4), got {v!r}")
    return s


# ------------------------------------------------------------------ models --
class PickupPerson(BaseModel):
    """Someone else authorized to pick up food for this household."""

    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=120)
    phone: str | None = None

    _phone = field_validator("phone", mode="before")(normalize_phone)


class ClientIn(BaseModel):
    """A validated client record (both pages of the registration form)."""

    model_config = ConfigDict(str_strip_whitespace=True, extra="ignore")

    # ---- Page 1: Registration form
    intake_date: date | None = None
    first_name: str = Field(min_length=1, max_length=60)
    middle_initial: str | None = Field(None, max_length=1)
    last_name: str = Field(min_length=1, max_length=60)
    age: int | None = Field(None, ge=0, le=120)
    is_senior: bool | None = None          # "Are you a Senior? (60 or older)"
    is_18_59: bool | None = None           # "Are you age 18 to 59?"
    household_others: int | None = Field(None, ge=0, le=30)  # NOT including the client
    seniors_in_hh: int | None = Field(None, ge=0, le=30)
    adults_in_hh: int | None = Field(None, ge=0, le=30)
    children_in_hh: int | None = Field(None, ge=0, le=30)
    others_pickup: bool | None = None
    pickup_persons: list[PickupPerson] = Field(default_factory=list)
    simc_number: str | None = Field(None, max_length=40)

    # ---- Page 2: TEFAP
    state: str | None = None
    zip: str | None = None
    county: str | None = Field(None, max_length=60)
    phone: str | None = None
    tefap_auto_eligible: bool | None = None          # Section 1 checkbox
    tefap_household_size: int | None = Field(None, ge=1, le=30)  # Section 2 row circled
    tefap_income_period: IncomePeriod | None = None   # Section 2 column circled
    tefap_income_limit: int | None = None             # snapshot of the circled limit
    tefap_income_at_or_below: bool | None = None      # "Is your income the same or lower?"
    signature_date: date | None = None                # Section 3

    # ---- Housekeeping
    notes: str | None = Field(None, max_length=4000)
    legacy_id: str | None = Field(None, max_length=64)

    # -- before-validators: accept messy input, emit clean values
    _blank = field_validator(
        "simc_number", "county", "notes", "legacy_id",
        mode="before",
    )(blank_to_none)
    _bools = field_validator(
        "is_senior", "is_18_59", "others_pickup", "tefap_auto_eligible", "tefap_income_at_or_below",
        mode="before",
    )(to_bool)
    _ints = field_validator(
        "age", "household_others", "seniors_in_hh", "adults_in_hh", "children_in_hh",
        "tefap_household_size", "tefap_income_limit", mode="before",
    )(to_int)
    _dates = field_validator("intake_date", "signature_date", mode="before")(to_date)
    _phone = field_validator("phone", mode="before")(normalize_phone)
    _state = field_validator("state", mode="before")(normalize_state)
    _zip = field_validator("zip", mode="before")(normalize_zip)

    @field_validator("first_name", "last_name", mode="before")
    @classmethod
    def _name(cls, v: Any) -> Any:
        v = blank_to_none(v)
        if v is None:
            return None
        s = " ".join(str(v).split())
        # "MARIA" / "maria" (common in exports) -> "Maria"; leave "McKinley", "de la Cruz" alone.
        return s.title() if (s.isupper() or s.islower()) else s

    @field_validator("middle_initial", mode="before")
    @classmethod
    def _mi(cls, v: Any) -> str | None:
        v = blank_to_none(v)
        if v is None:
            return None
        s = str(v).strip().rstrip(".").upper()
        return s[:1] or None

    @field_validator("tefap_income_period", mode="before")
    @classmethod
    def _period(cls, v: Any) -> str | None:
        v = blank_to_none(v)
        if v is None:
            return None
        s = str(v).strip().lower()
        return {"year": "annual", "yearly": "annual", "annually": "annual", "month": "monthly",
                "week": "weekly"}.get(s, s)

    @model_validator(mode="after")
    def _derive(self) -> "ClientIn":
        # Age answers the two Yes/No questions if they were left blank.
        if self.age is not None:
            if self.is_senior is None:
                self.is_senior = self.age >= 60
            if self.is_18_59 is None:
                self.is_18_59 = 18 <= self.age <= 59
        parts = [self.seniors_in_hh, self.adults_in_hh, self.children_in_hh]
        if self.household_others is None and all(p is not None for p in parts):
            self.household_others = sum(parts)  # type: ignore[arg-type]
        if self.others_pickup is False:
            self.pickup_persons = []
        if self.pickup_persons and self.others_pickup is None:
            self.others_pickup = True
        # Section 1 checked => Section 2 is skipped.
        if self.tefap_auto_eligible:
            self.tefap_household_size = None
            self.tefap_income_period = None
            self.tefap_income_limit = None
            self.tefap_income_at_or_below = None
        elif self.tefap_household_size and self.tefap_income_period:
            self.tefap_income_limit = tefap_limit(self.tefap_household_size, self.tefap_income_period)
        return self

    # -- derived / soft checks
    @property
    def household_size(self) -> int | None:
        """Total people in household, including the client (TEFAP page 'Number of people')."""
        return None if self.household_others is None else self.household_others + 1

    @property
    def full_name(self) -> str:
        mi = f" {self.middle_initial}." if self.middle_initial else ""
        return f"{self.first_name}{mi} {self.last_name}"

    def warnings(self) -> list[str]:
        """Inconsistencies worth a second look, but not worth blocking a save."""
        out: list[str] = []
        if self.age is not None:
            if self.is_senior is not None and self.is_senior != (self.age >= 60):
                out.append(f"Age {self.age} doesn't match 'Senior' = {'Yes' if self.is_senior else 'No'}.")
            if self.is_18_59 is not None and self.is_18_59 != (18 <= self.age <= 59):
                out.append(f"Age {self.age} doesn't match 'Age 18–59' = {'Yes' if self.is_18_59 else 'No'}.")
        parts = [self.seniors_in_hh, self.adults_in_hh, self.children_in_hh]
        if self.household_others is not None and all(p is not None for p in parts):
            if sum(parts) != self.household_others:  # type: ignore[arg-type]
                out.append(
                    f"Seniors + adults + children = {sum(parts)}, but household (not including client) "
                    f"= {self.household_others}."
                )
        if (
            self.tefap_household_size and self.household_size
            and self.tefap_household_size != self.household_size
        ):
            out.append(
                f"TEFAP household size circled ({self.tefap_household_size}) differs from "
                f"people in household ({self.household_size})."
            )
        if self.others_pickup and not self.pickup_persons:
            out.append("'Will anyone else pick up food' is Yes but no name was entered.")
        if self.tefap_auto_eligible is False and self.tefap_income_at_or_below is False:
            out.append("Not auto-eligible and income is above the limit — household may not qualify for TEFAP.")
        return out

    @property
    def tefap_eligible(self) -> bool | None:
        if self.tefap_auto_eligible:
            return True
        return self.tefap_income_at_or_below


# Columns a CSV can map onto, in display order (used by the importer + template).
SCHEMA_FIELDS: list[str] = [n for n in ClientIn.model_fields if n != "pickup_persons"]
