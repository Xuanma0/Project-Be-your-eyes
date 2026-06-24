from __future__ import annotations

from typing import Any, Dict, List, Optional

import requests

from .config import settings


class TrackerSidecarClient:
    def __init__(self) -> None:
        self.base_url = settings.tracker_sidecar_url
        self.timeout = settings.tracker_sidecar_timeout

    def status(self) -> Dict[str, Any]:
        if not settings.enable_tracker_sidecar:
            return {"enabled": False, "available": False, "url": self.base_url}
        try:
            res = requests.get(f"{self.base_url}/status", timeout=1.5)
            res.raise_for_status()
            data = res.json()
            data["enabled"] = True
            data["available"] = True
            data["url"] = self.base_url
            return data
        except Exception as exc:
            return {
                "enabled": True,
                "available": False,
                "url": self.base_url,
                "error": repr(exc)[:300],
            }

    def track(
        self,
        image_data: str,
        bbox: Optional[List[float]] = None,
        label: str = "",
        reset: bool = False,
    ) -> Dict[str, Any]:
        if not settings.enable_tracker_sidecar:
            raise RuntimeError("tracker sidecar disabled")
        payload: Dict[str, Any] = {"image_data": image_data, "label": label, "reset": reset}
        if bbox:
            payload["bbox"] = bbox
        res = requests.post(f"{self.base_url}/track", json=payload, timeout=self.timeout)
        res.raise_for_status()
        return res.json()

    def reset(self) -> Dict[str, Any]:
        if not settings.enable_tracker_sidecar:
            return {"ok": True, "enabled": False}
        res = requests.post(f"{self.base_url}/reset", timeout=3)
        res.raise_for_status()
        return res.json()
