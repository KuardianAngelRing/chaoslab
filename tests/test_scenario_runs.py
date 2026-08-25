from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import App, ExperimentSession, ScenarioRun
from app.services.regression import run_regression, scenario_snapshot
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
            return "running" if chaos_type == "PodChaos" else "recovered"
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
        ("PodChaos", {"app.kubernetes.io/name": "checkout-api"}),
        ("NetworkChaos", {"app.kubernetes.io/name": "catalog-api"}),
        ("PodChaos", {"app.kubernetes.io/name": "checkout-api"}),
        ("NetworkChaos", {"app.kubernetes.io/name": "catalog-api"}),
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
    assert deleted[0] == ("NetworkChaos", "failed-network")


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
