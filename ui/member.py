"""Member badge: QR code, member number, printable card."""
from __future__ import annotations

import streamlit as st

from core.config import TZ
from core.db import Client
from core.qr import make_member_card


@st.cache_data(show_spinner=False, max_entries=64)
def _card(full_name: str, code: str, qr_png: bytes, since: str) -> bytes:
    return make_member_card(full_name, code, qr_png, since)


def member_panel(c: Client, key: str) -> None:
    st.markdown(f'<div class="rg-member"><div class="rg-muted">Member #</div>'
                f'<div class="code">{c.member_code}</div></div>', unsafe_allow_html=True)
    if c.qr_png:
        st.image(c.qr_png, width=170)
    since = c.created_at.astimezone(TZ).strftime("%b %Y") if c.created_at else ""
    card = _card(c.full_name, c.member_code, c.qr_png or b"", since)
    st.download_button("🖨️ Card for printer (PNG)", card, file_name=f"{c.member_code}_card.png",
                       mime="image/png", key=f"{key}.card", width="stretch")
    with st.popover("Preview card", width="stretch"):
        st.image(card, width="stretch")
