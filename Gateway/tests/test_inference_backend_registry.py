from __future__ import annotations

from byes.config import load_config
from byes.inference.backends.http import HttpOCRBackend, HttpRiskBackend, HttpSegBackend
from byes.inference.backends.mock import MockOCRBackend, MockRiskBackend, MockSegBackend
from byes.inference.registry import get_ocr_backend, get_risk_backend, get_seg_backend


def test_backend_registry_defaults_to_mock(monkeypatch) -> None:
    monkeypatch.delenv("BYES_OCR_BACKEND", raising=False)
    monkeypatch.delenv("BYES_RISK_BACKEND", raising=False)
    monkeypatch.delenv("BYES_SEG_BACKEND", raising=False)
    config = load_config()

    ocr_backend = get_ocr_backend(config)
    risk_backend = get_risk_backend(config)
    seg_backend = get_seg_backend(config)

    assert isinstance(ocr_backend, MockOCRBackend)
    assert isinstance(risk_backend, MockRiskBackend)
    assert isinstance(seg_backend, MockSegBackend)


def test_backend_registry_selects_http(monkeypatch) -> None:
    monkeypatch.setenv("BYES_OCR_BACKEND", "http")
    monkeypatch.setenv("BYES_OCR_HTTP_URL", "http://127.0.0.1:9001/ocr")
    monkeypatch.setenv("BYES_OCR_HTTP_TIMEOUT_MS", "2222")
    monkeypatch.setenv("BYES_RISK_BACKEND", "http")
    monkeypatch.setenv("BYES_RISK_HTTP_URL", "http://127.0.0.1:9002/risk")
    monkeypatch.setenv("BYES_RISK_HTTP_TIMEOUT_MS", "3333")
    monkeypatch.setenv("BYES_OCR_MODEL_ID", "ocr-v1")
    monkeypatch.setenv("BYES_RISK_MODEL_ID", "risk-v1")
    monkeypatch.setenv("BYES_SEG_BACKEND", "http")
    monkeypatch.setenv("BYES_SEG_HTTP_URL", "http://127.0.0.1:9003/seg")
    monkeypatch.setenv("BYES_SEG_HTTP_TIMEOUT_MS", "4444")
    monkeypatch.setenv("BYES_SEG_MODEL_ID", "seg-v1")
    config = load_config()

    ocr_backend = get_ocr_backend(config)
    risk_backend = get_risk_backend(config)
    seg_backend = get_seg_backend(config)

    assert isinstance(ocr_backend, HttpOCRBackend)
    assert isinstance(risk_backend, HttpRiskBackend)
    assert isinstance(seg_backend, HttpSegBackend)
    assert ocr_backend.url == "http://127.0.0.1:9001/ocr"
    assert ocr_backend.timeout_ms == 2222
    assert ocr_backend.endpoint == "http://127.0.0.1:9001/ocr"
    assert ocr_backend.model_id == "ocr-v1"
    assert risk_backend.url == "http://127.0.0.1:9002/risk"
    assert risk_backend.timeout_ms == 3333
    assert risk_backend.endpoint == "http://127.0.0.1:9002/risk"
    assert risk_backend.model_id == "risk-v1"
    assert seg_backend.url == "http://127.0.0.1:9003/seg"
    assert seg_backend.timeout_ms == 4444
    assert seg_backend.endpoint == "http://127.0.0.1:9003/seg"
    assert seg_backend.model_id == "seg-v1"


def test_seg_targets_config_parsing(monkeypatch) -> None:
    monkeypatch.setenv("BYES_SEG_TARGETS_JSON", '["person", "car"]')
    monkeypatch.setenv("BYES_SEG_TARGETS", "stairs,person")
    config = load_config()
    assert config.inference_seg_targets == ("person", "car", "stairs")


def test_seg_prompt_config_json_precedence(monkeypatch) -> None:
    monkeypatch.setenv("BYES_SEG_PROMPT_TEXT", "find stairs")
    monkeypatch.setenv("BYES_SEG_PROMPT_JSON", '{"text":"find person","targets":["person"],"meta":{"promptVersion":"v1"}}')
    config = load_config()
    assert isinstance(config.inference_seg_prompt, dict)
    assert config.inference_seg_prompt.get("text") == "find person"
    assert config.inference_seg_prompt.get("meta", {}).get("promptVersion") == "v1"


def test_seg_prompt_config_field_env_parsing(monkeypatch) -> None:
    monkeypatch.delenv("BYES_SEG_PROMPT_JSON", raising=False)
    monkeypatch.setenv("BYES_SEG_PROMPT_TEXT", "find stairs and handrail")
    monkeypatch.setenv("BYES_SEG_PROMPT_TARGETS", "person,stairs")
    monkeypatch.setenv("BYES_SEG_PROMPT_BOXES_JSON", "[[0,0,10,10]]")
    monkeypatch.setenv("BYES_SEG_PROMPT_POINTS_JSON", '[{"x":8,"y":8,"label":1}]')
    monkeypatch.setenv("BYES_SEG_PROMPT_VERSION", "v1")
    config = load_config()
    assert isinstance(config.inference_seg_prompt, dict)
    assert config.inference_seg_prompt.get("text") == "find stairs and handrail"
    assert config.inference_seg_prompt.get("targets") == ["person", "stairs"]
    assert config.inference_seg_prompt.get("boxes") == [[0.0, 0.0, 10.0, 10.0]]
    assert config.inference_seg_prompt.get("points") == [{"x": 8.0, "y": 8.0, "label": 1}]
    assert config.inference_seg_prompt.get("meta", {}).get("promptVersion") == "v1"
