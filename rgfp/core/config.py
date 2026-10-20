"""App-wide settings. Override any of these with environment variables."""
from __future__ import annotations

import os
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
DATA_DIR.mkdir(exist_ok=True)

# True when running on Render (Render sets RENDER=true on every service).
ON_RENDER = os.environ.get("RENDER", "").lower() == "true"


def _db_url() -> str:
    """RGFP_DB_URL wins; else Render's DATABASE_URL (Postgres); else local SQLite."""
    url = os.environ.get("RGFP_DB_URL") or os.environ.get("DATABASE_URL")
    if not url:
        return f"sqlite:///{DATA_DIR / 'rgfp.db'}"
    # Render/Heroku hand out postgres:// or postgresql:// — tell SQLAlchemy to use psycopg 3.
    for prefix in ("postgres://", "postgresql://"):
        if url.startswith(prefix):
            return "postgresql+psycopg://" + url[len(prefix):]
    return url


DB_URL = _db_url()

# Albuquerque. "America/Denver" is MST in winter and MDT in summer, which is
# what a wall clock at the food bank shows. Set RGFP_TZ=America/Phoenix (or
# "Etc/GMT+7") if you truly want fixed MST year-round.
TZ = ZoneInfo(os.environ.get("RGFP_TZ", "America/Denver"))

ORG_NAME = "Rio Grande Food Project"
MEMBER_PREFIX = os.environ.get("RGFP_MEMBER_PREFIX", "RGFP")
FORM_VERSION = "Updated 06/23/2026"

# Visits allowed per calendar month (in TZ). The counter refills on the 1st.
MONTHLY_VISITS = int(os.environ.get("RGFP_MONTHLY_VISITS", "3"))

# ---- Access control -------------------------------------------------------
# Staff password: required for Returning Client / New Client (staff) / Admin.
# Admin password: an extra lock on the Admin page.
# Kiosk token: the tablet opens  https://<app>/?kiosk=<token>  (no staff login,
#   New Client form only). Without a token, ?kiosk=1 works — local use only.
# On Render, the app refuses to run until the staff password is set.
STAFF_PASSWORD = os.environ.get("RGFP_STAFF_PASSWORD")
ADMIN_PASSWORD = os.environ.get("RGFP_ADMIN_PASSWORD")
KIOSK_TOKEN = os.environ.get("RGFP_KIOSK_TOKEN")

LOGO_PATH = ROOT / "assets" / "logo.png"  # drop your logo here; optional
