from __future__ import annotations

import argparse
import contextlib
import os
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[2]
GATEWAY_DIR = REPO_ROOT / "Gateway"


@dataclass
class ServiceSpec:
    name: str
    cmd: list[str]
    env_updates: dict[str, str]
    url: str


@dataclass
class ServiceRuntime:
    spec: ServiceSpec
    process: subprocess.Popen[str]


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key:
            continue
        value = value.strip()
        if len(value) >= 2 and ((value[0] == '"' and value[-1] == '"') or (value[0] == "'" and value[-1] == "'")):
            value = value[1:-1]
        values[key] = value
    return values


def _build_base_env() -> dict[str, str]:
    env = dict(os.environ)
    dot_env = _parse_env_file(REPO_ROOT / ".env")
    for key, value in dot_env.items():
        env.setdefault(key, value)
    return env


def _start_service(spec: ServiceSpec, base_env: dict[str, str]) -> ServiceRuntime:
    env = dict(base_env)
    env.update(spec.env_updates)
    proc = subprocess.Popen(  # noqa: S603
        spec.cmd,
        cwd=REPO_ROOT,
        env=env,
        text=True,
    )
    return ServiceRuntime(spec=spec, process=proc)


def _stop_services(runtimes: list[ServiceRuntime]) -> None:
    for runtime in reversed(runtimes):
        proc = runtime.process
        if proc.poll() is None:
            proc.terminate()

    deadline = time.time() + 8.0
    for runtime in reversed(runtimes):
        proc = runtime.process
        if proc.poll() is not None:
            continue
        timeout = max(0.1, deadline - time.time())
        try:
            proc.wait(timeout=timeout)
        except Exception:
            pass

    for runtime in reversed(runtimes):
        proc = runtime.process
        if proc.poll() is None:
            proc.kill()
            with contextlib.suppress(Exception):
                proc.wait(timeout=2.0)


def _build_uvicorn_cmd(module_path: str, *, host: str, port: int, reload_enabled: bool) -> list[str]:
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        module_path,
        "--app-dir",
        str(GATEWAY_DIR),
        "--host",
        host,
        "--port",
        str(port),
    ]
    if reload_enabled:
        cmd.append("--reload")
    return cmd


def _build_service_specs(args: argparse.Namespace) -> list[ServiceSpec]:
    host = "0.0.0.0" if bool(args.public) else str(args.host).strip()
    host = host or "127.0.0.1"
    reload_enabled = bool(args.reload)

    gateway_spec = ServiceSpec(
        name="gateway",
        cmd=_build_uvicorn_cmd("main:app", host=host, port=int(args.gateway_port), reload_enabled=reload_enabled),
        env_updates={},
        url=f"http://{host}:{int(args.gateway_port)}",
    )

    if bool(args.gateway_only):
        return [gateway_spec]

    specs: list[ServiceSpec] = []

    if bool(args.with_reference_all) or bool(args.with_reference_seg):
        specs.append(
            ServiceSpec(
                name="reference_seg_service",
                cmd=_build_uvicorn_cmd(
                    "services.reference_seg_service.app:app",
                    host=host,
                    port=int(args.reference_seg_port),
                    reload_enabled=reload_enabled,
                ),
                env_updates={},
                url=f"http://{host}:{int(args.reference_seg_port)}",
            )
        )
    if bool(args.with_reference_all) or bool(args.with_reference_depth):
        specs.append(
            ServiceSpec(
                name="reference_depth_service",
                cmd=_build_uvicorn_cmd(
                    "services.reference_depth_service.app:app",
                    host=host,
                    port=int(args.reference_depth_port),
                    reload_enabled=reload_enabled,
                ),
                env_updates={},
                url=f"http://{host}:{int(args.reference_depth_port)}",
            )
        )
    if bool(args.with_reference_all) or bool(args.with_reference_ocr):
        specs.append(
            ServiceSpec(
                name="reference_ocr_service",
                cmd=_build_uvicorn_cmd(
                    "services.reference_ocr_service.app:app",
                    host=host,
                    port=int(args.reference_ocr_port),
                    reload_enabled=reload_enabled,
                ),
                env_updates={},
                url=f"http://{host}:{int(args.reference_ocr_port)}",
            )
        )
    if bool(args.with_reference_all) or bool(args.with_reference_slam):
        specs.append(
            ServiceSpec(
                name="reference_slam_service",
                cmd=_build_uvicorn_cmd(
                    "services.reference_slam_service.app:app",
                    host=host,
                    port=int(args.reference_slam_port),
                    reload_enabled=reload_enabled,
                ),
                env_updates={},
                url=f"http://{host}:{int(args.reference_slam_port)}",
            )
        )

    if bool(args.with_inference):
        specs.append(
            ServiceSpec(
                name="inference_service",
                cmd=_build_uvicorn_cmd(
                    "services.inference_service.app:app",
                    host=host,
                    port=int(args.inference_port),
                    reload_enabled=reload_enabled,
                ),
                env_updates={},
                url=f"http://{host}:{int(args.inference_port)}",
            )
        )

    if bool(args.with_planner):
        specs.append(
            ServiceSpec(
                name="planner_service",
                cmd=[sys.executable, str(GATEWAY_DIR / "services" / "planner_service" / "app.py")],
                env_updates={
                    "PLANNER_SERVICE_HOST": host,
                    "PLANNER_SERVICE_PORT": str(int(args.planner_port)),
                },
                url=f"http://{host}:{int(args.planner_port)}",
            )
        )

    specs.append(gateway_spec)
    return specs


def _print_startup_banner(runtimes: list[ServiceRuntime], *, host: str, public_mode: bool) -> None:
    print("== dev_up started ==")
    for runtime in runtimes:
        print(f"- {runtime.spec.name}: {runtime.spec.url}")
        print(f"  cmd: {' '.join(runtime.spec.cmd)}")
    print("Stop: Ctrl+C")

    if public_mode or host == "0.0.0.0":
        print("WARNING: host is public (0.0.0.0).")
        print("WARNING: Gateway defaults are development-oriented. Enable BYES_GATEWAY_API_KEY or protect with reverse proxy auth + TLS.")


def _monitor(runtimes: list[ServiceRuntime]) -> int:
    while True:
        for runtime in runtimes:
            code = runtime.process.poll()
            if code is not None:
                print(f"service exited early: {runtime.spec.name} code={code}")
                return int(code)
        time.sleep(0.5)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Start local BYES services for development.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--public", action="store_true", default=False, help="Shortcut for --host 0.0.0.0")

    parser.add_argument("--gateway-port", type=int, default=8000)
    parser.add_argument("--inference-port", type=int, default=19120)
    parser.add_argument("--planner-port", type=int, default=19211)
    parser.add_argument("--reference-seg-port", type=int, default=19231)
    parser.add_argument("--reference-depth-port", type=int, default=19241)
    parser.add_argument("--reference-ocr-port", type=int, default=19251)
    parser.add_argument("--reference-slam-port", type=int, default=19261)

    parser.add_argument("--gateway-only", action="store_true", default=False)
    parser.add_argument("--with-inference", action="store_true", default=False)
    parser.add_argument("--with-planner", action="store_true", default=False)
    parser.add_argument("--with-reference-all", action="store_true", default=False)
    parser.add_argument("--with-reference-seg", action="store_true", default=False)
    parser.add_argument("--with-reference-depth", action="store_true", default=False)
    parser.add_argument("--with-reference-ocr", action="store_true", default=False)
    parser.add_argument("--with-reference-slam", action="store_true", default=False)

    parser.add_argument("--reload", dest="reload", action="store_true", default=True)
    parser.add_argument("--no-reload", dest="reload", action="store_false")
    return parser


def main() -> int:
    parser = _build_parser()
    args = parser.parse_args()
    host = "0.0.0.0" if bool(args.public) else str(args.host).strip()
    if not host:
        host = "127.0.0.1"

    base_env = _build_base_env()
    specs = _build_service_specs(args)
    runtimes: list[ServiceRuntime] = []

    try:
        for spec in specs:
            runtimes.append(_start_service(spec, base_env))
        _print_startup_banner(runtimes, host=host, public_mode=bool(args.public))
        code = _monitor(runtimes)
        return code if code != 0 else 0
    except KeyboardInterrupt:
        print("Stopping services...")
        return 0
    finally:
        _stop_services(runtimes)


if __name__ == "__main__":
    raise SystemExit(main())
