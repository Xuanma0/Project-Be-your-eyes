from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from byes.middleware.rate_limit import RateLimitConfig, RateLimitMiddleware


def _build_app(config: RateLimitConfig) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RateLimitMiddleware, config=config)

    @app.post("/limited")
    async def limited() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/api/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_rate_limit_burst_then_429() -> None:
    app = _build_app(
        RateLimitConfig(
            enabled=True,
            requests_per_second=0.01,
            burst=2,
            key_mode="ip",
        )
    )
    with TestClient(app) as client:
        r1 = client.post("/limited")
        r2 = client.post("/limited")
        r3 = client.post("/limited")
    assert r1.status_code == 200, r1.text
    assert r2.status_code == 200, r2.text
    assert r3.status_code == 429, r3.text
    assert r3.json() == {"detail": "Too Many Requests"}


def test_rate_limit_key_mode_api_key_or_ip_isolated_by_key() -> None:
    app = _build_app(
        RateLimitConfig(
            enabled=True,
            requests_per_second=0.01,
            burst=1,
            key_mode="api_key_or_ip",
        )
    )
    with TestClient(app) as client:
        first_a = client.post("/limited", headers={"X-BYES-API-Key": "key-a"})
        first_b = client.post("/limited", headers={"X-BYES-API-Key": "key-b"})
        second_a = client.post("/limited", headers={"X-BYES-API-Key": "key-a"})
    assert first_a.status_code == 200, first_a.text
    assert first_b.status_code == 200, first_b.text
    assert second_a.status_code == 429, second_a.text


def test_rate_limit_skips_health_path() -> None:
    app = _build_app(
        RateLimitConfig(
            enabled=True,
            requests_per_second=0.01,
            burst=1,
            key_mode="ip",
        )
    )
    with TestClient(app) as client:
        first = client.get("/api/health")
        second = client.get("/api/health")
        third = client.get("/api/health")
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert third.status_code == 200, third.text
