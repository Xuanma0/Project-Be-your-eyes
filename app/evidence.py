from __future__ import annotations

import json
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional


@dataclass
class Evidence:
    type: str
    label: str
    source: str
    confidence: float
    timestamp: float
    ttl: float
    position: str = "unknown"
    bbox: Optional[List[float]] = None
    text: Optional[str] = None
    attributes: Dict[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    @property
    def age(self) -> float:
        return max(0.0, time.time() - self.timestamp)

    @property
    def expired(self) -> bool:
        return self.age > self.ttl

    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data["age"] = round(self.age, 3)
        data["expired"] = self.expired
        return data


class EvidenceStore:
    def __init__(self, log_path: Path, max_items: int = 240) -> None:
        self.log_path = log_path
        self.max_items = max_items
        self._items: List[Evidence] = []
        self._lock = threading.Lock()
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def add_many(self, items: Iterable[Evidence]) -> List[Evidence]:
        items = list(items)
        if not items:
            return []
        with self._lock:
            self._items.extend(items)
            self._items = self._items[-self.max_items :]
            with self.log_path.open("a", encoding="utf-8") as fh:
                for item in items:
                    fh.write(json.dumps(item.to_dict(), ensure_ascii=False) + "\n")
        return items

    def recent(self, include_expired: bool = False, limit: int = 80) -> List[Dict[str, Any]]:
        with self._lock:
            items = self._items[-limit:]
        if not include_expired:
            items = [item for item in items if not item.expired]
        return [item.to_dict() for item in items]

    def memory(self, limit: int = 80) -> List[Dict[str, Any]]:
        with self._lock:
            items = self._items[-limit:]
        return [item.to_dict() for item in items]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
        self.log_path.write_text("", encoding="utf-8")
