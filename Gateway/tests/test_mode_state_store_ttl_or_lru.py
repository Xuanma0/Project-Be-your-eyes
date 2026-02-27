from __future__ import annotations

from byes.mode_state import ModeStateStore


def test_mode_state_store_set_get_and_changed_flag() -> None:
    store = ModeStateStore(default_mode="walk", max_entries=8, ttl_ms=60000)
    store.set_mode(device_id="d1", run_id="r1", mode="read_text", source="unity")

    assert store.get_mode(device_id="d1", run_id="r1") == "read_text"
    assert store.consume_changed_flag(device_id="d1", run_id="r1") is True
    assert store.consume_changed_flag(device_id="d1", run_id="r1") is False

    store.mark_mode_changed(device_id="d1", run_id="r1")
    assert store.consume_changed_flag(device_id="d1", run_id="r1") is True


def test_mode_state_store_lru_eviction_by_capacity() -> None:
    store = ModeStateStore(default_mode="walk", max_entries=2, ttl_ms=60000)
    store.set_mode(device_id="d1", run_id=None, mode="inspect", source="system")
    store.set_mode(device_id="d2", run_id=None, mode="walk", source="system")
    store.set_mode(device_id="d3", run_id=None, mode="read_text", source="system")

    assert "d1" not in store._device_modes  # noqa: SLF001
    assert "d2" in store._device_modes  # noqa: SLF001
    assert "d3" in store._device_modes  # noqa: SLF001
    assert store.get_mode(device_id="d2", run_id=None) == "walk"
    assert store.get_mode(device_id="d3", run_id=None) == "read_text"
    # d1 should have been evicted from device-key bucket because max_entries=2
    assert store.get_mode(device_id="d1", run_id=None) == "walk"


def test_mode_state_store_ttl_expires_old_entries() -> None:
    store = ModeStateStore(default_mode="walk", max_entries=8, ttl_ms=1)
    store.set_mode(device_id="device-old", run_id=None, mode="inspect", ts_ms=0, source="system")

    # ts_ms=0 is far older than now; entry should be purged on access
    assert store.get_mode(device_id="device-old", run_id=None) == "walk"
    assert store.consume_changed_flag(device_id="device-old", run_id=None) is False
