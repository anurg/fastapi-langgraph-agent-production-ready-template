"""Shared pytest fixtures.

Import order matters here. Several application modules build singletons at import
time — ``settings`` in `app.core.config`, ``database_service`` (which constructs a
SQLAlchemy engine in its ``__init__``), ``llm_service`` (which instantiates every
model in the registry), and ``agent`` in `app.api.v1.chatbot`. Environment
variables must therefore be in place *before* the first ``app.*`` import, which is
why the ``os.environ`` block below sits at module scope, above the app imports,
rather than inside a fixture.
"""

import os

# --- must run before any `app.*` import ------------------------------------
os.environ["APP_ENV"] = "test"
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-that-is-definitely-long-enough-32")
os.environ.setdefault("OPENAI_API_KEY", "sk-test-not-a-real-key")
os.environ.setdefault("LANGFUSE_TRACING_ENABLED", "false")
os.environ.setdefault("VALKEY_HOST", "")  # force the in-memory cache fallback
os.environ.setdefault("SESSION_NAMING_ENABLED", "false")
# ---------------------------------------------------------------------------

from types import SimpleNamespace  # noqa: E402
from typing import AsyncGenerator  # noqa: E402

import pytest  # noqa: E402
from httpx import (  # noqa: E402
    ASGITransport,
    AsyncClient,
)
from langchain_core.messages import (  # noqa: E402
    AIMessage,
    BaseMessage,
)
from langgraph.checkpoint.memory import MemorySaver  # noqa: E402

from app.core.config import (  # noqa: E402
    Environment,
    settings,
)


@pytest.fixture(scope="session", autouse=True)
def _assert_test_environment() -> None:
    """Fail loudly if the suite is running against a non-test config.

    Without this, a stray ``.env`` on a developer machine could point the tests at
    a real database or a live LLM key and the failure would look like a flaky test
    rather than a misconfiguration.
    """
    assert settings.ENVIRONMENT == Environment.TEST, (
        f"tests must run with APP_ENV=test, got {settings.ENVIRONMENT.value}. Use `make test`."
    )


@pytest.fixture
async def client() -> AsyncGenerator[AsyncClient, None]:
    """An HTTP client bound to the ASGI app, with startup/shutdown skipped.

    The app's lifespan pre-warms the LangGraph connection pool, the cache and the
    mem0 memory service — all of which need live infrastructure. Driving the app
    through ``ASGITransport`` without entering the lifespan gives route coverage
    with no containers running.
    """
    from app.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        yield ac


class FakeLLMService:
    """Stand-in for `LLMService` that replays scripted responses.

    `LangGraphAgent._chat` only ever touches ``get_llm`` (for the metrics label)
    and ``call``, so faking the service is enough to drive the whole graph without
    a network call or an API key. Responses are returned in order; the last one
    repeats if the graph loops more times than were scripted.
    """

    def __init__(self, responses: list[BaseMessage]) -> None:
        if not responses:
            raise ValueError("FakeLLMService needs at least one scripted response")
        self.responses = responses
        self.calls: list[list[dict]] = []

    async def call(self, messages: list[dict], *args: object, **kwargs: object) -> BaseMessage:
        self.calls.append(messages)
        index = min(len(self.calls) - 1, len(self.responses) - 1)
        return self.responses[index]

    def get_llm(self) -> object:
        return SimpleNamespace(model_name="fake-model")

    def bind_tools(self, tools: list) -> "FakeLLMService":
        return self


class FailingLLMService(FakeLLMService):
    """A fake service whose `call` always raises, to exercise the error path."""

    def __init__(self, error: Exception | None = None) -> None:
        super().__init__([AIMessage(content="never returned")])
        self.error = error or RuntimeError("all models failed")

    async def call(self, messages: list[dict], *args: object, **kwargs: object) -> BaseMessage:
        self.calls.append(messages)
        raise self.error


@pytest.fixture
def make_agent():
    """Build a `LangGraphAgent` wired to a fake LLM and an in-memory checkpointer.

    Returns an async factory so each test can script its own LLM responses and,
    optionally, swap the tool set.
    """
    from app.core.langgraph.graph import LangGraphAgent

    async def _make(
        responses: list[BaseMessage] | None = None,
        *,
        llm_service: object | None = None,
        tools: list | None = None,
    ):
        agent = LangGraphAgent()
        agent.llm_service = llm_service or FakeLLMService(responses or [AIMessage(content="hello")])
        if tools is not None:
            agent.tools_by_name = {tool.name: tool for tool in tools}
        # Test-only alias: the production attribute is the private `_graph`, and
        # reaching through it in every test reads worse than naming it once here.
        agent.graph = await agent.create_graph(checkpointer=MemorySaver())
        return agent

    return _make


@pytest.fixture
def thread_config() -> dict:
    """A minimal runnable config — the graph requires a thread_id to checkpoint."""
    return {"configurable": {"thread_id": "test-thread"}, "metadata": {"username": "tester"}}
