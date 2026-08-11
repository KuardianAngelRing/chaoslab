"""assemble_handoff — seed 실험에서 계약 검증되는 페이로드가 나오는지."""
from app.db.repositories import ExperimentRepository
from app.db.seed import seed_data
from app.services.agent.assembler import assemble_handoff
from app.services.agent.handoff_schema import AgentHandoffPayload
from app.services.stubs import StubHandoffSource


def _seeded_exp(db_session):
    seed_data(db_session)
    return ExperimentRepository(db_session).list_all()[0]


def test_assemble_produces_valid_payload(db_session):
    exp = _seeded_exp(db_session)
    payload = assemble_handoff(db_session, StubHandoffSource(), exp)

    # round-trip: dump 후 재검증 가능해야 저장·PUT 계약과 동일
    AgentHandoffPayload.model_validate(payload.model_dump())

    assert payload.schema_version == "1.0"
    assert payload.experiment.app_name == "online-boutique"
    assert payload.experiment.allowed_ranges["latency_ms"]["max"] == 10_000
    assert payload.r_index.target_r == 0.7
    assert len(payload.improvement_history) == 3          # seed iteration 3건
    assert payload.budget.iterations_remaining == 0       # max 2 - 사용 3 → 0 (음수 금지)
    assert payload.budget.llm_cost_used_usd == 0.036      # 0.012 × 3
    assert len(payload.error_log_samples) <= 20


def test_stored_contract_metrics_win_over_stub(db_session):
    """Slice 5가 계약 형태로 저장해 두면 그 값이 Stub보다 우선."""
    exp = _seeded_exp(db_session)
    # Stub 출력은 계약 형태 — rps_avg만 바꿔 "저장된 계약형 metrics"를 흉내
    stored = StubHandoffSource().phase_summary("sut", "ob", "baseline")
    stored["rps_avg"] = 999.0
    exp.baseline_metrics = stored
    db_session.commit()

    payload = assemble_handoff(db_session, StubHandoffSource(), exp)
    assert payload.phase_summaries.baseline.rps_avg == 999.0


def test_legacy_metrics_fall_back_to_stub(db_session):
    """seed의 구형 {"error","p99"} 형태는 계약 불일치 → Stub 샘플로 대체."""
    exp = _seeded_exp(db_session)
    assert exp.baseline_metrics == {"error": 0.3, "p99": 89}

    payload = assemble_handoff(db_session, StubHandoffSource(), exp)
    assert payload.phase_summaries.baseline.rps_avg == 42.0  # Stub baseline 값
