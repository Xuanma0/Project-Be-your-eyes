from __future__ import annotations

from byes.quality_metrics import compute_ocr_metrics, levenshtein


def test_levenshtein_basic() -> None:
    assert levenshtein("kitten", "sitting") == 3
    assert levenshtein(["a", "b"], ["a", "c", "b"]) == 1


def test_compute_ocr_metrics() -> None:
    gt_map = {
        1: "EXIT",
        2: "NO ENTRY",
        3: "A",
    }
    pred_map = {
        1: {"text": "EXIT", "latencyMs": 100},
        2: {"text": "NO ENTRI", "latencyMs": 120},
    }

    metrics = compute_ocr_metrics(gt_map, pred_map, frames_total=4)
    assert metrics["framesTotal"] == 4
    assert metrics["framesWithGt"] == 3
    assert metrics["framesWithPred"] == 2
    assert metrics["coverage"] == 0.5
    assert abs(metrics["exactMatchRate"] - (1.0 / 3.0)) < 1e-9
    assert abs(metrics["cer"] - (2.0 / 13.0)) < 1e-9
    assert abs(metrics["wer"] - 0.5) < 1e-9
    assert metrics["latencyMs"]["count"] == 2
    assert metrics["latencyMs"]["p50"] == 100
    assert metrics["latencyMs"]["p90"] == 120
