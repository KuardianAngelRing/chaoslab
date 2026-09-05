from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import App, ExperimentSession, ScenarioRun
from app.db.repositories import HypothesisRepository
from app.services.agent.hypothesis_schema import CandidateProposal
from app.services.regression import (
    DEFAULT_CRITERIA,
    run_regression,
    scenario_snapshot,
    scenario_snapshot_from_hypothesis,
)
from app.services.report_writer import deterministic_report
from app.services.reports import report_html
from app.services.resilience import calculate_r, compare_runs


def _session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_scenario_snapshot_keeps_yaml_order():
    scenario = scenario_snapshot("order-resilience-lab", ["catalog", "frontend"])
    assert [item["id"] for item in scenario["experiments"]] == ["frontend", "catalog"]


def test_final_regression_runs_selected_experiments_in_order(monkeypatch):
    Session = _session_factory()
    session = Session()
    app = App(name="order-resilience-lab", repo_url="", framework="manifest", env="k3s")
    session.add(app)
    session.commit()
    preparation = ExperimentSession(app_id=app.id, status="ready", namespace="chaoslab-session-order")
    session.add(preparation)
    session.commit()
    run = ScenarioRun(
        app_id=app.id,
        preparation_session_id=preparation.id,
        scenario=scenario_snapshot(app.name, ["frontend", "catalog"]),
        status="queued",
        progress={},
        results=[],
    )
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    injected = []

    class _Chaos:
        def inject(self, namespace, app_name, chaos_type, params, target_selector=None):
            injected.append((chaos_type, target_selector))
            return f"crd-{len(injected)}"
        def phase(self, chaos_type, crd_name):
            return "running" if chaos_type == "pod-kill" else "recovered"
        def delete(self, chaos_type, crd_name):
            return None

    monkeypatch.setattr("app.services.regression.SessionLocal", Session)
    monkeypatch.setattr("app.services.regression.make_chaos", lambda *args: _Chaos())
    monkeypatch.setattr("app.services.regression.time.sleep", lambda _seconds: None)

    run_regression(run_id)

    session = Session()
    saved = session.get(ScenarioRun, run_id)
    assert saved.status == "completed"
    assert [item["scenario_experiment_id"] for item in saved.results] == ["frontend", "catalog"]
    assert all(item["cleanup_completed"] for item in saved.results)
    assert injected == [
        ("pod-kill", {"app.kubernetes.io/name": "checkout-api"}),
        ("network-delay", {"app.kubernetes.io/name": "catalog-api"}),
        ("pod-kill", {"app.kubernetes.io/name": "checkout-api"}),
        ("network-delay", {"app.kubernetes.io/name": "catalog-api"}),
    ]
    assert len(saved.baseline_results) == 2
    assert len(saved.improvement_changes) == 2
    assert saved.comparison["verdict"] == "passed"
    assert saved.comparison["r"]["before"]["available"] is True


def test_final_regression_fails_and_cleans_up_on_injection_error(monkeypatch):
    Session = _session_factory()
    session = Session()
    app = App(name="order-resilience-lab", repo_url="", framework="manifest", env="k3s")
    session.add(app)
    session.commit()
    preparation = ExperimentSession(app_id=app.id, status="ready", namespace="chaoslab-session-order")
    session.add(preparation)
    session.commit()
    run = ScenarioRun(
        app_id=app.id,
        preparation_session_id=preparation.id,
        scenario=scenario_snapshot(app.name, ["catalog", "cpu"]),
        status="queued",
        progress={},
        results=[],
    )
    session.add(run)
    session.commit()
    run_id = run.id
    session.close()

    deleted = []

    class _Chaos:
        def inject(self, namespace, app_name, chaos_type, params, target_selector=None):
            return "failed-network"
        def phase(self, chaos_type, crd_name):
            raise RuntimeError("unable to set ip tables chains")
        def delete(self, chaos_type, crd_name):
            deleted.append((chaos_type, crd_name))

    monkeypatch.setattr("app.services.regression.SessionLocal", Session)
    monkeypatch.setattr("app.services.regression.make_chaos", lambda *args: _Chaos())

    run_regression(run_id)

    session = Session()
    saved = session.get(ScenarioRun, run_id)
    assert saved.status == "completed"
    assert saved.results[0]["status"] == "inconclusive"
    assert saved.results[0]["cleanup_completed"] is True
    assert saved.results[0]["error"] == "unable to set ip tables chains"
    assert saved.comparison["verdict"] == "inconclusive"
    assert len(deleted) == 4
    assert deleted[0] == ("network-delay", "failed-network")


def test_report_uses_only_saved_execution_results():
    Session = _session_factory()
    session = Session()
    app = App(name="order-resilience-lab", repo_url="", framework="manifest", env="k3s")
    session.add(app)
    session.commit()
    preparation = ExperimentSession(app_id=app.id, status="ready", namespace="chaoslab-session-order")
    session.add(preparation)
    session.commit()
    scenario = scenario_snapshot(app.name, ["frontend", "catalog"])
    before_results = [
        _result(scenario["experiments"][0], "failed", error_rate=40, p95=800),
        _result(scenario["experiments"][1], "failed", error_rate=100, p95=500),
    ]
    after_results = [
        _result(scenario["experiments"][0], "passed", error_rate=0, p95=110),
        _result(scenario["experiments"][1], "passed", error_rate=0, p95=920),
    ]
    changes = [{
        "deployment": "order-api", "container": "app", "key": "UPSTREAM_TIMEOUT_SECONDS",
        "before": "0.45", "after": "1.2", "rollout_ready": True,
        "reason": "지연 응답 허용", "id": "timeout", "applies_to": ["catalog"],
    }]
    comparison = compare_runs(before_results, after_results, changes)
    facts = {"run_id": 1, "app_name": app.name, "namespace": preparation.namespace,
             "scenario_id": scenario["id"], "scenario_title": scenario["title"],
             "comparison": comparison}
    run = ScenarioRun(
        app_id=app.id,
        preparation_session_id=preparation.id,
        scenario=scenario,
        status="completed",
        progress={},
        baseline_results=before_results,
        results=after_results,
        improvement_changes=changes,
        comparison=comparison,
        report_content={**deterministic_report(facts), "source": "deterministic", "model": ""},
    )
    session.add(run)
    session.commit()

    html = report_html(run)
    assert "Checkout API Pod 1개 손실" in html
    assert "R 지수" in html
    assert "0.45 → 1.2" in html
    assert f"{comparison['r']['after']['score']}점" in html
    assert "SAMPLE DATA" not in html
    assert "contenteditable" not in html


def test_r_index_is_unavailable_when_a_result_is_inconclusive():
    scenario = scenario_snapshot("order-resilience-lab", ["frontend", "catalog"])
    results = [
        _result(scenario["experiments"][0], "passed", error_rate=0, p95=100),
        _result(scenario["experiments"][1], "inconclusive", error_rate=0, p95=100),
    ]
    r = calculate_r(results)
    assert r["available"] is False
    assert r["score"] is None


def _result(spec, status, *, error_rate, p95):
    checks = {
        "error_rate": error_rate <= spec["criteria"]["max_error_rate_pct"],
        "p95_latency": p95 <= spec["criteria"]["max_p95_latency_ms"],
        "ready_pods": True,
        "post_recovered": True,
        "recovery_time": True,
    }
    return {
        "scenario_experiment_id": spec["id"],
        "title": spec["title"],
        "target_selector": spec["target_selector"],
        "chaos_type": spec["chaos_type"],
        "crd_name": f"crd-{spec['id']}",
        "status": status,
        "criteria": spec["criteria"],
        "checks": checks,
        "failed_checks": [key for key, value in checks.items() if not value],
        "during": {"error_rate_pct": error_rate, "p95_latency_ms": p95,
                   "min_ready_pods": spec["criteria"]["min_ready_pods"]},
        "recovery_seconds": 5.0,
        "restart_delta": 0,
        "cleanup_completed": True,
        "error": "",
    }


# ── 가설 경로: 승인 후보 → 회귀 시나리오 조립 (스펙 2026-09-05) ──

def _hypothesis_fixture(Session, *, detailed=True):
    """nginx(k3s) 앱 + ready 준비 세션 + 후보 2개(하나만 detailed). (app_id, run_id, session_id, cand_id)"""
    session = Session()
    app = App(name="nginx", repo_url="k3s://manifest-upload", framework="manifest", env="k3s",
              health_path="/", status="registered",
              manifest="kind: Deployment\nmetadata:\n  name: nginx\nspec:\n  selector:\n    matchLabels:\n      app: nginx\n")
    session.add(app)
    session.commit()
    preparation = ExperimentSession(app_id=app.id, status="ready", namespace="chaoslab-session-nginx-1")
    session.add(preparation)
    session.commit()
    repo = HypothesisRepository(session)
    run = repo.create_run(app_id=app.id, goal_text="nginx가 파드 종료를 버티는지", candidate_count=2,
                          input_payload={}, status="ready")
    approved, proposed = repo.add_candidates(run.id, [
        CandidateProposal(title="nginx 파드 강제 종료 검증", chaos_type="pod-kill",
                          target_workload="nginx", hypothesis="h", expected_impact="i"),
        CandidateProposal(title="nginx 지연 검증", chaos_type="network-delay",
                          target_workload="nginx", hypothesis="h", expected_impact="i"),
    ])
    if detailed:
        repo.set_candidate_detail(approved, "detailed", params={"action": "pod-kill"}, rationale="r")
    ids = (app.id, run.id, preparation.id, approved.id)
    session.close()
    return ids


def test_scenario_snapshot_from_hypothesis_uses_detailed_candidates_only():
    Session = _session_factory()
    app_id, run_id, _, cand_id = _hypothesis_fixture(Session)
    session = Session()
    run = HypothesisRepository(session).get_run(run_id)
    scenario = scenario_snapshot_from_hypothesis(run, run.app)
    assert scenario["id"] == f"hyp-{run_id}"
    assert scenario["title"] == "nginx가 파드 종료를 버티는지"
    assert scenario["app"] == "nginx"
    assert scenario["observation"] == {"service": "nginx", "path": "/", "expected_status": 200}
    assert scenario["improvements"] == []
    [spec] = scenario["experiments"]                       # proposed 후보는 제외, 1개 허용
    assert spec["id"] == f"cand-{cand_id}"
    assert spec["title"] == "nginx 파드 강제 종료 검증"
    assert spec["chaos_type"] == "pod-kill"
    assert spec["params"] == {"action": "pod-kill"}          # validate_params 정규화
    assert spec["target_selector"] == {"app": "nginx"}              # 매니페스트 matchLabels에서 파싱
    assert spec["criteria"] == DEFAULT_CRITERIA
    session.close()


def test_scenario_snapshot_from_hypothesis_requires_detailed_candidate():
    import pytest

    Session = _session_factory()
    _, run_id, _, _ = _hypothesis_fixture(Session, detailed=False)
    session = Session()
    run = HypothesisRepository(session).get_run(run_id)
    with pytest.raises(ValueError):
        scenario_snapshot_from_hypothesis(run, run.app)
    session.close()


def test_create_scenario_run_from_hypothesis_and_reach_result_stage(monkeypatch, client):
    """POST /scenario-runs(hypothesis_run_id) → 201·컬럼 저장 → Stub 회귀 completed →
    셸 4단계(?view=result)에 R지수·보고서 링크, 보고서 HTML 200, 실험 목록 행은 4/4."""
    from app.db.database import get_session
    from app.main import app as fastapi_app

    Session = _session_factory()
    _, run_id, session_id, cand_id = _hypothesis_fixture(Session)
    monkeypatch.setattr("app.services.regression.SessionLocal", Session)
    monkeypatch.setattr("app.services.regression.time.sleep", lambda _seconds: None)

    def _override():
        s = Session()
        try:
            yield s
        finally:
            s.close()
    fastapi_app.dependency_overrides[get_session] = _override

    # YAML 경로 검증은 그대로 — 가설 앱에 selected_ids만 보내면 422 (order-resilience-lab 전용)
    resp = client.post("/scenario-runs", data={"session_id": session_id, "selected_ids": "frontend,catalog"})
    assert resp.status_code == 422

    resp = client.post("/scenario-runs", data={"session_id": session_id, "hypothesis_run_id": run_id})
    assert resp.status_code == 201, resp.text
    payload = resp.json()
    assert payload["hypothesis_run_id"] == run_id
    assert payload["scenario"]["id"] == f"hyp-{run_id}"
    assert [item["id"] for item in payload["scenario"]["experiments"]] == [f"cand-{cand_id}"]

    session = Session()
    saved = session.get(ScenarioRun, payload["id"])
    assert saved.hypothesis_run_id == run_id
    assert saved.status == "completed"                      # BackgroundTasks가 응답 후 동기 실행(Stub)
    assert saved.comparison["verdict"] == "passed"
    assert saved.improvement_changes == []                  # 가설 경로엔 개선 명세 없음
    assert saved.report_content
    session.close()

    resp = client.get(f"/hypothesis/{run_id}?view=result")
    assert resp.status_code == 200
    assert 'data-initial-stage="result"' in resp.text
    assert 'data-workflow-current-stage="4"' in resp.text
    assert f'data-scenario-run-id="{payload["id"]}"' in resp.text
    assert f"/scenario-runs/{payload['id']}/report" in resp.text
    assert f"/scenario-runs/{payload['id']}/report.pdf" in resp.text
    assert "R 지수" in resp.text and "전체 통과" in resp.text
    assert "data-hypothesis-regression-start" not in resp.text   # 회귀가 있으면 시작 블록 없음

    resp = client.get(f"/hypothesis/{run_id}?view=verify")
    assert 'data-initial-stage="verify"' in resp.text
    assert "nginx 파드 강제 종료 검증" in resp.text

    resp = client.get(f"/scenario-runs/{payload['id']}/report")
    assert resp.status_code == 200
    assert "nginx가 파드 종료를 버티는지" in resp.text and "chaoslab-session-nginx-1" in resp.text

    resp = client.get("/experiments")
    assert resp.status_code == 200
    assert f"/hypothesis/{run_id}?view=result" in resp.text
    assert "4/4" in resp.text and "전체 통과" in resp.text and "R=" in resp.text


def test_workload_selector_parses_match_labels_and_falls_back():
    from app.services.regression import workload_selector

    multi = ("kind: Deployment\nmetadata:\n  name: api\nspec:\n  selector:\n    matchLabels:\n      app.kubernetes.io/name: api\n"
             "---\nkind: Deployment\nmetadata:\n  name: web\nspec:\n  selector:\n    matchLabels:\n      app: web\n"
             "---\nkind: Service\nmetadata:\n  name: web\n")
    assert workload_selector(multi, "web") == {"app": "web"}
    assert workload_selector(multi, "api") == {"app.kubernetes.io/name": "api"}
    assert workload_selector(multi, "unknown") is None                    # 여러 개인데 이름 불일치 → ns 전체
    single = "kind: Deployment\nmetadata:\n  name: nginx\nspec:\n  selector:\n    matchLabels:\n      app: nginx\n"
    assert workload_selector(single, "other-name") == {"app": "nginx"}     # 유일 워크로드면 이름 달라도 그것
    assert workload_selector("kind: Deployment", "nginx") is None
    assert workload_selector(":: not yaml [", "nginx") is None
