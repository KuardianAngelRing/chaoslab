"""CHAOS_SPECS 범위검증 — 순수 함수, IO 없음."""
from app.services.chaos_specs import CHAOS_SPECS, validate_params


def test_network_delay_valid():
    params, errors = validate_params("NetworkChaos", {"latency_ms": "200", "duration_s": "300"})
    assert errors == []
    assert params == {"action": "delay", "latency_ms": 200, "duration_s": 300}


def test_pod_kill_no_fields():
    params, errors = validate_params("PodChaos", {})
    assert errors == []
    assert params == {"action": "pod-kill"}


def test_stress_cpu_valid():
    params, errors = validate_params("StressChaos", {"cpu_load": "80", "duration_s": "60"})
    assert errors == []
    assert params == {"action": "cpu", "cpu_load": 80, "duration_s": 60}


def test_out_of_range_rejected():
    _, errors = validate_params("NetworkChaos", {"latency_ms": "5", "duration_s": "300"})
    assert any("지연" in e for e in errors)          # min 10 미만
    _, errors = validate_params("NetworkChaos", {"latency_ms": "200", "duration_s": "9999"})
    assert any("지속" in e for e in errors)          # max 1800 초과


def test_non_integer_rejected():
    _, errors = validate_params("StressChaos", {"cpu_load": "abc", "duration_s": "60"})
    assert errors


def test_unknown_type_rejected():
    _, errors = validate_params("DiskChaos", {})
    assert errors


def test_specs_have_labels_for_ui():
    for spec in CHAOS_SPECS.values():
        for field in spec["fields"].values():
            assert {"min", "max", "label"} <= set(field)
