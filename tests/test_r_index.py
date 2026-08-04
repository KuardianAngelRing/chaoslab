from app.services.r_index import r_components


def test_r_components_from_seed_shape():
    """seed와 같은 형태의 metrics로 산식(0.4·가용성+0.3·레이턴시+0.3·복구속도) 검증."""
    comp = r_components(
        baseline={"rate": 38.0, "error": 0.3, "p99": 89},
        fault={"error": 2.1, "p99": 412},
        recovery={"error": 0.4, "p99": 120, "ttr_s": 95},
    )
    assert comp["availability"] == 0.98      # 1 - 2.1/100
    assert comp["latency_score"] == 0.22     # 89/412
    assert comp["recovery_speed"] == 0.68    # 1 - 95/300
    assert comp["r"] == 0.66                 # 0.4*0.979 + 0.3*0.216 + 0.3*0.683


def test_r_components_no_fault_returns_none():
    assert r_components(baseline={}, fault={}, recovery={}) is None


def test_r_components_missing_optional_parts():
    """baseline p99·recovery ttr이 없어도 죽지 않고 해당 항 0점 처리."""
    comp = r_components(baseline={}, fault={"error": 50.0, "p99": 900}, recovery={})
    assert comp["availability"] == 0.5
    assert comp["latency_score"] == 0.0
    assert comp["recovery_speed"] == 0.0
    assert comp["r"] == 0.2


def test_r_components_clamped_to_unit_range():
    """error>100%, ttr>300s 같은 극단값도 0~1로 클램프."""
    comp = r_components(baseline={"p99": 100}, fault={"error": 150.0, "p99": 50},
                        recovery={"ttr_s": 900})
    assert comp["availability"] == 0.0
    assert comp["latency_score"] == 1.0      # baseline보다 빨라도 최대 1
    assert comp["recovery_speed"] == 0.0
