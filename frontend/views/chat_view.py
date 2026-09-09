"""Main chat panel: transcript, composer and streaming reply rendering."""

from typing import (
    Iterator,
    List,
)

import streamlit as st

from frontend.api_client import APIError
from frontend.models import (
    MAX_MESSAGE_LENGTH,
    ChatMessage,
)
from frontend.state import (
    append_message,
    get_active_session,
    get_api,
    get_messages,
    load_messages,
    refresh_sessions,
)

KEY_ERROR = "chat_error"
KEY_STREAMING = "streaming_enabled"

_ROLE_AVATARS = {"user": "🧑", "assistant": "🤖"}


def _render_pending_error() -> None:
    """Show and clear an error recorded by the previous run, if any."""
    error = st.session_state.pop(KEY_ERROR, None)
    if error:
        st.error(error)


def _fail(message: str) -> None:
    """Record an error, resync the transcript with the server, and rerun.

    Args:
        message: The error to show once the app reruns.
    """
    st.session_state[KEY_ERROR] = message
    load_messages()
    st.rerun()


def _render_transcript(messages: List[ChatMessage]) -> None:
    """Render every displayable message in the conversation.

    Args:
        messages: The conversation to render.
    """
    for message in messages:
        if message.role == "system":
            continue
        with st.chat_message(message.role, avatar=_ROLE_AVATARS.get(message.role)):
            st.markdown(message.content)


def _render_empty_state() -> None:
    """Render the placeholder shown when no session is selected."""
    st.title("🤖 Agent Console")
    st.info("Select a chat from the sidebar, or start a new one to begin.")


def _stream_reply(session_token: str, conversation: List[ChatMessage]) -> Iterator[str]:
    """Yield the agent's reply chunks, surfacing errors as visible text.

    `st.write_stream` cannot propagate an exception mid-render, so a failure is
    recorded for the next run and the generator stops.

    Args:
        session_token: Token scoped to the active session.
        conversation: The full conversation to send.

    Yields:
        str: The next chunk of the reply.
    """
    try:
        yield from get_api().stream_chat(session_token, conversation)
    except APIError as exc:
        st.session_state[KEY_ERROR] = exc.message


def _send(session_token: str, prompt: str) -> None:
    """Send one user turn and render the agent's reply.

    Args:
        session_token: Token scoped to the active session.
        prompt: The user's message.
    """
    user_message = ChatMessage(role="user", content=prompt)
    append_message(user_message)

    with st.chat_message("user", avatar=_ROLE_AVATARS["user"]):
        st.markdown(prompt)

    # The agent checkpoints each session under its own thread id, so it already
    # holds the conversation. Only the new turn is sent — replaying the whole
    # transcript would append it to the stored history a second time.
    outgoing = [user_message]

    with st.chat_message("assistant", avatar=_ROLE_AVATARS["assistant"]):
        if st.session_state.get(KEY_STREAMING, True):
            reply = st.write_stream(_stream_reply(session_token, outgoing))
        else:
            try:
                with st.spinner("Thinking…"):
                    returned = get_api().chat(session_token, outgoing)
            except APIError as exc:
                _fail(exc.message)
                return
            reply = returned[-1].content if returned else ""
            st.markdown(reply)

    if KEY_ERROR in st.session_state:
        load_messages()
        st.rerun()

    text = reply if isinstance(reply, str) else "".join(str(part) for part in reply)
    if text:
        append_message(ChatMessage(role="assistant", content=text))

    # The backend names a session in the background after its first message.
    refresh_sessions()
    st.rerun()


def render() -> None:
    """Render the chat panel for the active session."""
    session = get_active_session()
    if session is None:
        _render_empty_state()
        return

    header, toggle = st.columns([4, 1], vertical_alignment="center")
    with header:
        st.subheader(session.display_name)
    with toggle:
        st.toggle("Stream", key=KEY_STREAMING, value=True, help="Render the reply token by token.")

    _render_pending_error()

    messages = get_messages()
    if not messages:
        st.caption("Say hello to start the conversation.")
    _render_transcript(messages)

    prompt = st.chat_input("Message the agent…", max_chars=MAX_MESSAGE_LENGTH)
    if not prompt:
        return

    cleaned = prompt.strip()
    if not cleaned:
        return

    try:
        _send(session.token.access_token, cleaned)
    except APIError as exc:
        if exc.is_auth_error:
            # Session tokens expire; listing sessions mints fresh ones.
            refresh_sessions()
            _fail("Your session token expired and was renewed. Send the message again.")
        _fail(exc.message)
