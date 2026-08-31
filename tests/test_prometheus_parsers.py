"""Prometheus HTTP 응답 파서·요약 순수 함수 — canned JSON, 네트워크 없음."""
import math

from app.services.real.prometheus import (
    instant_by_label, instant_value, istio_selector, range_values, summarize,
)


def _range_resp(values):
    return {"data": {"result": [{"values": [[0, str(v)] for v in values]}]}}


def test_range_values_filters_nan_and_empty():
    assert range_values(_range_resp([1.0, 2.5])) == [1.0, 2.5]
    assert range_values({"data": {"result": []}}) == []
    assert range_values(_range_resp([1.0, math.nan])) == [1.0]


def test_summarize():
    s = summarize([1.0, 3.0, 2.0])
    assert s == {"avg": 2.0, "min": 1.0, "max": 3.0, "peak": 3.0}
    assert summarize([]) == {"avg": 0.0, "min": 0.0, "max": 0.0, "peak": 0.0}


def test_instant_helpers():
    resp = {"data": {"result": [
        {"metric": {"response_code": "200"}, "value": [0, "120"]},
        {"metric": {"response_code": "503"}, "value": [0, "7.4"]},
    ]}}
    assert instant_by_label(resp, "response_code") == {"200": 120.0, "503": 7.0}
    assert instant_value({"data": {"result": [{"value": [0, "3.5"]}]}}) == 3.5
    assert instant_value({"data": {"result": []}}) == 0.0


def test_istio_selector():
    sel = istio_selector("sut", "demo")
    assert 'destination_workload="demo"' in sel
    assert 'destination_workload_namespace="sut"' in sel
    assert 'reporter="destination"' in sel
