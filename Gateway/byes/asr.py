from __future__ import annotations

import os
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def _now_ms() -> int:
    return int(time.time() * 1000)


@dataclass(slots=True)
class AsrTranscript:
    text: str
    backend: str
    model: str
    latency_ms: int
    language: str | None = None


class AsrBackend:
    def __init__(self) -> None:
        self.backend = str(os.getenv("BYES_ASR_BACKEND", "mock")).strip().lower() or "mock"
        self.model = str(os.getenv("BYES_ASR_MODEL", "mock-asr-v1")).strip() or "mock-asr-v1"
        self.mock_text = str(os.getenv("BYES_ASR_MOCK_TEXT", "read this")).strip() or "read this"

    def transcribe(self, *, audio_bytes: bytes, language: str | None = None) -> AsrTranscript:
        started = _now_ms()
        if self.backend == "mock":
            return AsrTranscript(
                text=self.mock_text,
                backend="mock",
                model=self.model,
                latency_ms=max(0, _now_ms() - started),
                language=language or "auto",
            )

        if self.backend == "faster_whisper":
            return self._transcribe_faster_whisper(audio_bytes=audio_bytes, language=language, started_ms=started)

        raise RuntimeError(f"unsupported_asr_backend:{self.backend}")

    def _transcribe_faster_whisper(
        self,
        *,
        audio_bytes: bytes,
        language: str | None,
        started_ms: int,
    ) -> AsrTranscript:
        try:
            from faster_whisper import WhisperModel  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(f"asr_dependency_missing:{exc.__class__.__name__}") from exc

        model_size = str(os.getenv("BYES_ASR_MODEL", "small")).strip() or "small"
        device = str(os.getenv("BYES_ASR_DEVICE", "cpu")).strip() or "cpu"
        compute_type = str(os.getenv("BYES_ASR_COMPUTE_TYPE", "int8")).strip() or "int8"

        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as fp:
            fp.write(bytes(audio_bytes or b""))
            temp_path = Path(fp.name)

        text = ""
        try:
            model = WhisperModel(model_size, device=device, compute_type=compute_type)
            segments, info = model.transcribe(str(temp_path), language=language if language else None)
            parts: list[str] = []
            for segment in segments:
                line = str(getattr(segment, "text", "")).strip()
                if line:
                    parts.append(line)
            text = " ".join(parts).strip()
            if not text:
                text = ""
            lang = str(getattr(info, "language", "") or "").strip() or (language or None)
            return AsrTranscript(
                text=text,
                backend="faster_whisper",
                model=model_size,
                latency_ms=max(0, _now_ms() - started_ms),
                language=lang,
            )
        finally:
            try:
                temp_path.unlink(missing_ok=True)
            except Exception:
                pass


def asr_capabilities() -> dict[str, Any]:
    backend = str(os.getenv("BYES_ASR_BACKEND", "mock")).strip().lower() or "mock"
    enabled = str(os.getenv("BYES_ENABLE_ASR", "0")).strip().lower() in {"1", "true", "yes", "on"}
    return {
        "enabled": bool(enabled),
        "backend": backend,
        "model": str(os.getenv("BYES_ASR_MODEL", "mock-asr-v1")).strip() or "mock-asr-v1",
    }
