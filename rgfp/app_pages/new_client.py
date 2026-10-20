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

side_save, paper_ok, side_msgs = False, False, None
if side is not None:
    with side:
        side_save = st.button("💾 Save New Client", type="primary", width="stretch")
        st.button("🧹 Clear form", on_click=_start_next, width="stretch")
        paper_ok = st.checkbox("Client signed a paper copy", key="nc_paper",
                               help="Allows saving without a signature image.")
        side_msgs = st.container()
        st.caption("Fields marked * are required. Page 1 is checked before moving to page 2.")

with main:
    form = cf.render_two_step(
        NS, submit_label="✅ Submit my registration" if kiosk else "💾 Save New Client",
        staff_notes=not kiosk)

# ------------------------------------------------------------------ save --
if form.submitted or side_save:
    out = side_msgs if (side_save and side_msgs is not None) else form.messages
    data, errors = cf.build(NS, form.p1, form.p2, form.notes)
    if not form.new_sig and not paper_ok:
        errors.append("**Signature** (page 2): please add a signature photo in Section 3.")
    with out:
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
                row = repo.create_client(data, form.new_sig, source="kiosk" if kiosk else "intake")
                ss["nc_saved_id"] = row.client_id
                st.rerun()
