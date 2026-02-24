from __future__ import annotations

import json
from pathlib import Path

import scripts.run_regression_suite as regression_runner


def test_regression_suite_runner_contract_requires_pov_by_default(tmp_path: Path, monkeypatch) -> None:
    suite_path = tmp_path / "suite_contract.json"
    out_path = tmp_path / "suite_out.json"
    ws_path = tmp_path / "events.jsonl"
    metrics_before = tmp_path / "metrics_before.txt"
    metrics_after = tmp_path / "metrics_after.txt"
    ws_path.write_text("", encoding="utf-8")
    metrics_before.write_text("byes_frame_received_total 0\n", encoding="utf-8")
    metrics_after.write_text("byes_frame_received_total 1\n", encoding="utf-8")

    suite_payload = {
        "name": "contract",
        "runs": [{"id": "contract_case", "path": "dummy_run_package"}],
    }
    suite_path.write_text(json.dumps(suite_payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _fake_resolve_run_package_input(_run_path: Path):
        return ws_path, metrics_before, metrics_after, {"scenarioTag": "contract_case"}, None

    def _fake_generate_report_outputs(
        *,
        ws_jsonl: Path,
        output: Path,
        metrics_url: str,
        metrics_before_path: Path,
        metrics_after_path: Path,
        external_readiness_url,
        run_package_summary,
        output_json: Path,
    ):
        _ = (ws_jsonl, metrics_url, metrics_before_path, metrics_after_path, external_readiness_url, run_package_summary)
        payload = {
            "scenarioTag": "contract_case",
            "quality": {
                "hasGroundTruth": False,
                "safetyBehavior": {"confirm": {"timeouts": 0, "missingResponseCount": 0}},
                "eventSchema": {"source": "eventsV1Jsonl", "normalizedEvents": 1, "warningsCount": 0},
                "riskLatencyMs": {"p90": 0, "max": 0},
                "topFindings": [],
            },
            "pov": {"present": False, "counts": {"decisions": 0}, "time": {}, "budget": {}},
            "inference": {"ocr": {}, "risk": {}},
        }
        output.write_text("# report\n", encoding="utf-8")
        output_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return output, output_json, payload

    monkeypatch.setattr(regression_runner, "resolve_run_package_input", _fake_resolve_run_package_input)
    monkeypatch.setattr(regression_runner, "generate_report_outputs", _fake_generate_report_outputs)

    result, exit_code = regression_runner.run_suite(
        suite_path=suite_path,
        out_path=out_path,
        baseline_path=None,
        fail_on_drop=False,
        fail_on_critical_fn=True,
        write_baseline=False,
    )

    assert exit_code == 1
    failures = result.get("failures", [])
    assert isinstance(failures, list)
    assert any("pov.present is false" in item for item in failures)
