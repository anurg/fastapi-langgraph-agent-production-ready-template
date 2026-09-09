"""Sidebar: session list, session management, account and API status."""

import streamlit as st

from frontend.api_client import APIError
from frontend.state import (
    add_session,
    get_account,
    get_active_session,
    get_api,
    get_sessions,
    refresh_sessions,
    set_active_session,
    set_messages,
    sign_out,
)

_STATUS_ICONS = {"healthy": "🟢", "degraded": "🟡"}


def _render_new_chat_button() -> None:
    """Render the button that creates and activates a new chat session."""
    account = get_account()
    if account is None:
        return

    if not st.button("✚ New chat", use_container_width=True, type="primary"):
        return

    try:
        session = get_api().create_session(account.token.access_token)
    except APIError as exc:
        st.error(exc.message)
        return

    add_session(session)
    set_active_session(session.session_id)
    st.rerun()


def _render_session_list() -> None:
    """Render one selectable button per chat session."""
    sessions = get_sessions()
    if not sessions:
        st.caption("No chats yet. Start one above.")
        return

    active = get_active_session()
    active_id = active.session_id if active else None

    for session in sessions:
        is_active = session.session_id == active_id
        if st.button(
            session.display_name,
            key=f"select_{session.session_id}",
            use_container_width=True,
            type="primary" if is_active else "secondary",
            disabled=is_active,
        ):
            set_active_session(session.session_id)
            st.rerun()


def _render_rename(session_token: str, session_id: str, current_name: str) -> None:
    """Render the rename control for the active session.

    Args:
        session_token: Token scoped to the session.
        session_id: The session's identifier.
        current_name: The session's current name.
    """
    with st.form(f"rename_{session_id}"):
        new_name = st.text_input("Rename chat", value=current_name, max_chars=100)
        if not st.form_submit_button("Save name", use_container_width=True):
            return

        cleaned = new_name.strip()
        if not cleaned:
            st.error("The name cannot be empty.")
            return

        try:
            get_api().rename_session(session_token, session_id, cleaned)
        except APIError as exc:
            st.error(exc.message)
            return

    refresh_sessions()
    st.rerun()


def _render_danger_zone(session_token: str, session_id: str) -> None:
    """Render history-clearing and session-deletion controls.

    Args:
        session_token: Token scoped to the session.
        session_id: The session's identifier.
    """
    if st.button("Clear history", key=f"clear_{session_id}", use_container_width=True):
        try:
            get_api().clear_messages(session_token)
        except APIError as exc:
            st.error(exc.message)
        else:
            set_messages([])
            st.toast("Chat history cleared.")
            st.rerun()

    with st.popover("Delete chat", use_container_width=True):
        st.write("Delete this chat and its history? This cannot be undone.")
        if st.button("Yes, delete it", key=f"confirm_delete_{session_id}", type="primary"):
            try:
                get_api().delete_session(session_token, session_id)
            except APIError as exc:
                st.error(exc.message)
                return

            st.session_state["active_session_id"] = None
            set_messages([])
            refresh_sessions()
            st.rerun()


def _render_session_settings() -> None:
    """Render the settings expander for the active session."""
    session = get_active_session()
    if session is None:
        return

    with st.expander("Chat settings"):
        _render_rename(session.token.access_token, session.session_id, session.name)
        st.divider()
        _render_danger_zone(session.token.access_token, session.session_id)


def _render_footer() -> None:
    """Render the account row and the API health indicator."""
    account = get_account()
    if account is None:
        return

    st.divider()
    st.caption(f"Signed in as **{account.username or account.email}**")

    try:
        health = get_api().health()
    except APIError:
        st.caption("🔴 API unreachable")
    else:
        icon = _STATUS_ICONS.get(health.status, "🔴")
        st.caption(f"{icon} API {health.status} · v{health.version} · {health.environment}")

    if st.button("Sign out", use_container_width=True):
        sign_out()
        st.rerun()


def render() -> None:
    """Render the whole sidebar."""
    with st.sidebar:
        st.subheader("🤖 Agent Console")
        _render_new_chat_button()
        st.divider()
        _render_session_list()
        _render_session_settings()
        _render_footer()
