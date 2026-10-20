"""Who is using this browser session: the client tablet (kiosk) or staff."""
from __future__ import annotations

import hmac

import streamlit as st

from core.config import KIOSK_TOKEN, ON_RENDER, STAFF_PASSWORD


def _same(a: str, b: str) -> bool:
    return hmac.compare_digest(a.encode(), b.encode())


def resolve_kiosk() -> bool:
    """True if this browser session is the client tablet (valid ?kiosk= link). Stops on a bad link."""
    ss = st.session_state

    if "kiosk" not in ss:
        q = st.query_params.get("kiosk")
        if q is None:
            ss["kiosk"] = False
        else:
            if KIOSK_TOKEN:
                # Render's generated tokens are base64; a "+" in a URL arrives as a space.
                ok = _same(q, KIOSK_TOKEN) or _same(q.replace(" ", "+"), KIOSK_TOKEN)
            else:  # no token configured: plain ?kiosk=1, but never on a public deployment
                ok = (not ON_RENDER) and q.lower() in {"1", "true", "yes"}
            if not ok:
                st.error("This tablet link isn't valid. Ask a staff member for the current link.")
                st.stop()
            ss["kiosk"] = True
    return ss["kiosk"]


def staff_signed_in() -> bool:
    return bool(st.session_state.get("staff_ok")) or not STAFF_PASSWORD


def require_staff() -> None:
    """Shows the staff sign-in and stops the script until the password is entered."""
    ss = st.session_state

    if not STAFF_PASSWORD:
        if ON_RENDER:
            st.error("Staff login isn't configured. In Render, set the **RGFP_STAFF_PASSWORD** "
                     "environment variable, then redeploy.")
            st.stop()
        return  # local development

    if ss.get("staff_ok"):
        return

    _, mid, _ = st.columns([1, 1.2, 1])
    with mid:
        st.markdown("### Rio Grande Food Project — staff sign-in")
        with st.form("staff_login"):
            pw = st.text_input("Staff password", type="password")
            if st.form_submit_button("Sign in", type="primary", width="stretch"):
                if _same(pw, STAFF_PASSWORD):
                    ss["staff_ok"] = True
                    st.rerun()
                st.error("Wrong password.")
    st.stop()
