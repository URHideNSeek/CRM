"""Streamlit Community Cloud entry point for the password-protected prototype."""
import runpy
from pathlib import Path

runpy.run_path(str(Path(__file__).resolve().parents[1] / "simple_streamlit_app.py"))
