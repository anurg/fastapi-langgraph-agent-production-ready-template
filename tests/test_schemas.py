"""Tests for request/response schema validation boundaries."""

import pytest
from pydantic import ValidationError

from app.schemas import (
    ChatRequest,
    Message,
    UserMessage,
)
from app.schemas.chat import SessionTitle


class TestMessage:
    @pytest.mark.parametrize("role", ["user", "assistant", "system"])
    def test_accepts_the_three_known_roles(self, role: str) -> None:
        assert Message(role=role, content="x").role == role  # pyright: ignore[reportArgumentType]

    def test_rejects_an_unknown_role(self) -> None:
        with pytest.raises(ValidationError):
            Message(role="robot", content="x")  # pyright: ignore[reportArgumentType]

    def test_rejects_empty_content(self) -> None:
        with pytest.raises(ValidationError):
            Message(role="user", content="")

    def test_does_not_cap_content_length(self) -> None:
        """Message carries agent output too — see tests/test_long_response_regression.py."""
        assert len(Message(role="assistant", content="x" * 10_000).content) == 10_000

    def test_does_not_reject_script_tags(self) -> None:
        content = "<script>alert(1)</script>"

        assert Message(role="assistant", content=content).content == content

    def test_ignores_unknown_fields_rather_than_failing(self) -> None:
        message = Message(role="user", content="x", unexpected="ignored")  # pyright: ignore[reportCallIssue]

        assert not hasattr(message, "unexpected")


class TestUserMessage:
    """Inbound validation lives here, not on the shared Message model."""

    def test_accepts_content_at_exactly_the_cap(self) -> None:
        assert len(UserMessage(role="user", content="x" * 3000).content) == 3000

    def test_rejects_content_over_the_length_cap(self) -> None:
        with pytest.raises(ValidationError):
            UserMessage(role="user", content="x" * 3001)

    def test_rejects_script_tags(self) -> None:
        with pytest.raises(ValidationError, match="harmful script tags"):
            UserMessage(role="user", content="<script>alert(1)</script>")

    def test_rejects_script_tags_case_insensitively(self) -> None:
        with pytest.raises(ValidationError, match="harmful script tags"):
            UserMessage(role="user", content="<SCRIPT>alert(1)</SCRIPT>")

    def test_rejects_null_bytes(self) -> None:
        with pytest.raises(ValidationError, match="null bytes"):
            UserMessage(role="user", content="bad\0value")


class TestChatRequest:
    def test_requires_at_least_one_message(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(messages=[])

    def test_accepts_a_single_message(self) -> None:
        assert len(ChatRequest(messages=[UserMessage(role="user", content="hi")]).messages) == 1

    def test_rejects_a_request_whose_nested_message_is_invalid(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(messages=[{"role": "user", "content": ""}])  # pyright: ignore[reportArgumentType]


class TestSessionTitle:
    def test_collapses_internal_whitespace(self) -> None:
        assert SessionTitle(title="a   spaced   title").title == "a spaced title"

    @pytest.mark.parametrize("raw", ['"Quoted"', "Trailing.", "Dashed-", "Question?"])
    def test_strips_surrounding_punctuation(self, raw: str) -> None:
        title = SessionTitle(title=raw).title

        assert not title.endswith((".", "-", "?", '"'))
        assert not title.startswith('"')

    def test_rejects_a_title_that_normalises_to_nothing(self) -> None:
        with pytest.raises(ValidationError, match="empty title after normalization"):
            SessionTitle(title="...")

    def test_rejects_a_title_over_the_length_cap(self) -> None:
        with pytest.raises(ValidationError):
            SessionTitle(title="x" * 61)
