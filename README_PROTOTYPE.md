# Be Your Eyes Prototype

Run:

```powershell
cd D:\Be-your-eyes
.\run_app.ps1
```

Open:

```text
http://127.0.0.1:8000
```

The current prototype uses:

- backend OpenCV camera preview through `/api/server-camera/stream.mjpg`
- local YOLO26 for stable object evidence
- optional YOLO-World open-vocabulary search for find-mode targets, using CLIP ViT-B/32 text prompts
- RapidOCR first for text evidence, with PaddleOCR kept optional
- local faster-whisper endpoint for microphone transcription
- browser speech synthesis for headphone feedback
- heuristic local planner for fixed buttons: scene, find, OCR, safety, memory
- DeepSeek V4 only for free-form text planning over structured evidence
- local safety gate that can override every other answer

The LLM does not receive the image. It receives only tool evidence.

Evaluation:

```powershell
.\.venv\Scripts\python.exe scripts\eval_toolchain.py demo --out data\eval\demo
```

See `EVAL.md` for recording clips, writing labels, running offline benchmarks, and comparing `full / no_agent / detect_only` variants.
