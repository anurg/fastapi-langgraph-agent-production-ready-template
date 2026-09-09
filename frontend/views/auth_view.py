"""Sign-in and registration screen."""

import re

import streamlit as st

from frontend.api_client import APIError
from frontend.state import (
    get_api,
    refresh_sessions,
    sign_in,
)

PASSWORD_RULES = (
    (r".{8,}", "at least 8 characters"),
    (r"[A-Z]", "an uppercase letter"),
    (r"[a-z]", "a lowercase letter"),
    (r"[0-9]", "a number"),
    (r'[!@#$%^&*(),.?":{}|<>]', "a special character"),
)


def _password_problems(password: str) -> list[str]:
    """Check a password against the backend's strength rules.

    Validating here avoids burning the register endpoint's 10-per-hour budget
    on passwords the API would reject anyway.

    Args:
        password: The candidate password.

    Returns:
        list[str]: Descriptions of every unmet requirement.
    """
    return [label for pattern, label in PASSWORD_RULES if not re.search(pattern, password)]


def _render_sign_in() -> None:
    """Render the sign-in form and authenticate on submit."""
    with st.form("sign_in"):
        email = st.text_input("Email", placeholder="you@example.com")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", use_container_width=True, type="primary")

    if not submitted:
        return

    if not email or not password:
        st.error("Enter both your email and password.")
        return

    with st.spinner("Signing in…"):
        try:
            account = get_api().login(email.strip(), password)
        except APIError as exc:
            st.error(exc.message)
            return

    sign_in(account)
    refresh_sessions()
    st.rerun()


def _render_register() -> None:
    """Render the registration form and create an account on submit."""
    with st.form("register"):
        email = st.text_input("Email", placeholder="you@example.com")
        username = st.text_input("Display name", placeholder="Optional")
        password = st.text_input("Password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        st.caption("Needs 8+ characters with upper and lower case, a number, and a special character.")
        submitted = st.form_submit_button("Create account", use_container_width=True, type="primary")

    if not submitted:
        return

    if not email or not password:
        st.error("Enter both your email and password.")
        return

    if password != confirm:
        st.error("The two passwords do not match.")
        return

    problems = _password_problems(password)
    if problems:
        st.error("Your password still needs " + ", ".join(problems) + ".")
        return

    with st.spinner("Creating your account…"):
        try:
            account = get_api().register(email.strip(), password, username.strip() or None)
        except APIError as exc:
            st.error(exc.message)
            return

    sign_in(account)
    refresh_sessions()
    st.rerun()


def render() -> None:
    """Render the authentication screen."""
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.title("🤖 Agent Console")
        st.caption("Sign in to chat with the LangGraph agent.")
        sign_in_tab, register_tab = st.tabs(["Sign in", "Create account"])
        with sign_in_tab:
            _render_sign_in()
        with register_tab:
            _render_register()
