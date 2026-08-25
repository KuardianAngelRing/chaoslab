"""페이로드 조립 — manifest 원문 + 정적 분석(하이브리드 5) + 과거 이력 + 9종 가드레일."""
from app.db.repositories import AppRepository
from app.db.seed import seed_data
from app.services.agent.hypothesis_assembler import analyze_manifest, assemble_hypothesis_input
from app.services.chaos_specs import CHAOS_SPECS


def _order_msa(session):
    return next(a for a in AppRepository(session).list_all() if a.name == "order-msa")


def test_assemble_includes_manifest_and_findings(db_session):
    seed_data(db_session)
    app = _order_msa(db_session)
    payload = assemble_hypothesis_input(db_session, app, "목표", 5)
    assert payload.manifest_yaml == app.manifest          # 원문 그대로 — 요약으로 대체 금지
    texts = [f.finding for f in payload.manifest_findings]
    assert any("replicas 1" in t for t in texts)
    assert any("probe 없음" in t for t in texts)
    assert all(f.workload == "order-api" for f in payload.manifest_findings)


def test_assemble_allowed_chaos_derived_from_specs(db_session):
    seed_data(db_session)
    payload = assemble_hypothesis_input(db_session, _order_msa(db_session), "", 5)
    assert {a.chaos_type for a in payload.allowed_chaos} == set(CHAOS_SPECS)


def test_assemble_past_experiments(db_session):
    seed_data(db_session)
    payload = assemble_hypothesis_input(db_session, _order_msa(db_session), "", 5)
    assert any(p.chaos_type == "pod-kill" for p in payload.past_experiments)


def test_assemble_clamps_candidate_count(db_session):
    seed_data(db_session)
    app = _order_msa(db_session)
    assert assemble_hypothesis_input(db_session, app, "", 0).candidate_count == 1
    assert assemble_hypothesis_input(db_session, app, "", 99).candidate_count == 10


def test_analyze_manifest_empty_and_broken():
    assert analyze_manifest("") == []
    broken = analyze_manifest("a: [1,")
    assert broken and "파싱 실패" in broken[0].finding
