"""Map an arbitrary CSV export onto the client schema.

Pipeline: read_csv -> suggest_mapping (auto) -> [user adjusts] -> transform
(rows -> validated ClientIn, or per-row error messages).

Besides real schema fields, a column can map to a *virtual* target that is
split/derived during transform:
  full_name      "Garcia, Maria J" / "Maria J. Garcia"  -> first, MI, last
  state_zip      "NM 87102" / "New Mexico, 87102"       -> state, zip
  date_of_birth  any date                                -> age (as of intake/today)
  pickup_name / pickup_phone                             -> one pickup person
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from datetime import date
from difflib import SequenceMatcher

import pandas as pd
from pydantic import ValidationError

from .reference import STATE_BY_NAME, US_STATES
from .schemas import SCHEMA_FIELDS, ClientIn, PickupPerson, to_date

IGNORE = "— ignore —"
VIRTUAL = ["full_name", "state_zip", "date_of_birth", "pickup_name", "pickup_phone"]
TARGETS = [*SCHEMA_FIELDS, *VIRTUAL]

# Synonyms are compared after normalization (lowercase, alphanumerics only).
SYNONYMS: dict[str, list[str]] = {
    "first_name": ["first", "fname", "firstname", "givenname", "given", "forename", "clientfirstname"],
    "middle_initial": ["mi", "middle", "middlename", "middleinitial", "minitial"],
    "last_name": ["last", "lname", "lastname", "surname", "familyname", "clientlastname"],
    "full_name": ["name", "fullname", "clientname", "customername", "householdname", "headofhousehold"],
    "age": ["age", "clientage", "ageyears"],
    "date_of_birth": ["dob", "birthdate", "dateofbirth", "birthday", "bday"],
    "is_senior": ["senior", "isasenior", "senior60", "over60", "60orolder", "aresenior"],
    "is_18_59": ["adult", "age1859", "18to59", "is1859", "adult1859"],
    "household_others": ["householdothers", "otherpeople", "othersinhousehold", "additionalmembers",
                         "peoplenotincludingyou", "othermembers"],
    "seniors_in_hh": ["seniors", "numseniors", "seniorsinhousehold", "householdseniors", "seniorcount"],
    "adults_in_hh": ["adults", "numadults", "adultsinhousehold", "householdadults", "adultcount"],
    "children_in_hh": ["children", "kids", "numchildren", "childreninhousehold", "minors", "childcount"],
    "others_pickup": ["otherpickup", "proxy", "proxypickup", "anyoneelsepickup", "authorizedpickup"],
    "pickup_name": ["proxyname", "pickupname", "pickupperson", "authorizedname", "alternatename"],
    "pickup_phone": ["proxyphone", "pickupphone", "alternatephone", "authorizedphone"],
    "simc_number": ["simc", "simcnumber", "simcno", "simcid"],
    "state": ["state", "st", "stateprovince"],
    "zip": ["zip", "zipcode", "postal", "postalcode", "zip5"],
    "state_zip": ["statezip", "statezipcode", "stzip"],
    "county": ["county", "countyname"],
    "phone": ["phone", "phonenumber", "telephone", "tel", "cell", "mobile", "cellphone", "primaryphone"],
    "tefap_auto_eligible": ["autoeligible", "snap", "receivessnap", "programs", "section1", "categorical",
                            "snapwicfdpircsfp", "automaticeligibility"],
    "tefap_household_size": ["tefaphouseholdsize", "incomehouseholdsize", "circledsize"],
    "tefap_income_period": ["incomeperiod", "period", "incomefrequency"],
    "tefap_income_limit": ["incomelimit", "tefaplimit"],
    "tefap_income_at_or_below": ["incomeeligible", "belowlimit", "incomeatorbelow", "incomeunderlimit",
                                 "incomequalified"],
    "signature_date": ["signaturedate", "signeddate", "datesigned", "attestationdate"],
    "intake_date": ["date", "intakedate", "registrationdate", "enrolled", "enrolleddate", "createdate",
                    "dateregistered", "firstvisit", "created"],
    "notes": ["notes", "note", "comments", "comment", "remarks"],
    "legacy_id": ["id", "clientid", "customerid", "memberid", "recordid", "householdid", "pantrytraxid",
                  "oldid", "legacyid"],
}


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def read_csv(data: bytes) -> pd.DataFrame:
    """All columns as strings; tolerant of BOMs, Excel/latin-1 encodings and ; or tab separators."""
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = data.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    df = pd.read_csv(io.StringIO(text), dtype=str, keep_default_na=False, sep=None, engine="python")
    df.columns = [str(c).strip() for c in df.columns]
    return df.loc[:, [c for c in df.columns if c and not c.startswith("Unnamed")]]


def suggest_mapping(columns: list[str]) -> dict[str, str]:
    """source column -> target (or IGNORE). Each target is used at most once."""
    scored: list[tuple[float, str, str]] = []
    for col in columns:
        n = _norm(col)
        for target in TARGETS:
            cands = [_norm(target), *SYNONYMS.get(target, [])]
            if n in cands:
                score = 1.0
            else:
                score = max(SequenceMatcher(None, n, c).ratio() for c in cands)
                # containment ("Client First Name" contains "firstname")
                if any(len(c) >= 4 and c in n for c in cands):
                    score = max(score, 0.86)
            if score >= 0.8:
                scored.append((score, col, target))
    mapping = {c: IGNORE for c in columns}
    used: set[str] = set()
    for score, col, target in sorted(scored, key=lambda t: -t[0]):
        if mapping[col] == IGNORE and target not in used:
            mapping[col] = target
            used.add(target)
    # A real first/last pair beats a "name" column.
    if {"first_name", "last_name"} <= used and "full_name" in used:
        for c, t in mapping.items():
            if t == "full_name":
                mapping[c] = IGNORE
    return mapping


# ---------------------------------------------------------- splitting helpers --
def split_full_name(s: str) -> tuple[str | None, str | None, str | None]:
    s = " ".join(str(s).replace(".", " ").split())
    if not s:
        return None, None, None
    if "," in s:  # "Last, First M"
        last, rest = [p.strip() for p in s.split(",", 1)]
        parts = rest.split()
        first = parts[0] if parts else None
        mi = parts[1][0] if len(parts) > 1 else None
        return first, mi, last
    parts = s.split()
    if len(parts) == 1:
        return parts[0], None, None
    if len(parts) == 2:
        return parts[0], None, parts[1]
    if len(parts[1]) == 1:  # "Maria J Garcia Lopez"
        return parts[0], parts[1], " ".join(parts[2:])
    return parts[0], None, " ".join(parts[1:])


def split_state_zip(s: str) -> tuple[str | None, str | None]:
    s = str(s).strip()
    m = re.search(r"(\d{5}(?:-\d{4})?)", s)
    z = m.group(1) if m else None
    rest = re.sub(r"[\d\-,]+", " ", s).strip(" ,")
    rest = " ".join(rest.split())
    st = None
    if rest:
        if rest.upper() in US_STATES:
            st = rest.upper()
        else:
            st = STATE_BY_NAME.get(rest.lower(), rest)
    return st, z


def age_from_dob(dob: date, as_of: date) -> int:
    return as_of.year - dob.year - ((as_of.month, as_of.day) < (dob.month, dob.day))


# ---------------------------------------------------------------- transform --
@dataclass
class RowResult:
    row: int                     # 1-based row number in the CSV (excluding header)
    client: ClientIn | None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _fmt_error(e: ValidationError) -> list[str]:
    out = []
    for err in e.errors():
        loc = ".".join(str(p) for p in err["loc"]) or "record"
        msg = err["msg"].removeprefix("Value error, ")
        out.append(f"{loc}: {msg}")
    return out


def _with_area_code(v: str, area: str | None) -> str:
    digits = re.sub(r"\D", "", v or "")
    return f"{area}{digits}" if area and len(digits) == 7 else v


NEVER_DROP = {"first_name", "last_name"}


def transform(df: pd.DataFrame, mapping: dict[str, str], unmapped_to_notes: bool = False,
              today: date | None = None, default_area_code: str | None = "505",
              salvage: bool = True) -> list[RowResult]:
    """salvage=True: a bad value in a non-name field is blanked (and recorded in notes)
    instead of rejecting the whole row."""
    today = today or date.today()
    active = {c: t for c, t in mapping.items() if t and t != IGNORE}
    unmapped = [c for c in df.columns if c not in active]
    results: list[RowResult] = []
    for i, rec in enumerate(df.to_dict(orient="records"), start=1):
        d: dict = {}
        errs: list[str] = []
        extra_notes: list[str] = []
        for col, target in active.items():
            val = rec.get(col, "")
            if target not in VIRTUAL:
                if target == "notes" and d.get("notes"):
                    d["notes"] = f"{d['notes']} | {val}"
                else:
                    d[target] = val
        for col, target in active.items():  # virtual targets fill only what's still empty
            val = str(rec.get(col, "")).strip()
            if not val:
                continue
            if target == "full_name":
                f, mi, l = split_full_name(val)
                if not d.get("first_name"):
                    d["first_name"] = f
                if not d.get("middle_initial") and mi:
                    d["middle_initial"] = mi
                if not d.get("last_name"):
                    d["last_name"] = l
            elif target == "state_zip":
                st, z = split_state_zip(val)
                if not d.get("state"):
                    d["state"] = st
                if not d.get("zip"):
                    d["zip"] = z
            elif target == "date_of_birth" and not str(d.get("age", "")).strip():
                try:
                    dob = to_date(val)
                    as_of = to_date(d.get("intake_date")) or today
                    d["age"] = age_from_dob(dob, as_of) if dob else None
                except ValueError as e:
                    errs.append(f"date_of_birth: {e}")
        pname = next((str(rec[c]).strip() for c, t in active.items() if t == "pickup_name"), "")
        pphone = next((str(rec[c]).strip() for c, t in active.items() if t == "pickup_phone"), "")
        if d.get("phone"):
            d["phone"] = _with_area_code(str(d["phone"]), default_area_code)
        pphone = _with_area_code(pphone, default_area_code)
        if pname:
            try:
                d["pickup_persons"] = [PickupPerson(name=pname, phone=pphone or None)]
            except ValidationError as e:
                errs += [f"pickup_{m}" for m in _fmt_error(e)]
        if unmapped_to_notes:
            extra_notes = [f"{c}: {rec[c]}" for c in unmapped if str(rec.get(c, "")).strip()]
            if extra_notes:
                d["notes"] = " | ".join(filter(None, [d.get("notes"), *extra_notes]))
        if errs:
            results.append(RowResult(i, None, errs))
            continue
        try:
            c = ClientIn.model_validate(d)
            results.append(RowResult(i, c, [], c.warnings()))
            continue
        except ValidationError as e:
            first_err = e
        bad = {str(err["loc"][0]) for err in first_err.errors() if err["loc"]}
        if not salvage or bad & NEVER_DROP or not bad:
            results.append(RowResult(i, None, _fmt_error(first_err)))
            continue
        dropped = [f"{f}={d.get(f)!r}" for f in sorted(bad)]
        for f in bad:
            d.pop(f, None)
        d["notes"] = " | ".join(filter(None, [d.get("notes"), "Import dropped invalid: " + ", ".join(dropped)]))
        try:
            c = ClientIn.model_validate(d)
            results.append(RowResult(i, c, [], [*_fmt_error(first_err), *c.warnings()]))
        except ValidationError as e:
            results.append(RowResult(i, None, _fmt_error(e)))
    return results


def template_csv() -> bytes:
    """A blank CSV with the exact schema columns (plus helper columns)."""
    cols = [*SCHEMA_FIELDS, "pickup_name", "pickup_phone"]
    return (",".join(cols) + "\n").encode()
