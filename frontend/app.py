"""Streamlit entry point for the LangGraph agent console.

Run with:
    make ui              # or: uv run streamlit run frontend/app.py

Set `AGENT_API_URL` to point at a non-local API (default http://localhost:8000).
"""

import sys
from pathlib import Path

import streamlit as st

# Allow `streamlit run frontend/app.py` to resolve the `frontend` package.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from frontend.state import (  # noqa: E402
    init_state,
    is_authenticated,
)
from frontend.views import (  # noqa: E402
    auth_view,
    chat_view,
    sidebar,
)


def main() -> None:
    """Configure the page and render the appropriate screen."""
    st.set_page_config(
        page_title="Agent Console",
        page_icon="🤖",
        layout="centered",
        initial_sidebar_state="expanded",
    )

    init_state()

    if not is_authenticated():
        auth_view.render()
        return

    sidebar.render()
    chat_view.render()


main()
