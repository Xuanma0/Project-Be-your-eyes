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
    intent_frames = {1, 2, 4}

    metrics = compute_ocr_metrics(gt_map, pred_map, frames_total=4, intent_frames=intent_frames)
    assert metrics["framesTotal"] == 4
    assert metrics["framesWithGt"] == 3
    assert metrics["framesWithPred"] == 2
    assert metrics["coverage"] == 0.5
    assert metrics["resultCoverage"] == 0.5
    assert metrics["intentCoverage"] == 0.75
    assert metrics["framesWithGtAndPred"] == 2
    assert abs(metrics["gtHitRate"] - (2.0 / 3.0)) < 1e-9
    assert metrics["framesPredButGtEmpty"] == 0
    assert metrics["falsePositiveRate"] == 0.0
    assert abs(metrics["exactMatchRate"] - (1.0 / 3.0)) < 1e-9
    assert abs(metrics["cer"] - (2.0 / 13.0)) < 1e-9
    assert abs(metrics["wer"] - 0.5) < 1e-9
    assert metrics["latencyMs"]["count"] == 2
    assert metrics["latencyMs"]["p50"] == 100
    assert metrics["latencyMs"]["p90"] == 120
    mismatches = metrics["topMismatches"]
    assert len(mismatches) == 1
    assert mismatches[0]["frameSeq"] == 2
