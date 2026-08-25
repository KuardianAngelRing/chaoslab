"""CHAOS_SPECS 범위검증 — 순수 함수, IO 없음. 슬러그 키 9종 (2026-08-25 확장)."""
from app.services.chaos_specs import CHAOS_SPECS, kind_of, validate_params


def test_all_nine_types_registered():
    assert set(CHAOS_SPECS) == {
        "network-delay", "network-loss", "network-partition", "network-bandwidth",
        "pod-kill", "pod-failure", "container-kill",
        "cpu-stress", "memory-stress",
    }


def test_kind_of():
    assert kind_of("network-loss") == "NetworkChaos"
    assert kind_of("pod-failure") == "PodChaos"
    assert kind_of("memory-stress") == "StressChaos"


def test_network_delay_valid():
    params, errors = validate_params("network-delay", {"latency_ms": "200", "duration_s": "300"})
    assert errors == []
    assert params == {"action": "delay", "latency_ms": 200, "duration_s": 300}


def test_network_loss_valid():
    params, errors = validate_params("network-loss", {"loss_percent": "25", "duration_s": "60"})
    assert errors == []
    assert params == {"action": "loss", "loss_percent": 25, "duration_s": 60}


def test_network_partition_valid():
    params, errors = validate_params("network-partition", {"duration_s": "120"})
    assert errors == []
    assert params == {"action": "partition", "duration_s": 120}


def test_network_bandwidth_valid():
    params, errors = validate_params("network-bandwidth", {"rate_mbps": "10", "duration_s": "60"})
    assert errors == []
    assert params == {"action": "bandwidth", "rate_mbps": 10, "duration_s": 60}


def test_pod_kill_no_fields():
    params, errors = validate_params("pod-kill", {})
    assert errors == []
    assert params == {"action": "pod-kill"}


def test_pod_failure_valid():
    params, errors = validate_params("pod-failure", {"duration_s": "90"})
    assert errors == []
    assert params == {"action": "pod-failure", "duration_s": 90}


def test_container_kill_requires_name():
    params, errors = validate_params("container-kill", {"container_name": "server"})
    assert errors == []
    assert params == {"action": "container-kill", "container_name": "server"}

    _, errors = validate_params("container-kill", {"container_name": "  "})
    assert any("컨테이너" in e for e in errors)

    _, errors = validate_params("container-kill", {"container_name": "x" * 64})
    assert any("63자" in e for e in errors)


def test_stress_cpu_valid():
    params, errors = validate_params("cpu-stress", {"cpu_load": "80", "duration_s": "60"})
    assert errors == []
    assert params == {"action": "cpu", "cpu_load": 80, "duration_s": 60}


def test_memory_stress_valid():
    params, errors = validate_params("memory-stress", {"memory_mb": "256", "duration_s": "60"})
    assert errors == []
    assert params == {"action": "memory", "memory_mb": 256, "duration_s": 60}


def test_out_of_range_rejected():
    _, errors = validate_params("network-delay", {"latency_ms": "5", "duration_s": "300"})
    assert any("지연" in e for e in errors)          # min 10 미만
    _, errors = validate_params("network-delay", {"latency_ms": "200", "duration_s": "9999"})
    assert any("지속" in e for e in errors)          # max 1800 초과
    _, errors = validate_params("network-loss", {"loss_percent": "0", "duration_s": "60"})
    assert any("유실률" in e for e in errors)        # min 1 미만
    _, errors = validate_params("memory-stress", {"memory_mb": "8", "duration_s": "60"})
    assert any("메모리" in e for e in errors)        # min 16 미만


def test_non_integer_rejected():
    _, errors = validate_params("cpu-stress", {"cpu_load": "abc", "duration_s": "60"})
    assert errors


def test_unknown_type_rejected():
    _, errors = validate_params("DiskChaos", {})
    assert errors
    _, errors = validate_params("NetworkChaos", {})  # 구 kind 키는 더 이상 유효하지 않음
    assert errors


def test_specs_have_labels_for_ui():
    for spec in CHAOS_SPECS.values():
        assert {"kind", "action", "label", "fields"} <= set(spec)
        for field in spec["fields"].values():
            assert "label" in field
            if field.get("type") != "str":
                assert {"min", "max"} <= set(field)
