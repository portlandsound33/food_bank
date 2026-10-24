"""All Clients: browse, search and filter every record; click one to open it."""
from __future__ import annotations

from datetime import timedelta

import streamlit as st

from core import repo
from core.config import MONTHLY_VISITS, TZ
from core.reference import NM_COUNTIES
from ui.theme import header, now_local

ss = st.session_state
header("All clients — browse and search every record")

df = repo.all_clients_df()

c1, c2, c3, c4 = st.columns([3, 1.6, 1.6, 1.4], vertical_alignment="bottom")
text = c1.text_input("Search", key="ac_text", placeholder="Name, member #, phone, SIMC #, ZIP or county…",
                     help="Every word must match. Results update as you type (press Enter).")
visit_opts = ["All", "Has visits left", "No visits left", "Flagged this month", "Never checked in"]
vfilter = c2.selectbox("Visits this month", visit_opts, key="ac_visits")
reg_opts = ["Any time", "Today", "Last 7 days", "This month", "Last 12 months"]
rfilter = c3.selectbox("Registered", reg_opts, key="ac_reg")
counties = sorted(set(df["county"].dropna()) | set(NM_COUNTIES)) if not df.empty else NM_COUNTIES
cfilter = c4.multiselect("County", counties, key="ac_county", placeholder="Any")

view = repo.filter_clients(df, text)
if vfilter == "Has visits left":
    view = view[view["visits_left"] > 0]
elif vfilter == "No visits left":
    view = view[view["visits_left"] <= 0]
elif vfilter == "Flagged this month":
    view = view[view["flagged_month"] > 0]
elif vfilter == "Never checked in":
    view = view[view["last_checkin"].isna()]
if rfilter != "Any time" and not view.empty:
    now = now_local()
    start = {
        "Today": now.replace(hour=0, minute=0, second=0, microsecond=0),
        "Last 7 days": now - timedelta(days=7),
        "This month": now.replace(day=1, hour=0, minute=0, second=0, microsecond=0),
        "Last 12 months": now - timedelta(days=365),
    }[rfilter]
    view = view[view["created_at"] >= start]
if cfilter:
    view = view[view["county"].isin(cfilter)]

left, right = st.columns([4, 1], vertical_alignment="center")
left.caption(f"Showing **{len(view):,}** of **{len(df):,}** clients · click a row to open it · "
             f"click a column header to sort")
if right.button("🔄 Refresh", width="stretch"):
    st.rerun()

if df.empty:
    st.info("No clients yet. Register one on **New Client**, or add test data in **Admin**.")
    st.stop()

table = view[["member", "name", "age", "phone", "household", "county", "zip", "simc_number", "visits_left",
              "flagged_month", "last_checkin", "created_at"]].copy()
for col in ("phone", "county", "zip", "simc_number"):
    table[col] = table[col].fillna("")
table["last_checkin"] = table["last_checkin"].dt.tz_convert(TZ).dt.tz_localize(None)
table["created_at"] = table["created_at"].dt.tz_convert(TZ).dt.tz_localize(None)
event = st.dataframe(
    table, hide_index=True, on_select="rerun", selection_mode="single-row", key="ac_table", height=600,
    column_config={
        "member": st.column_config.TextColumn("Member #", width=110),
        "name": st.column_config.TextColumn("Name", width="medium"),
        "age": st.column_config.NumberColumn("Age", width="small"),
        "phone": "Phone",
        "household": st.column_config.NumberColumn("HH size", width="small"),
        "county": "County", "zip": "ZIP", "simc_number": "SIMC #",
        "visits_left": st.column_config.ProgressColumn(
            "Visits left", min_value=0, max_value=MONTHLY_VISITS, format="%d", width="small"),
        "flagged_month": st.column_config.NumberColumn("🚩 This month", width="small",
                                                       help="Flagged check-ins this month"),
        "last_checkin": st.column_config.DatetimeColumn("Last check-in", format="MMM D, YYYY h:mm a"),
        "created_at": st.column_config.DatetimeColumn("Registered", format="MMM D, YYYY"),
    },
)
if event.selection.rows:
    cid = int(view.iloc[event.selection.rows[0]]["client_id"])
    ss["rc_open_request"] = cid
    st.switch_page("app_pages/returning_client.py")
