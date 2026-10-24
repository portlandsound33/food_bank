import os
import sys
import tempfile
from pathlib import Path

# Each test session gets its own throwaway SQLite database, unless DATABASE_URL
# points at a (throwaway!) Postgres:  DATABASE_URL=postgresql://... pytest
if not os.environ.get("DATABASE_URL"):
    os.environ["RGFP_DB_URL"] = f"sqlite:///{tempfile.mkdtemp()}/test.db"
os.environ.setdefault("RGFP_DISABLE_SCHEDULER", "1")  # no background backups in tests
os.environ.setdefault("RGFP_SECRET_KEY", "test-secret")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
