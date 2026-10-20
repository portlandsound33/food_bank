"""Shared look & feel: CSS, header bar with live food-bank clock."""
from __future__ import annotations

import base64
from datetime import datetime

import streamlit as st

from core.config import LOGO_PATH, ORG_NAME, TZ

CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible:wght@400;700&display=swap');
:root{
  --brick:#9E3424; --brick-soft:#F6E3DE; --teal:#1F7F81; --teal-soft:#DDF0EF;
  --sand:#FBF7F2; --ink:#2B2622; --muted:#7A6F66; --line:#E7DED4;
}
html, body, p, label, input, textarea, li, td, th, h1, h2, h3, h4, h5, .stMarkdown {
  font-family:'Atkinson Hyperlegible', 'Source Sans Pro', system-ui, sans-serif !important;
}
[data-testid="stIconMaterial"], .material-symbols-rounded{font-family:'Material Symbols Rounded' !important}
.block-container{padding-top:4rem; max-width:1400px;}
/* header */
.rg-header{display:flex; align-items:center; gap:1rem; padding:.6rem 1rem; border-radius:14px;
  background:linear-gradient(100deg,var(--brick) 0%, #B5482F 70%, var(--teal) 140%); color:#fff;
  box-shadow:0 2px 10px rgba(80,30,20,.15); margin-bottom:.4rem}
.rg-header img{height:46px; background:#fff; border-radius:8px; padding:3px}
.rg-mark{width:46px;height:46px;border-radius:10px;background:#fff;color:var(--brick);display:flex;
  align-items:center;justify-content:center;font-weight:700;font-size:1.05rem;letter-spacing:.5px}
.rg-title{font-size:1.45rem; font-weight:700; line-height:1.1}
.rg-sub{font-size:.85rem; opacity:.85}
.rg-clock{font-variant-numeric:tabular-nums; text-align:center; background:#fff; color:var(--ink);
  border-radius:12px; padding:.5rem .8rem; border:1px solid var(--line); line-height:1.25}
.rg-clock b{font-size:1.3rem; display:block} .rg-clock span{color:var(--muted); font-size:.78rem}
/* section headings */
.rg-sec{display:flex; align-items:baseline; gap:.6rem; margin:.2rem 0 .3rem}
.rg-sec .num{background:var(--brick); color:#fff; border-radius:999px; padding:.05rem .6rem;
  font-size:.8rem; font-weight:700}
.rg-sec .t{font-size:1.15rem; font-weight:700; color:var(--ink)}
.rg-consent{background:var(--sand); border:1px solid var(--line); border-left:5px solid var(--teal);
  padding:.7rem .9rem; border-radius:10px; font-size:.95rem; color:var(--ink)}
.rg-callout{background:var(--brick-soft); border-radius:10px; padding:.6rem .9rem; color:#5b1e14;
  font-weight:600; text-align:center}
.rg-callout em{color:var(--brick); font-style:normal; text-decoration:underline}
.rg-muted{color:var(--muted); font-size:.85rem}
/* TEFAP table */
table.tefap{border-collapse:separate; border-spacing:0; width:100%; font-variant-numeric:tabular-nums;
  border:1px solid var(--line); border-radius:10px; overflow:hidden; font-size:.95rem}
table.tefap th{background:var(--ink); color:#fff; padding:.4rem .6rem; text-align:right}
table.tefap th:first-child, table.tefap td:first-child{text-align:center}
table.tefap td{padding:.32rem .6rem; text-align:right; border-top:1px solid var(--line)}
table.tefap tr.sel td{background:var(--teal-soft); font-weight:700}
table.tefap tr td.hit{background:var(--teal) !important; color:#fff !important; border-radius:6px; box-shadow:inset 0 0 0 2px #0f5355}
/* member badge */
.rg-member{border:2px dashed var(--teal); border-radius:14px; padding:.8rem; text-align:center; background:#fff}
.rg-member .code{font-size:1.3rem; white-space:nowrap; font-weight:700; color:var(--brick); letter-spacing:1px}
/* two-step progress */
.rg-steps{display:flex; gap:.5rem; margin:.2rem 0 .8rem}
.rg-step{flex:1; display:flex; align-items:center; gap:.55rem; padding:.55rem .8rem; border-radius:10px;
  border:1px solid var(--line); color:var(--muted); background:#fff; font-weight:600}
.rg-step .n{width:1.7rem; height:1.7rem; border-radius:999px; display:inline-flex; align-items:center;
  justify-content:center; background:var(--line); color:var(--ink); font-size:.9rem}
.rg-step.on{border-color:var(--brick); color:var(--ink); background:var(--brick-soft)}
.rg-step.on .n{background:var(--brick); color:#fff}
.rg-step.done .n{background:var(--teal); color:#fff}
/* visit allowance */
.rg-visits{border-radius:14px; padding:.7rem .8rem; text-align:center; margin:.4rem 0}
.rg-visits .big{font-size:2rem; font-weight:700; line-height:1}
.rg-visits.ok{background:var(--teal-soft); color:#0f5355}
.rg-visits.low{background:#FFF4D6; color:#7a5300}
.rg-visits.out{background:#FDE2DE; color:#8f1d10; border:2px solid #c2412d}
/* bigger touch targets for the tablet */
.stButton>button, .stDownloadButton>button, .stFormSubmitButton>button{min-height:2.9rem; border-radius:10px; font-weight:700}
div[data-testid="stRadio"] label{padding-right:.6rem}
</style>
"""


def inject_css() -> None:
    st.markdown(CSS, unsafe_allow_html=True)


def _logo_html() -> str:
    if LOGO_PATH.exists():
        b64 = base64.b64encode(LOGO_PATH.read_bytes()).decode()
        return f'<img src="data:image/png;base64,{b64}" alt="logo"/>'
    return '<div class="rg-mark">RG</div>'


def now_local() -> datetime:
    return datetime.now(TZ)


def fmt_time(d: datetime, seconds: bool = False) -> str:
    """'6:02:41 PM' — portable (Windows strftime has no %-I)."""
    return f"{d.hour % 12 or 12}:{d:%M}" + (f":{d:%S}" if seconds else "") + f" {d:%p}"


def fmt_date(d: datetime, weekday: bool = False, year: bool = False) -> str:
    """'Mon Oct 19' / 'Oct 19, 2026' — portable (Windows strftime has no %-d)."""
    s = f"{d:%b} {d.day}"
    if weekday:
        s = f"{d:%a} {s}"
    return f"{s}, {d.year}" if year else s


@st.fragment(run_every="1s")
def _clock() -> None:
    n = now_local()
    st.markdown(
        f'<div class="rg-clock"><b>{fmt_time(n, seconds=True)}</b>'
        f'<span>{fmt_date(n, weekday=True)} · {n.tzname()}</span></div>',
        unsafe_allow_html=True,
    )


def header(subtitle: str) -> None:
    left, right = st.columns([5, 1.6], vertical_alignment="center")
    with left:
        st.markdown(
            f'<div class="rg-header">{_logo_html()}<div><div class="rg-title">{ORG_NAME} Intake</div>'
            f'<div class="rg-sub">{subtitle}</div></div></div>',
            unsafe_allow_html=True,
        )
    with right:
        _clock()


def section(num: str, title: str) -> None:
    st.markdown(f'<div class="rg-sec"><span class="num">{num}</span><span class="t">{title}</span></div>',
                unsafe_allow_html=True)
