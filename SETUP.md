# Be Your Eyes Prototype Setup

This repo is configured for the first research prototype:

- local visual tool chain: OpenCV, Ultralytics YOLO, YOLO-World, PaddleOCR
- local speech pieces: faster-whisper, Windows TTS via pyttsx3
- online planner: DeepSeek V4 through the OpenAI-compatible API

## One-click Windows setup

Open PowerShell in `D:\Be-your-eyes`, then run:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\setup_windows.ps1
```

If you do not have Conda, the script creates `.venv`. If you do have Conda, it creates/updates a `bye` Conda environment.

## Light setup first

If you want to avoid large downloads, run the light setup:

```powershell
Set-ExecutionPolicy -Scope Process Bypass -Force
.\scripts\setup_light_windows.ps1 -UseVenv
```

This installs only the smaller control-plane dependencies and writes the heavy commands to `HEAVY_DOWNLOADS.md`.

After setup, edit `.env` and set:

```text
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_MODEL=deepseek-v4-flash
```

Use `deepseek-v4-pro` when you want stronger but slower planning.

## Useful variants

Skip the live DeepSeek API check before you have a key:

```powershell
.\scripts\setup_windows.ps1 -SkipDeepSeekCheck
```

Force a `.venv` instead of Conda:

```powershell
.\scripts\setup_windows.ps1 -UseVenv
```

Install CPU PyTorch only:

```powershell
.\scripts\setup_windows.ps1 -CpuTorch
```

Do dependency install only, without downloading model weights:

```powershell
.\scripts\setup_windows.ps1 -NoModelDownload
```

## DeepSeek note

DeepSeek's current official V4 API model IDs are:

- `deepseek-v4-flash`
- `deepseek-v4-pro`

The old names `deepseek-chat` and `deepseek-reasoner` are scheduled for deprecation on `2026-07-24`, so this prototype defaults to `deepseek-v4-flash`.
