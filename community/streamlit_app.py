"""Streamlit Community Cloud entry point for the password-protected prototype."""
import sys
import runpy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
runpy.run_path(str(Path(__file__).resolve().parents[1] / "simple_streamlit_app.py"))
