"""Tests for system prompt loading.

The template is read once at import and formatted per request, so a placeholder
added to `system.md` without a matching kwarg fails at request time rather than at
startup. These tests pin that contract down.
"""

import pytest

from app.core.config import settings
from app.core.prompts import (
    SESSION_TITLE_PROMPT,
    load_system_prompt,
)


class TestLoadSystemPrompt:
    def test_substitutes_the_agent_name_from_settings(self) -> None:
        prompt = load_system_prompt(long_term_memory="")

        assert f"{settings.PROJECT_NAME} Agent" in prompt

    def test_leaves_no_unsubstituted_placeholders(self) -> None:
        prompt = load_system_prompt(username="ada", long_term_memory="likes tea")

        for placeholder in ("{agent_name}", "{current_date_and_time}", "{user_context}", "{long_term_memory}"):
            assert placeholder not in prompt

    def test_includes_the_user_when_a_username_is_given(self) -> None:
        prompt = load_system_prompt(username="ada", long_term_memory="")

        assert "You are talking to ada." in prompt

    def test_omits_the_user_block_entirely_when_anonymous(self) -> None:
        prompt = load_system_prompt(long_term_memory="")

        assert "You are talking to" not in prompt

    def test_embeds_long_term_memory(self) -> None:
        prompt = load_system_prompt(long_term_memory="the user prefers metric units")

        assert "the user prefers metric units" in prompt

    def test_raises_when_a_required_placeholder_kwarg_is_missing(self) -> None:
        # `long_term_memory` has no default — omitting it is a request-time
        # KeyError, not a startup failure. This is the trap documented in
        # docs/using-as-a-template.md.
        with pytest.raises(KeyError, match="long_term_memory"):
            load_system_prompt(username="ada")


class TestSessionTitlePrompt:
    def test_exposes_a_user_message_placeholder(self) -> None:
        assert "{user_message}" in SESSION_TITLE_PROMPT

    def test_formats_without_error(self) -> None:
        assert "hello there" in SESSION_TITLE_PROMPT.format(user_message="hello there")
