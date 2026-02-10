from __future__ import annotations

import os
import re

_SPACE_RE = re.compile(r"\s+")


def postprocess_text(text: str) -> str:
    value = str(text or "")
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = value.strip()
    value = _SPACE_RE.sub(" ", value)
    uppercase = str(os.getenv("BYES_OCR_UPPERCASE", "1")).strip().lower() in {"1", "true", "yes", "on"}
    if uppercase:
        value = value.upper()
    return value

