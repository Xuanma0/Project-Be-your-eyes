from __future__ import annotations

import base64
import ctypes
import os
import site
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, Tuple

from .config import settings


class AudioTranscriber:
    def __init__(self) -> None:
        self._model = None
        self._lock = threading.Lock()
        self._force_cpu = False
        self._active_device = ""
        self._active_compute_type = ""
        self._last_error = ""
        self._cuda_runtime_checked = False
        self._cuda_runtime_available = False
        self._cuda_runtime_message = ""
        self._dll_dir_handles = []
        self._dll_dirs_added = False

    def status(self) -> Dict[str, Any]:
        return {
            "model": settings.asr_model,
            "loaded": self._model is not None,
            "device": self._resolve_device(),
            "compute_type": self._resolve_compute_type(),
            "active_device": self._active_device,
            "active_compute_type": self._active_compute_type,
            "cuda_runtime_available": self._asr_cuda_runtime_available(),
            "cuda_runtime_message": self._cuda_runtime_message,
            "last_error": self._last_error,
        }

    def transcribe_data_url(self, audio_data: str) -> Dict[str, Any]:
        started = time.time()
        raw, suffix = self._decode_audio_data(audio_data)
        if not raw:
            raise ValueError("audio_data is empty")

        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
                fh.write(raw)
                tmp_path = Path(fh.name)

            try:
                model = self._get_model()
                segments, info = self._transcribe_file(model, tmp_path)
            except Exception as exc:
                if not self._should_cpu_fallback(exc):
                    raise
                self._last_error = repr(exc)[:300]
                with self._lock:
                    self._force_cpu = True
                    self._model = None
                segments, info = self._transcribe_file(self._get_model(), tmp_path)
            text = "".join(segment.text.strip() for segment in segments).strip()
            return {
                "text": text,
                "language": getattr(info, "language", "zh"),
                "language_probability": round(float(getattr(info, "language_probability", 0.0)), 4),
                "latency_ms": round((time.time() - started) * 1000, 1),
                "model": settings.asr_model,
            }
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _decode_audio_data(self, audio_data: str) -> Tuple[bytes, str]:
        header = ""
        payload = audio_data
        if "," in audio_data:
            header, payload = audio_data.split(",", 1)

        suffix = ".webm"
        if "audio/wav" in header:
            suffix = ".wav"
        elif "audio/mp4" in header or "audio/m4a" in header:
            suffix = ".m4a"
        elif "audio/ogg" in header:
            suffix = ".ogg"

        return base64.b64decode(payload), suffix

    def _get_model(self) -> Any:
        if self._model is None:
            with self._lock:
                if self._model is None:
                    from faster_whisper import WhisperModel

                    self._add_cuda_dll_dirs()
                    device = self._resolve_device()
                    compute_type = self._resolve_compute_type()
                    try:
                        self._model = WhisperModel(
                            settings.asr_model,
                            device=device,
                            compute_type=compute_type,
                        )
                        self._active_device = device
                        self._active_compute_type = compute_type
                    except Exception as exc:
                        if not self._should_cpu_fallback(exc, attempted_device=device):
                            raise
                        self._last_error = repr(exc)[:300]
                        self._force_cpu = True
                        self._model = WhisperModel(
                            settings.asr_model,
                            device="cpu",
                            compute_type="int8",
                        )
                        self._active_device = "cpu"
                        self._active_compute_type = "int8"
        return self._model

    def _transcribe_file(self, model: Any, path: Path) -> Any:
        return model.transcribe(
            str(path),
            language="zh",
            vad_filter=True,
            beam_size=1,
            temperature=0.0,
        )

    def _resolve_device(self) -> str:
        if self._force_cpu:
            return "cpu"
        if settings.asr_device != "auto":
            return settings.asr_device
        try:
            import torch

            if torch.cuda.is_available():
                return "cuda" if self._asr_cuda_runtime_available() else "cpu"
        except Exception:
            pass
        return "cpu"

    def _resolve_compute_type(self) -> str:
        if settings.asr_compute_type != "auto":
            return settings.asr_compute_type
        return "float16" if self._resolve_device() == "cuda" else "int8"

    def _asr_cuda_runtime_available(self) -> bool:
        if self._cuda_runtime_checked:
            return self._cuda_runtime_available
        self._add_cuda_dll_dirs()
        self._cuda_runtime_checked = True
        self._cuda_runtime_available = True
        self._cuda_runtime_message = ""
        if os.name == "nt":
            try:
                ctypes.WinDLL("cublas64_12.dll")
            except Exception:
                self._cuda_runtime_available = False
                self._cuda_runtime_message = "cublas64_12.dll is not available; ASR will use CPU int8."
        return self._cuda_runtime_available

    def _should_cpu_fallback(self, exc: Exception, attempted_device: str | None = None) -> bool:
        if settings.asr_device == "cpu":
            return False
        device = attempted_device or self._resolve_device()
        if device != "cuda":
            return False
        message = repr(exc).lower()
        cuda_error_tokens = (
            "cublas",
            "cudnn",
            "cuda",
            "ctranslate2",
            "library",
            "dll",
        )
        return settings.asr_device == "auto" or any(token in message for token in cuda_error_tokens)

    def _add_cuda_dll_dirs(self) -> None:
        if self._dll_dirs_added or os.name != "nt" or not hasattr(os, "add_dll_directory"):
            return
        self._dll_dirs_added = True
        candidates = []
        for base in site.getsitepackages():
            root = Path(base) / "nvidia"
            candidates.extend(
                [
                    root / "cublas" / "bin",
                    root / "cuda_runtime" / "bin",
                    root / "cudnn" / "bin",
                ]
            )
        for path in candidates:
            if path.exists():
                try:
                    self._dll_dir_handles.append(os.add_dll_directory(str(path)))
                except Exception:
                    pass
