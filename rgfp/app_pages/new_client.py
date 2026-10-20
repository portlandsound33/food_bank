"""New Client: the two-page registration form. Also the tablet/kiosk page."""
from __future__ import annotations

import streamlit as st

from core import repo
from ui import client_form as cf
from ui.member import member_panel
from ui.theme import header

NS = "nc"
ss = st.session_state
kiosk = ss.get("kiosk", False)
cf.ensure_initialized(NS)

header("New client registration" + (" · please fill out both pages" if kiosk else ""))


def _start_next() -> None:
    ss.pop("nc_saved_id", None)
    ss.pop("nc_dup_ok", None)
    cf.clear_form(NS)


# ---------------------------------------------------------- after a save --
if ss.get("nc_saved_id"):
    c = repo.get_client(ss["nc_saved_id"])
    if kiosk:
        st.balloons()
        st.markdown(f"## Thank you, {c.first_name}! 🎉")
        st.markdown(f"Your registration is saved. Your member number is **{c.member_code}**.\n\n"
                    "**Please hand the tablet back to a volunteer** — they'll print your member card.")
        st.button("Start a new form", type="primary", on_click=_start_next)
        st.stop()
    st.success(f"Saved **{c.full_name}** as **{c.member_code}**. Send the card to the printer, then start "
               "the next client.")
    a, b = st.columns([1, 3])
    with a:
        member_panel(c, "nc_saved")
    with b:
        st.button("➕ Register next client", type="primary", on_click=_start_next)
    st.stop()


# ------------------------------------------------------------------ form --
if kiosk:
    main, side = st.container(), None
else:
    main, side = st.columns([3.2, 1], gap="large")

if side is not None:
    with side:
        save = st.button("💾 Save New Client", type="primary", width="stretch")
        st.button("🧹 Clear form", on_click=_start_next, width="stretch")
        paper_ok = st.checkbox("Client signed a paper copy", key="nc_paper",
                               help="Allows saving without a signature image.")
        msgs = st.container()

with main:
    p1_tab, p2_tab = st.tabs(["**Page 1 ·** Registration", "**Page 2 ·** TEFAP eligibility & signature"])
    with p1_tab:
        p1 = cf.render_page1(NS)
        st.info("Next: open **Page 2** (tab above) for TEFAP eligibility and signature.", icon="➡️")
    with p2_tab:
        p2 = cf.render_page2(NS, p1)
        new_sig = cf.render_signature(NS)
    notes = None
    if not kiosk:
        with p2_tab:
            notes = cf.render_staff_notes(NS)

if kiosk:
    st.divider()
    save = st.button("✅ Submit my registration", type="primary", width="stretch")
    paper_ok = False
    msgs = st.container()

# ------------------------------------------------------------------ save --
if save:
    data, errors = cf.build(NS, p1, p2, notes)
    if not new_sig and not paper_ok:
        errors.append("**Signature**: please add a signature photo in Section 3 (Page 2).")
    with msgs:
        if errors:
            st.error("Please fix the following before saving:\n\n" + "\n".join(f"- {e}" for e in errors))
        else:
            dups = repo.possible_duplicates(data)
            if not kiosk and not dups.empty and not ss.get("nc_dup_ok"):
                st.warning("This may already be a member. Check with the client, or press save again "
                           "to create a new record anyway.")
                st.dataframe(dups[["member", "first_name", "last_name", "age", "phone"]], hide_index=True)
                ss["nc_dup_ok"] = True
            else:
                for w in data.warnings():
                    st.toast(w, icon="⚠️")
                row = repo.create_client(data, new_sig, source="kiosk" if kiosk else "intake")
                ss["nc_saved_id"] = row.client_id
                st.rerun()
elif side is not None:
    with msgs:
        st.caption("Fields marked * are required. Page 2 holds TEFAP + signature.")
