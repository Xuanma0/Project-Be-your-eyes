from __future__ import annotations

import argparse
import base64
import csv
import html
import json
import math
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Tuple

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.agent import AssistanceAgent
from app.evidence import Evidence
from app.planner import Planner
from app.vision import VisionToolchain


IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
VIDEO_SUFFIXES = {".mp4", ".mov", ".avi", ".mkv", ".webm"}
DEFAULT_QUESTION = "\u5e2e\u6211\u770b\u4e00\u4e0b\u753b\u9762\u91cc\u6709\u4ec0\u4e48"
DEFAULT_REACH_QUESTION = "\u5f15\u5bfc\u6211\u7684\u624b\u62ff\u8d77\u7ea2\u8272\u7f50\u5b50"


@dataclass
class FrameSource:
    frame: np.ndarray
    frame_index: int
    timestamp_s: float
    frame_shape: List[int]


@dataclass
class SampleAccumulator:
    sample_id: str
    variant: str
    media: str
    question: str
    mode: str
    expected: Dict[str, Any]
    frame_count: int = 0
    latencies_ms: List[float] = field(default_factory=list)
    target_seen: bool = False
    confirmed_target_seen: bool = False
    weak_target_seen: bool = False
    target_false_positive: bool = False
    position_hit: Optional[bool] = None
    hand_seen: bool = False
    hand_false_positive: bool = False
    safety_blocking_seen: bool = False
    expected_safety_blocking: Optional[bool] = None
    phase_hit: Optional[bool] = None
    required_speech_hit: Optional[bool] = None
    avoided_speech_hit: Optional[bool] = None
    final_phase: str = ""
    final_speech: str = ""
    errors: List[str] = field(default_factory=list)

    def update_from_frame(self, frame_result: Dict[str, Any], target_items: List[Dict[str, Any]]) -> None:
        self.frame_count += 1
        stats = frame_result.get("stats") or {}
        latency = stats.get("latency_ms")
        if isinstance(latency, (int, float)):
            self.latencies_ms.append(float(latency))

        speech = str(frame_result.get("speech") or "")
        if speech:
            self.final_speech = speech

        agent_state = frame_result.get("agent") or {}
        phase = str(agent_state.get("phase") or "")
        if phase:
            self.final_phase = phase

        evidence = frame_result.get("evidence") or []
        target_present = _expected_target_present(self.expected)
        if target_items:
            if target_present is False:
                self.target_false_positive = True
            else:
                self.target_seen = True
                self.confirmed_target_seen = self.confirmed_target_seen or any(
                    _target_kind(item) == "confirmed" for item in target_items
                )
                self.weak_target_seen = self.weak_target_seen or any(
                    _target_kind(item) == "weak" for item in target_items
                )

        hand_items = [item for item in evidence if item.get("type") == "hand"]
        if hand_items:
            if _expected_hand_present(self.expected) is False:
                self.hand_false_positive = True
            else:
                self.hand_seen = True

        safety = frame_result.get("safety") or {}
        if safety.get("blocking"):
            self.safety_blocking_seen = True

        phase_expect = _expected_phases(self.expected)
        if phase_expect:
            self.phase_hit = bool(self.phase_hit or phase in phase_expect)

        required = _as_text_list(self.expected.get("speech_contains"))
        if required:
            ok = all(text in speech for text in required)
            self.required_speech_hit = bool(self.required_speech_hit or ok)

        avoided = _as_text_list(self.expected.get("speech_avoids"))
        if avoided:
            ok = not any(text in speech for text in avoided)
            self.avoided_speech_hit = bool(self.avoided_speech_hit if self.avoided_speech_hit is not None else True) and ok

    def finalize(self) -> Dict[str, Any]:
        target_present = _expected_target_present(self.expected)
        if target_present is True:
            target_hit = self.target_seen
        elif target_present is False:
            target_hit = not self.target_false_positive
        else:
            target_hit = None

        hand_present = _expected_hand_present(self.expected)
        if hand_present is True:
            hand_hit = self.hand_seen
        elif hand_present is False:
            hand_hit = not self.hand_false_positive
        else:
            hand_hit = None

        safety_expected = _expected_safety_blocking(self.expected)
        self.expected_safety_blocking = safety_expected
        if safety_expected is None:
            safety_hit = None
        else:
            safety_hit = self.safety_blocking_seen == safety_expected

        checks = {
            "target_hit": target_hit,
            "position_hit": self.position_hit,
            "hand_hit": hand_hit,
            "safety_hit": safety_hit,
            "phase_hit": self.phase_hit,
            "speech_contains_hit": self.required_speech_hit,
            "speech_avoids_hit": self.avoided_speech_hit,
        }
        applicable = [1.0 if value else 0.0 for value in checks.values() if value is not None]
        score = round(sum(applicable) / len(applicable), 4) if applicable else 0.0

        return {
            "id": self.sample_id,
            "variant": self.variant,
            "media": self.media,
            "question": self.question,
            "mode": self.mode,
            "frames": self.frame_count,
            "score": score,
            "target_hit": target_hit,
            "target_confirmed": self.confirmed_target_seen,
            "target_weak": self.weak_target_seen,
            "position_hit": self.position_hit,
            "hand_hit": hand_hit,
            "safety_hit": safety_hit,
            "phase_hit": self.phase_hit,
            "speech_contains_hit": self.required_speech_hit,
            "speech_avoids_hit": self.avoided_speech_hit,
            "final_phase": self.final_phase,
            "final_speech": self.final_speech,
            "latency_avg_ms": round(sum(self.latencies_ms) / len(self.latencies_ms), 1) if self.latencies_ms else 0.0,
            "latency_p95_ms": round(_percentile(self.latencies_ms, 0.95), 1) if self.latencies_ms else 0.0,
            "errors": "; ".join(self.errors),
        }


class OfflinePipeline:
    def __init__(self, variant: str = "full") -> None:
        self.variant = variant
        self.vision = VisionToolchain()
        self.planner = Planner()
        self.agent = AssistanceAgent()
        self.memory: List[Dict[str, Any]] = []

    def reset(self) -> None:
        self.agent.reset()
        self.memory = []

    def analyze(self, frame: np.ndarray, question: str, mode: str) -> Dict[str, Any]:
        plan = self.planner.plan_tools(question, mode)
        if self.variant == "detect_only":
            plan = dict(plan)
            plan["tools"] = sorted({"detect", "safety"})
            if not plan.get("target_en"):
                plan["intent"] = "describe"
        start = time.time()
        result = self.vision.analyze(frame, plan)
        current = [item.to_dict() if isinstance(item, Evidence) else item for item in result["evidence"]]
        self.memory.extend(current)
        self.memory = self.memory[-160:]

        if self.variant == "no_agent":
            evidence_for_answer = current
            agent_state: Dict[str, Any] = {"active": False, "phase": "disabled"}
            answer = self.planner.compose_answer(
                question=question,
                mode=mode,
                plan=plan,
                current_evidence=evidence_for_answer,
                memory=self.memory,
                safety=result["safety"],
                quality=result["quality"],
            )
        else:
            agent_context = self.agent.update(
                question=question,
                mode=mode,
                plan=plan,
                current_evidence=current,
                recent_evidence=self.memory,
                quality=result["quality"],
                safety=result["safety"],
            )
            evidence_for_answer = agent_context["evidence"]
            agent_state = agent_context["agent"]
            answer = self.planner.compose_answer(
                question=question,
                mode=mode,
                plan=plan,
                current_evidence=evidence_for_answer,
                memory=self.memory,
                safety=result["safety"],
                quality=result["quality"],
            )
            answer = self.agent.refine_answer(answer, mode, agent_state)
            agent_state = answer.get("agent", agent_state)

        stats = dict(result.get("stats") or {})
        stats["eval_wall_ms"] = round((time.time() - start) * 1000, 1)
        return {
            "action": answer.get("action"),
            "speech": answer.get("speech"),
            "confidence": float(answer.get("confidence", 0.0)),
            "planner": answer.get("planner"),
            "plan": plan,
            "quality": result["quality"],
            "safety": result["safety"],
            "evidence": evidence_for_answer,
            "stats": stats,
            "agent": agent_state,
            "annotated_image": result.get("annotated_image", ""),
        }


def cmd_record(args: argparse.Namespace) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    cap = cv2.VideoCapture(int(args.camera), cv2.CAP_DSHOW)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, int(args.width))
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, int(args.height))
    cap.set(cv2.CAP_PROP_FPS, float(args.fps))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open camera index {args.camera}")

    suffix = out.suffix.lower()
    fourcc = cv2.VideoWriter_fourcc(*("MJPG" if suffix == ".avi" else "mp4v"))
    writer = cv2.VideoWriter(str(out), fourcc, float(args.fps), (int(args.width), int(args.height)))
    if not writer.isOpened():
        cap.release()
        raise RuntimeError(f"Could not open video writer: {out}")

    deadline = time.time() + float(args.seconds)
    frames = 0
    try:
        while time.time() < deadline:
            ok, frame = cap.read()
            if ok and frame is not None:
                frame = cv2.resize(frame, (int(args.width), int(args.height)))
                writer.write(frame)
                frames += 1
            time.sleep(max(0.0, 1.0 / max(1.0, float(args.fps)) - 0.005))
    finally:
        writer.release()
        cap.release()
    print(f"recorded {frames} frames -> {out}")
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    media_dir = Path(args.media_dir)
    out = Path(args.out)
    if not media_dir.exists():
        raise FileNotFoundError(media_dir)
    media_paths = sorted(
        path for path in media_dir.rglob("*") if path.suffix.lower() in IMAGE_SUFFIXES | VIDEO_SUFFIXES
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as fh:
        for index, path in enumerate(media_paths, 1):
            sample = {
                "id": path.stem or f"sample_{index:04d}",
                "media": _relative_or_absolute(path, out.parent),
                "question": args.question,
                "mode": args.mode,
                "sample_fps": float(args.sample_fps),
                "expect": {
                    "target": {
                        "present": None,
                        "label": "",
                        "color": "",
                        "position": "",
                    },
                    "hand": {"present": None},
                    "safety": {"blocking": None},
                    "final_phases": [],
                    "speech_contains": [],
                    "speech_avoids": [],
                },
            }
            fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
    print(f"wrote {len(media_paths)} samples -> {out}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    out = Path(args.out)
    media_dir = out / "media"
    media_dir.mkdir(parents=True, exist_ok=True)
    manifest = out / "manifest.demo.jsonl"
    image_path = media_dir / "red_can_demo.jpg"
    _write_demo_image(image_path)
    sample = {
        "id": "demo_red_can_find",
        "media": _relative_or_absolute(image_path, manifest.parent),
        "question": "\u5e2e\u6211\u627e\u4e00\u4e0b\u7ea2\u8272\u7684\u7f50\u5b50\u5728\u54ea\u91cc",
        "mode": "find",
        "sample_fps": 1.0,
        "expect": {
            "target": {"present": True, "label": "can", "color": "red", "position": "left"},
            "hand": {"present": False},
            "safety": {"blocking": False},
            "speech_contains": [],
            "speech_avoids": [],
        },
    }
    with manifest.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(sample, ensure_ascii=False) + "\n")
    print(f"demo manifest -> {manifest}")
    if args.run:
        run_out = out / "run"
        run_args = argparse.Namespace(
            manifest=str(manifest),
            out=str(run_out),
            variant=args.variant,
            sample_fps=0.0,
            every_n=1,
            max_frames=1,
            max_samples=0,
            save_annotated=True,
        )
        return cmd_run(run_args)
    print("run it with:")
    print(f"  .\\.venv\\Scripts\\python.exe scripts\\eval_toolchain.py run --manifest {manifest} --out {out / 'run'}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    manifest_path = Path(args.manifest)
    out_dir = Path(args.out) if args.out else ROOT / "data" / "eval" / "runs" / time.strftime("%Y%m%d-%H%M%S")
    out_dir.mkdir(parents=True, exist_ok=True)
    samples = load_manifest(manifest_path)
    if args.max_samples and args.max_samples > 0:
        samples = samples[: int(args.max_samples)]
    pipeline = OfflinePipeline(variant=args.variant)
    frame_jsonl = out_dir / "frames.jsonl"
    sample_csv = out_dir / "samples.csv"
    summaries: List[Dict[str, Any]] = []

    with frame_jsonl.open("w", encoding="utf-8", newline="\n") as frame_fh:
        for sample in samples:
            pipeline.reset()
            sample_id = str(sample.get("id") or Path(str(sample.get("media") or "")).stem)
            media_path = resolve_media_path(manifest_path, str(sample.get("media") or ""))
            question = str(sample.get("question") or DEFAULT_QUESTION)
            mode = str(sample.get("mode") or "ask")
            expected = dict(sample.get("expect") or sample.get("expected") or {})
            sample_fps = float(sample.get("sample_fps") or args.sample_fps or 0.0)
            every_n = int(sample.get("every_n") or args.every_n or 1)
            accumulator = SampleAccumulator(
                sample_id=sample_id,
                variant=args.variant,
                media=str(media_path),
                question=question,
                mode=mode,
                expected=expected,
            )
            try:
                for frame_source in iter_media_frames(
                    media_path,
                    sample_fps=sample_fps,
                    every_n=every_n,
                    max_frames=int(args.max_frames or sample.get("max_frames") or 0),
                ):
                    result = pipeline.analyze(frame_source.frame, question, mode)
                    target_items = [
                        item
                        for item in result.get("evidence", [])
                        if item_matches_expected_target(item, expected.get("target") or {}, frame_source.frame_shape)
                    ]
                    update_position_metric(accumulator, target_items, expected.get("target") or {}, frame_source.frame_shape)
                    accumulator.update_from_frame(result, target_items)
                    annotated_path = ""
                    if args.save_annotated and result.get("annotated_image"):
                        annotated_path = save_data_url_image(
                            result["annotated_image"],
                            out_dir / "annotated" / f"{sample_id}_{frame_source.frame_index:06d}.jpg",
                        )
                    frame_record = compact_frame_record(
                        sample_id,
                        media_path,
                        frame_source,
                        result,
                        target_items,
                        annotated_path,
                    )
                    frame_fh.write(json.dumps(frame_record, ensure_ascii=False) + "\n")
                    frame_fh.flush()
            except Exception as exc:
                accumulator.errors.append(repr(exc))
            summaries.append(accumulator.finalize())

    write_samples_csv(sample_csv, summaries)
    summary = make_summary(summaries, args.variant, manifest_path)
    summary_path = out_dir / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    write_html_report(out_dir / "report.html", summary, summaries)
    print(f"frames  -> {frame_jsonl}")
    print(f"samples -> {sample_csv}")
    print(f"summary -> {summary_path}")
    print(f"report  -> {out_dir / 'report.html'}")
    print(f"score={summary['score_avg']:.3f} samples={summary['samples']} latency_p95={summary['latency_p95_ms']:.1f}ms")
    return 0


def load_manifest(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return []
    if path.suffix.lower() == ".json":
        data = json.loads(text)
        if isinstance(data, dict) and "samples" in data:
            return list(data["samples"])
        if isinstance(data, list):
            return data
        raise ValueError("JSON manifest must be a list or {'samples': [...]}")
    samples = []
    for line_no, line in enumerate(text.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        try:
            samples.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path}:{line_no}: invalid JSONL: {exc}") from exc
    return samples


def iter_media_frames(path: Path, sample_fps: float = 0.0, every_n: int = 1, max_frames: int = 0) -> Iterator[FrameSource]:
    suffix = path.suffix.lower()
    if suffix in IMAGE_SUFFIXES:
        frame = cv2.imread(str(path), cv2.IMREAD_COLOR)
        if frame is None:
            raise RuntimeError(f"Could not read image: {path}")
        yield FrameSource(frame=frame, frame_index=0, timestamp_s=0.0, frame_shape=list(frame.shape))
        return
    if suffix not in VIDEO_SUFFIXES:
        raise ValueError(f"Unsupported media suffix: {path.suffix}")
    cap = cv2.VideoCapture(str(path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {path}")
    native_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
    stride = max(1, int(every_n))
    if sample_fps > 0 and native_fps > 0:
        stride = max(1, int(round(native_fps / sample_fps)))
    frame_index = -1
    yielded = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame is None:
                break
            frame_index += 1
            if frame_index % stride != 0:
                continue
            timestamp_s = frame_index / native_fps if native_fps > 0 else 0.0
            yield FrameSource(frame=frame, frame_index=frame_index, timestamp_s=timestamp_s, frame_shape=list(frame.shape))
            yielded += 1
            if max_frames and yielded >= max_frames:
                break
    finally:
        cap.release()


def item_matches_expected_target(item: Dict[str, Any], target: Dict[str, Any], frame_shape: List[int]) -> bool:
    if item.get("type") != "object":
        return False
    attrs = item.get("attributes") or {}
    if attrs.get("target_rejected_by") or attrs.get("target_color_mismatch") or attrs.get("duplicate_of"):
        return False
    label = str(item.get("label") or "").lower()
    label_zh = str(attrs.get("label_zh") or item.get("text") or "")
    expected_label = str(target.get("label") or target.get("target_en") or "").lower().strip()
    aliases = {expected_label}
    aliases.update(str(value).lower().strip() for value in target.get("aliases") or [] if str(value).strip())
    if expected_label == "can":
        aliases.update({"can", "tin can", "food can", "snack can", "cylindrical can", "cup", "mug", "jar", "carton", "box"})
    label_ok = False
    if attrs.get("target_match") or attrs.get("agent_primary_target") or attrs.get("weak_target_match"):
        label_ok = True
    elif expected_label:
        label_ok = any(alias and alias in label for alias in aliases)
    else:
        label_ok = bool(label or label_zh)
    if not label_ok:
        return False
    expected_color = str(target.get("color") or "").lower().strip()
    if expected_color and not color_matches(item, expected_color):
        return False
    return True


def color_matches(item: Dict[str, Any], expected_color: str) -> bool:
    label = str(item.get("label") or "").lower()
    attrs = item.get("attributes") or {}
    if expected_color in label:
        return True
    if attrs.get("target_color") == expected_color:
        return True
    color_score = float(attrs.get("color_score") or 0.0)
    thresholds = {
        "red": 0.12,
        "green": 0.12,
        "blue": 0.12,
        "yellow": 0.10,
        "black": 0.12,
        "white": 0.16,
    }
    return color_score >= thresholds.get(expected_color, 0.14)


def update_position_metric(
    accumulator: SampleAccumulator,
    target_items: List[Dict[str, Any]],
    target_expect: Dict[str, Any],
    frame_shape: List[int],
) -> None:
    expected = _position_tokens(str(target_expect.get("position") or ""))
    if not expected:
        return
    if accumulator.position_hit is True:
        return
    if not target_items:
        accumulator.position_hit = bool(accumulator.position_hit)
        return
    hit = any(expected.issubset(item_position_tokens(item, frame_shape)) for item in target_items)
    accumulator.position_hit = bool(accumulator.position_hit or hit)


def item_position_tokens(item: Dict[str, Any], frame_shape: List[int]) -> set[str]:
    bbox = item.get("bbox") or []
    tokens: set[str] = set()
    if isinstance(bbox, list) and len(bbox) >= 4 and len(frame_shape) >= 2:
        h = float(frame_shape[0] or 1)
        w = float(frame_shape[1] or 1)
        cx = (float(bbox[0]) + float(bbox[2])) / 2.0 / w
        cy = (float(bbox[1]) + float(bbox[3])) / 2.0 / h
        tokens.add("left" if cx < 0.38 else "right" if cx > 0.62 else "center")
        tokens.add("top" if cy < 0.38 else "bottom" if cy > 0.62 else "middle")
    tokens.update(_position_tokens(str(item.get("position") or "")))
    return tokens


def compact_frame_record(
    sample_id: str,
    media_path: Path,
    frame_source: FrameSource,
    result: Dict[str, Any],
    target_items: List[Dict[str, Any]],
    annotated_path: str,
) -> Dict[str, Any]:
    evidence = []
    for item in result.get("evidence", [])[:80]:
        attrs = dict(item.get("attributes") or {})
        evidence.append(
            {
                "id": item.get("id"),
                "type": item.get("type"),
                "label": item.get("label"),
                "source": item.get("source"),
                "confidence": item.get("confidence"),
                "position": item.get("position"),
                "bbox": item.get("bbox"),
                "text": item.get("text"),
                "attributes": {
                    key: attrs.get(key)
                    for key in [
                        "label_zh",
                        "target_match",
                        "weak_target_match",
                        "agent_primary_target",
                        "agent_target_kind",
                        "color_score",
                        "gesture",
                        "motion",
                    ]
                    if key in attrs
                },
            }
        )
    return {
        "sample_id": sample_id,
        "media": str(media_path),
        "frame_index": frame_source.frame_index,
        "timestamp_s": round(frame_source.timestamp_s, 3),
        "action": result.get("action"),
        "speech": result.get("speech"),
        "confidence": result.get("confidence"),
        "planner": result.get("planner"),
        "target_count": len(target_items),
        "agent": result.get("agent"),
        "quality": result.get("quality"),
        "safety": result.get("safety"),
        "stats": result.get("stats"),
        "evidence": evidence,
        "annotated": annotated_path,
    }


def write_samples_csv(path: Path, rows: List[Dict[str, Any]]) -> None:
    fieldnames = [
        "id",
        "variant",
        "frames",
        "score",
        "target_hit",
        "target_confirmed",
        "target_weak",
        "position_hit",
        "hand_hit",
        "safety_hit",
        "phase_hit",
        "speech_contains_hit",
        "speech_avoids_hit",
        "final_phase",
        "latency_avg_ms",
        "latency_p95_ms",
        "mode",
        "question",
        "media",
        "errors",
    ]
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})


def make_summary(rows: List[Dict[str, Any]], variant: str, manifest_path: Path) -> Dict[str, Any]:
    scores = [float(row.get("score") or 0.0) for row in rows]
    latencies = [float(row.get("latency_p95_ms") or 0.0) for row in rows if float(row.get("latency_p95_ms") or 0.0) > 0]
    return {
        "variant": variant,
        "manifest": str(manifest_path),
        "samples": len(rows),
        "score_avg": round(sum(scores) / len(scores), 4) if scores else 0.0,
        "latency_p95_ms": round(_percentile(latencies, 0.95), 1) if latencies else 0.0,
        "target_hit_rate": _rate(rows, "target_hit"),
        "target_confirmed_rate": _rate(rows, "target_confirmed"),
        "position_hit_rate": _rate(rows, "position_hit"),
        "hand_hit_rate": _rate(rows, "hand_hit"),
        "safety_hit_rate": _rate(rows, "safety_hit"),
        "phase_hit_rate": _rate(rows, "phase_hit"),
        "speech_contains_hit_rate": _rate(rows, "speech_contains_hit"),
        "speech_avoids_hit_rate": _rate(rows, "speech_avoids_hit"),
        "created_at": time.strftime("%Y-%m-%d %H:%M:%S"),
    }


def write_html_report(path: Path, summary: Dict[str, Any], rows: List[Dict[str, Any]]) -> None:
    cards = [
        ("Score", f"{summary['score_avg']:.3f}"),
        ("Samples", str(summary["samples"])),
        ("Target Hit", _fmt_rate(summary["target_hit_rate"])),
        ("Position Hit", _fmt_rate(summary["position_hit_rate"])),
        ("Hand Hit", _fmt_rate(summary["hand_hit_rate"])),
        ("Phase Hit", _fmt_rate(summary["phase_hit_rate"])),
        ("Latency P95", f"{summary['latency_p95_ms']:.1f} ms"),
    ]
    card_html = "\n".join(
        f"<div class='card'><div class='label'>{html.escape(label)}</div><div class='value'>{html.escape(value)}</div></div>"
        for label, value in cards
    )
    rows_html = "\n".join(
        "<tr>"
        + "".join(
            f"<td>{html.escape(str(row.get(key, '')))}</td>"
            for key in [
                "id",
                "score",
                "target_hit",
                "target_confirmed",
                "target_weak",
                "position_hit",
                "hand_hit",
                "phase_hit",
                "final_phase",
                "latency_p95_ms",
                "errors",
            ]
        )
        + "</tr>"
        for row in rows
    )
    doc = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <title>Be Your Eyes Eval Report</title>
  <style>
    body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; margin: 28px; color: #172026; }}
    h1 {{ font-size: 24px; margin: 0 0 6px; }}
    .meta {{ color: #60707c; margin-bottom: 18px; }}
    .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 18px 0 24px; }}
    .card {{ border: 1px solid #d8e1e6; border-radius: 8px; padding: 12px; }}
    .label {{ color: #60707c; font-size: 12px; }}
    .value {{ font-size: 22px; font-weight: 700; margin-top: 4px; }}
    table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
    th, td {{ border-bottom: 1px solid #e4eaee; padding: 8px; text-align: left; vertical-align: top; }}
    th {{ background: #f6f8fa; color: #34424c; position: sticky; top: 0; }}
  </style>
</head>
<body>
  <h1>Be Your Eyes Eval Report</h1>
  <div class="meta">variant={html.escape(str(summary["variant"]))} · created={html.escape(str(summary["created_at"]))}</div>
  <div class="cards">{card_html}</div>
  <table>
    <thead>
      <tr>
        <th>ID</th><th>Score</th><th>Target</th><th>Confirmed</th><th>Weak</th><th>Position</th>
        <th>Hand</th><th>Phase</th><th>Final Phase</th><th>P95 ms</th><th>Errors</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</body>
</html>
"""
    path.write_text(doc, encoding="utf-8")


def save_data_url_image(data_url: str, path: Path) -> str:
    if "," not in data_url:
        return ""
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = base64.b64decode(data_url.split(",", 1)[1])
    path.write_bytes(raw)
    return str(path)


def resolve_media_path(manifest_path: Path, media: str) -> Path:
    path = Path(media)
    if path.is_absolute():
        return path
    candidate = manifest_path.parent / path
    if candidate.exists():
        return candidate
    return ROOT / path


def _relative_or_absolute(path: Path, base: Path) -> str:
    try:
        return str(path.resolve().relative_to(base.resolve())).replace("\\", "/")
    except ValueError:
        try:
            return str(path.resolve().relative_to(ROOT.resolve())).replace("\\", "/")
        except ValueError:
            return str(path)


def _write_demo_image(path: Path) -> None:
    img = np.full((720, 1280, 3), 242, dtype=np.uint8)
    cv2.rectangle(img, (190, 250), (390, 610), (38, 38, 220), -1)
    cv2.ellipse(img, (290, 250), (100, 22), 0, 0, 360, (230, 230, 230), -1)
    cv2.ellipse(img, (290, 610), (100, 18), 0, 0, 360, (150, 150, 150), -1)
    cv2.rectangle(img, (520, 250), (720, 610), (40, 160, 60), -1)
    cv2.ellipse(img, (620, 250), (100, 22), 0, 0, 360, (230, 230, 230), -1)
    cv2.rectangle(img, (810, 350), (1120, 560), (195, 165, 120), -1)
    cv2.putText(img, "RED CAN", (215, 430), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 3)
    cv2.putText(img, "GREEN CAN", (535, 430), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 3)
    path.parent.mkdir(parents=True, exist_ok=True)
    ok = cv2.imwrite(str(path), img)
    if not ok:
        raise RuntimeError(f"Could not write demo image: {path}")


def _target_kind(item: Dict[str, Any]) -> str:
    attrs = item.get("attributes") or {}
    if attrs.get("agent_target_kind"):
        return str(attrs["agent_target_kind"])
    if attrs.get("weak_target_match"):
        return "weak"
    return "confirmed"


def _position_tokens(text: str) -> set[str]:
    lowered = text.lower().strip()
    tokens: set[str] = set()
    if not lowered:
        return tokens
    if "left" in lowered or "\u5de6" in lowered:
        tokens.add("left")
    if "right" in lowered or "\u53f3" in lowered:
        tokens.add("right")
    if "center" in lowered or "middle" in lowered or "\u4e2d" in lowered or "\u6b63\u524d" in lowered:
        tokens.add("center")
    if "top" in lowered or "up" in lowered or "\u4e0a" in lowered:
        tokens.add("top")
    if "bottom" in lowered or "down" in lowered or "\u4e0b" in lowered:
        tokens.add("bottom")
    return tokens


def _expected_target_present(expected: Dict[str, Any]) -> Optional[bool]:
    target = expected.get("target") or {}
    value = target.get("present")
    return value if isinstance(value, bool) else None


def _expected_hand_present(expected: Dict[str, Any]) -> Optional[bool]:
    hand = expected.get("hand") or {}
    value = hand.get("present")
    return value if isinstance(value, bool) else None


def _expected_safety_blocking(expected: Dict[str, Any]) -> Optional[bool]:
    safety = expected.get("safety") or {}
    value = safety.get("blocking")
    return value if isinstance(value, bool) else None


def _expected_phases(expected: Dict[str, Any]) -> set[str]:
    phases = set(_as_text_list(expected.get("final_phases")))
    phases.update(_as_text_list(expected.get("agent_phases")))
    phase = str(expected.get("agent_phase") or "").strip()
    if phase:
        phases.add(phase)
    return phases


def _as_text_list(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [str(item) for item in value if str(item)]
    return []


def _percentile(values: Iterable[float], q: float) -> float:
    data = sorted(float(value) for value in values)
    if not data:
        return 0.0
    if len(data) == 1:
        return data[0]
    pos = (len(data) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return data[lo]
    return data[lo] * (hi - pos) + data[hi] * (pos - lo)


def _rate(rows: List[Dict[str, Any]], key: str) -> Optional[float]:
    values = [row.get(key) for row in rows if row.get(key) is not None and row.get(key) != ""]
    if not values:
        return None
    return round(sum(1 for value in values if value is True) / len(values), 4)


def _fmt_rate(value: Optional[float]) -> str:
    if value is None:
        return "n/a"
    return f"{value * 100:.1f}%"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Offline benchmark runner for the Be Your Eyes toolchain.")
    sub = parser.add_subparsers(dest="command", required=True)

    record = sub.add_parser("record", help="Record a short camera clip for evaluation.")
    record.add_argument("--out", required=True, help="Output video path, e.g. data/eval/media/red_can_001.mp4")
    record.add_argument("--camera", type=int, default=0)
    record.add_argument("--seconds", type=float, default=12.0)
    record.add_argument("--width", type=int, default=1280)
    record.add_argument("--height", type=int, default=720)
    record.add_argument("--fps", type=float, default=20.0)
    record.set_defaults(func=cmd_record)

    init = sub.add_parser("init", help="Create a JSONL manifest template from a media folder.")
    init.add_argument("--media-dir", required=True)
    init.add_argument("--out", required=True)
    init.add_argument("--question", default=DEFAULT_REACH_QUESTION)
    init.add_argument("--mode", default="auto_assist")
    init.add_argument("--sample-fps", type=float, default=2.0)
    init.set_defaults(func=cmd_init)

    demo = sub.add_parser("demo", help="Create a tiny synthetic demo manifest.")
    demo.add_argument("--out", default=str(ROOT / "data" / "eval" / "demo"))
    demo.add_argument("--run", action="store_true")
    demo.add_argument("--variant", choices=["full", "no_agent", "detect_only"], default="full")
    demo.set_defaults(func=cmd_demo)

    run = sub.add_parser("run", help="Run offline evaluation from a manifest.")
    run.add_argument("--manifest", required=True)
    run.add_argument("--out", default="")
    run.add_argument("--variant", choices=["full", "no_agent", "detect_only"], default="full")
    run.add_argument("--sample-fps", type=float, default=0.0, help="Override video sampling FPS if a sample does not set it.")
    run.add_argument("--every-n", type=int, default=1, help="Video frame stride when sample_fps is not set.")
    run.add_argument("--max-frames", type=int, default=0, help="Limit frames per sample. 0 means no limit.")
    run.add_argument("--max-samples", type=int, default=0, help="Limit samples for a smoke run. 0 means all.")
    run.add_argument("--save-annotated", action="store_true", help="Save annotated frames to the run folder.")
    run.set_defaults(func=cmd_run)
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
