from __future__ import annotations

import shutil
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urlparse

import byes.planner_backends.http as http_backend
from scripts.report_run import generate_report_outputs, load_run_package
from services.planner_service.app import app as planner_app


def test_report_includes_pov_plan_metrics(monkeypatch, tmp_path: Path) -> None:
    fixture_src = Path(__file__).resolve().parent / "fixtures" / "pov_plan_min"
    run_pkg = tmp_path / "pov_plan_runpkg"
    shutil.copytree(fixture_src, run_pkg)

    flask_client = planner_app.test_client()

    class FakeResponse:
        def __init__(self, inner) -> None:
            self._inner = inner
            self.status_code = int(inner.status_code)

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise RuntimeError(f"http status {self.status_code}")

        def json(self):
            return self._inner.get_json()

    class FakeClient:
        def __init__(self, timeout: float = 20.0) -> None:
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

        def post(self, url: str, json: dict | None = None, headers: dict | None = None):
            path = urlparse(url).path or "/plan"
            inner = flask_client.post(path, json=json, headers=headers or {})
            return FakeResponse(inner)

    monkeypatch.setattr(http_backend, "httpx", SimpleNamespace(Client=FakeClient))
    monkeypatch.setenv("BYES_PLANNER_BACKEND", "http")
    monkeypatch.setenv("BYES_PLANNER_ENDPOINT", "http://127.0.0.1:19211/plan")
    monkeypatch.setenv("BYES_PLANNER_PROVIDER", "pov")
    monkeypatch.setenv("BYES_PLANNER_ALLOW_RUN_PACKAGE_PATH", "1")

    ws_jsonl, metrics_before, metrics_after, run_pkg_summary = load_run_package(run_pkg)
    report_md = tmp_path / "report.md"
    report_json = tmp_path / "report.json"

    _md, _json, summary = generate_report_outputs(
        ws_jsonl=ws_jsonl,
        output=report_md,
        metrics_url="http://127.0.0.1:8000/metrics",
        metrics_before_path=metrics_before,
        metrics_after_path=metrics_after,
        external_readiness_url=None,
        run_package_summary=run_pkg_summary,
        output_json=report_json,
    )

    assert bool(summary.get("pov", {}).get("present")) is True
    assert bool(summary.get("plan", {}).get("present")) is True
    assert summary.get("plan", {}).get("planner", {}).get("backend") == "pov"

    pov_plan = summary.get("povPlan", {})
    assert isinstance(pov_plan, dict)
    assert bool(pov_plan.get("present")) is True
    assert float(pov_plan.get("decisionCoverage", 0.0) or 0.0) > 0.0
    assert float(pov_plan.get("actionCoverage", 0.0) or 0.0) > 0.0
