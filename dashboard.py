"""Entry point for Streamlit dashboard."""

import sys
from pathlib import Path

# Ensure project root is resolved properly
ROOT_DIR = Path(__file__).resolve().parent
if not (ROOT_DIR / "data").exists() and (ROOT_DIR.parent / "data").exists():
    ROOT_DIR = ROOT_DIR.parent

sys.path.insert(0, str(ROOT_DIR))

dashboard_path = ROOT_DIR / "ui" / "dashboard.py"
with open(dashboard_path, "r", encoding="utf-8") as f:
    code = f.read()

exec_globals = {
    "__file__": str(dashboard_path),
    "__name__": "__main__",
    "ROOT_DIR": ROOT_DIR,
}
exec(compile(code, str(dashboard_path), "exec"), exec_globals)