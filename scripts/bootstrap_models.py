from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel


console = Console()

CLIP_VIT_B32_URL = (
    "https://openaipublic.azureedge.net/clip/models/"
    "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af/ViT-B-32.pt"
)
CLIP_VIT_B32_SHA256 = "40d365715913c9da98579312b702a82c18be219cc2a73407c4526f58eba950af"


def ok(name: str, detail: str = "") -> None:
    suffix = f" - {detail}" if detail else ""
    console.print(f"[green]OK[/green] {name}{suffix}")


def warn(name: str, detail: str) -> None:
    console.print(f"[yellow]WARN[/yellow] {name} - {detail}")


def fail(name: str, detail: str) -> None:
    console.print(f"[red]FAIL[/red] {name} - {detail}")


def download_yolo(model_name: str) -> None:
    from ultralytics import YOLO

    model = YOLO(model_name)
    ok("Ultralytics model", model_name)
    # Touch model metadata so a bad download fails during setup.
    _ = model.names


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_clip_vit_b32() -> None:
    import requests

    cache_dir = Path.home() / ".cache" / "clip"
    cache_dir.mkdir(parents=True, exist_ok=True)
    model_path = cache_dir / "ViT-B-32.pt"
    if model_path.exists() and sha256_file(model_path) == CLIP_VIT_B32_SHA256:
        ok("CLIP text encoder", str(model_path))
        return

    tmp_path = model_path.with_suffix(".pt.download")
    with requests.get(CLIP_VIT_B32_URL, stream=True, timeout=(20, 60)) as response:
        response.raise_for_status()
        with tmp_path.open("wb") as fh:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    fh.write(chunk)

    actual_hash = sha256_file(tmp_path)
    if actual_hash != CLIP_VIT_B32_SHA256:
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"CLIP ViT-B/32 checksum mismatch: {actual_hash}")
    tmp_path.replace(model_path)
    ok("CLIP text encoder", str(model_path))


def download_paddleocr(lang: str) -> None:
    from paddleocr import PaddleOCR

    try:
        # PaddleOCR 3.x signature.
        _ = PaddleOCR(lang=lang, use_textline_orientation=True)
    except TypeError:
        # PaddleOCR 2.x compatibility.
        _ = PaddleOCR(lang=lang, use_angle_cls=True)
    ok("PaddleOCR", f"lang={lang}")


def download_whisper(model_name: str) -> None:
    from faster_whisper import WhisperModel

    # CPU/int8 is used here only to force the model download in a broadly
    # compatible way. Runtime code can still use CUDA/FP16 on the 2080Ti.
    _ = WhisperModel(model_name, device="cpu", compute_type="int8")
    ok("faster-whisper", model_name)


def check_deepseek(env_path: Path) -> None:
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - setup diagnostic
        fail("DeepSeek SDK imports", repr(exc))
        return

    if env_path.exists():
        load_dotenv(env_path)

    api_key = os.getenv("DEEPSEEK_API_KEY", "").strip()
    base_url = os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com").strip()
    model = os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash").strip()

    if not api_key or api_key == "sk-your-key-here":
        warn("DeepSeek API", "DEEPSEEK_API_KEY is not set yet; skipping live API check")
        return

    client = OpenAI(api_key=api_key, base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        messages=[
            {
                "role": "system",
                "content": "Return only compact JSON.",
            },
            {
                "role": "user",
                "content": (
                    "Return {\"status\":\"ok\",\"role\":\"planner\"} to confirm "
                    "the online planner is reachable."
                ),
            },
        ],
        response_format={"type": "json_object"},
        max_tokens=80,
        stream=False,
    )
    content = response.choices[0].message.content or "{}"
    parsed = json.loads(content)
    ok("DeepSeek API", f"{model}: {parsed}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Download and sanity-check BYE prototype dependencies.")
    parser.add_argument("--yolo-model", default=os.getenv("BYE_YOLO_MODEL", "yolo11n.pt"))
    parser.add_argument("--yolo-world-model", default=os.getenv("BYE_YOLO_WORLD_MODEL", "yolov8s-worldv2.pt"))
    parser.add_argument("--asr-model", default=os.getenv("BYE_ASR_MODEL", "small"))
    parser.add_argument("--ocr-lang", default="ch")
    parser.add_argument("--env", default=".env")
    parser.add_argument("--skip-deepseek-check", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    env_path = repo_root / args.env

    console.print(Panel.fit("Be Your Eyes dependency bootstrap", border_style="cyan"))

    failures: list[str] = []

    for name, fn in [
        (f"YOLO detector {args.yolo_model}", lambda: download_yolo(args.yolo_model)),
        (f"YOLO-World detector {args.yolo_world_model}", lambda: download_yolo(args.yolo_world_model)),
        ("CLIP ViT-B/32 text encoder", download_clip_vit_b32),
        (f"PaddleOCR {args.ocr_lang}", lambda: download_paddleocr(args.ocr_lang)),
        (f"faster-whisper {args.asr_model}", lambda: download_whisper(args.asr_model)),
    ]:
        try:
            fn()
        except Exception as exc:  # pragma: no cover - setup diagnostic
            fail(name, repr(exc))
            failures.append(name)

    if not args.skip_deepseek_check:
        try:
            check_deepseek(env_path)
        except Exception as exc:  # pragma: no cover - setup diagnostic
            fail("DeepSeek API", repr(exc))
            failures.append("DeepSeek API")

    if failures:
        console.print("\n[red]Some setup checks failed:[/red]")
        for item in failures:
            console.print(f"  - {item}")
        return 1

    console.print("\n[green]All requested downloads/checks completed.[/green]")
    return 0


if __name__ == "__main__":
    sys.exit(main())
