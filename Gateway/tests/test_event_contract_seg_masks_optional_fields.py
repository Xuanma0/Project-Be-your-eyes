from services.inference_service.app import _normalize_seg_mask


def test_seg_mask_fields_optional_when_absent() -> None:
    assert _normalize_seg_mask(None) is None


def test_seg_mask_normalizer_accepts_valid_rle() -> None:
    payload = _normalize_seg_mask({"format": "rle_v1", "size": [2, 3], "counts": [1, 1, 2, 2]})
    assert isinstance(payload, dict)
    assert payload["format"] == "rle_v1"
    assert payload["size"] == [2, 3]
    assert payload["counts"] == [1, 1, 2, 2]


def test_seg_mask_normalizer_rejects_invalid_shape() -> None:
    assert _normalize_seg_mask({"format": "rle_v1", "size": [2, 3], "counts": [1, 2]}) is None
