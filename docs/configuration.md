# Configuration

All configuration is read from environment variables. Use `.env.development`, `.env.staging`, or `.env.production` — the app loads the right file based on the `APP_ENV` variable.

Copy `.env.example` to get started:

```bash
cp .env.example .env.development
```

---

## Application

| Variable | Default | Description |
| --- | --- | --- |
| `APP_ENV` | `development` | Environment: `development`, `staging`, `production`, `test` |
| `PROJECT_NAME` | `FastAPI LangGraph Template` | Displayed in API docs and logs |
| `VERSION` | `1.0.0` | API version |
| `DEBUG` | `false` | Enables debug logging and profiling middleware |
| `API_V1_STR` | `/api/v1` | API prefix |
| `ALLOWED_ORIGINS` | `*` | Comma-separated CORS origins |

---

## LLM

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `OPENAI_API_KEY` | — | Yes | OpenAI API key |
| `DEFAULT_LLM_MODEL` | `gpt-5-mini` | No | Starting model — see [LLM Service](llm-service.md) for fallback order |
| `DEFAULT_LLM_TEMPERATURE` | `0.2` | No | Temperature for chat completions |
| `MAX_TOKENS` | `2000` | No | Max tokens per LLM response |
| `MAX_LLM_CALL_RETRIES` | `3` | No | Retries per model before switching to fallback |
| `LLM_TOTAL_TIMEOUT` | `60` | No | Max seconds for the entire fallback loop |
| `SESSION_NAMING_ENABLED` | `true` | No | Auto-generate a session title from the user's first message using an LLM background task |

---

## Long-term memory

| Variable | Default | Description |
| --- | --- | --- |
| `LONG_TERM_MEMORY_COLLECTION_NAME` | `longterm_memory` | pgvector collection name |
| `LONG_TERM_MEMORY_MODEL` | `gpt-5-nano` | LLM used by mem0 to extract memories |
| `LONG_TERM_MEMORY_EMBEDDER_MODEL` | `text-embedding-3-small` | Embedding model for semantic search |

---

## Database

| Variable | Default | Description |
| --- | --- | --- |
| `POSTGRES_HOST` | `localhost` | PostgreSQL host |
| `POSTGRES_PORT` | `5432` | PostgreSQL port |
| `POSTGRES_DB` | `food_order_db` | Database name |
| `POSTGRES_USER` | `postgres` | Database user |
| `POSTGRES_PASSWORD` | `postgres` | Database password |
| `POSTGRES_POOL_SIZE` | `20` | SQLAlchemy connection pool size |
| `POSTGRES_MAX_OVERFLOW` | `10` | Max overflow connections above pool size |

---

## Auth

| Variable | Default | Required | Description |
| --- | --- | --- | --- |
| `JWT_SECRET_KEY` | — | Yes | Secret used to sign JWT tokens — use a long random string in production |
| `JWT_ALGORITHM` | `HS256` | No | JWT signing algorithm |
| `JWT_ACCESS_TOKEN_EXPIRE_DAYS` | `30` | No | Token lifetime in days |

---

## Cache (Valkey/Redis)

When `VALKEY_HOST` is set, the app uses Valkey/Redis for memory search caching and rate limiting. When absent, it falls back to an in-memory TTL cache (not shared across instances).

> **The env var alone is not enough.** The `redis` client lives in the `cache`
> optional extra in `pyproject.toml`, so the image must be built with
> `uv sync --extra cache` (the Dockerfile does this). Without it the app logs
> `redis_client_not_installed` and
> `rate_limiter_valkey_configured_but_redis_missing`, then falls back to
> in-memory regardless of `VALKEY_HOST`. Confirm which backend is live by
> looking for `cache_initialized backend=redis` and `rate_limiter_using_valkey`
> at startup.

With Docker, set `VALKEY_HOST=valkey` — the Compose service name, not
`localhost`.

| Variable | Default | Description |
| --- | --- | --- |
| `VALKEY_HOST` | `` (disabled) | Valkey/Redis host — leave empty to use in-memory fallback |
| `VALKEY_PORT` | `6379` | Port |
| `VALKEY_DB` | `0` | Database index |
| `VALKEY_PASSWORD` | `` | Password (if required) |
| `VALKEY_MAX_CONNECTIONS` | `20` | Connection pool size |
| `CACHE_TTL_SECONDS` | `60` | TTL for cached memory search results |

---

## Observability (Langfuse)

| Variable | Default | Description |
| --- | --- | --- |
| `LANGFUSE_TRACING_ENABLED` | `true` | Set to `false` to disable tracing entirely |
| `LANGFUSE_PUBLIC_KEY` | — | Langfuse project public key |
| `LANGFUSE_SECRET_KEY` | — | Langfuse project secret key |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse host (self-hosted or cloud) |

With the bundled self-hosted stack, `LANGFUSE_HOST` is `http://langfuse-web:3000`
— the Compose service name as seen from the app container, not the `localhost:3001`
URL your browser uses.

### Self-hosted Langfuse (`langfuse` compose profile)

Only needed when running `make langfuse-up`. Generate each secret with
`openssl rand -hex 32`; Compose refuses to start the profile if one is missing.

| Variable | Description |
| --- | --- |
| `LANGFUSE_NEXTAUTH_SECRET` | Session signing secret for the UI |
| `LANGFUSE_SALT` | Hashing salt for API keys |
| `LANGFUSE_ENCRYPTION_KEY` | 32-byte hex key for encrypted fields |
| `LANGFUSE_POSTGRES_PASSWORD` | Password for Langfuse's own Postgres |
| `LANGFUSE_CLICKHOUSE_PASSWORD` | ClickHouse password |
| `LANGFUSE_MINIO_PASSWORD` | MinIO root password |
| `LANGFUSE_REDIS_PASSWORD` | Redis password |
| `LANGFUSE_NEXTAUTH_URL` | Browser-facing UI URL (default `http://localhost:3001`) |
| `LANGFUSE_MINIO_PUBLIC_URL` | Browser-facing MinIO URL (default `http://localhost:9190`) |
| `LANGFUSE_TELEMETRY_ENABLED` | Send usage telemetry upstream (default `false`) |

First-boot provisioning — these create the org, project and login user, and
mint the API keys above. They only apply to an empty database:

| Variable | Description |
| --- | --- |
| `LANGFUSE_INIT_ORG_ID` / `LANGFUSE_INIT_ORG_NAME` | Organization to create |
| `LANGFUSE_INIT_PROJECT_ID` / `LANGFUSE_INIT_PROJECT_NAME` | Project to create |
| `LANGFUSE_INIT_USER_EMAIL` / `LANGFUSE_INIT_USER_NAME` / `LANGFUSE_INIT_USER_PASSWORD` | UI login |

---

## Rate limiting

| Variable | Default | Description |
| --- | --- | --- |
| `RATE_LIMIT_DEFAULT` | `200 per day, 50 per hour` | Fallback limit |
| `RATE_LIMIT_CHAT` | `30 per minute` | POST /chat |
| `RATE_LIMIT_CHAT_STREAM` | `20 per minute` | POST /chat/stream |
| `RATE_LIMIT_MESSAGES` | `50 per minute` | GET/DELETE /messages |
| `RATE_LIMIT_LOGIN` | `20 per minute` | POST /auth/login |
| `RATE_LIMIT_REGISTER` | `10 per hour` | POST /auth/register |

When Valkey is configured, rate limiting is shared across all app instances. Without it, limits are per-process.

---

## Profiling (debug only)

Only active when `DEBUG=true`. Profiles every request and saves a JSON report when the request exceeds the threshold.

| Variable | Default | Description |
| --- | --- | --- |
| `PROFILING_DIR` | `/tmp/fastapi_profiles` | Directory for profile JSON files |
| `PROFILING_THRESHOLD_SECONDS` | `2.0` | Minimum wall time to trigger saving a profile. Set to `0` to profile every request. |

---

## Logging

| Variable | Default (dev) | Default (prod) | Description |
| --- | --- | --- | --- |
| `LOG_LEVEL` | `DEBUG` | `WARNING` | Log level |
| `LOG_FORMAT` | `console` | `json` | `console` for coloured dev output, `json` for structured production logs |
