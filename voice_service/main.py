from __future__ import annotations

import base64
import audioop
import importlib.util
import os
import subprocess
import sys
import tempfile
import threading
import time
import wave
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel


ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_INDEXTTS_DIR = ROOT_DIR / "models" / "IndexTTS-2"
DEFAULT_QWEN_ASR_DIR = ROOT_DIR / "models" / "Qwen3-ASR-0.6B"
DEFAULT_PROMPT_WAV = ROOT_DIR / "data" / "voice" / "reference.wav"


class TTSRequest(BaseModel):
    text: str = ""
    rate: float = 1.0
    engine: str = "auto"


class ASRRequest(BaseModel):
    audio_data: str = ""
    language: Optional[str] = "Chinese"


app = FastAPI(title="Be Your Eyes Voice Sidecar")


def _env_path(name: str, default: Path) -> Path:
    value = os.getenv(name, "").strip()
    return Path(value) if value else default


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False


def _safe_import_error(module: str) -> str:
    try:
        __import__(module)
        return ""
    except Exception as exc:
        return repr(exc)[:300]


def _decode_audio_data(audio_data: str) -> Tuple[bytes, str]:
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


def _torch_status() -> Dict[str, Any]:
    if not _module_available("torch"):
        return {"available": False, "cuda": False, "error": "torch is not installed"}
    if os.getenv("BYE_VOICE_STATUS_IMPORT_TORCH", "0").strip() != "1":
        return {
            "available": True,
            "cuda": None,
            "detail": "set BYE_VOICE_STATUS_IMPORT_TORCH=1 for CUDA details",
        }
    try:
        import torch

        return {
            "available": True,
            "version": getattr(torch, "__version__", ""),
            "cuda": bool(torch.cuda.is_available()),
            "device": torch.cuda.get_device_name(0) if torch.cuda.is_available() else "cpu",
        }
    except Exception as exc:
        return {"available": False, "cuda": False, "error": repr(exc)[:300]}


class VoiceRuntime:
    def __init__(self) -> None:
        self.indextts_model_dir = _env_path("BYE_INDEXTTS_MODEL_DIR", DEFAULT_INDEXTTS_DIR)
        self.qwen_asr_model_dir = _env_path("BYE_QWEN_ASR_MODEL_DIR", DEFAULT_QWEN_ASR_DIR)
        self.prompt_wav = _env_path("BYE_TTS_PROMPT_WAV", DEFAULT_PROMPT_WAV)
        self._index_tts = None
        self._qwen_asr = None
        self._pyttsx3 = None
        self._tts_lock = threading.Lock()
        self._asr_lock = threading.Lock()
        self._last_tts_error = ""
        self._last_asr_error = ""

    def status(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "engines": {
                "pyttsx3": {
                    "available": _module_available("pyttsx3"),
                    "loaded": self._pyttsx3 is not None,
                    "error": _safe_import_error("pyttsx3") if not _module_available("pyttsx3") else "",
                },
                "windows_sapi": {
                    "available": os.name == "nt",
                    "loaded": False,
                    "error": "" if os.name == "nt" else "Windows SAPI is only available on Windows",
                },
                "indextts2": {
                    "available": _module_available("indextts"),
                    "loaded": self._index_tts is not None,
                    "model_dir": str(self.indextts_model_dir),
                    "model_exists": self.indextts_model_dir.exists(),
                    "prompt_wav": str(self.prompt_wav),
                    "prompt_exists": self.prompt_wav.exists(),
                    "last_error": self._last_tts_error,
                },
                "qwen3_asr": {
                    "available": _module_available("qwen_asr"),
                    "loaded": self._qwen_asr is not None,
                    "model_dir": str(self.qwen_asr_model_dir),
                    "model_exists": self.qwen_asr_model_dir.exists(),
                    "last_error": self._last_asr_error,
                },
            },
            "torch": _torch_status(),
        }

    def synthesize(self, text: str, rate: float, engine: str = "auto") -> Tuple[bytes, str, str]:
        text = text.strip()
        if not text:
            raise ValueError("text is required")
        rate = max(0.5, min(2.0, float(rate or 1.0)))
        preferred = (engine or "auto").strip().lower()

        if preferred in ("auto", "indextts", "indextts2") and self._can_use_indextts():
            try:
                return self._synthesize_indextts(text, rate)
            except Exception as exc:
                self._last_tts_error = repr(exc)[:300]
                if preferred in ("indextts", "indextts2"):
                    raise

        if preferred in ("auto", "sapi", "windows_sapi") and os.name == "nt":
            try:
                return self._synthesize_windows_sapi(text, rate)
            except Exception as exc:
                self._last_tts_error = repr(exc)[:300]
                if preferred in ("sapi", "windows_sapi"):
                    raise

        return self._synthesize_pyttsx3(text, rate)

    def transcribe(self, audio_data: str, language: Optional[str]) -> Dict[str, Any]:
        raw, suffix = _decode_audio_data(audio_data)
        if not raw:
            raise ValueError("audio_data is empty")
        if not _module_available("qwen_asr"):
            raise RuntimeError("qwen-asr runtime is not installed in the voice sidecar environment")

        started = time.time()
        tmp_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as fh:
                fh.write(raw)
                tmp_path = Path(fh.name)
            model = self._get_qwen_asr()
            results = model.transcribe(audio=str(tmp_path), language=language or "Chinese")
            first = results[0] if isinstance(results, list) else results
            return {
                "text": str(getattr(first, "text", "")).strip(),
                "language": str(getattr(first, "language", language or "Chinese")),
                "language_probability": 1.0,
                "latency_ms": round((time.time() - started) * 1000, 1),
                "model": "Qwen3-ASR-0.6B",
            }
        finally:
            if tmp_path is not None:
                try:
                    tmp_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def warmup_asr(self) -> Dict[str, Any]:
        if not _module_available("qwen_asr"):
            raise RuntimeError("qwen-asr runtime is not installed in the voice sidecar environment")
        started = time.time()
        self._get_qwen_asr()
        return {
            "ok": True,
            "engine": "qwen3_asr",
            "loaded": self._qwen_asr is not None,
            "latency_ms": round((time.time() - started) * 1000, 1),
        }

    def _can_use_indextts(self) -> bool:
        return (
            _module_available("indextts")
            and self.indextts_model_dir.exists()
            and (self.indextts_model_dir / "config.yaml").exists()
            and self.prompt_wav.exists()
        )

    def _synthesize_indextts(self, text: str, rate: float) -> Tuple[bytes, str, str]:
        model = self._get_indextts()
        out_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as fh:
                out_path = Path(fh.name)
            out_path.unlink(missing_ok=True)

            with self._tts_lock:
                model.infer(
                    spk_audio_prompt=str(self.prompt_wav),
                    text=text,
                    output_path=str(out_path),
                    verbose=False,
                )

            audio = self._apply_wav_rate(out_path.read_bytes(), rate)
            return audio, "audio/wav", "indextts2"
        finally:
            if out_path is not None:
                try:
                    out_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _get_indextts(self) -> Any:
        if self._index_tts is None:
            with self._tts_lock:
                if self._index_tts is None:
                    from indextts.infer_v2 import IndexTTS2

                    use_fp16 = _torch_status().get("cuda", False)
                    self._index_tts = IndexTTS2(
                        cfg_path=str(self.indextts_model_dir / "config.yaml"),
                        model_dir=str(self.indextts_model_dir),
                        use_fp16=use_fp16,
                        use_cuda_kernel=False,
                        use_deepspeed=False,
                    )
        return self._index_tts

    def _synthesize_windows_sapi(self, text: str, rate: float) -> Tuple[bytes, str, str]:
        text_path = None
        out_path = None
        script_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as fh:
                fh.write(text)
                text_path = Path(fh.name)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as fh:
                out_path = Path(fh.name)
            out_path.unlink(missing_ok=True)
            sapi_rate = int(max(-10, min(10, round((float(rate) - 1.0) * 8))))
            script = f"""
Add-Type -AssemblyName System.Speech
$text = Get-Content -LiteralPath '{str(text_path).replace("'", "''")}' -Raw -Encoding UTF8
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$s.Rate = {sapi_rate}
$s.Volume = 100
$s.SetOutputToWaveFile('{str(out_path).replace("'", "''")}')
$s.Speak($text)
$s.Dispose()
"""
            with tempfile.NamedTemporaryFile(delete=False, suffix=".ps1", mode="w", encoding="utf-8") as fh:
                fh.write(script)
                script_path = Path(fh.name)
            completed = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script_path)],
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                timeout=35,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(f"Windows SAPI failed: {message}")
            deadline = time.time() + 10
            while out_path.stat().st_size == 0 and time.time() < deadline:
                time.sleep(0.05)
            audio = out_path.read_bytes()
            if not audio:
                raise RuntimeError("Windows SAPI generated an empty audio file")
            self._assert_wav_has_samples(out_path)
            return audio, "audio/wav", "windows_sapi"
        finally:
            for path in (text_path, out_path, script_path):
                if path is not None:
                    try:
                        path.unlink(missing_ok=True)
                    except Exception:
                        pass

    def _synthesize_pyttsx3(self, text: str, rate: float) -> Tuple[bytes, str, str]:
        if not _module_available("pyttsx3"):
            raise RuntimeError("pyttsx3 is not installed and IndexTTS2 is not ready")

        text_path = None
        out_path = None
        try:
            with tempfile.NamedTemporaryFile(delete=False, suffix=".txt", mode="w", encoding="utf-8") as fh:
                fh.write(text)
                text_path = Path(fh.name)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as fh:
                out_path = Path(fh.name)

            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "voice_service.pyttsx3_worker",
                    str(text_path),
                    str(out_path),
                    str(rate),
                ],
                cwd=str(ROOT_DIR),
                capture_output=True,
                text=True,
                timeout=35,
            )
            if completed.returncode != 0:
                message = (completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(f"pyttsx3 worker failed: {message}")

            deadline = time.time() + 10
            while out_path.stat().st_size == 0 and time.time() < deadline:
                time.sleep(0.05)
            audio = out_path.read_bytes()
            if not audio:
                raise RuntimeError("pyttsx3 generated an empty audio file")
            self._assert_wav_has_samples(out_path)
            audio = self._apply_wav_rate(audio, rate, pyttsx3_already_applied=True)
            return audio, "audio/wav", "pyttsx3"
        finally:
            if text_path is not None:
                try:
                    text_path.unlink(missing_ok=True)
                except Exception:
                    pass
            if out_path is not None:
                try:
                    out_path.unlink(missing_ok=True)
                except Exception:
                    pass

    def _get_pyttsx3(self) -> Any:
        if self._pyttsx3 is None:
            import pyttsx3

            self._pyttsx3 = pyttsx3.init()
            self._select_chinese_voice(self._pyttsx3)
        return self._pyttsx3

    def _select_chinese_voice(self, engine: Any) -> None:
        try:
            voices = engine.getProperty("voices") or []
            for voice in voices:
                marker = f"{voice.id} {getattr(voice, 'name', '')} {getattr(voice, 'languages', '')}".lower()
                if "zh" in marker or "chinese" in marker or "huihui" in marker or "xiaoxiao" in marker:
                    engine.setProperty("voice", voice.id)
                    return
        except Exception:
            pass

    def _assert_wav_has_samples(self, path: Path) -> None:
        try:
            import soundfile as sf

            info = sf.info(str(path))
            if int(getattr(info, "frames", 0)) <= 0:
                raise RuntimeError("pyttsx3 generated a WAV file with zero audio samples")
        except RuntimeError:
            raise
        except Exception:
            pass

    def _apply_wav_rate(self, audio: bytes, rate: float, pyttsx3_already_applied: bool = False) -> bytes:
        if pyttsx3_already_applied or abs(float(rate or 1.0) - 1.0) < 0.03:
            return audio
        try:
            with wave.open(BytesIO(audio), "rb") as reader:
                params = reader.getparams()
                frames = reader.readframes(params.nframes)
            speed = max(0.5, min(2.0, float(rate)))
            target_rate = max(4000, int(params.framerate / speed))
            converted, _state = audioop.ratecv(
                frames,
                params.sampwidth,
                params.nchannels,
                params.framerate,
                target_rate,
                None,
            )
            out = BytesIO()
            with wave.open(out, "wb") as writer:
                writer.setnchannels(params.nchannels)
                writer.setsampwidth(params.sampwidth)
                writer.setframerate(params.framerate)
                writer.writeframes(converted)
            return out.getvalue()
        except Exception:
            return audio

    def _get_qwen_asr(self) -> Any:
        if self._qwen_asr is None:
            with self._asr_lock:
                if self._qwen_asr is None:
                    from qwen_asr import Qwen3ASRModel
                    import torch

                    cuda = bool(torch.cuda.is_available())
                    self._qwen_asr = Qwen3ASRModel.from_pretrained(
                        str(self.qwen_asr_model_dir),
                        dtype=torch.float16 if cuda else torch.float32,
                        device_map="cuda:0" if cuda else "cpu",
                        max_inference_batch_size=1,
                        max_new_tokens=256,
                    )
        return self._qwen_asr


runtime = VoiceRuntime()


@app.get("/status")
def status() -> Dict[str, Any]:
    return runtime.status()


@app.post("/tts")
def tts(req: TTSRequest) -> Response:
    try:
        audio, media_type, engine = runtime.synthesize(req.text, req.rate, req.engine)
        return Response(
            content=audio,
            media_type=media_type,
            headers={"X-TTS-Engine": engine, "X-TTS-Rate-Applied": "1"},
        )
    except Exception as exc:
        raise HTTPException(status_code=503, detail=repr(exc)) from exc


@app.post("/asr")
def asr(req: ASRRequest) -> Dict[str, Any]:
    try:
        return runtime.transcribe(req.audio_data, req.language)
    except Exception as exc:
        raise HTTPException(status_code=503, detail=repr(exc)) from exc


@app.post("/warmup/asr")
def warmup_asr() -> Dict[str, Any]:
    try:
        return runtime.warmup_asr()
    except Exception as exc:
        raise HTTPException(status_code=503, detail=repr(exc)) from exc
