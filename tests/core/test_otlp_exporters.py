"""OTLP exporter selection: HTTP by default, gRPC behind the ``otel-grpc`` extra."""

from __future__ import annotations

import sys

import pytest

from tuvl.core.engine import telemetry


@pytest.mark.parametrize(
    ("endpoint", "signal", "expected"),
    [
        ("http://localhost:4318", "traces", "http://localhost:4318/v1/traces"),
        ("http://localhost:4318/", "metrics", "http://localhost:4318/v1/metrics"),
        ("https://otlp.example.com/otlp", "traces", "https://otlp.example.com/otlp/v1/traces"),
        ("http://c:4318/v1/traces", "metrics", "http://c:4318/v1/metrics"),
        ("http://c:4318/v1/metrics", "traces", "http://c:4318/v1/traces"),
    ],
)
def test_signal_url(endpoint: str, signal: str, expected: str) -> None:
    assert telemetry.signal_url(endpoint, signal) == expected


def test_http_exporters_target_signal_urls() -> None:
    spans, metrics = telemetry.build_exporters("http/protobuf", "http://collector:4318")
    assert spans._endpoint == "http://collector:4318/v1/traces"
    assert metrics._endpoint == "http://collector:4318/v1/metrics"


def test_grpc_without_extra_names_the_extra(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "opentelemetry.exporter.otlp.proto.grpc.trace_exporter", None)
    with pytest.raises(RuntimeError, match=r"tuvl\[otel-grpc\]"):
        telemetry.build_exporters("grpc", "http://collector:4317")


def test_unknown_protocol_is_rejected() -> None:
    with pytest.raises(RuntimeError, match="unsupported OTLP protocol"):
        telemetry.build_exporters("http/json", "http://collector:4318")


def test_protocol_setting_prefers_standard_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from tuvl.core.config import Settings

    assert Settings().otlp_protocol == "http/protobuf"
    monkeypatch.setenv("TUVL_OTLP_PROTOCOL", "grpc")
    assert Settings().otlp_protocol == "grpc"
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_PROTOCOL", "http/protobuf")
    assert Settings().otlp_protocol == "http/protobuf"
