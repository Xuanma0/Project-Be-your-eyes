from __future__ import annotations

import shutil
import subprocess
import sys
import zipfile
from pathlib import Path


def test_report_packages_batch_scan(tmp_path: Path) -> None:
    tests_dir = Path(__file__).resolve().parent
    gateway_dir = tests_dir.parent
    report_packages_script = gateway_dir / "scripts" / "report_packages.py"
    fixture_dir = tests_dir / "fixtures" / "run_package_min"

    root = tmp_path / "scan_root"
    root.mkdir(parents=True, exist_ok=True)
    copied_dir = root / "run_package_min_dir"
    shutil.copytree(fixture_dir, copied_dir)

    zip_path = root / "run_package_min.zip"
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for item in fixture_dir.rglob("*"):
            if item.is_file():
                zf.write(item, item.relative_to(fixture_dir))

    out_dir = root / "_out"
    result = subprocess.run(
        [
            sys.executable,
            str(report_packages_script),
            "--root",
            str(root),
            "--out",
            str(out_dir),
        ],
        cwd=gateway_dir,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, f"stdout={result.stdout}\nstderr={result.stderr}"
    index_md = out_dir / "index.md"
    index_json = out_dir / "index.json"
    assert index_md.exists()
    assert index_json.exists()

    content = index_md.read_text(encoding="utf-8")
    assert "Run Package Reports" in content
    assert "fixture_baseline" in content
    assert "frame_recv_delta" in content
    assert "report_run_package_min.zip" in content or "run_package_min.zip" in content

