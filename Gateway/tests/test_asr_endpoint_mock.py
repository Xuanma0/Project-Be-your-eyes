from __future__ import annotations

from fastapi.testclient import TestClient

from byes.asr import AsrBackend
from main import app, gateway


def test_asr_endpoint_mock_enabled(monkeypatch) -> None:
    monkeypatch.setenv("BYES_ENABLE_ASR", "1")
    monkeypatch.setenv("BYES_ASR_BACKEND", "mock")
    monkeypatch.setenv("BYES_ASR_MOCK_TEXT", "read this now")
    gateway.asr_backend = AsrBackend()
    gateway.drain_inference_events()

    with TestClient(app) as client:
        response = client.post(
            "/api/asr",
            files={"audio": ("voice.wav", b"RIFFfake_wav_payload", "audio/wav")},
            data={"deviceId": "quest", "runId": "asr-run", "frameSeq": 7},
        )
        assert response.status_code == 200
        payload = response.json()
        assert payload.get("text") == "read this now"
        assert payload.get("backend") == "mock"
        assert payload.get("frameSeq") == 7

    names = [str(row.get("name", "")).strip() for row in gateway.drain_inference_events()]
    assert "asr.transcript.v1" in names


def test_asr_endpoint_disabled(monkeypatch) -> None:
    monkeypatch.delenv("BYES_ENABLE_ASR", raising=False)
    gateway.asr_backend = AsrBackend()
    with TestClient(app) as client:
        response = client.post("/api/asr", files={"audio": ("voice.wav", b"RIFFx", "audio/wav")})
        assert response.status_code == 503
