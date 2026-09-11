"""Smoke test proving the harness boots the app without live infrastructure."""

from unittest.mock import AsyncMock

import pytest
from httpx import AsyncClient


@pytest.fixture(autouse=True)
def _stub_database_health(monkeypatch: pytest.MonkeyPatch) -> None:
    """Report a healthy database without connecting to one."""
    from app.services.database import database_service

    monkeypatch.setattr(database_service, "health_check", AsyncMock(return_value=True))


async def test_health_returns_200_when_database_is_reachable(client: AsyncClient) -> None:
    response = await client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "healthy"
    assert body["environment"] == "test"
    assert body["components"]["database"] == "healthy"


async def test_health_returns_503_when_database_is_unreachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services.database import database_service

    monkeypatch.setattr(database_service, "health_check", AsyncMock(return_value=False))

    response = await client.get("/health")

    assert response.status_code == 503
    body = response.json()
    assert body["status"] == "degraded"
    assert body["components"]["database"] == "unhealthy"
