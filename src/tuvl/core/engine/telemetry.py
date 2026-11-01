"""OpenTelemetry initialisation for tuvl.

Call ``init_telemetry()`` once during the FastAPI startup lifecycle
(``app.py`` lifespan).  All configuration is read from ``settings``
(``src/tuvl/core/config.py``) which respects ``.env`` files and
environment variables via pydantic-settings.

Dev mode (``TUVL_DEV_MODE=true``)
    ``init_telemetry`` is a no-op.  The default OTel SDK yields
    ``NonRecordingSpan`` objects — no exporter is attached, so zero bytes leave
    the process.  Insight reads runs from the journal, not from spans.

Prod mode (``TUVL_DEV_MODE=false``)
    When ``TUVL_TELEMETRY_ENABLED=true`` (the default) a ``TracerProvider``
    backed by a ``BatchSpanProcessor`` + an OTLP span exporter is installed as
    the global SDK provider.  Set ``TUVL_TELEMETRY_ENABLED=false`` to disable
    export while remaining in production mode.

Configuration (all read from ``.env`` or environment)
    ============================================  ============================
    Variable                                      Default
    ============================================  ============================
    ``TUVL_TELEMETRY_ENABLED``                    ``true``
    ``TUVL_OTLP_ENDPOINT``                        ``http://localhost:4318``
    ``TUVL_OTLP_PROTOCOL``                        ``http/protobuf``
    ``TUVL_SERVICE_NAME``                         ``tuvl``
    ============================================  ============================

Protocol
    ``http/protobuf`` (default) posts to ``<endpoint>/v1/traces`` and
    ``<endpoint>/v1/metrics``. ``grpc`` needs ``pip install 'tuvl[otel-grpc]'``.

Idempotency
    The function is guarded by a module-level flag so repeated calls (e.g. in
    test environments) do not reinstall the provider.
"""

from __future__ import annotations

from typing import Any

import structlog

logger = structlog.get_logger(__name__)

_initialized = False

PROTOCOLS = ("http/protobuf", "grpc")
_SIGNAL_PATHS = ("traces", "metrics", "logs")
_GRPC_PORT = ":4317"


def signal_url(endpoint: str, signal: str) -> str:
    """``<base>/v1/<signal>`` for an OTLP/HTTP endpoint given as a base URL or a full signal URL."""
    base = endpoint.rstrip("/")
    for known in _SIGNAL_PATHS:
        suffix = f"/v1/{known}"
        if base.endswith(suffix):
            base = base[: -len(suffix)]
            break
    return f"{base}/v1/{signal}"


def build_exporters(protocol: str, endpoint: str) -> tuple[Any, Any]:
    """The span and metric exporters for *protocol*; raises ``RuntimeError`` when it can't be used."""
    if protocol == "http/protobuf":
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

        return (
            OTLPSpanExporter(endpoint=signal_url(endpoint, "traces")),
            OTLPMetricExporter(endpoint=signal_url(endpoint, "metrics")),
        )
    if protocol == "grpc":
        try:
            from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
                OTLPMetricExporter as GrpcMetricExporter,
            )
            from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
                OTLPSpanExporter as GrpcSpanExporter,
            )
        except ImportError as exc:
            raise RuntimeError(
                "OTLP protocol 'grpc' needs the gRPC exporter: pip install 'tuvl[otel-grpc]'"
            ) from exc
        return GrpcSpanExporter(endpoint=endpoint), GrpcMetricExporter(endpoint=endpoint)
    raise RuntimeError(f"unsupported OTLP protocol '{protocol}' (one of: {', '.join(PROTOCOLS)})")


def _load_yaml_config() -> dict:
    """Read ``.tuvl/telemetry.yaml`` from the project directory if it exists.

    Returns an empty dict when the file is absent or unparseable so callers
    can treat missing file as "use defaults" without special-casing.
    """
    import yaml

    from tuvl.core.config import settings

    path = settings.project_dir / ".tuvl" / "telemetry.yaml"
    if not path.exists():
        return {}
    try:
        raw = yaml.safe_load(path.read_text()) or {}
        # Support full-structured (kind/version/metadata/spec) and legacy
        # flat formats.
        return raw.get("spec", raw) if isinstance(raw, dict) else {}
    except Exception:
        return {}


def init_telemetry() -> None:
    """Configure the global OTel ``TracerProvider`` from tuvl settings.

    Config resolution order (first wins):
      1. Environment variable (``TUVL_TELEMETRY_ENABLED``, ``TUVL_OTLP_ENDPOINT``,
         ``TUVL_SERVICE_NAME``) — set in shell or ``.env``.
      2. ``{project_dir}/.tuvl/telemetry.yaml`` — written by ``tuvl dev`` UI.
      3. Hardcoded defaults (enabled=true, endpoint=localhost:4318, protocol=http/protobuf, service=tuvl).
    """
    global _initialized

    import os

    from tuvl.core.config import settings

    if settings.tuvl_dev_mode:
        logger.debug("OTel: dev mode — TracerProvider not configured (NonRecordingSpan in effect)")
        return

    # Layer 2: YAML file values (only when no env var explicitly set).
    file_cfg = _load_yaml_config()

    enabled = settings.tuvl_telemetry_enabled
    if "TUVL_TELEMETRY_ENABLED" not in os.environ and "enabled" in file_cfg:
        enabled = bool(file_cfg["enabled"])

    if not enabled:
        logger.info("OTel: telemetry disabled")
        return

    if _initialized:
        logger.debug("OTel: already initialised — skipping")
        return

    endpoint = settings.otlp_endpoint
    if (
        "TUVL_OTLP_ENDPOINT" not in os.environ
        and "OTEL_EXPORTER_OTLP_ENDPOINT" not in os.environ
        and "otlp_endpoint" in file_cfg
    ):
        endpoint = str(file_cfg["otlp_endpoint"])

    protocol = settings.otlp_protocol
    if (
        "TUVL_OTLP_PROTOCOL" not in os.environ
        and "OTEL_EXPORTER_OTLP_PROTOCOL" not in os.environ
        and "otlp_protocol" in file_cfg
    ):
        protocol = str(file_cfg["otlp_protocol"])
    if protocol == "http/protobuf" and endpoint.rstrip("/").endswith(_GRPC_PORT):
        logger.warning(
            "OTel: endpoint uses the gRPC port 4317 but the protocol is http/protobuf; use "
            "port 4318, or set TUVL_OTLP_PROTOCOL=grpc (pip install 'tuvl[otel-grpc]')",
            endpoint=endpoint,
        )
    span_exporter, metric_exporter = build_exporters(protocol, endpoint)

    service_name = settings.tuvl_service_name
    if "TUVL_SERVICE_NAME" not in os.environ and "service_name" in file_cfg:
        service_name = str(file_cfg["service_name"])

    _initialized = True

    import opentelemetry.trace as trace
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
    from opentelemetry.semconv.resource import ResourceAttributes

    resource = Resource.create(
        {
            ResourceAttributes.SERVICE_NAME: service_name,
        }
    )

    provider = TracerProvider(resource=resource)
    provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(provider)

    # Metrics — loop agents and hooks emit counters (iterations, tool calls,
    # aborts, budget-exceeded, supervisor actions) so agent health is
    # dashboardable and alertable, not just buried in span attributes.
    from opentelemetry import metrics
    from opentelemetry.sdk.metrics import MeterProvider
    from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader

    metric_reader = PeriodicExportingMetricReader(metric_exporter)
    metrics.set_meter_provider(MeterProvider(resource=resource, metric_readers=[metric_reader]))
    logger.info("OTel MeterProvider initialised")

    # Install the W3C TraceContext propagator so inbound ``traceparent`` /
    # ``tracestate`` headers are read and outbound requests carry them.
    from opentelemetry.propagate import set_global_textmap
    from opentelemetry.propagators.composite import CompositePropagator
    from opentelemetry.trace.propagation.tracecontext import TraceContextTextMapPropagator

    set_global_textmap(CompositePropagator([TraceContextTextMapPropagator()]))

    logger.info(
        "OTel TracerProvider initialised",
        service=service_name,
        endpoint=endpoint,
    )
