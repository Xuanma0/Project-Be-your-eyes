from __future__ import annotations

import os
import re
import secrets
from contextlib import contextmanager, nullcontext
from dataclasses import dataclass
from typing import Any, Iterator

from fastapi import FastAPI

try:
    from opentelemetry import trace
    from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
    from opentelemetry.propagate import extract, inject
    from opentelemetry.sdk.resources import SERVICE_NAME, Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter

    _OTEL_AVAILABLE = True
except Exception:  # noqa: BLE001
    _OTEL_AVAILABLE = False

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-[0-9a-f]{2}$")


@dataclass(frozen=True)
class TraceInfo:
    trace_id: str
    span_id: str
    context: Any | None = None


class Observability:
    def __init__(self, service_name: str = "byes-gateway") -> None:
        self._enabled = _OTEL_AVAILABLE
        self._tracer = None
        self._instrumented = False
        if not self._enabled:
            return

        current_provider = trace.get_tracer_provider()
        if not isinstance(current_provider, TracerProvider):
            resource = Resource.create({SERVICE_NAME: service_name})
            provider = TracerProvider(resource=resource)
            if os.getenv("BYES_OTEL_CONSOLE_EXPORT", "0").strip().lower() in {"1", "true", "yes", "on"}:
                provider.add_span_processor(BatchSpanProcessor(ConsoleSpanExporter()))
            trace.set_tracer_provider(provider)
        self._tracer = trace.get_tracer(service_name)

    @property
    def enabled(self) -> bool:
        return self._enabled

    def instrument_app(self, app: FastAPI) -> None:
        if not self._enabled or self._instrumented:
            return
        FastAPIInstrumentor.instrument_app(app)
        self._instrumented = True

    def extract_trace(self, headers: dict[str, str] | Any) -> TraceInfo:
        carrier = {str(k).lower(): str(v) for k, v in dict(headers).items()}
        parsed_trace_id, parsed_span_id = self._parse_traceparent(carrier.get("traceparent", ""))

        if not self._enabled:
            return TraceInfo(
                trace_id=parsed_trace_id or self._new_trace_id(),
                span_id=parsed_span_id or self._new_span_id(),
                context=None,
            )

        ctx = extract(carrier)
        span_context = trace.get_current_span(ctx).get_span_context()
        if span_context.is_valid:
            return TraceInfo(
                trace_id=f"{span_context.trace_id:032x}",
                span_id=f"{span_context.span_id:016x}",
                context=ctx,
            )

        return TraceInfo(
            trace_id=parsed_trace_id or self._new_trace_id(),
            span_id=parsed_span_id or self._new_span_id(),
            context=ctx,
        )

    @contextmanager
    def start_span(self, name: str, trace_info: TraceInfo | None = None, **attributes: Any) -> Iterator[Any]:
        if not self._enabled or self._tracer is None:
            with nullcontext() as ctx:
                yield ctx
            return

        ctx = trace_info.context if trace_info is not None else None
        with self._tracer.start_as_current_span(name, context=ctx) as span:
            for key, value in attributes.items():
                span.set_attribute(key, value)
            yield span

    def inject_headers(self, trace_info: TraceInfo) -> dict[str, str]:
        if not self._enabled:
            return {"traceparent": self._build_traceparent(trace_info.trace_id, trace_info.span_id)}

        carrier: dict[str, str] = {}
        inject(carrier=carrier, context=trace_info.context)
        if "traceparent" not in carrier:
            carrier["traceparent"] = self._build_traceparent(trace_info.trace_id, trace_info.span_id)
        return carrier

    @staticmethod
    def _parse_traceparent(value: str) -> tuple[str | None, str | None]:
        match = _TRACEPARENT_RE.match(value.strip().lower())
        if not match:
            return None, None
        return match.group(1), match.group(2)

    @staticmethod
    def _build_traceparent(trace_id: str, span_id: str) -> str:
        return f"00-{trace_id}-{span_id}-01"

    @staticmethod
    def _new_trace_id() -> str:
        return secrets.token_hex(16)

    @staticmethod
    def _new_span_id() -> str:
        return secrets.token_hex(8)
