# Voice Sidecar Setup

This project keeps TTS/ASR in a separate sidecar process so heavy voice
dependencies do not slow the live camera and vision loop.

## 1. Install the lightweight sidecar

```powershell
cd D:\Be-your-eyes
.\scripts\setup_voice_sidecar.ps1
```

This enables local Windows SAPI TTS through `pyttsx3`. The frontend speed
slider also applies `audio.playbackRate`, so speed changes take effect during
playback.

## 2. Start the sidecar

```powershell
cd D:\Be-your-eyes
.\scripts\run_voice_sidecar.ps1
```

The main app calls `http://127.0.0.1:8010`.

## 3. Optional: Qwen3-ASR runtime

Qwen3-ASR officially recommends a fresh Python 3.12 environment.

```powershell
cd D:\Be-your-eyes
.\scripts\setup_voice_sidecar.ps1 -InstallQwenAsr -Recreate
```

Weights should stay in:

```text
D:\Be-your-eyes\models\Qwen3-ASR-0.6B
```

## 4. Optional: IndexTTS2 runtime

Weights should stay in:

```text
D:\Be-your-eyes\models\IndexTTS-2
```

IndexTTS2 also needs a reference voice:

```text
D:\Be-your-eyes\data\voice\reference.wav
```

Use a clean 3-10 second Chinese WAV clip. After the official IndexTTS2 runtime
is importable as `indextts`, the sidecar will prefer it automatically and fall
back to `pyttsx3` if it is not ready.
