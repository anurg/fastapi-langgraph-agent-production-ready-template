# Frontend (Streamlit)

A Streamlit console for the agent API, living in `frontend/`. It covers every
endpoint the API exposes: registration, login, session management, streaming and
non-streaming chat, history loading and clearing.

## Running it

```bash
make ui                              # http://localhost:8501, API at http://localhost:8000
make ui UI_PORT=3000                 # different port
AGENT_API_URL=https://api.example.com make ui   # different API
```

`make ui` resolves the `ui` extra on the fly (`uv run --extra ui`), so no extra
install step is needed. The API must be running separately (`make dev`).

## Layout

```
frontend/
  app.py              # entry point: page config, auth gate, layout
  api_client.py       # AgentAPI — one method per endpoint, raises APIError
  models.py           # Pydantic mirrors of the backend schemas
  state.py            # every st.session_state key lives here
  views/
    auth_view.py      # sign in / create account
    sidebar.py        # session list, rename, clear, delete, health, sign out
    chat_view.py      # transcript, composer, streaming reply
```

## The two token scopes

The API issues two kinds of JWT and the UI holds both:

| Token | Issued by | Used for |
|---|---|---|
| **User** token | `POST /auth/register`, `POST /auth/login` | `POST /auth/session`, `GET /auth/sessions` |
| **Session** token | `POST /auth/session`, `GET /auth/sessions` | all `/chatbot/*` calls, session rename and delete |

`GET /auth/sessions` returns a freshly minted session token for every session, so
listing sessions is also how the UI obtains tokens for chats created earlier —
and how it recovers when a session token expires.

## Endpoint coverage

| Endpoint | Where it is used |
|---|---|
| `POST /auth/register` | Create account tab |
| `POST /auth/login` | Sign in tab |
| `POST /auth/session` | Sidebar → **✚ New chat** |
| `GET /auth/sessions` | Sidebar list; refreshed after each turn to pick up auto-generated names |
| `PATCH /auth/session/{id}/name` | Sidebar → Chat settings → Rename |
| `DELETE /auth/session/{id}` | Sidebar → Chat settings → Delete |
| `POST /chatbot/chat` | Composer with **Stream** toggled off |
| `POST /chatbot/chat/stream` | Composer with **Stream** toggled on (default) |
| `GET /chatbot/messages` | Loading a session's transcript |
| `DELETE /chatbot/messages` | Sidebar → Chat settings → Clear history |
| `GET /health` | Sidebar status indicator |

## Behaviour notes

- **The chat endpoints are stateful.** The agent checkpoints each session under
  a `thread_id` equal to the session id, and `GraphState.messages` uses the
  `add_messages` reducer — so the conversation already lives server-side. The UI
  therefore sends **only the new user turn**. Replaying the whole transcript
  appends it to the stored history a second time, which shows up as duplicated
  turns the next time the session is opened.
- **Streaming.** `/chatbot/chat/stream` emits `data: {"content": ..., "done": ...}`
  events. A terminating event that still carries content means the server failed
  mid-stream, so it is raised as an error rather than rendered as agent output.
- **Session naming.** The backend names a session in a background task after its
  first message, so the UI re-lists sessions after every turn to pick the name up.
- **Retries.** Read-only calls (health, list sessions, get messages) retry with
  tenacity's exponential backoff. Sends are never retried, so a message cannot be
  delivered twice.
- **Password rules** are checked client-side before calling `/auth/register`,
  which is limited to 10 requests per hour.
- **Rate limits** surface as a plain "Rate limit reached" message rather than a
  raw 429.
- CORS is irrelevant here: Streamlit calls the API from its own Python process,
  not from the browser.
