from __future__ import annotations

from typing import Any, Dict, Tuple

import requests

from .config import settings


class VoiceSidecarClient:
    def __init__(self) -> None:
        self.base_url = settings.voice_sidecar_url
        self.timeout = settings.voice_sidecar_timeout

    def status(self) -> Dict[str, Any]:
        try:
            res = requests.get(f"{self.base_url}/status", timeout=1.5)
            res.raise_for_status()
            data = res.json()
            data["available"] = True
            data["url"] = self.base_url
            return data
        except Exception as exc:
            return {
                "available": False,
                "url": self.base_url,
                "error": repr(exc)[:300],
            }

    def tts(self, text: str, rate: float = 1.0) -> Tuple[bytes, str, str]:
        payload = {"text": text, "rate": rate}
        res = requests.post(f"{self.base_url}/tts", json=payload, timeout=self.timeout)
        res.raise_for_status()
        media_type = res.headers.get("content-type", "audio/wav").split(";")[0]
        engine = res.headers.get("x-tts-engine", "voice_sidecar")
        return res.content, media_type, engine

    def transcribe_data_url(self, audio_data: str) -> Dict[str, Any]:
        res = requests.post(
            f"{self.base_url}/asr",
            json={"audio_data": audio_data, "language": "Chinese"},
            timeout=self.timeout,
        )
        res.raise_for_status()
        return res.json()

    def warmup_asr(self) -> Dict[str, Any]:
        res = requests.post(f"{self.base_url}/warmup/asr", timeout=self.timeout)
        res.raise_for_status()
        return res.json()
