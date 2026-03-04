from __future__ import annotations

import os

from services.inference_service.providers.base import OCRProvider, RiskProvider, SegProvider, DetProvider, DepthProvider, SlamProvider
from services.inference_service.providers.depth_base import DepthMap, DepthProvider as RiskDepthProvider
from services.inference_service.providers.depth_midas import MidasOnnxDepthProvider
from services.inference_service.providers.depth_none import NoneDepthProvider
from services.inference_service.providers.onnx_depth import OnnxDepthProvider
from services.inference_service.providers.depth_synth import SynthDepthProvider
from services.inference_service.providers.http_seg import HttpSegProvider
from services.inference_service.providers.http_depth import HttpDepthProvider
from services.inference_service.providers.http_ocr import HttpOcrProvider
from services.inference_service.providers.http_slam import HttpSlamProvider
from services.inference_service.providers.heuristic_risk import HeuristicRiskProvider
from services.inference_service.providers.mock_det import MockDetProvider
from services.inference_service.providers.mock_seg import MockSegProvider
from services.inference_service.providers.mock_depth import MockDepthProvider
from services.inference_service.providers.mock_ocr import MockOcrProvider
from services.inference_service.providers.mock_slam import MockSlamProvider
from services.inference_service.providers.paddleocr_ocr import PaddleOcrProvider
from services.inference_service.providers.reference_ocr import ReferenceOcrProvider
from services.inference_service.providers.reference_risk import ReferenceRiskProvider
from services.inference_service.providers.tesseract_ocr import TesseractOcrProvider
from services.inference_service.providers.ultralytics_det import UltralyticsDetProvider
from services.inference_service.providers.yolo26_det import Yolo26DetProvider
from services.inference_service.providers.sam3_seg import Sam3SegProvider
from services.inference_service.providers.da3_depth import Da3DepthProvider


def create_ocr_provider(name: str | None = None) -> OCRProvider:
    provider = str(name or os.getenv("BYES_SERVICE_OCR_PROVIDER", "mock")).strip().lower()
    model_id = str(os.getenv("BYES_SERVICE_OCR_MODEL_ID", "")).strip() or None
    if provider == "http":
        endpoint = str(os.getenv("BYES_SERVICE_OCR_ENDPOINT", "")).strip()
        timeout_ms = int(str(os.getenv("BYES_SERVICE_OCR_TIMEOUT_MS", "1200")).strip() or "1200")
        return HttpOcrProvider(endpoint=endpoint, model_id=model_id, timeout_ms=timeout_ms)
    if provider == "reference":
        return ReferenceOcrProvider()
    if provider == "tesseract":
        return TesseractOcrProvider()
    if provider == "paddleocr":
        return PaddleOcrProvider()
    return MockOcrProvider(model_id=model_id)


def create_seg_provider(name: str | None = None) -> SegProvider:
    provider = str(name or os.getenv("BYES_SERVICE_SEG_PROVIDER", "mock")).strip().lower()
    model_id = str(os.getenv("BYES_SERVICE_SEG_MODEL_ID", "")).strip() or None
    if provider == "sam3":
        return Sam3SegProvider()
    if provider == "http":
        endpoint = str(os.getenv("BYES_SERVICE_SEG_ENDPOINT", "")).strip()
        timeout_ms = int(str(os.getenv("BYES_SERVICE_SEG_TIMEOUT_MS", "1200")).strip() or "1200")
        downstream = str(os.getenv("BYES_SERVICE_SEG_HTTP_DOWNSTREAM", "reference")).strip().lower() or "reference"
        tracking = str(os.getenv("BYES_SERVICE_SEG_HTTP_TRACKING", "0")).strip().lower() in {"1", "true", "yes", "on"}
        return HttpSegProvider(
            endpoint=endpoint,
            model_id=model_id,
            timeout_ms=timeout_ms,
            downstream=downstream,
            tracking=tracking,
        )
    return MockSegProvider(model_id=model_id)


def create_det_provider(name: str | None = None) -> DetProvider:
    provider = str(name or os.getenv("BYES_SERVICE_DET_PROVIDER", "mock")).strip().lower()
    model_id = str(os.getenv("BYES_SERVICE_DET_MODEL_ID", "")).strip() or None
    if provider == "yolo26":
        return Yolo26DetProvider()
    if provider == "ultralytics":
        return UltralyticsDetProvider()
    return MockDetProvider(model_id=model_id)


def create_depth_provider(name: str | None = None) -> DepthProvider:
    provider = str(name or os.getenv("BYES_SERVICE_DEPTH_PROVIDER", "mock")).strip().lower()
    if provider == "da3":
        return Da3DepthProvider()
    if provider == "onnx":
        return Da3DepthProvider()
    if provider not in {"mock", "http", "onnx", "none"}:
        provider = str(os.getenv("BYES_SERVICE_DEPTH_TOOL_PROVIDER", "mock")).strip().lower() or "mock"
    model_id = str(os.getenv("BYES_SERVICE_DEPTH_MODEL_ID", "")).strip() or None
    if provider == "none":
        return MockDepthProvider(model_id=model_id or "none-depth")
    if provider == "http":
        endpoint = str(os.getenv("BYES_SERVICE_DEPTH_ENDPOINT", "")).strip()
        timeout_ms = int(str(os.getenv("BYES_SERVICE_DEPTH_TIMEOUT_MS", "1200")).strip() or "1200")
        downstream = str(os.getenv("BYES_SERVICE_DEPTH_HTTP_DOWNSTREAM", "reference")).strip().lower() or "reference"
        ref_view_strategy = str(os.getenv("BYES_SERVICE_DEPTH_HTTP_REF_VIEW_STRATEGY", "")).strip() or None
        return HttpDepthProvider(
            endpoint=endpoint,
            model_id=model_id,
            timeout_ms=timeout_ms,
            downstream=downstream,
            ref_view_strategy=ref_view_strategy,
        )
    return MockDepthProvider(model_id=model_id)


def create_slam_provider(name: str | None = None) -> SlamProvider:
    provider = str(name or os.getenv("BYES_SERVICE_SLAM_PROVIDER", "mock")).strip().lower()
    model_id = str(os.getenv("BYES_SERVICE_SLAM_MODEL_ID", "")).strip() or None
    if provider == "http":
        endpoint = str(os.getenv("BYES_SERVICE_SLAM_ENDPOINT", "")).strip()
        timeout_ms = int(str(os.getenv("BYES_SERVICE_SLAM_TIMEOUT_MS", "1200")).strip() or "1200")
        return HttpSlamProvider(endpoint=endpoint, model_id=model_id, timeout_ms=timeout_ms)
    return MockSlamProvider(model_id=model_id)


__all__ = [
    "OCRProvider",
    "RiskProvider",
    "SegProvider",
    "DetProvider",
    "DepthProvider",
    "SlamProvider",
    "RiskDepthProvider",
    "DepthMap",
    "ReferenceOcrProvider",
    "TesseractOcrProvider",
    "PaddleOcrProvider",
    "MockOcrProvider",
    "HttpOcrProvider",
    "create_ocr_provider",
    "ReferenceRiskProvider",
    "HeuristicRiskProvider",
    "MockSegProvider",
    "HttpSegProvider",
    "create_seg_provider",
    "MockDetProvider",
    "UltralyticsDetProvider",
    "Yolo26DetProvider",
    "create_det_provider",
    "MockDepthProvider",
    "HttpDepthProvider",
    "Da3DepthProvider",
    "create_depth_provider",
    "NoneDepthProvider",
    "SynthDepthProvider",
    "MidasOnnxDepthProvider",
    "OnnxDepthProvider",
    "Sam3SegProvider",
    "MockSlamProvider",
    "HttpSlamProvider",
    "create_slam_provider",
]
