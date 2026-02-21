from __future__ import annotations

from threading import Lock
from typing import Optional, Tuple

import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

DEFAULT_MODEL_NAME = "Qwen/Qwen3-TTS-12Hz-1.7B-CustomVoice"


class QwenTTSService:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        preferred_device: str = "cuda:0",
        enable_cpu_fallback: bool = True,
    ):
        self.model_name = model_name
        self.preferred_device = preferred_device
        self.enable_cpu_fallback = enable_cpu_fallback
        self._model: Optional[Qwen3TTSModel] = None
        self._is_cpu_model = False
        self._lock = Lock()

    def _load_model(self) -> None:
        if self._model is not None:
            return

        prefer_gpu = self.preferred_device.startswith("cuda") and torch.cuda.is_available()
        if prefer_gpu:
            try:
                self._model = Qwen3TTSModel.from_pretrained(
                    self.model_name,
                    device_map=self.preferred_device,
                    dtype=torch.bfloat16,
                    attn_implementation="flash_attention_2",
                )
                self._is_cpu_model = False
                return
            except Exception:
                if not self.enable_cpu_fallback:
                    raise

        self._model = Qwen3TTSModel.from_pretrained(
            self.model_name,
            device_map="cpu",
            dtype=torch.float32,
        )
        self._is_cpu_model = True

    def _ensure_model(self) -> None:
        if self._model is None:
            with self._lock:
                self._load_model()

    def synthesize(
        self,
        text: str,
        speaker: str,
        language: str = "Auto",
        instruct: str = "",
    ) -> Tuple[np.ndarray, int]:
        self._ensure_model()
        if self._model is None:
            raise RuntimeError("TTS model was not initialized.")

        try:
            wavs, sr = self._model.generate_custom_voice(
                text=text,
                language=language,
                speaker=speaker,
                instruct=instruct,
            )
        except RuntimeError as exc:
            is_cuda_runtime_error = "cuda" in str(exc).lower() or "cublas" in str(exc).lower()
            if not (self.enable_cpu_fallback and not self._is_cpu_model and is_cuda_runtime_error):
                raise

            with self._lock:
                self._model = Qwen3TTSModel.from_pretrained(
                    self.model_name,
                    device_map="cpu",
                    dtype=torch.float32,
                )
                self._is_cpu_model = True

            wavs, sr = self._model.generate_custom_voice(
                text=text,
                language=language,
                speaker=speaker,
                instruct=instruct,
            )

        return wavs[0], sr

    def synthesize_to_file(
        self,
        output_path: str,
        text: str,
        speaker: str,
        language: str = "Auto",
        instruct: str = "",
    ) -> str:
        wav, sr = self.synthesize(text=text, speaker=speaker, language=language, instruct=instruct)
        sf.write(output_path, wav, sr)
        return output_path


_default_service: Optional[QwenTTSService] = None
_default_service_lock = Lock()


def get_tts_service(
    model_name: str = DEFAULT_MODEL_NAME,
    preferred_device: str = "cuda:0",
    enable_cpu_fallback: bool = True,
) -> QwenTTSService:
    global _default_service

    if _default_service is None:
        with _default_service_lock:
            if _default_service is None:
                _default_service = QwenTTSService(
                    model_name=model_name,
                    preferred_device=preferred_device,
                    enable_cpu_fallback=enable_cpu_fallback,
                )
    return _default_service


def synthesize_speech(
    text: str,
    speaker: str,
    language: str = "Auto",
    instruct: str = "",
) -> Tuple[np.ndarray, int]:
    service = get_tts_service()
    return service.synthesize(text=text, speaker=speaker, language=language, instruct=instruct)