# Using This as a Template

This repo is two things stacked on each other:

- a **platform** — auth, persistence, tracing, metrics, evals, deploy — that is ready to carry a real workload
- a **demo agent** — a two-node ReAct loop with two toy tools — that exists to prove the platform works

Adopting the template means keeping the first and replacing the second. This guide walks through
that, in the order you actually hit the work.

## What you keep, what you replace

| Area | Files | Verdict |
|---|---|---|
| Auth, sessions, threads | [app/api/v1/auth.py](../app/api/v1/auth.py), [app/models/](../app/models/) | Keep — JWT, sessions and Alembic migrations are done |
| Config | [app/core/config.py](../app/core/config.py) | Keep — rename values, keep the structure |
| Observability | [app/core/observability.py](../app/core/observability.py), [logging.py](../app/core/logging.py), [metrics.py](../app/core/metrics.py) | Keep — Langfuse + structlog + Prometheus already wired |
| LLM service | [app/services/llm/](../app/services/llm/) | Keep the service, rewrite the model list |
| Memory | [app/services/memory.py](../app/services/memory.py) | Keep if you want mem0; drop cleanly if you don't |
| Checkpointing | `_get_connection_pool` / `create_graph` in [graph.py](../app/core/langgraph/graph.py) | Keep — this is what makes multi-step runs resumable |
| Evals | [evals/](../evals/) | Keep — rewrite the metrics for your domain |
| Ops | [docker-compose.yml](../docker-compose.yml), [Makefile](../Makefile), [alembic/](../alembic/) | Keep |
| **Agent graph** | `_chat` / `_tool_call` in [graph.py](../app/core/langgraph/graph.py) | **Replace** |
| **Graph state** | [app/schemas/graph.py](../app/schemas/graph.py) | **Replace** |
| **Tools** | [app/core/langgraph/tools/](../app/core/langgraph/tools/) | **Replace** |
| **System prompt** | [app/core/prompts/system.md](../app/core/prompts/system.md) | **Replace** |

## Step 1 — Fork and rename

```bash
git clone <this-repo> my-new-agent && cd my-new-agent
rm -rf .git && git init
cp .env.example .env.development
make install
```

Rename in this order:

1. `name` and `description` in [pyproject.toml](../pyproject.toml).
2. `PROJECT_NAME`, `VERSION`, `DESCRIPTION` in your `.env.*` files. `PROJECT_NAME` is not cosmetic —
   it feeds the agent's display name in the system prompt and the compiled graph name that shows up
   in Langfuse traces.
3. `POSTGRES_DB` and the Langfuse `LANGFUSE_INIT_PROJECT_*` values, so your traces don't land in a
   project named after the template.

Then generate fresh secrets. Do not ship the example values:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"   # JWT_SECRET_KEY
```

Verify before writing any agent code:

```bash
make docker-up ENV=development
make migrate ENV=development
curl localhost:8000/health
```

A green health check means the platform half is yours and working. Everything after this is agent work.

## Step 2 — Strip the demo agent

The demo is small enough to delete outright, and deleting it is better than editing around it:

```bash
rm app/core/langgraph/tools/duckduckgo_search.py
# keep ask_human.py if you want human-in-the-loop; otherwise remove it too
```

Then rewrite [app/core/prompts/system.md](../app/core/prompts/system.md). Note the contract in
[app/core/prompts/__init__.py](../app/core/prompts/__init__.py): the template is read once at import
and formatted with `agent_name`, `current_date_and_time`, `user_context` and `long_term_memory`. If
you add a placeholder to the markdown you must pass it through `load_system_prompt(**kwargs)`, or
`.format()` raises at request time — not at startup.

## Step 3 — Add your tools

Tools are registered by appending to the `tools` list in
[app/core/langgraph/tools/__init__.py](../app/core/langgraph/tools/__init__.py). The graph picks them
up from there; there is no other registry to update.

```python
# app/core/langgraph/tools/lookup_order.py
from langchain_core.tools import tool

from app.core.logging import logger
from app.services.database import database_service


@tool
async def lookup_order(order_id: str) -> str:
    """Look up an order by its ID. Returns status, items and shipping state."""
    logger.info("tool_lookup_order_called", order_id=order_id)
    ...
```

Rules that matter here, beyond the ones in [AGENTS.md](../AGENTS.md):

- **Make tools `async`.** `_tool_call` runs them through `asyncio.gather`, so a sync tool blocks the
  event loop and serialises every other concurrent request.
- **The docstring is the tool spec.** It is what the model sees when deciding to call it. Write it
  for the model, not for a human reading the source.
- **Return a string, not an object.** `_tool_call` puts the result straight into `ToolMessage.content`.
- **Never let a tool raise for an expected failure.** An uncaught exception aborts the node, and the
  `RetryPolicy(max_attempts=3)` on `tool_call` will re-run it two more times before the request dies.
  Return a message the model can recover from — `"no order found with id X"` — and reserve exceptions
  for genuine outages.

### Hardening the tool layer

The template does not do these, and a complex agent needs all of them. Add them in `_execute_tool`:

- **Per-tool timeout** — wrap the `ainvoke` in `asyncio.wait_for`. One hanging tool currently hangs
  the whole turn.
- **Result size limits** — truncate long results before they reach `ToolMessage`, or a single scrape
  blows your context window.
- **Structured error handling** — catch per tool call and return an error `ToolMessage` instead of
  failing the node, so one bad call out of four doesn't discard the other three.
- **Permissioning** — `config` carries the authenticated user; gate destructive tools on it.

## Step 4 — Widen the graph state

[GraphState](../app/schemas/graph.py) currently holds `messages` and `long_term_memory`. That is
enough for a chat loop and nothing more. Agentic apps need somewhere to put the plan and the
intermediate work:

```python
class GraphState(BaseModel):
    messages: Annotated[list, add_messages] = Field(default_factory=list)
    long_term_memory: str = Field(default="")

    plan: list[str] = Field(default_factory=list)
    completed_steps: Annotated[list[str], operator.add] = Field(default_factory=list)
    scratchpad: dict[str, Any] = Field(default_factory=dict)
    error_count: int = Field(default=0)
```

The `Annotated[..., reducer]` part is the one to get right. Without a reducer, two branches running
in parallel both write the whole field and the last one wins — silently. `add_messages` already does
this for `messages`; any field that parallel nodes write needs the same treatment.

## Step 5 — Grow past the single loop

`create_graph` builds two nodes: `chat` routes to `tool_call` or `END`, `tool_call` routes back. The
patterns you'll likely want instead:

**Planner → executor.** A planning node writes `state.plan`, an executor node walks it, and a
conditional edge returns to the planner when a step fails.

```python
graph_builder.add_node("plan", self._plan, destinations=("execute",))
graph_builder.add_node("execute", self._execute, destinations=("plan", "chat", END))
graph_builder.set_entry_point("plan")
```

**Supervisor → sub-agents.** Each sub-agent is its own compiled graph added as a node. Give each one
its own state channel so they don't fight over `messages`.

**Human-in-the-loop.** Use LangGraph's `interrupt()` and resume with a `Command`. The checkpointer
already persists across the pause — that part is free. The template ships `ask_human` as a tool but
never actually interrupts, so this is wiring you add.

### Split the orchestrator first

[LangGraphAgent](../app/core/langgraph/graph.py) is ~474 lines doing four jobs: connection-pool
lifecycle, graph construction, node implementations, and the public streaming/history API. Adding
three sub-agents to it will not go well. Before you grow the graph, move the node bodies out:

```
app/core/langgraph/
  graph.py          # orchestrator: pool, create_graph, get_response, streaming
  nodes/
    chat.py
    plan.py
    execute.py
  tools/
```

The nodes take `(state, config)` and return `Command` — they don't need the agent instance for
anything except `self.llm_service`, which is better passed in than reached through.

## Step 6 — Extend the tests

The template ships a test suite that runs with no infrastructure — no database, no Valkey, no API
key, no network:

```bash
make test          # APP_ENV=test uv run pytest -q
make check         # lint + typecheck + test
```

```
tests/
  conftest.py           # env setup, ASGI client, FakeLLMService, agent factory
  test_health.py        # smoke test proving the harness boots the app
  test_sanitization.py  # XSS/escaping, email, password strength
  test_auth_utils.py    # JWT create/verify, expiry, tampering, forged keys
  test_prompts.py       # system prompt substitution and its failure mode
  test_graph_utils.py   # message prep, trimming, structured-content flattening
  test_schemas.py       # request/response validation boundaries
  test_graph.py         # agent routing against a scripted LLM
```

Two things in [conftest.py](../tests/conftest.py) are load-bearing and worth understanding before
you extend it:

**Environment must be set before the first `app.*` import.** Several modules build singletons at
import time — `settings`, `database_service` (which constructs a SQLAlchemy engine in `__init__`),
`llm_service` (which instantiates every model in the registry), and `agent` in
[chatbot.py](../app/api/v1/chatbot.py). The `os.environ` block therefore sits at module scope above
the imports, not inside a fixture. `APP_ENV=test` also skips the JWT strength check in
[config.py](../app/core/config.py), which is why `make test` sets it.

**The LLM is faked at the service boundary, not the model boundary.** `_chat` only touches
`llm_service.call()` and `llm_service.get_llm()`, so `FakeLLMService` replays a scripted list of
`AIMessage` objects — no `GenericFakeChatModel`, no tool-binding to reproduce. Combined with the
`checkpointer` parameter on `create_graph`, which accepts a `MemorySaver` in place of
`AsyncPostgresSaver`, the whole graph runs in-process:

```python
async def test_a_tool_call_routes_through_tool_call_and_back_to_chat(make_agent, thread_config):
    agent = await make_agent(
        [_tool_call_message(args={"text": "world"}), AIMessage(content="done")],
        tools=[echo],
    )
    result = await agent.graph.ainvoke({"messages": [HumanMessage(content="go")]}, thread_config)
    assert result["messages"][-1].content == "done"
```

Assert on **routing and state**, not on model wording: did a tool call reach `tool_call`, did a plain
answer reach `END`, did the tool result reach the next LLM call. Those stay true when you change the
prompt or the model.

### Characterization tests — read these before you refactor

Three tests pin behaviour that is arguably wrong, so that changing it is a visible, deliberate act
rather than a silent regression:

- `test_returns_mixed_message_types` — `prepare_messages` returns a `Message` for the system prompt
  followed by LangChain `BaseMessage` objects, so `dump_messages` emits dicts of two different
  shapes (`role`/`content` vs `type`/`content`).
- `test_a_raising_tool_fails_the_run_after_retries` — one raising tool aborts the whole turn, after
  `RetryPolicy(max_attempts=3)` re-runs it twice.
- `test_an_unknown_tool_name_fails_rather_than_hanging` — a hallucinated tool name raises `KeyError`.

The last two are exactly the tool-layer hardening described in Step 3. When you add it, these tests
should fail — update them to assert the new, better behaviour.

### What is still missing

- **API integration tests** — routes are only covered via `/health`. Override `get_current_session`
  through `app.dependency_overrides`, monkeypatch the module-level `agent`, and disable the limiter.
- **Real-database tests** — nothing exercises [database.py](../app/services/database.py) against
  Postgres.
- **Rate-limit coverage** — nothing asserts a 429, or that every route carries a limiter decorator,
  despite that being the first rule in [AGENTS.md](../AGENTS.md).
- **Typechecking of tests** — `[tool.pyright]` includes `app`, `evals` and `frontend`, not `tests`.

## Adoption checklist

- [ ] Renamed project, regenerated `JWT_SECRET_KEY`, own `POSTGRES_DB`
- [ ] Own Langfuse project — traces are not landing in the template's
- [ ] Demo tools deleted, system prompt rewritten
- [ ] Model list in [registry.py](../app/services/llm/registry.py) points at models you actually use
- [ ] Every tool is `async`, returns a string, and handles expected failures without raising
- [ ] Per-tool timeouts and result-size limits added to `_execute_tool`
- [ ] `GraphState` has reducers on every field that parallel nodes write
- [ ] Node implementations moved out of `LangGraphAgent`
- [ ] `make check` passes (lint + typecheck + tests) after your rewrite
- [ ] Eval metrics in [evals/metrics/prompts/](../evals/metrics/prompts/) rewritten for your domain

## When this template is the wrong fit

- **You need durable, long-running workflows** — runs spanning hours, exactly-once side effects,
  saga-style rollback. Checkpointing resumes a graph; it does not give you those. That is where a
  workflow engine earns its keep.
- **You don't need auth or multi-tenancy** — a single-user internal tool pays the full cost of the
  auth and session layer for nothing.
- **You want a non-OpenAI provider** — [registry.py](../app/services/llm/registry.py) hardcodes
  `ChatOpenAI` and reasoning-model parameters. The abstraction is provider-agnostic but the
  implementation is not; budget a half-day.
- **You want something small** — twelve compose services is a lot of machinery to run for a
  prototype.

## See also

- [Architecture](architecture.md) — request flow and component diagrams
- [Getting Started](getting-started.md) — first-run setup
- [AGENTS.md](../AGENTS.md) — coding conventions this repo enforces
- [LLM Service](llm-service.md) — retries, fallback chain, timeout budget
