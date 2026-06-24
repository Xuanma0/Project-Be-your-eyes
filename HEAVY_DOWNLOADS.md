# Heavy Downloads

Run these yourself when you are ready for multi-GB downloads.

```powershell
cd D:\Be-your-eyes
.\.venv\Scripts\python.exe -m pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
.\.venv\Scripts\python.exe -m pip install ultralytics paddlepaddle paddleocr faster-whisper mediapipe
.\.venv\Scripts\python.exe scripts\bootstrap_models.py --skip-deepseek-check
```

Optional SAM 3 SOTA segmentation:

1. Request access to Meta's SAM 3 checkpoint on Hugging Face.
2. Download `sam3.pt`.
3. Put it at `D:\Be-your-eyes\sam3.pt` or set `BYE_SAM3_MODEL` in `.env`.

Expected heavy items:

- PyTorch CUDA wheels: large
- PaddlePaddle/PaddleOCR: large
- YOLO/YOLO-World weights: model downloads
- faster-whisper `small`: model download
- MediaPipe hand tracker package: tens of MB
- SAM 3 checkpoint: large, gated download

Current local-only weights are intentionally ignored by Git:

- `yolo11n.pt`, `yolo11s.pt`
- `yolo26n.pt`, `yolo26s.pt`
- `yoloe-26s-seg.pt`, `yoloe-26m-seg.pt`
- `yolov8s-worldv2.pt`
- `mobileclip2_b.ts`, `mobileclip_blt.ts`
- `models/`
- `data/models/hand_landmarker.task`

Keep `.env` local as well; it contains `DEEPSEEK_API_KEY`.
