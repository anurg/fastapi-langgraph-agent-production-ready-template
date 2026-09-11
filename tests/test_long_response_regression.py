"""Regression tests: a long or code-bearing assistant reply must not break a session.

`Message` was used both as the inbound request model and as the representation of
whatever the agent produced, so request-side validation — a 3000-character cap and
a script-tag rejection — was applied to the LLM's own output. A long answer, or one
containing a `<script>` example, raised `ValidationError` inside
`__process_messages`, surfaced as HTTP 500, and — because `get_chat_history` runs
through the same function — made the whole session permanently unreadable.
"""

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
)
from pydantic import ValidationError

from app.core.prompts import load_system_prompt
from app.schemas import (
    ChatRequest,
    ChatResponse,
    Message,
)
from app.schemas.chat import UserMessage
from app.utils.graph import prepare_messages

LONG_ANSWER = "An explanation of coding agents. " * 200  # ~6600 chars
SCRIPT_ANSWER = "Here is an example:\n```html\n<script>alert(1)</script>\n```"


class TestOutboundMessagesAreNotLengthCapped:
    def test_a_long_assistant_message_is_representable(self) -> None:
        assert len(Message(role="assistant", content=LONG_ANSWER).content) == len(LONG_ANSWER)

    def test_a_long_assistant_message_serialises_in_a_chat_response(self) -> None:
        response = ChatResponse(messages=[Message(role="assistant", content=LONG_ANSWER)])

        assert response.messages[0].content == LONG_ANSWER

    def test_an_assistant_message_may_contain_script_tags(self) -> None:
        """A code example is content, not an attack. Escaping belongs at render time."""
        assert Message(role="assistant", content=SCRIPT_ANSWER).content == SCRIPT_ANSWER

    def test_a_long_system_prompt_is_representable(self) -> None:
        """Long-term memory is interpolated into the system prompt, so it grows past 3000 chars."""
        prompt = load_system_prompt(username="ada", long_term_memory="remembered detail. " * 400)

        assert len(prompt) > 3000
        assert prepare_messages([], prompt)[0].content == prompt


class TestInboundMessagesAreStillValidated:
    def test_rejects_user_input_over_the_cap(self) -> None:
        with pytest.raises(ValidationError):
            UserMessage(role="user", content="x" * 3001)

    def test_rejects_user_input_containing_script_tags(self) -> None:
        with pytest.raises(ValidationError, match="harmful script tags"):
            UserMessage(role="user", content="<script>alert(1)</script>")

    def test_rejects_user_input_containing_null_bytes(self) -> None:
        with pytest.raises(ValidationError, match="null bytes"):
            UserMessage(role="user", content="bad\0value")

    def test_chat_request_enforces_the_inbound_rules(self) -> None:
        with pytest.raises(ValidationError):
            ChatRequest(messages=[{"role": "user", "content": "x" * 3001}])  # pyright: ignore[reportArgumentType]

    def test_chat_request_still_accepts_a_normal_message(self) -> None:
        request = ChatRequest(messages=[{"role": "user", "content": "what are coding agents?"}])  # pyright: ignore[reportArgumentType]

        assert request.messages[0].content == "what are coding agents?"


class TestSessionSurvivesALongAnswer:
    async def test_a_long_answer_round_trips_through_the_graph(self, make_agent, thread_config) -> None:
        agent = await make_agent([AIMessage(content=LONG_ANSWER)])

        await agent.graph.ainvoke({"messages": [HumanMessage(content="what are coding agents?")]}, thread_config)

        history = await agent.get_chat_history(thread_config["configurable"]["thread_id"])
        assert history[-1].content == LONG_ANSWER

    async def test_a_script_bearing_answer_round_trips_through_the_graph(self, make_agent, thread_config) -> None:
        agent = await make_agent([AIMessage(content=SCRIPT_ANSWER)])

        await agent.graph.ainvoke({"messages": [HumanMessage(content="show me html")]}, thread_config)

        history = await agent.get_chat_history(thread_config["configurable"]["thread_id"])
        assert history[-1].content == SCRIPT_ANSWER

    async def test_history_remains_readable_on_repeated_loads(self, make_agent, thread_config) -> None:
        """The original failure made a session unreadable forever, not just once."""
        agent = await make_agent([AIMessage(content=LONG_ANSWER)])
        await agent.graph.ainvoke({"messages": [HumanMessage(content="go")]}, thread_config)

        thread_id = thread_config["configurable"]["thread_id"]
        first = await agent.get_chat_history(thread_id)
        second = await agent.get_chat_history(thread_id)

        assert [m.content for m in first] == [m.content for m in second]
