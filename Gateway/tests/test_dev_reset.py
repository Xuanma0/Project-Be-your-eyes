from __future__ import annotations

from fastapi.testclient import TestClient

from main import app, gateway


def test_dev_reset_clears_runtime_state() -> None:
    with TestClient(app) as client:
        fault_resp = client.post("/api/fault/set", json={"tool": "mock_risk", "mode": "timeout", "value": True})
        assert fault_resp.status_code == 200

        gateway.degradation.record_timeout("mock_risk")
        gateway.frame_tracker.start_frame(seq=12345, received_at_ms=1, ttl_ms=1000)
        assert gateway.degradation.state.value in {"DEGRADED", "SAFE_MODE"}
        assert gateway.frame_tracker.record_count > 0

        reset_resp = client.post("/api/dev/reset")
        assert reset_resp.status_code == 200
        payload = reset_resp.json()
        assert payload["ok"] is True
        assert payload["state"] == "NORMAL"
        assert payload["frameTrackerRecords"] == 0
        assert payload["faults"] == []

        health_resp = client.get("/api/health")
        assert health_resp.status_code == 200
        health_payload = health_resp.json()
        assert health_payload["state"] == "NORMAL"
        assert health_payload["faults"] == []
