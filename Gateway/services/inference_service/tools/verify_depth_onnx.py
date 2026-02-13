from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fp:
        while True:
            chunk = fp.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify ONNX depth model file hash")
    parser.add_argument("--path", required=True, help="Path to ONNX model file")
    parser.add_argument("--expected-sha256", default="", help="Optional expected sha256 hex")
    args = parser.parse_args()

    model_path = Path(str(args.path)).expanduser()
    if not model_path.exists() or not model_path.is_file():
        print(f"path: {model_path}")
        print("error: file does not exist")
        return 2

    file_size = model_path.stat().st_size
    sha256 = _sha256_file(model_path)
    expected = str(args.expected_sha256 or "").strip().lower()
    matched = (sha256.lower() == expected) if expected else None

    print(f"path: {model_path}")
    print(f"size_bytes: {file_size}")
    print(f"sha256: {sha256}")
    if expected:
        print(f"expected_sha256: {expected}")
        print(f"match: {matched}")
        return 0 if matched else 1
    print("match: n/a")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
