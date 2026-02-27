from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from byes.middleware.request_size_limit import RequestSizeLimitMiddleware, RequestSizeLimits


def _build_app(limits: RequestSizeLimits) -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestSizeLimitMiddleware, limits=limits)

    @app.post("/api/frame")
    async def frame(request: Request) -> dict[str, int]:
        payload = await request.body()
        return {"bytes": len(payload)}

    @app.post("/api/run_package/upload")
    async def upload(request: Request) -> dict[str, int]:
        payload = await request.body()
        return {"bytes": len(payload)}

    @app.post("/api/plan")
    async def plan(request: Request) -> dict[str, int]:
        payload = await request.body()
        return {"bytes": len(payload)}

    @app.get("/api/health")
    async def health() -> dict[str, bool]:
        return {"ok": True}

    return app


def test_frame_route_rejects_when_payload_exceeds_limit() -> None:
    app = _build_app(RequestSizeLimits(frame_bytes=8, runpackage_zip_bytes=256, json_bytes=64))
    with TestClient(app) as client:
        ok = client.post("/api/frame", content=b"12345678", headers={"content-type": "application/octet-stream"})
        too_large = client.post(
            "/api/frame",
            content=b"123456789",
            headers={"content-type": "application/octet-stream"},
        )
    assert ok.status_code == 200, ok.text
    assert too_large.status_code == 413, too_large.text
    assert too_large.json() == {"detail": "Payload Too Large"}


def test_upload_route_rejects_when_payload_exceeds_limit() -> None:
    app = _build_app(RequestSizeLimits(frame_bytes=64, runpackage_zip_bytes=16, json_bytes=64))
    with TestClient(app) as client:
        response = client.post(
            "/api/run_package/upload",
            content=b"0123456789ABCDEFG",
            headers={"content-type": "application/octet-stream"},
        )
    assert response.status_code == 413, response.text
    assert response.json() == {"detail": "Payload Too Large"}


def test_json_route_rejects_large_body_and_get_is_unaffected() -> None:
    app = _build_app(RequestSizeLimits(frame_bytes=64, runpackage_zip_bytes=64, json_bytes=12))
    with TestClient(app) as client:
        ok_get = client.get("/api/health")
        too_large_json = client.post("/api/plan", json={"message": "this-body-is-too-large"})
    assert ok_get.status_code == 200, ok_get.text
    assert too_large_json.status_code == 413, too_large_json.text
    assert too_large_json.json() == {"detail": "Payload Too Large"}
