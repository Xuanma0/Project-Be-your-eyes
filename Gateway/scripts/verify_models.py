from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
GATEWAY_ROOT = THIS_DIR.parent
if str(GATEWAY_ROOT) not in sys.path:
    sys.path.insert(0, str(GATEWAY_ROOT))

from byes.config import load_config  # noqa: E402
from byes.model_manifest import build_model_manifest  # noqa: E402


def _missing_required_total(manifest: dict[str, object]) -> int:
    summary = manifest.get("summary") if isinstance(manifest, dict) else None
    summary = summary if isinstance(summary, dict) else {}
    try:
        return int(summary.get("missingRequiredTotal", 0) or 0)
    except Exception:
        return 0


def _enabled_total(manifest: dict[str, object]) -> int:
    summary = manifest.get("summary") if isinstance(manifest, dict) else None
    summary = summary if isinstance(summary, dict) else {}
    try:
        return int(summary.get("enabledTotal", 0) or 0)
    except Exception:
        return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify required model/env/endpoint configuration for the current runtime.")
    parser.add_argument("--json", action="store_true", default=False, help="Print full byes.models.v1 JSON manifest")
    parser.add_argument(
        "--check",
        action="store_true",
        default=False,
        help="Exit non-zero when enabled components have missing required dependencies",
    )
    parser.add_argument("--quiet", action="store_true", default=False, help="Print one-line summary only")
    args = parser.parse_args(argv)

    manifest = build_model_manifest(load_config())
    missing = _missing_required_total(manifest)
    enabled = _enabled_total(manifest)

    if args.json:
        print(json.dumps(manifest, ensure_ascii=False, indent=2))
    elif args.quiet:
        print(f"models enabled={enabled} missingRequired={missing}")
    else:
        print("[models]")
        print(f"enabledTotal={enabled}")
        print(f"missingRequiredTotal={missing}")
        components = manifest.get("components") if isinstance(manifest, dict) else None
        components = components if isinstance(components, list) else []
        for component in components:
            if not isinstance(component, dict):
                continue
            name = str(component.get("name", "")).strip() or "unknown"
            provider = str(component.get("provider", "")).strip() or "none"
            is_enabled = bool(component.get("enabled"))
            required = component.get("required")
            required = required if isinstance(required, list) else []
            missing_count = 0
            for req in required:
                if not isinstance(req, dict):
                    continue
                if not bool(req.get("exists")):
                    missing_count += 1
            print(
                f"- {name}: enabled={is_enabled} provider={provider} missingRequired={missing_count} required={len(required)}"
            )

    if args.check and missing > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
