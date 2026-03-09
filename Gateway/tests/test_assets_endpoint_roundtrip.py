from __future__ import annotations

from fastapi.testclient import TestClient

from main import app, gateway


def test_assets_endpoint_roundtrip() -> None:
    with TestClient(app) as client:
        gateway.asset_cache.reset()
        cached = gateway.asset_cache.put(
            data=b"\x89PNG\r\n\x1a\nfake",
            content_type="image/png",
            meta={"kind": "unit"},
        )
        response = client.get(f"/api/assets/{cached.asset_id}")
        assert response.status_code == 200
        assert response.headers.get("content-type", "").startswith("image/png")
        assert response.content.startswith(b"\x89PNG")

        meta_resp = client.get(f"/api/assets/{cached.asset_id}/meta")
        assert meta_resp.status_code == 200
        meta = meta_resp.json()
        assert meta.get("assetId") == cached.asset_id
        assert int(meta.get("sizeBytes", 0)) > 0
        assert meta.get("meta", {}).get("kind") == "unit"


def test_assets_endpoint_404_for_missing_asset() -> None:
    with TestClient(app) as client:
        response = client.get("/api/assets/not_found")
        assert response.status_code == 404
