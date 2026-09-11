"""Tests for JWT creation and verification."""

from datetime import (
    UTC,
    datetime,
    timedelta,
)

import pytest
from jose import jwt

from app.core.config import settings
from app.utils.auth import (
    create_access_token,
    verify_token,
)


class TestCreateAccessToken:
    def test_round_trips_the_thread_id(self) -> None:
        token = create_access_token("thread-123")

        assert verify_token(token.access_token) == "thread-123"

    def test_sets_expiry_from_settings_by_default(self) -> None:
        token = create_access_token("thread-123")

        expected = datetime.now(UTC) + timedelta(days=settings.JWT_ACCESS_TOKEN_EXPIRE_DAYS)
        assert abs((token.expires_at - expected).total_seconds()) < 5

    def test_honours_an_explicit_expiry_delta(self) -> None:
        token = create_access_token("thread-123", expires_delta=timedelta(minutes=5))

        expected = datetime.now(UTC) + timedelta(minutes=5)
        assert abs((token.expires_at - expected).total_seconds()) < 5

    def test_issues_a_distinct_jti_per_token(self) -> None:
        first = jwt.decode(
            create_access_token("t").access_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )
        second = jwt.decode(
            create_access_token("t").access_token,
            settings.JWT_SECRET_KEY,
            algorithms=[settings.JWT_ALGORITHM],
        )

        assert first["jti"] != second["jti"]


class TestVerifyToken:
    @pytest.mark.parametrize("bad", ["", None, 123])
    def test_rejects_non_string_input(self, bad: object) -> None:
        with pytest.raises(ValueError, match="non-empty string"):
            verify_token(bad)  # pyright: ignore[reportArgumentType]

    @pytest.mark.parametrize("bad", ["not-a-jwt", "only.two", "has four.parts.here.now", "a.b.c!"])
    def test_rejects_malformed_jwt_shapes(self, bad: str) -> None:
        with pytest.raises(ValueError, match="Token format is invalid"):
            verify_token(bad)

    def test_returns_none_for_a_token_signed_with_another_key(self) -> None:
        forged = jwt.encode(
            {"sub": "thread-123", "exp": datetime.now(UTC) + timedelta(days=1)},
            "a-completely-different-secret-key-value",
            algorithm=settings.JWT_ALGORITHM,
        )

        assert verify_token(forged) is None

    def test_returns_none_for_an_expired_token(self) -> None:
        expired = create_access_token("thread-123", expires_delta=timedelta(seconds=-30))

        assert verify_token(expired.access_token) is None

    def test_returns_none_when_the_subject_claim_is_missing(self) -> None:
        no_sub = jwt.encode(
            {"exp": datetime.now(UTC) + timedelta(days=1)},
            settings.JWT_SECRET_KEY,
            algorithm=settings.JWT_ALGORITHM,
        )

        assert verify_token(no_sub) is None

    def test_returns_none_when_the_payload_is_tampered_with(self) -> None:
        header, payload, signature = create_access_token("thread-123").access_token.split(".")
        tampered = f"{header}.{payload[:-2]}xy.{signature}"

        assert verify_token(tampered) is None
