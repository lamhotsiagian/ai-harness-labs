"""Tracing with OpenTelemetry GenAI-style attributes (Chapter 20).

Spans are kept in memory, exported as JSONL for eval and training pipelines,
and optionally shipped as OTLP/HTTP JSON to any OTel backend (Langfuse, Phoenix,
Jaeger, Grafana Tempo) by setting OTEL_EXPORTER_OTLP_ENDPOINT.
"""
from __future__ import annotations

import base64
import json
import os
import threading
import time
import urllib.request
import uuid
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class Span:
    trace_id: str
    span_id: str
    parent_id: str | None
    name: str
    start: float
    end: float | None = None
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[dict] = field(default_factory=list)
    status: str = "ok"

    def set(self, **attrs: Any) -> None:
        self.attributes.update(attrs)

    def event(self, name: str, **attrs: Any) -> None:
        self.events.append({"name": name, "ts": time.time(), **attrs})


class Tracer:
    def __init__(self, service: str = "forge", resource: dict | None = None):
        self.service = service
        self.resource = resource or {}
        self.spans: list[Span] = []
        self._local = threading.local()

    def _stack(self) -> list[Span]:
        if not hasattr(self._local, "stack"):
            self._local.stack = []
        return self._local.stack

    @contextmanager
    def span(self, name: str, **attrs: Any):
        stack = self._stack()
        parent = stack[-1] if stack else None
        trace_id = parent.trace_id if parent else uuid.uuid4().hex
        s = Span(trace_id, uuid.uuid4().hex[:16], parent.span_id if parent else None, name,
                 time.time(), attributes={**self.resource, **attrs})
        stack.append(s)
        try:
            yield s
        except Exception as exc:
            s.status = "error"
            s.event("exception", type=type(exc).__name__, message=str(exc))
            raise
        finally:
            s.end = time.time()
            stack.pop()
            self.spans.append(s)

    # ------------------------------------------------------------- exporters
    def export_jsonl(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as fh:
            for s in self.spans:
                fh.write(json.dumps(asdict(s), default=str) + "\n")
        return path

    def to_otlp(self) -> dict:
        def val(v: Any) -> dict:
            if isinstance(v, bool):
                return {"boolValue": v}
            if isinstance(v, int):
                return {"intValue": str(v)}
            if isinstance(v, float):
                return {"doubleValue": v}
            return {"stringValue": str(v)}
        spans = [{
            "traceId": s.trace_id, "spanId": s.span_id, "parentSpanId": s.parent_id or "",
            "name": s.name, "kind": 1,
            "startTimeUnixNano": str(int(s.start * 1e9)), "endTimeUnixNano": str(int((s.end or s.start) * 1e9)),
            "attributes": [{"key": k, "value": val(v)} for k, v in s.attributes.items()],
            "status": {"code": 2 if s.status == "error" else 1},
        } for s in self.spans]
        return {"resourceSpans": [{
            "resource": {"attributes": [{"key": "service.name", "value": {"stringValue": self.service}}]},
            "scopeSpans": [{"scope": {"name": "forge"}, "spans": spans}]}]}

    def ship_otlp(self, endpoint: str | None = None) -> int:
        """POST spans to <endpoint>/v1/traces. Langfuse: set LANGFUSE_PUBLIC_KEY/SECRET_KEY."""
        endpoint = endpoint or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT")
        if not endpoint:
            return 0
        headers = {"content-type": "application/json"}
        pk, sk = os.environ.get("LANGFUSE_PUBLIC_KEY"), os.environ.get("LANGFUSE_SECRET_KEY")
        if pk and sk:
            headers["authorization"] = "Basic " + base64.b64encode(f"{pk}:{sk}".encode()).decode()
        req = urllib.request.Request(endpoint.rstrip("/") + "/v1/traces",
                                     data=json.dumps(self.to_otlp()).encode(), headers=headers)
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status
