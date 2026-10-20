"""The two-page registration form, shared by New Client, Returning Client and kiosk.

State handling: every widget key is ``"{ns}.{nonce}.{field}"``. Clearing or
loading a record just bumps the nonce, so Streamlit discards the old widgets
(including file uploaders and the data editor, which can't be reset via
session_state) and fresh ones are created with the new values.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import pandas as pd
import streamlit as st
from pydantic import ValidationError

from core.reference import INCOME_PERIODS, NM_COUNTIES, TEFAP_ADDITIONAL, TEFAP_LIMITS, TEFAP_LIMITS_YEAR, US_STATES, tefap_limit
from core.schemas import ClientIn, normalize_phone
from ui.theme import now_local, section

LABELS = {
    "intake_date": "Date", "first_name": "First name", "middle_initial": "Middle initial",
    "last_name": "Last name", "age": "Age", "is_senior": "Senior (60+)", "is_18_59": "Age 18–59",
    "household_others": "People in household (not including you)", "seniors_in_hh": "Seniors in household",
    "adults_in_hh": "Adults in household", "children_in_hh": "Children in household",
    "others_pickup": "Anyone else picks up", "pickup_persons": "Pick-up person", "simc_number": "SIMC #",
    "state": "State", "zip": "ZIP", "county": "County", "phone": "Phone",
    "tefap_auto_eligible": "Section 1", "tefap_household_size": "Household size (Section 2)",
    "tefap_income_period": "Income period (Section 2)", "tefap_income_at_or_below": "Income at/below limit",
    "signature_date": "Signature date", "notes": "Notes",
}
REQUIRED = ["first_name", "last_name", "age", "household_others", "state", "zip", "county", "phone"]
YES_NO = [True, False]


def _yn(v: bool) -> str:
    return "Yes" if v else "No"


# -------------------------------------------------------------- key mgmt --
def _nonce(ns: str) -> int:
    return st.session_state.setdefault(f"{ns}.nonce", 0)


def k(ns: str, name: str) -> str:
    return f"{ns}.{_nonce(ns)}.{name}"


def _drop_ns(ns: str) -> None:
    for key in [x for x in st.session_state if isinstance(x, str) and x.startswith(f"{ns}.")
                and not x.endswith(".nonce")]:
        del st.session_state[key]


def clear_form(ns: str, defaults: bool = True) -> None:
    _drop_ns(ns)
    st.session_state[f"{ns}.nonce"] = _nonce(ns) + 1
    if defaults:
        today = now_local().date()
        st.session_state[k(ns, "intake_date")] = today
        st.session_state[k(ns, "signature_date")] = today
        st.session_state[k(ns, "state")] = "NM"


def load_form(ns: str, data: ClientIn, signature: bytes | None = None) -> None:
    clear_form(ns, defaults=False)
    ss = st.session_state
    for f, v in data.model_dump(exclude={"pickup_persons"}).items():
        if v is not None:
            ss[k(ns, f)] = v
    if data.county:
        ss[k(ns, "county_nm" if data.state == "NM" else "county_txt")] = data.county
    ss[k(ns, "pickup_init")] = pd.DataFrame([p.model_dump() for p in data.pickup_persons],
                                            columns=["name", "phone"])
    ss[k(ns, "existing_signature")] = signature


def ensure_initialized(ns: str) -> None:
    if f"{ns}.nonce" not in st.session_state:
        clear_form(ns)


# ---------------------------------------------------------------- page 1 --
def render_page1(ns: str) -> dict[str, Any]:
    ss = st.session_state
    v: dict[str, Any] = {}
    top_l, top_r = st.columns([3, 1])
    with top_l:
        st.markdown("#### Registration Form")
    with top_r:
        v["intake_date"] = st.date_input("Date", key=k(ns, "intake_date"), value=None, format="MM/DD/YYYY")
    st.markdown(
        '<div class="rg-consent">By filling out this form, you agree that your information can be entered '
        "into Rio Grande Food Project's private and secure database. Our database is used to make food "
        "distributions more efficient and is used for reporting purposes (totals only — identifying "
        "information is never reported out).</div>", unsafe_allow_html=True)
    st.write("")

    with st.container(border=True):
        section("A", "About you")
        c1, c2, c3 = st.columns([4, 1.3, 4])
        v["first_name"] = c1.text_input("First name *", key=k(ns, "first_name"), max_chars=60)
        v["middle_initial"] = c2.text_input("M.I.", key=k(ns, "middle_initial"), max_chars=1)
        v["last_name"] = c3.text_input("Last name *", key=k(ns, "last_name"), max_chars=60)

        c1, c2, c3 = st.columns([1.2, 2, 2])
        v["age"] = c1.number_input("Age *", key=k(ns, "age"), min_value=0, max_value=120, step=1, value=None)
        age = v["age"]
        for col, field, label, rule in (
            (c2, "is_senior", "Are you a Senior? (60 or older)", lambda a: a >= 60),
            (c3, "is_18_59", "Are you age 18 to 59?", lambda a: 18 <= a <= 59),
        ):
            with col:
                # Pre-fill from age until the person answers themselves.
                key = k(ns, field)
                if age is not None and ss.get(key) is None and not ss.get(f"{key}.touched"):
                    ss[key] = rule(age)
                v[field] = st.radio(label, YES_NO, format_func=_yn, key=key, index=None, horizontal=True,
                                    on_change=lambda kk=key: ss.__setitem__(f"{kk}.touched", True))
        v["household_others"] = st.number_input(
            "How many people (NOT including you) live in the household? *",
            key=k(ns, "household_others"), min_value=0, max_value=30, step=1, value=None)

    with st.container(border=True):
        section("B", "Other people who live with you")
        st.markdown('<div class="rg-callout">Please tell us about <em>any other people</em> '
                    "that live with you.</div>", unsafe_allow_html=True)
        st.write("")
        c1, c2, c3 = st.columns(3)
        v["seniors_in_hh"] = c1.number_input("Seniors (60+)", key=k(ns, "seniors_in_hh"), min_value=0,
                                             max_value=30, step=1, value=None,
                                             help="Does not include yourself, if you are 60 or older.")
        v["adults_in_hh"] = c2.number_input("Adults (18–59)", key=k(ns, "adults_in_hh"), min_value=0,
                                            max_value=30, step=1, value=None,
                                            help="Does not include yourself, if you are in this age range.")
        v["children_in_hh"] = c3.number_input("Children (0–17)", key=k(ns, "children_in_hh"), min_value=0,
                                              max_value=30, step=1, value=None)
        parts = [v["seniors_in_hh"], v["adults_in_hh"], v["children_in_hh"]]
        if v["household_others"] is not None and all(p is not None for p in parts):
            total = sum(parts)
            if total == v["household_others"]:
                st.caption(f"✅ Adds up: {total} other people + you = household of {total + 1}.")
            else:
                st.warning(f"These add up to **{total}**, but you said **{v['household_others']}** other "
                           "people live with you.")

    with st.container(border=True):
        section("C", "Pick-up & program info")
        v["others_pickup"] = st.radio("Will anyone else pick up food for you?", YES_NO, format_func=_yn,
                                      key=k(ns, "others_pickup"), index=None, horizontal=True)
        v["pickup_persons"] = []
        if v["others_pickup"]:
            init = ss.get(k(ns, "pickup_init"))
            if init is None or init.empty:
                init = pd.DataFrame([{"name": "", "phone": ""}])
            df = st.data_editor(
                init, key=k(ns, "pickup_editor"), num_rows="dynamic",
                hide_index=True,
                column_config={
                    "name": st.column_config.TextColumn("Name", required=True, max_chars=120),
                    "phone": st.column_config.TextColumn("Phone (XXX-XXX-XXXX)", max_chars=14),
                },
            )
            v["pickup_persons"] = [
                {"name": str(r["name"]).strip(), "phone": (str(r["phone"]).strip() or None)
                 if pd.notna(r["phone"]) else None}
                for _, r in df.iterrows() if pd.notna(r["name"]) and str(r["name"]).strip()
            ]
            st.caption("Add a row for each person allowed to pick up food for this household.")
        v["simc_number"] = st.text_input("SIMC #", key=k(ns, "simc_number"), max_chars=40)
    return v


# ---------------------------------------------------------------- page 2 --
def tefap_table_html(size: int | None, period: str | None) -> str:
    head = "<tr><th>Household size</th><th>Annual</th><th>Monthly</th><th>Weekly</th></tr>"
    rows = []
    sizes = list(TEFAP_LIMITS) + ([size] if size and size > 8 else [])
    for n in sizes:
        cls = ' class="sel"' if n == size else ""
        cells = "".join(
            f'<td{" class=hit" if n == size and p == period else ""}>${tefap_limit(n, p):,}</td>'
            for p in INCOME_PERIODS)
        rows.append(f"<tr{cls}><td>{n}</td>{cells}</tr>")
    add = "".join(f"<td>+${x:,}</td>" for x in TEFAP_ADDITIONAL)
    rows.append(f'<tr><td class="rg-muted">Each additional</td>{add}</tr>')
    return f'<table class="tefap">{head}{"".join(rows)}</table>'


def render_page2(ns: str, p1: dict[str, Any]) -> dict[str, Any]:
    ss = st.session_state
    v: dict[str, Any] = {}
    st.markdown("#### State of New Mexico — The Emergency Food Assistance Program (TEFAP)")
    hh = None if p1.get("household_others") is None else p1["household_others"] + 1
    name = " ".join(x for x in [p1.get("first_name"), (p1.get("middle_initial") or "") and
                                f"{p1['middle_initial']}.", p1.get("last_name")] if x)

    with st.container(border=True):
        c1, c2 = st.columns([3, 2])
        c1.markdown(f'<span class="rg-muted">Name (from page 1)</span><br><b>{name or "—"}</b>',
                    unsafe_allow_html=True)
        c2.markdown(f'<span class="rg-muted">Number of people in household</span><br><b>{hh or "—"}</b>',
                    unsafe_allow_html=True)
        c1, c2, c3, c4 = st.columns([2.4, 1.3, 2.4, 2])
        v["state"] = c1.selectbox("State *", list(US_STATES), key=k(ns, "state"), index=None,
                                  format_func=lambda s: f"{s} — {US_STATES[s]}")
        v["zip"] = c2.text_input("ZIP *", key=k(ns, "zip"), max_chars=10, placeholder="87102")
        if v["state"] == "NM":
            v["county"] = c3.selectbox("County *", NM_COUNTIES, key=k(ns, "county_nm"), index=None,
                                       accept_new_options=True, placeholder="Choose or type…")
        else:
            v["county"] = c3.text_input("County *", key=k(ns, "county_txt"), max_chars=60)
        v["phone"] = c4.text_input("Phone *", key=k(ns, "phone"), max_chars=14, placeholder="505-555-0123")
        if v["phone"]:
            try:
                fmt = normalize_phone(v["phone"])
                if fmt != v["phone"]:
                    st.caption(f"Phone will be saved as **{fmt}**")
            except ValueError:
                st.caption("⚠️ Phone needs 10 digits, like 505-555-0123")

    with st.container(border=True):
        section("1", "Automatic eligibility for TEFAP")
        v["tefap_auto_eligible"] = st.checkbox(
            "My household receives **SNAP (Food Stamps), FDPIR, WIC, or CSFP (Senior Food Box Program)**",
            key=k(ns, "tefap_auto_eligible"))
        if v["tefap_auto_eligible"]:
            st.success("Automatically eligible — Section 2 is skipped. Go to Section 3 to sign.")

    if not v["tefap_auto_eligible"]:
        with st.container(border=True):
            section("2", f"Gross income limits — NM TEFAP/USDA Foods (Federal {TEFAP_LIMITS_YEAR})")
            st.caption("Select your household size, then the column (annual, monthly or weekly) that "
                       "matches how you think about your income.")
            size_key = k(ns, "tefap_household_size")
            if hh and ss.get(size_key) is None and not ss.get(f"{size_key}.touched"):
                ss[size_key] = min(hh, 20)
            c1, c2 = st.columns([1, 2.2])
            v["tefap_household_size"] = c1.selectbox(
                "Household size", list(range(1, 21)), key=size_key, index=None,
                on_change=lambda: ss.__setitem__(f"{size_key}.touched", True))
            v["tefap_income_period"] = c2.segmented_control(
                "Income period", list(INCOME_PERIODS), key=k(ns, "tefap_income_period"),
                format_func=str.title)
            st.markdown(tefap_table_html(v["tefap_household_size"], v["tefap_income_period"]),
                        unsafe_allow_html=True)
            limit = (tefap_limit(v["tefap_household_size"], v["tefap_income_period"])
                     if v["tefap_household_size"] and v["tefap_income_period"] else None)
            st.write("")
            q = "Is your income the same or lower than the number you selected?"
            if limit:
                q = (f"Is your household's gross {v['tefap_income_period']} income the same or lower than "
                     f"**${limit:,}**?")
            v["tefap_income_at_or_below"] = st.radio(q, YES_NO, format_func=_yn,
                                                     key=k(ns, "tefap_income_at_or_below"),
                                                     index=None, horizontal=True)
    return v


def render_signature(ns: str) -> bytes | None:
    """Section 3. Returns new signature bytes, or None to keep whatever exists."""
    ss = st.session_state
    existing = ss.get(k(ns, "existing_signature"))
    with st.container(border=True):
        section("3", "Please sign and date")
        st.markdown(
            "I self-attest that the total gross income for my household is at or less than the income I "
            "selected, or that my household is automatically eligible based on the programs I checked "
            "above. I self-attest that I reside within the NM County and ZIP code provided above.")
        new_sig: bytes | None = None
        c1, c2 = st.columns([3, 1.3])
        with c1:
            t_cam, t_up = st.tabs(["📷 Photograph signature", "⬆️ Upload image"])
            with t_cam:
                st.caption("Client signs a slip of paper; hold it up to the tablet camera.")
                if st.toggle("Open camera", key=k(ns, "cam_on")):
                    shot = st.camera_input("Signature photo", key=k(ns, "sig_cam"),
                                           label_visibility="collapsed")
                    if shot:
                        new_sig = shot.getvalue()
            with t_up:
                up = st.file_uploader("Signature image", type=["png", "jpg", "jpeg", "heic", "webp"],
                                      key=k(ns, "sig_upload"), label_visibility="collapsed")
                if up:
                    new_sig = up.getvalue()
        with c2:
            st.date_input("Date signed", key=k(ns, "signature_date"), value=None, format="MM/DD/YYYY")
            shown = new_sig or existing
            if shown:
                st.image(shown, caption="New signature" if new_sig else "Signature on file",
                         width="stretch")
            else:
                st.caption("No signature yet.")
    return new_sig


def render_staff_notes(ns: str) -> str | None:
    return st.text_area("Staff notes (not shown to client)", key=k(ns, "notes"), height=80)


# ------------------------------------------------------------- validation --
def build(ns: str, p1: dict, p2: dict, notes: str | None = None) -> tuple[ClientIn | None, list[str]]:
    raw = {**p1, **p2, "signature_date": st.session_state.get(k(ns, "signature_date")), "notes": notes}
    missing = [LABELS[f] for f in REQUIRED if raw.get(f) in (None, "")]
    try:
        data = ClientIn.model_validate(raw)
    except ValidationError as e:
        errs = []
        for err in e.errors():
            f = str(err["loc"][0]) if err["loc"] else "record"
            if f in REQUIRED and raw.get(f) in (None, ""):
                continue  # reported once as "missing" below
            msg = err["msg"].removeprefix("Value error, ")
            errs.append(f"**{LABELS.get(f, f)}**: {msg}")
        return None, ([f"Required: {', '.join(missing)}"] if missing else []) + errs
    return (None, [f"Required: {', '.join(missing)}"]) if missing else (data, [])


def form_dirty(ns: str) -> bool:
    return any(isinstance(x, str) and x.startswith(f"{ns}.{_nonce(ns)}.") for x in st.session_state)


def today() -> date:
    return now_local().date()
