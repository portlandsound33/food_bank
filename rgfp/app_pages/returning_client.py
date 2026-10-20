"""Returning Client: scan a card (or search), review with the client, update."""
from __future__ import annotations

from datetime import datetime, time

import streamlit as st

from core import repo
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
    return True


def close_client() -> None:
    ss.pop("rc_client_id", None)
    cf.clear_form(NS, defaults=False)


# ---------------------------------------------------------------- lookup --
with st.form("scan", clear_on_submit=True, border=False):
    c1, c2 = st.columns([5, 1], vertical_alignment="bottom")
    scanned = c1.text_input(
        "Scan card, or search by member #, name, phone or SIMC #",
        placeholder="Click here, then scan the QR code  ·  or type e.g. 'garcia 505'",
    )
    go = c2.form_submit_button("🔎 Find", type="primary", width="stretch")

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

main, side = st.columns([3.2, 1], gap="large")
with side:
    member_panel(client, "rc")
    update = st.button("💾 Update Client", type="primary", width="stretch")
    st.button("✖ Close record", on_click=close_client, width="stretch")
    msgs = st.container()
    created = (f"{fmt_date(client.created_at.astimezone(TZ), year=True)} {fmt_time(client.created_at.astimezone(TZ))}"
               if client.created_at else "—")
    updated = (f"{fmt_date(client.updated_at.astimezone(TZ), year=True)} {fmt_time(client.updated_at.astimezone(TZ))}"
               if client.updated_at else "—")
    st.caption(f"Created {created} · via {client.source}\n\nLast updated {updated}"
               + (f"\n\nLegacy ID: {client.legacy_id}" if client.legacy_id else ""))

with main:
    st.markdown(f"### {client.full_name}")
    p1_tab, p2_tab = st.tabs(["**Page 1 ·** Registration", "**Page 2 ·** TEFAP eligibility & signature"])
    with p1_tab:
        p1 = cf.render_page1(NS)
    with p2_tab:
        p2 = cf.render_page2(NS, p1)
        new_sig = cf.render_signature(NS)
        notes = cf.render_staff_notes(NS)

if update:
    data, errors = cf.build(NS, p1, p2, notes)
    with msgs:
        if errors:
            st.error("Please fix:\n\n" + "\n".join(f"- {e}" for e in errors))
        else:
            repo.update_client(client.client_id, data, new_sig)
            for w in data.warnings():
                st.toast(w, icon="⚠️")
            st.toast(f"Updated {data.full_name}", icon="✅")
            open_client(client.client_id)  # reload clean from DB
            st.rerun()
