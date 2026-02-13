from __future__ import annotations

from services.inference_service.providers.utils import postprocess_text


def test_postprocess_text_normalizes_whitespace_and_uppercase(monkeypatch) -> None:
    monkeypatch.setenv("BYES_OCR_UPPERCASE", "1")
    assert postprocess_text("  exit \n door\t ") == "EXIT DOOR"


def test_postprocess_text_preserves_case_when_disabled(monkeypatch) -> None:
    monkeypatch.setenv("BYES_OCR_UPPERCASE", "0")
    assert postprocess_text("  Exit  Door ") == "Exit Door"
