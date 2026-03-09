from __future__ import annotations

import json
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

_ALLOWED_TARGETS = {"risk", "ocr", "det", "seg", "depth", "slam"}
_MODE_ALIASES = {
    "walk": "walk",
    "nav": "walk",
    "navigation": "walk",
    "read": "read_text",
    "read_text": "read_text",
    "inspect": "inspect",
}


def _now_ms() -> int:
    return int(time.time() * 1000)


def normalize_mode_value(value: Any) -> str | None:
    token = str(value or "").strip().lower()
    if not token:
        return None
    return _MODE_ALIASES.get(token)


@dataclass(frozen=True)
class ModeProfile:
    profiles: dict[str, dict[str, int]]

    def stride_for(self, mode: str | None, target: str) -> int | None:
        target_token = str(target or "").strip().lower()
        if target_token not in _ALLOWED_TARGETS:
            return None
        mode_token = normalize_mode_value(mode) or "walk"
        merged: dict[str, int] = {}
        merged.update(self.profiles.get("default", {}))
        merged.update(self.profiles.get(mode_token, {}))
        stride = merged.get(target_token)
        if stride is None:
            return None
        return max(1, int(stride))


def parse_mode_profile_json(raw: str | None) -> ModeProfile | None:
    text = str(raw or "").strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"BYES_MODE_PROFILE_JSON invalid json: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError("BYES_MODE_PROFILE_JSON must be an object")

    normalized: dict[str, dict[str, int]] = {}
    for raw_mode, raw_targets in payload.items():
        mode_key = str(raw_mode or "").strip().lower()
        if mode_key == "default":
            mode_token = "default"
        else:
            mode_token = normalize_mode_value(mode_key)
            if mode_token is None:
                raise ValueError(f"BYES_MODE_PROFILE_JSON unsupported mode key: {raw_mode}")
        if not isinstance(raw_targets, dict):
            raise ValueError(f"BYES_MODE_PROFILE_JSON mode '{raw_mode}' must map to an object")

        target_config: dict[str, int] = {}
        for raw_target, raw_rule in raw_targets.items():
            target_token = str(raw_target or "").strip().lower()
            if target_token not in _ALLOWED_TARGETS:
                continue
            if isinstance(raw_rule, dict):
                value = raw_rule.get("every_n_frames", raw_rule.get("everyNFrames"))
            else:
                value = raw_rule
            try:
                stride = int(value)
            except (TypeError, ValueError) as exc:
                raise ValueError(
                    f"BYES_MODE_PROFILE_JSON invalid every_n_frames for mode='{raw_mode}' target='{raw_target}'"
                ) from exc
            if stride < 1:
                raise ValueError(
                    f"BYES_MODE_PROFILE_JSON every_n_frames must be >=1 for mode='{raw_mode}' target='{raw_target}'"
                )
            target_config[target_token] = stride
        normalized[mode_token] = target_config

    if "default" not in normalized:
        normalized["default"] = {}
    return ModeProfile(profiles=normalized)


@dataclass
class _ModeEntry:
    mode: str
    updated_at_ms: int
    source: str
    changed: bool


@dataclass(frozen=True)
class ModeSnapshot:
    device_id: str
    mode: str
    updated_ts_ms: int
    expires_in_ms: int | None
    source: str


class ModeStateStore:
    def __init__(
        self,
        *,
        default_mode: str = "walk",
        max_entries: int = 256,
        ttl_ms: int = 30 * 60 * 1000,
        max_clock_skew_ms: int = 10 * 60 * 1000,
        explicit_mode_hold_ms: int = 0,
    ) -> None:
        normalized_default = normalize_mode_value(default_mode) or "walk"
        self.default_mode = normalized_default
        self.max_entries = max(1, int(max_entries))
        self.ttl_ms = max(0, int(ttl_ms))
        # Device clocks on standalone headsets can drift; clamp stale/future client ts
        # to server-now so mode entries are not purged immediately.
        self.max_clock_skew_ms = max(0, int(max_clock_skew_ms))
        # Protect explicit mode switches from frame-meta rollback.
        # 0 means "never allow frame to override explicit mode".
        self.explicit_mode_hold_ms = max(0, int(explicit_mode_hold_ms))
        self._device_modes: OrderedDict[str, _ModeEntry] = OrderedDict()
        self._run_modes: OrderedDict[str, _ModeEntry] = OrderedDict()

    def reset_runtime(self) -> None:
        self._device_modes.clear()
        self._run_modes.clear()

    @staticmethod
    def _normalize_key(value: str | None) -> str | None:
        token = str(value or "").strip()
        return token or None

    def _resolve_ts_ms(self, ts_ms: int | None) -> int:
        now_ms = _now_ms()
        if ts_ms is None:
            return now_ms
        try:
            numeric = int(ts_ms)
        except (TypeError, ValueError):
            return now_ms
        if numeric < 0:
            return now_ms
        if self.max_clock_skew_ms > 0:
            lower_bound = now_ms - self.max_clock_skew_ms
            upper_bound = now_ms + self.max_clock_skew_ms
            if numeric < lower_bound or numeric > upper_bound:
                return now_ms
        return numeric

    def _purge_expired(self, now_ms: int) -> None:
        if self.ttl_ms <= 0:
            return
        cutoff = now_ms - self.ttl_ms
        for bucket in (self._device_modes, self._run_modes):
            stale = [key for key, entry in bucket.items() if int(entry.updated_at_ms) < cutoff]
            for key in stale:
                bucket.pop(key, None)

    def _upsert(self, bucket: OrderedDict[str, _ModeEntry], key: str, mode: str, ts_ms: int, source: str) -> None:
        previous = bucket.get(key)
        if previous is not None and source == "frame" and previous.mode != mode:
            previous_source = str(previous.source or "").strip().lower()
            source_is_explicit = previous_source in {"hotkey", "xr", "system", "unity"}
            if source_is_explicit:
                if self.explicit_mode_hold_ms <= 0:
                    bucket.move_to_end(key, last=True)
                    return
                age_ms = max(0, int(ts_ms) - int(previous.updated_at_ms))
                if age_ms < self.explicit_mode_hold_ms:
                    bucket.move_to_end(key, last=True)
                    return
        changed = previous is None or previous.mode != mode
        pending_changed = bool(previous.changed) if previous is not None else False
        bucket[key] = _ModeEntry(
            mode=mode,
            updated_at_ms=ts_ms,
            source=source,
            changed=pending_changed or changed,
        )
        bucket.move_to_end(key, last=True)
        while len(bucket) > self.max_entries:
            bucket.popitem(last=False)

    def set_mode(
        self,
        *,
        device_id: str | None,
        run_id: str | None,
        mode: str,
        ts_ms: int | None = None,
        source: str | None = None,
    ) -> str:
        normalized_mode = normalize_mode_value(mode) or self.default_mode
        normalized_source = str(source or "system").strip().lower() or "system"
        now_ms = self._resolve_ts_ms(ts_ms)
        self._purge_expired(now_ms)

        device_key = self._normalize_key(device_id)
        run_key = self._normalize_key(run_id)
        if device_key is not None:
            self._upsert(self._device_modes, device_key, normalized_mode, now_ms, normalized_source)
        if run_key is not None:
            self._upsert(self._run_modes, run_key, normalized_mode, now_ms, normalized_source)
        return normalized_mode

    def get_mode(self, *, device_id: str | None, run_id: str | None) -> str:
        now_ms = _now_ms()
        self._purge_expired(now_ms)
        device_key = self._normalize_key(device_id)
        run_key = self._normalize_key(run_id)
        if device_key is not None:
            entry = self._device_modes.get(device_key)
            if entry is not None:
                self._device_modes.move_to_end(device_key, last=True)
                return entry.mode
        if run_key is not None:
            entry = self._run_modes.get(run_key)
            if entry is not None:
                self._run_modes.move_to_end(run_key, last=True)
                return entry.mode
        return self.default_mode

    def mark_mode_changed(self, *, device_id: str | None, run_id: str | None) -> None:
        now_ms = _now_ms()
        self._purge_expired(now_ms)
        device_key = self._normalize_key(device_id)
        run_key = self._normalize_key(run_id)
        if device_key is not None and device_key in self._device_modes:
            entry = self._device_modes[device_key]
            entry.changed = True
            self._device_modes.move_to_end(device_key, last=True)
        if run_key is not None and run_key in self._run_modes:
            entry = self._run_modes[run_key]
            entry.changed = True
            self._run_modes.move_to_end(run_key, last=True)

    def consume_changed_flag(self, *, device_id: str | None, run_id: str | None) -> bool:
        now_ms = _now_ms()
        self._purge_expired(now_ms)
        changed = False
        device_key = self._normalize_key(device_id)
        run_key = self._normalize_key(run_id)
        if device_key is not None and device_key in self._device_modes:
            entry = self._device_modes[device_key]
            changed = changed or bool(entry.changed)
            entry.changed = False
            self._device_modes.move_to_end(device_key, last=True)
        if run_key is not None and run_key in self._run_modes:
            entry = self._run_modes[run_key]
            changed = changed or bool(entry.changed)
            entry.changed = False
            self._run_modes.move_to_end(run_key, last=True)
        return changed

    def get_device_snapshot(self, *, device_id: str | None) -> ModeSnapshot:
        now_ms = _now_ms()
        self._purge_expired(now_ms)
        normalized_device = self._normalize_key(device_id) or "default"
        lookup_key = self._normalize_key(device_id)
        if lookup_key is None:
            return ModeSnapshot(
                device_id=normalized_device,
                mode=self.default_mode,
                updated_ts_ms=now_ms,
                expires_in_ms=None,
                source="default",
            )

        entry = self._device_modes.get(lookup_key)
        if entry is None:
            return ModeSnapshot(
                device_id=normalized_device,
                mode=self.default_mode,
                updated_ts_ms=now_ms,
                expires_in_ms=None,
                source="default",
            )

        self._device_modes.move_to_end(lookup_key, last=True)
        expires_in_ms: int | None
        if self.ttl_ms <= 0:
            expires_in_ms = None
        else:
            remaining = int(self.ttl_ms) - max(0, now_ms - int(entry.updated_at_ms))
            expires_in_ms = max(0, remaining)
        return ModeSnapshot(
            device_id=lookup_key,
            mode=entry.mode,
            updated_ts_ms=int(entry.updated_at_ms),
            expires_in_ms=expires_in_ms,
            source="explicit",
        )
