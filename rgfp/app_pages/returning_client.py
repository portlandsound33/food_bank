"""Returning Client: scan a card (or search), review with the client, update."""
from __future__ import annotations

from datetime import datetime, time

import streamlit as st

from core import repo, visits
from core.config import TZ
from core.qr import parse_member_code
from ui import client_form as cf
from ui.member import member_panel
from ui.theme import fmt_date, fmt_time, header, now_local

NS = "rc"
ss = st.session_state
header("Returning client — scan the member card")


def open_client(client_id: int) -> bool:
    row = repo.get_client(client_id)
    if row is None:
        return False
    cf.load_form(NS, repo.to_client_in(row), row.signature_png)
    ss["rc_client_id"] = client_id
    ss.pop("rc_results", None)
    ss.pop("rc_checkin_result", None)
    ss.pop("rc_confirm_again", None)
    return True


def close_client() -> None:
    ss.pop("rc_client_id", None)
    ss.pop("rc_checkin_result", None)
    cf.clear_form(NS, defaults=False)


# Opened from the All Clients page
if (req := ss.pop("rc_open_request", None)) is not None:
    open_client(req)

# ---------------------------------------------------------------- lookup --
f_col, b_col = st.columns([6, 1.1], vertical_alignment="bottom")
with f_col, st.form("scan", clear_on_submit=True, border=False):
    c1, c2 = st.columns([5, 1.2], vertical_alignment="bottom")
    scanned = c1.text_input(
        "Scan card, or search by member #, name, phone or SIMC #",
        placeholder="Click here, then scan the QR code  ·  or type e.g. 'garcia 505'",
    )
    go = c2.form_submit_button("🔎 Find", type="primary", width="stretch")
if b_col.button("📋 Browse all", width="stretch", help="See and search every client record"):
    st.switch_page("app_pages/all_clients.py")

if go and scanned.strip():
    cid = parse_member_code(scanned)
    if cid is not None and open_client(cid):
        st.rerun()
    res = repo.search(scanned, limit=50)
    if res.empty:
        st.warning(f"No member found for “{scanned}”.")
    elif len(res) == 1:
        open_client(int(res.iloc[0]["client_id"]))
        st.rerun()
    else:
        ss["rc_results"] = res


def _pick_table(df, key: str, title: str) -> None:  # noqa: ANN001
    st.markdown(f"**{title}** — click a row to open")
    view = df.assign(name=df["first_name"] + " " + df["last_name"])[
        ["member", "name", "age", "phone", "household", "simc_number"]]
    ev = st.dataframe(view, hide_index=True, on_select="rerun", selection_mode="single-row", key=key,
                      column_config={"household": st.column_config.NumberColumn("HH size")})
    if ev.selection.rows:
        open_client(int(df.iloc[ev.selection.rows[0]]["client_id"]))
        st.rerun()


if "rc_client_id" not in ss:
    if ss.get("rc_results") is not None:
        _pick_table(ss["rc_results"], "rc_pick", f"{len(ss['rc_results'])} matches")
    midnight = datetime.combine(now_local().date(), time.min, tzinfo=TZ)
    todays = repo.recent(midnight, limit=30)
    st.divider()
    if todays.empty:
        st.caption("No new registrations yet today. Tablet sign-ups will appear here.")
    else:
        _pick_table(todays, "rc_today", f"Registered today ({len(todays)})")
    st.stop()

# ---------------------------------------------------------- loaded record --
client = repo.get_client(ss["rc_client_id"])
if client is None:
    close_client()
    st.rerun()

def _stamp(dt) -> str:  # noqa: ANN001
    d = dt.astimezone(TZ)
    return f"{fmt_date(d, year=True)} {fmt_time(d)}"


def visits_panel(client_id: int) -> None:
    vs = visits.status(client_id)
    cls = "out" if vs.exhausted else ("low" if vs.remaining == 1 else "ok")
    sub = ("No visits left — next check-in will be flagged" if vs.exhausted
           else f"of {vs.allowance} visits left this month")
    st.markdown(f'<div class="rg-visits {cls}"><div class="big">{vs.remaining}</div>'
                f'<div>{sub}</div></div>', unsafe_allow_html=True)

    today = now_local().date()
    already_today = vs.last_checkin is not None and vs.last_checkin.astimezone(TZ).date() == today
    if already_today:
        st.caption(f"⚠️ Already checked in today at {fmt_time(vs.last_checkin.astimezone(TZ))}.")
    label = "✔ Check in again" if already_today else "✔ Check in"
    if st.button(label, type="primary", width="stretch", key="rc_checkin"):
        if already_today and not ss.get("rc_confirm_again"):
            ss["rc_confirm_again"] = True
            st.warning("This client already checked in today. Press **Check in again** to record "
                       "another visit.")
        else:
            ss.pop("rc_confirm_again", None)
            ss["rc_checkin_result"] = visits.check_in(client_id)
            st.rerun()
    if vs.flagged_this_month:
        st.caption(f"🚩 {vs.flagged_this_month} flagged check-in(s) this month.")


main, side = st.columns([3.2, 1], gap="large")
with side:
    visits_panel(client.client_id)
    member_panel(client, "rc")
    update = st.button("💾 Update Client", width="stretch")
    st.button("✖ Close record", on_click=close_client, width="stretch")
    msgs = st.container()
    created = _stamp(client.created_at) if client.created_at else "—"
    updated = _stamp(client.updated_at) if client.updated_at else "—"
    st.caption(f"Created {created} · via {client.source}\n\nLast updated {updated}"
               + (f"\n\nLegacy ID: {client.legacy_id}" if client.legacy_id else ""))

with main:
    st.markdown(f"### {client.full_name}")
    res = ss.get("rc_checkin_result")
    if res is not None:
        ordinal = {1: "1st", 2: "2nd", 3: "3rd"}.get(res.visit_number, f"{res.visit_number}th")
        if res.flagged:
            st.error(f"🚩 **FLAGGED — {ordinal} visit this month.** {client.first_name} has no visits left "
                     f"({res.allowance} per month). The check-in was recorded and flagged for review.")
        else:
            st.success(f"✔ Checked in — {ordinal} visit this month. "
                       f"{res.remaining} of {res.allowance} visits left.")
    with st.expander("Visit history"):
        hist = visits.history(client_id=client.client_id, limit=24)
        if hist.empty:
            st.caption("No check-ins yet.")
        else:
            st.dataframe(
                hist.assign(when=hist["checked_in_at"].map(_stamp))[
                    ["when", "visit_number", "remaining_after", "flagged"]],
                hide_index=True,
                column_config={"visit_number": "Visit # (month)", "remaining_after": "Left after",
                               "flagged": st.column_config.CheckboxColumn("Flagged")})
    form = cf.render_two_step(NS, submit_label="💾 Update Client", staff_notes=True)

if update or form.submitted:
    out = msgs if update else form.messages
    data, errors = cf.build(NS, form.p1, form.p2, form.notes)
    with out:
        if errors:
            st.error("Please fix:\n\n" + "\n".join(f"- {e}" for e in errors))
        else:
            repo.update_client(client.client_id, data, form.new_sig)
            for w in data.warnings():
                st.toast(w, icon="⚠️")
            st.toast(f"Updated {data.full_name}", icon="✅")
            open_client(client.client_id)  # reload clean from DB
            st.rerun()
