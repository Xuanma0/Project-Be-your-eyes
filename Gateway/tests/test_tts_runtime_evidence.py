from __future__ import annotations

from fastapi.testclient import TestClient

from main import app, gateway


def test_frame_ack_tts_updates_runtime_evidence() -> None:
    original_tts = dict(gateway._provider_runtime_evidence.get("tts", {}))  # noqa: SLF001
    try:
        with TestClient(app) as client:
            ack_resp = client.post(
                "/api/frame/ack",
                json={
                    "runId": "quest3-smoke",
                    "frameSeq": 42,
                    "feedbackTsMs": 123456789,
                    "kind": "tts",
                    "accepted": True,
                    "providerBackend": "android_tts",
                    "providerModel": "quest-tts",
                    "providerDevice": "quest",
                    "providerReason": "client_tts",
                    "providerIsMock": False,
                },
            )
            assert ack_resp.status_code == 200

            providers_resp = client.get("/api/providers")
            assert providers_resp.status_code == 200
            providers_payload = providers_resp.json()
            runtime = providers_payload.get("runtimeEvidence", {})
            tts_runtime = runtime.get("tts", {})
            assert tts_runtime.get("backend") == "android_tts"
            assert tts_runtime.get("model") == "quest-tts"
            assert tts_runtime.get("isMock") is False

            ui_resp = client.get("/api/ui/state")
            assert ui_resp.status_code == 200
            ui_payload = ui_resp.json()
            tts_row = (
                ui_payload.get("capabilities", {})
                .get("available_providers", {})
                .get("tts", {})
            )
            assert tts_row.get("backend") == "android_tts"
            runtime_row = tts_row.get("runtime", {})
            assert runtime_row.get("backend") == "android_tts"
            assert runtime_row.get("isMock") is False
    finally:
        gateway._provider_runtime_evidence["tts"] = original_tts  # noqa: SLF001
