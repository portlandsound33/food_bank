"""Rio Grande Food Project — intake app.

Run:  streamlit run app.py
Tablet/kiosk (client fills out the form themselves):  http://<host>:8501/?kiosk=<token>
(see core/config.py for RGFP_STAFF_PASSWORD / RGFP_KIOSK_TOKEN; plain ?kiosk=1 works locally)
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).parent))

from core import repo  # noqa: E402
from core.config import KIOSK_TOKEN  # noqa: E402
from ui.auth import require_staff, resolve_kiosk, staff_signed_in  # noqa: E402
from ui.theme import inject_css  # noqa: E402

st.set_page_config(page_title="RGFP Intake", page_icon="🥫", layout="wide",
                   initial_sidebar_state="auto")
inject_css()

ss = st.session_state
kiosk = resolve_kiosk()

new_client = st.Page("app_pages/new_client.py", title="New Client", icon="📝", default=True)

if kiosk:
    # Tablet mode: one page, no sidebar, no way into staff screens.
    st.markdown("<style>[data-testid='stSidebar'],[data-testid='stSidebarCollapsedControl']"
                "{display:none}</style>", unsafe_allow_html=True)
    st.navigation([new_client], position="hidden").run()
    st.stop()

pages = {
    "Intake": [
        st.Page("app_pages/returning_client.py", title="Returning Client", icon="🔁"),
        new_client,
    ],
    "Admin": [st.Page("app_pages/admin.py", title="Admin", icon="🛠️")],
}
# Register the pages before the sign-in check, so a link to e.g. /returning_client still
# lands there after signing in. The menu stays hidden until then.
page = st.navigation(pages, position="sidebar" if staff_signed_in() else "hidden")
require_staff()

with st.sidebar:
    try:
        s = repo.stats()
        st.caption(f"**{s['clients']:,}** clients on file")
    except Exception as e:  # noqa: BLE001
        st.error(f"Database unavailable: {e}")
    st.caption("Tablet link: add " + ("`?kiosk=<your RGFP_KIOSK_TOKEN>`" if KIOSK_TOKEN
                                      else "`?kiosk=1`") + " to this site's address.")
    if ss.get("staff_ok") and st.button("Sign out", width="stretch"):
        ss.clear()
        st.rerun()
page.run()
