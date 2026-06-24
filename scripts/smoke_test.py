from __future__ import annotations

import base64
import sys

import cv2
import numpy as np
import requests


BASE_URL = "http://127.0.0.1:8000"


def make_test_image() -> str:
    img = np.full((360, 640, 3), 245, dtype=np.uint8)
    cv2.putText(img, "EXIT 123", (50, 190), cv2.FONT_HERSHEY_SIMPLEX, 1.6, (0, 0, 0), 3)
    ok, buf = cv2.imencode(".jpg", img)
    if not ok:
        raise RuntimeError("Could not encode test image")
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode("ascii")


def main() -> int:
    status = requests.get(f"{BASE_URL}/api/status", timeout=10).json()
    print("status:", status)
    payload = {
        "image_data": make_test_image(),
        "question": "读一下文字",
        "mode": "ocr",
    }
    response = requests.post(f"{BASE_URL}/api/analyze", json=payload, timeout=60)
    print("http:", response.status_code)
    response.raise_for_status()
    data = response.json()
    print("action:", data["action"])
    print("speech:", data["speech"])
    print("stats:", data["stats"])
    print("evidence:", data["evidence"][:2])
    if not data["evidence"]:
        raise RuntimeError("No evidence returned")
    return 0


if __name__ == "__main__":
    sys.exit(main())
