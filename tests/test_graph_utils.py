"""Tests for message preparation and LLM response normalisation."""

from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)

from app.schemas import Message
from app.utils.graph import (
    dump_messages,
    extract_text_content,
    prepare_messages,
    process_llm_response,
)


class TestDumpMessages:
    def test_dumps_each_message_to_a_dict(self) -> None:
        dumped = dump_messages([Message(role="user", content="hi")])

        assert dumped == [{"role": "user", "content": "hi"}]

    def test_returns_empty_list_for_no_messages(self) -> None:
        assert dump_messages([]) == []


class TestExtractTextContent:
    def test_passes_a_plain_string_through(self) -> None:
        assert extract_text_content("hello") == "hello"

    def test_concatenates_text_blocks(self) -> None:
        blocks = [{"type": "text", "text": "one "}, {"type": "text", "text": "two"}]

        assert extract_text_content(blocks) == "one two"

    def test_drops_reasoning_blocks(self) -> None:
        blocks = [
            {"type": "reasoning", "id": "r1", "summary": ["thinking"]},
            {"type": "text", "text": "the answer"},
        ]

        assert extract_text_content(blocks) == "the answer"

    def test_accepts_bare_strings_inside_the_block_list(self) -> None:
        assert extract_text_content(["a", {"type": "text", "text": "b"}]) == "ab"

    def test_returns_empty_string_when_nothing_is_extractable(self) -> None:
        assert extract_text_content([{"type": "reasoning", "id": "r1"}]) == ""

    def test_treats_a_text_block_with_no_text_key_as_empty(self) -> None:
        assert extract_text_content([{"type": "text"}]) == ""

    def test_ignores_unknown_block_types(self) -> None:
        assert extract_text_content([{"type": "image", "url": "x"}, {"type": "text", "text": "y"}]) == "y"


class TestProcessLLMResponse:
    def test_flattens_structured_content_to_a_string(self) -> None:
        response = AIMessage(content=[{"type": "text", "text": "flattened"}])

        assert process_llm_response(response).content == "flattened"

    def test_leaves_string_content_untouched(self) -> None:
        response = AIMessage(content="already a string")

        assert process_llm_response(response).content == "already a string"

    def test_mutates_and_returns_the_same_instance(self) -> None:
        response = AIMessage(content=[{"type": "text", "text": "x"}])

        assert process_llm_response(response) is response

    def test_preserves_tool_calls_while_flattening_content(self) -> None:
        response = AIMessage(
            content=[{"type": "reasoning", "id": "r"}, {"type": "text", "text": "calling"}],
            tool_calls=[{"name": "search", "args": {"q": "x"}, "id": "call_1"}],
        )

        processed = process_llm_response(response)

        assert processed.content == "calling"
        assert len(processed.tool_calls) == 1
        assert processed.tool_calls[0]["name"] == "search"


class TestPrepareMessages:
    def test_puts_the_system_prompt_first(self) -> None:
        prepared = prepare_messages([Message(role="user", content="hi")], "SYSTEM")

        assert prepared[0].role == "system"  # pyright: ignore[reportAttributeAccessIssue]
        assert prepared[0].content == "SYSTEM"

    def test_keeps_the_conversation_after_the_system_prompt(self) -> None:
        prepared = prepare_messages(
            [Message(role="user", content="hi"), Message(role="assistant", content="hello")],
            "SYSTEM",
        )

        assert [m.content for m in prepared] == ["SYSTEM", "hi", "hello"]

    def test_returns_mixed_message_types(self) -> None:
        """Characterization test, not an endorsement.

        `_trim_messages` converts the dumped dicts into LangChain messages, so the
        result is a `Message` for the system prompt followed by `BaseMessage`
        instances. `dump_messages` then produces dicts of two different shapes —
        ``{"role", "content"}`` for the system prompt, ``{"type", "content", ...}``
        for the rest. Both are accepted downstream, but the asymmetry is real.
        """
        prepared = prepare_messages([Message(role="user", content="hi")], "SYSTEM")

        assert isinstance(prepared[0], Message)
        assert isinstance(prepared[1], HumanMessage)

        dumped = dump_messages(prepared)
        assert "role" in dumped[0] and "type" not in dumped[0]
        assert "type" in dumped[1] and "role" not in dumped[1]

    def test_handles_a_conversation_with_no_prior_messages(self) -> None:
        prepared = prepare_messages([], "SYSTEM")

        assert len(prepared) == 1
        assert prepared[0].content == "SYSTEM"

    def test_trims_history_that_exceeds_the_token_budget(self, monkeypatch) -> None:
        from app.utils import graph as graph_utils

        monkeypatch.setattr(graph_utils.settings, "MAX_TOKENS", 30)
        long_history = [
            Message(role="user" if i % 2 == 0 else "assistant", content=f"message number {i} " * 5) for i in range(20)
        ]

        prepared = prepare_messages(long_history, "SYSTEM")

        assert len(prepared) < len(long_history) + 1
        assert prepared[0].content == "SYSTEM"
