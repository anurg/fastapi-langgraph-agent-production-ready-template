"""Tests for the Streamlit console's message model.

The console parsed every API reply into `ChatMessage`, which capped content at 3000
characters. That made a long agent answer unparseable in the UI even once the API
returned it correctly, so the cap had to come off here too.
"""

import pytest
from pydantic import ValidationError

from frontend.models import (
    MAX_MESSAGE_LENGTH,
    ChatMessage,
)


class TestChatMessage:
    def test_accepts_a_reply_longer_than_the_composer_limit(self) -> None:
        long_reply = "An explanation of coding agents. " * 200

        assert len(ChatMessage(role="assistant", content=long_reply).content) > MAX_MESSAGE_LENGTH

    def test_accepts_a_reply_containing_script_tags(self) -> None:
        content = "```html\n<script>alert(1)</script>\n```"

        assert ChatMessage(role="assistant", content=content).content == content

    def test_still_rejects_empty_content(self) -> None:
        with pytest.raises(ValidationError):
            ChatMessage(role="assistant", content="")

    def test_parses_a_long_reply_from_an_api_payload(self) -> None:
        """`get_messages` validates raw API dicts through this model."""
        payload = {"role": "assistant", "content": "x" * 10_000}

        assert len(ChatMessage.model_validate(payload).content) == 10_000


class TestComposerLimit:
    def test_input_cap_matches_the_api(self) -> None:
        from app.schemas.chat import MAX_USER_MESSAGE_LENGTH

        assert MAX_MESSAGE_LENGTH == MAX_USER_MESSAGE_LENGTH, (
            "the composer cap and the API's inbound cap must agree, or the UI lets "
            "users type messages the API will reject"
        )
