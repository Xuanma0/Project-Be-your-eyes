from __future__ import annotations

import asyncio

from byes.inference.backends.base import OCRResult, RiskResult
from byes.inference.event_emitters import emit_ocr_events, emit_risk_events


def test_emitters_generate_schema_v1_rows() -> None:
    rows: list[dict[str, object]] = []

    async def _sink(event: dict[str, object]) -> None:
        rows.append(event)

    async def _run() -> None:
        await emit_ocr_events(
            OCRResult(text="EXIT", latency_ms=12, status="ok", payload={"text": "EXIT"}),
            frame_seq=7,
            ts_ms=123456,
            started_ts_ms=123440,
            sink=_sink,
            run_id="run-1",
            component="gateway",
        )
        await emit_risk_events(
            RiskResult(
                hazards=[{"hazardKind": "stair_down", "severity": "critical"}],
                latency_ms=8,
                status="ok",
                payload={},
            ),
            frame_seq=7,
            ts_ms=123457,
            sink=_sink,
            run_id="run-1",
            component="gateway",
        )

    asyncio.run(_run())

    assert len(rows) == 3
    for row in rows:
        assert row["schemaVersion"] == "byes.event.v1"
        assert "name" in row
        assert "phase" in row
        assert isinstance(row.get("payload"), dict)

    names = [str(row["name"]) for row in rows]
    assert names == ["ocr.scan_text", "ocr.scan_text", "risk.hazards"]
    assert rows[0]["phase"] == "start"
    assert rows[1]["phase"] == "result"
    assert rows[2]["phase"] == "result"
