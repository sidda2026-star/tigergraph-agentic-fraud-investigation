"""Entry point for Streamlit dashboard."""

import sys
from pathlib import Path

# Redirect to ui/dashboard.py
dashboard_path = Path(__file__).resolve().parent / "ui" / "dashboard.py"
with open(dashboard_path, "r", encoding="utf-8") as f:
    code = f.read()
exec(compile(code, str(dashboard_path), "exec"))