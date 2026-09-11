"""Behavioural tests for the LangGraph agent.

These assert on *routing* — which node runs next, what ends up in state — rather
than on model wording, so they stay meaningful when the prompt or model changes.
The LLM is scripted and the checkpointer is in-memory, so nothing here touches the
network or a database.
"""

import asyncio

import pytest
from langchain_core.messages import (
    AIMessage,
    HumanMessage,
    ToolMessage,
)
from langchain_core.tools import tool

from tests.conftest import (
    FailingLLMService,
    FakeLLMService,
)


def _tool_call_message(name: str = "echo", args: dict | None = None, call_id: str = "call_1") -> AIMessage:
    """An assistant message that requests one tool call."""
    return AIMessage(content="", tool_calls=[{"name": name, "args": args or {"text": "hi"}, "id": call_id}])


@tool
async def echo(text: str) -> str:
    """Echo the supplied text back to the caller."""
    return f"echo: {text}"


@tool
async def slow_echo(text: str) -> str:
    """Echo after a short delay, to make concurrency observable."""
    await asyncio.sleep(0.1)
    return f"slow: {text}"


@tool
async def exploding(text: str) -> str:
    """Always raise, to exercise the tool failure path."""
    raise RuntimeError("tool blew up")


class TestGraphConstruction:
    async def test_compiles_with_an_injected_checkpointer_and_no_database(self, make_agent) -> None:
        agent = await make_agent()

        assert agent.graph is not None
        assert agent._connection_pool is None, "injecting a checkpointer must not open a Postgres pool"

    async def test_exposes_the_expected_nodes(self, make_agent) -> None:
        agent = await make_agent()

        assert {"chat", "tool_call"} <= set(agent.graph.get_graph().nodes)

    async def test_graph_is_built_once_and_reused(self, make_agent) -> None:
        agent = await make_agent()
        first = agent.graph

        assert await agent.create_graph() is first, "create_graph must be idempotent"


class TestChatRouting:
    async def test_a_plain_answer_ends_the_run(self, make_agent, thread_config) -> None:
        agent = await make_agent([AIMessage(content="the answer")])

        result = await agent.graph.ainvoke({"messages": [HumanMessage(content="question")]}, thread_config)

        assert result["messages"][-1].content == "the answer"
        assert not any(isinstance(m, ToolMessage) for m in result["messages"]), "no tool should have run"

    async def test_a_tool_call_routes_through_tool_call_and_back_to_chat(self, make_agent, thread_config) -> None:
        agent = await make_agent(
            [_tool_call_message(args={"text": "world"}), AIMessage(content="done")],
            tools=[echo],
        )

        result = await agent.graph.ainvoke({"messages": [HumanMessage(content="please echo")]}, thread_config)

        tool_messages = [m for m in result["messages"] if isinstance(m, ToolMessage)]
        assert len(tool_messages) == 1
        assert tool_messages[0].content == "echo: world"
        assert result["messages"][-1].content == "done", "control must return to chat after the tool"

    async def test_the_llm_sees_the_tool_result_on_the_second_call(self, make_agent, thread_config) -> None:
        fake = FakeLLMService([_tool_call_message(args={"text": "abc"}), AIMessage(content="done")])
        agent = await make_agent(llm_service=fake, tools=[echo])

        await agent.graph.ainvoke({"messages": [HumanMessage(content="go")]}, thread_config)

        assert len(fake.calls) == 2
        second_call_contents = [m.get("content") for m in fake.calls[1]]
        assert "echo: abc" in second_call_contents

    async def test_every_call_is_prefixed_with_the_system_prompt(self, make_agent, thread_config) -> None:
        fake = FakeLLMService([AIMessage(content="hi")])
        agent = await make_agent(llm_service=fake)

        await agent.graph.ainvoke({"messages": [HumanMessage(content="hello")]}, thread_config)

        assert fake.calls[0][0]["role"] == "system"

    async def test_the_username_from_config_reaches_the_system_prompt(self, make_agent, thread_config) -> None:
        fake = FakeLLMService([AIMessage(content="hi")])
        agent = await make_agent(llm_service=fake)

        await agent.graph.ainvoke({"messages": [HumanMessage(content="hello")]}, thread_config)

        assert "You are talking to tester." in fake.calls[0][0]["content"]

    async def test_long_term_memory_in_state_reaches_the_system_prompt(self, make_agent, thread_config) -> None:
        fake = FakeLLMService([AIMessage(content="hi")])
        agent = await make_agent(llm_service=fake)

        await agent.graph.ainvoke(
            {"messages": [HumanMessage(content="hello")], "long_term_memory": "prefers metric units"},
            thread_config,
        )

        assert "prefers metric units" in fake.calls[0][0]["content"]


class TestToolExecution:
    async def test_multiple_tool_calls_run_concurrently(self, make_agent, thread_config) -> None:
        two_calls = AIMessage(
            content="",
            tool_calls=[
                {"name": "slow_echo", "args": {"text": "a"}, "id": "c1"},
                {"name": "slow_echo", "args": {"text": "b"}, "id": "c2"},
                {"name": "slow_echo", "args": {"text": "c"}, "id": "c3"},
            ],
        )
        agent = await make_agent([two_calls, AIMessage(content="done")], tools=[slow_echo])

        started = asyncio.get_event_loop().time()
        result = await agent.graph.ainvoke({"messages": [HumanMessage(content="go")]}, thread_config)
        elapsed = asyncio.get_event_loop().time() - started

        assert len([m for m in result["messages"] if isinstance(m, ToolMessage)]) == 3
        assert elapsed < 0.25, f"three 0.1s tools ran in {elapsed:.2f}s — they were not concurrent"

    async def test_tool_results_carry_the_originating_call_id(self, make_agent, thread_config) -> None:
        agent = await make_agent(
            [_tool_call_message(call_id="call_xyz"), AIMessage(content="done")],
            tools=[echo],
        )

        result = await agent.graph.ainvoke({"messages": [HumanMessage(content="go")]}, thread_config)

        tool_message = next(m for m in result["messages"] if isinstance(m, ToolMessage))
        assert tool_message.tool_call_id == "call_xyz"
        assert tool_message.name == "echo"

    async def test_a_raising_tool_fails_the_run_after_retries(self, make_agent, thread_config) -> None:
        """Characterization test for a known sharp edge.

        `_execute_tool` does not catch per-call failures, so one bad tool aborts the
        whole turn — and the `RetryPolicy(max_attempts=3)` on the `tool_call` node
        re-runs it twice more first. Hardening this is listed in
        docs/using-as-a-template.md; this test pins the current behaviour so the
        change is visible when it happens.
        """
        agent = await make_agent(
            [_tool_call_message(name="exploding"), AIMessage(content="unreachable")],
            tools=[exploding],
        )

        with pytest.raises(RuntimeError, match="tool blew up"):
            await agent.graph.ainvoke({"messages": [HumanMessage(content="go")]}, thread_config)

    async def test_an_unknown_tool_name_fails_rather_than_hanging(self, make_agent, thread_config) -> None:
        agent = await make_agent(
            [_tool_call_message(name="does_not_exist"), AIMessage(content="unreachable")],
            tools=[echo],
        )

        with pytest.raises(KeyError):
            await agent.graph.ainvoke({"messages": [HumanMessage(content="go")]}, thread_config)


class TestChatFailure:
    async def test_an_llm_outage_surfaces_as_an_exception(self, make_agent, thread_config) -> None:
        agent = await make_agent(llm_service=FailingLLMService())

        with pytest.raises(Exception, match="failed to get llm response after trying all models"):
            await agent.graph.ainvoke({"messages": [HumanMessage(content="go")]}, thread_config)


class TestCheckpointing:
    async def test_history_persists_across_invocations_on_one_thread(self, make_agent, thread_config) -> None:
        agent = await make_agent([AIMessage(content="first"), AIMessage(content="second")])

        await agent.graph.ainvoke({"messages": [HumanMessage(content="one")]}, thread_config)
        result = await agent.graph.ainvoke({"messages": [HumanMessage(content="two")]}, thread_config)

        contents = [m.content for m in result["messages"]]
        assert contents == ["one", "first", "two", "second"]

    async def test_separate_threads_do_not_share_history(self, make_agent) -> None:
        agent = await make_agent([AIMessage(content="reply")])

        await agent.graph.ainvoke(
            {"messages": [HumanMessage(content="thread one")]},
            {"configurable": {"thread_id": "a"}},
        )
        result = await agent.graph.ainvoke(
            {"messages": [HumanMessage(content="thread two")]},
            {"configurable": {"thread_id": "b"}},
        )

        contents = [m.content for m in result["messages"]]
        assert "thread one" not in contents
