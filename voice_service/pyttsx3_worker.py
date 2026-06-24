from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pyttsx3


def _select_chinese_voice(engine: Any) -> None:
    try:
        voices = engine.getProperty("voices") or []
        for voice in voices:
            marker = f"{voice.id} {getattr(voice, 'name', '')} {getattr(voice, 'languages', '')}".lower()
            if "zh" in marker or "chinese" in marker or "huihui" in marker or "xiaoxiao" in marker:
                engine.setProperty("voice", voice.id)
                return
    except Exception:
        pass


def main() -> int:
    if len(sys.argv) != 4:
        print("usage: pyttsx3_worker <text_path> <output_wav> <rate>", file=sys.stderr)
        return 2

    text = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
    if any(ord(ch) > 127 for ch in text) and not text.startswith("\ufeff"):
        text = "\ufeff" + text
    out_path = Path(sys.argv[2])
    rate = max(0.5, min(2.0, float(sys.argv[3] or 1.0)))
    if not text:
        print("empty text", file=sys.stderr)
        return 2

    engine = pyttsx3.init()
    _select_chinese_voice(engine)
    engine.setProperty("rate", int(185 * rate))
    engine.setProperty("volume", 1.0)
    engine.save_to_file(text, str(out_path))
    engine.runAndWait()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
