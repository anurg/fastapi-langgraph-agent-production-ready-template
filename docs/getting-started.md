# Getting Started

## Prerequisites

- Python 3.13+
- [uv](https://docs.astral.sh/uv/) — `pip install uv`
- Docker + Docker Compose (recommended for local dev)
- OpenAI API key
- Langfuse account (optional — set `LANGFUSE_TRACING_ENABLED=false` to skip)

## Option A: Docker (recommended)

The fastest way to get running. One command starts the API and PostgreSQL with pgvector.

```bash
git clone <repo-url> my-agent
cd my-agent

# Copy and fill in your env file
cp .env.example .env.development
# Required: OPENAI_API_KEY, JWT_SECRET_KEY
# Optional: LANGFUSE_* keys (or set LANGFUSE_TRACING_ENABLED=false)
# Optional: VALKEY_HOST=valkey to use the Valkey cache

make install       # installs Python deps + pre-commit hooks
make docker-up     # starts API (port 8000) + PostgreSQL
make docker-migrate # runs Alembic migrations inside the app container
```

Open [http://localhost:8000/docs](http://localhost:8000/docs).

### Optional extras

```bash
make stack-up      # adds Prometheus, Grafana and cAdvisor
make langfuse-up   # adds self-hosted Langfuse tracing (UI on port 3001)
make ui            # Streamlit chat console on port 8501
```

Self-hosted Langfuse needs its own secrets in `.env.development` — see
[Observability](observability.md#self-hosted-langfuse). To use the Valkey cache
instead of the in-memory fallback, set `VALKEY_HOST=valkey`; the Docker image
already ships the required client.

## Option B: Local Python

```bash
git clone <repo-url> my-agent
cd my-agent

cp .env.example .env.development
# Fill in: OPENAI_API_KEY, JWT_SECRET_KEY, POSTGRES_* (point to your DB)

make install       # installs deps + pre-commit hooks
make migrate       # creates tables via Alembic
make dev           # starts server with hot reload on port 8000
```

## Your first API call

### 1. Register a user

```bash
curl -X POST http://localhost:8000/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "Secret123!", "username": "you"}'  # pragma: allowlist secret
```

Returns a `user_id` and a JWT token.

### 2. Create a session

```bash
curl -X POST http://localhost:8000/api/v1/auth/session \
  -H "Authorization: Bearer <token from step 1>"
```

Returns a `session_id` and a session-scoped JWT.

### 3. Chat

```bash
curl -X POST http://localhost:8000/api/v1/chatbot/chat \
  -H "Authorization: Bearer <session token>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

Or use the streaming endpoint for real-time responses:

```bash
curl -X POST http://localhost:8000/api/v1/chatbot/chat/stream \
  -H "Authorization: Bearer <session token>" \
  -H "Content-Type: application/json" \
  -d '{"messages": [{"role": "user", "content": "Hello!"}]}'
```

## Using the web console

Instead of curl, you can drive the whole API from a Streamlit UI:

```bash
make ui        # http://localhost:8501 (API assumed at http://localhost:8000)
```

It handles registration, login, chat sessions and streaming replies for you.
See [frontend.md](frontend.md) for details.

## Customising the agent

The parts you'll most likely change:

| What | Where |
|---|---|
| Agent personality & instructions | `app/core/prompts/system.md` |
| Available tools | `app/core/langgraph/tools.py` |
| LLM models & fallback order | `app/services/llm.py` → `LLMRegistry.LLMS` |
| Memory collection name | `LONG_TERM_MEMORY_COLLECTION_NAME` in `.env` |

## Running the tests

```bash
make test          # pytest suite, APP_ENV=test
make check         # lint + typecheck + tests
```

The suite needs nothing running — no database, no Valkey, no API key, no network. The LLM is faked at
the service boundary and the agent graph is compiled with an in-memory checkpointer. See
[Using as a Template](using-as-a-template.md#step-6--extend-the-tests) for how the fixtures work and
what is still uncovered.

## Running pre-commit hooks

Hooks run automatically on `git commit`. To run manually:

```bash
make pre-commit
```

Hooks include: trailing whitespace, YAML/TOML/JSON validation, secret detection, ruff lint + format.

## Troubleshooting

**Database connection error on startup**
Make sure PostgreSQL is running and `POSTGRES_*` vars in your `.env` match. With Docker: `make docker-up` handles this (including migrations).

**`could not translate host name "db"`**
`POSTGRES_HOST=db` only resolves *inside* the Docker network (it's the Compose
service name). If you run a command on your host (e.g. `make migrate` or `make dev`
in the local-Python flow), set `POSTGRES_HOST=localhost` instead — the DB's port is
published to the host via `docker-compose.yml`. Inside the container, keep `db`.

**`detect-secrets` blocking a commit**
If it's a false positive, add `# pragma: allowlist secret` to the end of the flagged line.

**Langfuse errors**
Set `LANGFUSE_TRACING_ENABLED=false` in your `.env` to disable tracing entirely during development.
