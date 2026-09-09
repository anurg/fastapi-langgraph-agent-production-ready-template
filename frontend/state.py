"""Streamlit session-state helpers.

Centralises every key stored in `st.session_state` so views never reach for raw
string keys, and keeps the account/session/message triple consistent.
"""

from typing import List

import streamlit as st

from frontend.api_client import (
    AgentAPI,
    APIError,
)
from frontend.models import (
    ChatMessage,
    ChatSession,
    UserAccount,
)

KEY_ACCOUNT = "account"
KEY_SESSIONS = "sessions"
KEY_ACTIVE_SESSION_ID = "active_session_id"
KEY_MESSAGES = "messages"
KEY_RENAMING = "renaming_session_id"


@st.cache_resource
def get_api() -> AgentAPI:
    """Return the process-wide API client.

    Cached so the underlying connection pool is reused across reruns.

    Returns:
        AgentAPI: The shared client.
    """
    return AgentAPI()


def init_state() -> None:
    """Populate any session-state keys that are not set yet."""
    defaults: dict[str, object] = {
        KEY_ACCOUNT: None,
        KEY_SESSIONS: [],
        KEY_ACTIVE_SESSION_ID: None,
        KEY_MESSAGES: [],
        KEY_RENAMING: None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


def get_account() -> UserAccount | None:
    """Return the signed-in account, if any.

    Returns:
        UserAccount | None: The current account or None when signed out.
    """
    return st.session_state.get(KEY_ACCOUNT)


def is_authenticated() -> bool:
    """Whether a user is signed in.

    Returns:
        bool: True when an account with a user token is present.
    """
    return get_account() is not None


def sign_in(account: UserAccount) -> None:
    """Record a freshly authenticated account and clear stale chat state.

    Args:
        account: The authenticated account.
    """
    st.session_state[KEY_ACCOUNT] = account
    st.session_state[KEY_SESSIONS] = []
    st.session_state[KEY_ACTIVE_SESSION_ID] = None
    st.session_state[KEY_MESSAGES] = []


def sign_out() -> None:
    """Forget the current account and all derived state."""
    st.session_state[KEY_ACCOUNT] = None
    st.session_state[KEY_SESSIONS] = []
    st.session_state[KEY_ACTIVE_SESSION_ID] = None
    st.session_state[KEY_MESSAGES] = []
    st.session_state[KEY_RENAMING] = None


def get_sessions() -> List[ChatSession]:
    """Return the cached list of the user's chat sessions.

    Returns:
        List[ChatSession]: The sessions, as last fetched.
    """
    return st.session_state.get(KEY_SESSIONS, [])


def refresh_sessions() -> None:
    """Re-fetch the user's sessions, refreshing names and session tokens.

    Silently does nothing when signed out. When the active session is missing
    or unset, falls back to the newest session and loads its history.
    """
    account = get_account()
    if account is None:
        return

    try:
        sessions = get_api().list_sessions(account.token.access_token)
    except APIError as exc:
        st.warning(f"Could not refresh sessions: {exc.message}")
        return

    st.session_state[KEY_SESSIONS] = sessions

    previous_id = st.session_state.get(KEY_ACTIVE_SESSION_ID)
    if previous_id and any(s.session_id == previous_id for s in sessions):
        return

    # The active session is gone (or none was chosen yet, as just after
    # sign-in): fall back to the newest one and pull its history in.
    st.session_state[KEY_ACTIVE_SESSION_ID] = sessions[0].session_id if sessions else None
    st.session_state[KEY_MESSAGES] = []
    load_messages()


def add_session(session: ChatSession) -> None:
    """Insert a newly created session at the top of the cached list.

    Recording it directly avoids re-listing sessions and depending on the new
    row being visible to the very next read.

    Args:
        session: The session that was just created.
    """
    existing = [s for s in get_sessions() if s.session_id != session.session_id]
    st.session_state[KEY_SESSIONS] = [session, *existing]


def get_active_session() -> ChatSession | None:
    """Return the session the chat view is pointed at.

    Returns:
        ChatSession | None: The active session, or None when none is selected.
    """
    active_id = st.session_state.get(KEY_ACTIVE_SESSION_ID)
    if not active_id:
        return None
    return next((s for s in get_sessions() if s.session_id == active_id), None)


def set_active_session(session_id: str) -> None:
    """Point the chat view at a session and load its history.

    Args:
        session_id: The session to activate.
    """
    st.session_state[KEY_ACTIVE_SESSION_ID] = session_id
    st.session_state[KEY_MESSAGES] = []
    load_messages()


def get_messages() -> List[ChatMessage]:
    """Return the messages currently rendered in the chat view.

    Returns:
        List[ChatMessage]: The in-memory conversation.
    """
    return st.session_state.get(KEY_MESSAGES, [])


def set_messages(messages: List[ChatMessage]) -> None:
    """Replace the in-memory conversation.

    Args:
        messages: The messages to display.
    """
    st.session_state[KEY_MESSAGES] = messages


def append_message(message: ChatMessage) -> None:
    """Append one message to the in-memory conversation.

    Args:
        message: The message to add.
    """
    st.session_state[KEY_MESSAGES] = [*get_messages(), message]


def load_messages() -> None:
    """Load the active session's history from the API into session state."""
    session = get_active_session()
    if session is None:
        set_messages([])
        return

    try:
        set_messages(get_api().get_messages(session.token.access_token))
    except APIError as exc:
        st.warning(f"Could not load history: {exc.message}")
        set_messages([])
