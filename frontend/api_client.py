"""HTTP client for the LangGraph FastAPI agent.

Wraps every endpoint the API exposes and translates transport and HTTP errors
into a single `APIError` the UI layer can render. Read-only calls are retried
with exponential backoff via tenacity; mutating calls are never retried so a
message is not delivered twice.
"""

import json
import os
from typing import (
    Any,
    Iterator,
    List,
    Sequence,
)

import requests
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from frontend.models import (
    ChatMessage,
    ChatSession,
    HealthStatus,
    Token,
    UserAccount,
)

logger = structlog.get_logger(__name__)

DEFAULT_BASE_URL = os.getenv("AGENT_API_URL", "http://localhost:8000")
API_PREFIX = os.getenv("AGENT_API_PREFIX", "/api/v1")

# (connect, read) timeouts. Streaming reads get a long read budget because the
# agent may think and call tools before the first token arrives.
REQUEST_TIMEOUT = (5, 60)
STREAM_TIMEOUT = (5, 300)

_SSE_DATA_PREFIX = "data: "


class APIError(Exception):
    """An API call failed.

    Attributes:
        message: A human-readable description suitable for display.
        status_code: The HTTP status code, when the failure came from the API.
    """

    def __init__(self, message: str, status_code: int | None = None) -> None:
        """Build an API error.

        Args:
            message: A human-readable description of the failure.
            status_code: The HTTP status code, when one was received.
        """
        super().__init__(message)
        self.message = message
        self.status_code = status_code

    @property
    def is_auth_error(self) -> bool:
        """Whether the failure means the caller's token is no longer usable.

        Includes 404, which is what the session dependency returns once a
        session has been deleted — re-listing sessions recovers from it.

        Returns:
            bool: True for 401, 403 and 404 responses.
        """
        return self.status_code in (401, 403, 404)

    @property
    def is_rate_limited(self) -> bool:
        """Whether the failure was a rate-limit rejection.

        Returns:
            bool: True when the API responded with 429.
        """
        return self.status_code == 429


def _extract_error(response: requests.Response) -> str:
    """Turn an error response body into a readable message.

    Handles FastAPI's `detail` field and this project's custom validation
    handler, which returns a list of `{field, message}` objects.

    Args:
        response: The failed HTTP response.

    Returns:
        str: A message suitable for showing to the user.
    """
    if response.status_code == 429:
        return "Rate limit reached. Wait a moment and try again."

    try:
        payload: Any = response.json()
    except ValueError:
        return f"{response.status_code}: {response.text[:200] or response.reason}"

    if isinstance(payload, dict):
        errors = payload.get("errors")
        if isinstance(errors, list) and errors:
            return "; ".join(
                f"{item.get('field', 'field')}: {item.get('message', '')}".strip(": ")
                for item in errors
                if isinstance(item, dict)
            )
        detail = payload.get("detail")
        if isinstance(detail, str):
            return detail
        if detail is not None:
            return json.dumps(detail)

    return f"{response.status_code}: {response.reason}"


class AgentAPI:
    """Client for the LangGraph agent's REST API.

    The API uses two token scopes: a *user* token returned by register/login
    that manages sessions, and a *session* token returned per chat session that
    unlocks the chatbot endpoints. Callers pass whichever the endpoint needs.
    """

    def __init__(self, base_url: str = DEFAULT_BASE_URL, api_prefix: str = API_PREFIX) -> None:
        """Create a client bound to one API deployment.

        Args:
            base_url: Root URL of the API, e.g. "http://localhost:8000".
            api_prefix: Versioned path prefix, e.g. "/api/v1".
        """
        self.base_url = base_url.rstrip("/")
        self.api_prefix = api_prefix
        self._session = requests.Session()

    def _url(self, path: str) -> str:
        """Build a full URL for a versioned API path.

        Args:
            path: Path below the version prefix, e.g. "/auth/login".

        Returns:
            str: The absolute URL.
        """
        return f"{self.base_url}{self.api_prefix}{path}"

    @staticmethod
    def _auth(token: str) -> dict[str, str]:
        """Build an Authorization header.

        Args:
            token: The bearer token value.

        Returns:
            dict[str, str]: Headers carrying the bearer token.
        """
        return {"Authorization": f"Bearer {token}"}

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:
        """Perform a request and return the decoded JSON body.

        Args:
            method: HTTP method.
            path: Path below the version prefix.
            **kwargs: Extra arguments forwarded to requests.

        Returns:
            Any: The decoded JSON body, or None when the body is empty.

        Raises:
            APIError: If the network call fails or the API returns an error.
        """
        kwargs.setdefault("timeout", REQUEST_TIMEOUT)
        try:
            response = self._session.request(method, self._url(path), **kwargs)
        except requests.RequestException as exc:
            logger.exception("api_request_failed", method=method, path=path, error=str(exc))
            raise APIError(f"Cannot reach the API at {self.base_url}. Is it running?") from exc

        if not response.ok:
            message = _extract_error(response)
            logger.error("api_error_response", method=method, path=path, status=response.status_code)
            raise APIError(message, status_code=response.status_code)

        if not response.content:
            return None
        try:
            return response.json()
        except ValueError:
            return None

    # ------------------------------------------------------------------
    # Health
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(APIError),
        reraise=True,
    )
    def health(self) -> HealthStatus:
        """Fetch the API's health report.

        Returns:
            HealthStatus: The parsed health payload.

        Raises:
            APIError: If the API is unreachable or unhealthy.
        """
        try:
            response = self._session.get(f"{self.base_url}/health", timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            raise APIError("API unreachable") from exc

        try:
            payload = response.json()
        except ValueError as exc:
            raise APIError("Malformed health response") from exc

        return HealthStatus.model_validate(payload)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------
    def register(self, email: str, password: str, username: str | None = None) -> UserAccount:
        """Register a new user and return the account with its user token.

        Args:
            email: The new user's email address.
            password: The new user's password.
            username: Optional display name.

        Returns:
            UserAccount: The created account including its user-scoped token.

        Raises:
            APIError: If registration is rejected.
        """
        payload: dict[str, Any] = {"email": email, "password": password}
        if username:
            payload["username"] = username

        data = self._request("POST", "/auth/register", json=payload)
        logger.info("user_registered", email=email)
        return UserAccount.model_validate(data)

    def login(self, email: str, password: str) -> UserAccount:
        """Log in and return the account with its user token.

        The login endpoint takes form-encoded credentials and returns only a
        token, so the resulting account carries the email supplied here.

        Args:
            email: The user's email address.
            password: The user's password.

        Returns:
            UserAccount: The authenticated account.

        Raises:
            APIError: If the credentials are rejected.
        """
        data = self._request(
            "POST",
            "/auth/login",
            data={"email": email, "password": password, "grant_type": "password"},
        )
        logger.info("user_logged_in", email=email)
        return UserAccount(email=email, token=Token.model_validate(data))

    # ------------------------------------------------------------------
    # Sessions
    # ------------------------------------------------------------------
    def create_session(self, user_token: str) -> ChatSession:
        """Create a new chat session.

        Args:
            user_token: A user-scoped token.

        Returns:
            ChatSession: The new session and its session-scoped token.

        Raises:
            APIError: If the session cannot be created.
        """
        data = self._request("POST", "/auth/session", headers=self._auth(user_token))
        session = ChatSession.model_validate(data)
        logger.info("session_created", session_id=session.session_id)
        return session

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(APIError),
        reraise=True,
    )
    def list_sessions(self, user_token: str) -> List[ChatSession]:
        """List every session belonging to the user.

        Each entry carries a freshly minted session token, so this doubles as
        the way the UI obtains tokens for previously created sessions.

        Args:
            user_token: A user-scoped token.

        Returns:
            List[ChatSession]: The user's sessions, newest names included.

        Raises:
            APIError: If the sessions cannot be listed.
        """
        data = self._request("GET", "/auth/sessions", headers=self._auth(user_token))
        return [ChatSession.model_validate(item) for item in (data or [])]

    def rename_session(self, session_token: str, session_id: str, name: str) -> ChatSession:
        """Rename a session.

        Args:
            session_token: The token scoped to the session being renamed.
            session_id: The session's identifier.
            name: The new display name.

        Returns:
            ChatSession: The updated session.

        Raises:
            APIError: If the rename is rejected.
        """
        data = self._request(
            "PATCH",
            f"/auth/session/{session_id}/name",
            headers=self._auth(session_token),
            data={"name": name},
        )
        logger.info("session_renamed", session_id=session_id)
        return ChatSession.model_validate(data)

    def delete_session(self, session_token: str, session_id: str) -> None:
        """Delete a session.

        Args:
            session_token: The token scoped to the session being deleted.
            session_id: The session's identifier.

        Raises:
            APIError: If the deletion is rejected.
        """
        self._request("DELETE", f"/auth/session/{session_id}", headers=self._auth(session_token))
        logger.info("session_deleted", session_id=session_id)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type(APIError),
        reraise=True,
    )
    def get_messages(self, session_token: str) -> List[ChatMessage]:
        """Fetch a session's full message history.

        Args:
            session_token: The token scoped to the session.

        Returns:
            List[ChatMessage]: Every stored message, oldest first.

        Raises:
            APIError: If the history cannot be read.
        """
        data = self._request("GET", "/chatbot/messages", headers=self._auth(session_token))
        messages = (data or {}).get("messages", [])
        return [ChatMessage.model_validate(item) for item in messages]

    def clear_messages(self, session_token: str) -> None:
        """Delete a session's message history.

        Args:
            session_token: The token scoped to the session.

        Raises:
            APIError: If the history cannot be cleared.
        """
        self._request("DELETE", "/chatbot/messages", headers=self._auth(session_token))
        logger.info("chat_history_cleared")

    def chat(self, session_token: str, messages: Sequence[ChatMessage]) -> List[ChatMessage]:
        """Send new turns and wait for the complete reply.

        The agent checkpoints history per session, so pass only the new
        message(s) — resending the stored transcript duplicates it.

        Args:
            session_token: The token scoped to the session.
            messages: The new turns to send, usually a single user message.

        Returns:
            List[ChatMessage]: The conversation as the agent returned it.

        Raises:
            APIError: If the request fails.
        """
        data = self._request(
            "POST",
            "/chatbot/chat",
            headers=self._auth(session_token),
            json={"messages": [m.model_dump() for m in messages]},
            timeout=STREAM_TIMEOUT,
        )
        return [ChatMessage.model_validate(item) for item in (data or {}).get("messages", [])]

    def stream_chat(self, session_token: str, messages: Sequence[ChatMessage]) -> Iterator[str]:
        """Send new turns and yield reply chunks as they arrive.

        As with `chat`, the agent keeps the session's history itself, so pass
        only the new message(s).

        The endpoint emits server-sent events shaped `{"content": ..., "done": ...}`.
        A terminating event that still carries content signals a server-side
        failure, which is raised rather than rendered as agent output.

        Args:
            session_token: The token scoped to the session.
            messages: The new turns to send, usually a single user message.

        Yields:
            str: The next chunk of the agent's reply.

        Raises:
            APIError: If the request fails or the stream reports an error.
        """
        payload = {"messages": [m.model_dump() for m in messages]}
        try:
            response = self._session.post(
                self._url("/chatbot/chat/stream"),
                headers=self._auth(session_token),
                json=payload,
                stream=True,
                timeout=STREAM_TIMEOUT,
            )
        except requests.RequestException as exc:
            logger.exception("stream_request_failed", error=str(exc))
            raise APIError(f"Cannot reach the API at {self.base_url}. Is it running?") from exc

        with response:
            if not response.ok:
                raise APIError(_extract_error(response), status_code=response.status_code)

            for raw_line in response.iter_lines(decode_unicode=True):
                if not raw_line or not raw_line.startswith(_SSE_DATA_PREFIX):
                    continue
                try:
                    event = json.loads(raw_line[len(_SSE_DATA_PREFIX) :])
                except ValueError:
                    logger.warning("stream_chunk_undecodable")
                    continue

                content = event.get("content", "")
                if event.get("done"):
                    if content:
                        logger.error("stream_reported_error", error=content)
                        raise APIError(content)
                    return
                if content:
                    yield content
