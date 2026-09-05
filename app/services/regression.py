"""최종 회귀 시나리오 계약과 순차 실행."""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.db.database import SessionLocal
from app.db.models import App, Experiment, HypothesisRun, ScenarioRun
from app.deps import make_chaos, make_k3s_workload
from app.services.chaos_specs import validate_params
from app.services.improvement_specs import validate_improvement
from app.services.observations import summarize, take_sample
from app.services.report_writer import write_report
from app.services.resilience import compare_runs, evaluate_experiment

logger = logging.getLogger(__name__)

_SCENARIOS = Path(__file__).parents[1] / "samples" / "scenarios"
_POLL_S = 5
_PODKILL_GRACE_S = 30
_MIN_FAULT_SAMPLES = 6  # 장애 구간 최소 관측 샘플(팀 결정 B1) — 30s/5s
_ONE_SHOT = ("pod-kill", "container-kill")
_RECOVER_POLLS = 60
_CRITERIA_KEYS = {
    "max_error_rate_pct", "max_p95_latency_ms", "max_recovery_seconds", "min_ready_pods",
}
_IMPROVEMENT_META_KEYS = {"id", "title", "reason", "applies_to"}
# 가설 경로 기본 판정 기준 — nginx 매니페스트(replicas 2) 기준 min_ready_pods=1이 안전.
# 값은 팀 튜닝 대상이므로 여기 한 곳에서만 관리한다.
DEFAULT_CRITERIA = {
    "max_error_rate_pct": 20,
    "max_p95_latency_ms": 1500,
    "max_recovery_seconds": 30,
    "min_ready_pods": 1,
}


def scenario_snapshot(app_name: str, selected_ids: list[str]) -> dict:
    """등록된 시나리오에서 사용자가 고른 실험과 허용된 개선만 원래 순서로 고정한다 (YAML 경로)."""
    return _snapshot_from_yaml(app_name, selected_ids)


def workload_selector(manifest_yaml: str, workload_name: str) -> dict[str, str] | None:
    """매니페스트에서 워크로드(Deployment/StatefulSet/DaemonSet)의 `spec.selector.matchLabels`를 찾는다.

    이름이 일치하는 워크로드 우선, 없으면 워크로드가 정확히 1개일 때 그것. 못 찾으면 None
    (= 실험 전용 ns 전체 대상 — 가설 경로 단일 실험과 같은 동작). nginx 샘플처럼 `app: nginx`
    라벨만 쓰는 앱을 `app.kubernetes.io/name` 가정으로 잘못 고르지 않기 위한 처리."""
    workloads = []
    try:
        docs = list(yaml.safe_load_all(manifest_yaml or ""))
    except yaml.YAMLError:
        return None
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") not in ("Deployment", "StatefulSet", "DaemonSet"):
            continue
        labels = ((doc.get("spec") or {}).get("selector") or {}).get("matchLabels") or {}
        if labels:
            workloads.append(((doc.get("metadata") or {}).get("name"), dict(labels)))
    for name, labels in workloads:
        if name == workload_name:
            return labels
    if len(workloads) == 1:
        return workloads[0][1]
    return None


def entry_service(manifest_yaml: str, app_name: str) -> str | None:
    """manifest의 Service 목록에서 회귀 관측 요청을 보낼 진입 Service를 추론한다.

    앱명과 같은 Service가 있으면 그것, 아니면 Service가 정확히 1개일 때 그것. 그 외(0개·다중)는 None —
    다중 Service 앱의 진입점은 등록 정보(`App.observe_service`)로 명시해야 한다.
    """
    try:
        docs = list(yaml.safe_load_all(manifest_yaml or ""))
    except yaml.YAMLError:
        return None
    names = [
        ((doc.get("metadata") or {}).get("name") or "")
        for doc in docs if isinstance(doc, dict) and doc.get("kind") == "Service"
    ]
    names = [n for n in names if n]
    if app_name in names:
        return app_name
    if len(names) == 1:
        return names[0]
    return None


def observation_for_app(app: App) -> dict | None:
    """앱의 관측 요청 대상(회귀 `take_sample`·단독 실험 트래픽 공용) — 한 곳 원칙.

    service=`App.observe_service`(등록 정보) 우선, 없으면 manifest에서 `entry_service` 추론.
    path=`App.health_path or "/"`. Service를 알 수 없으면 None — 호출자가 422/스킵을 정한다.
    """
    service = app.observe_service or entry_service(app.manifest, app.name)
    if not service:
        return None
    return {"service": service, "path": app.health_path or "/", "expected_status": 200}


def scenario_snapshot_from_hypothesis(run: HypothesisRun, app: App) -> dict:
    """가설 경로 — 승인(detailed)된 후보를 회귀 시나리오 스냅샷으로 조립한다.

    YAML 경로와 같은 스펙 형태(`_run_one`이 그대로 소비)를 만들되, 후보는 최소 1개로 완화.
    improvements = 사용자가 승인한 ImprovementProposal(설계 09/05) — 없으면 빈 리스트로
    baseline·final을 같은 조건으로 돌리고 보고서에 "적용된 개선 없음"이 정직하게 드러난다.
    """
    approved = [c for c in run.candidates if c.detail_status == "detailed" and c.params]
    if not approved:
        raise ValueError("승인(구체화 완료)된 후보가 없어 최종 회귀를 조립할 수 없습니다")
    experiments = []
    for candidate in approved:
        params, errors = validate_params(candidate.chaos_type, candidate.params)
        if errors:
            raise ValueError(" / ".join(errors))
        if not candidate.target_workload:
            raise ValueError("후보의 대상 워크로드가 비어 있습니다")
        experiments.append({
            "id": f"cand-{candidate.id}",
            "title": candidate.title,
            "chaos_type": candidate.chaos_type,
            "params": params,
            "target_selector": workload_selector(app.manifest, candidate.target_workload),
            "criteria": dict(DEFAULT_CRITERIA),
        })
    observation = observation_for_app(app)
    if observation is None:
        raise ValueError(
            "검증 요청을 보낼 Service를 알 수 없습니다 — manifest에 앱명과 같은 Service가 없고 Service가 "
            "여러 개(또는 없음)입니다. 앱 등록 정보의 관측 Service를 지정해 주세요"
        )
    return {
        "id": f"hyp-{run.id}",
        "title": run.goal_text or f"{app.name} 복원력 검증",
        "app": app.name,
        "observation": observation,
        "improvements": [
            _improvement_spec(p, [e["id"] for e in experiments])
            for p in run.proposals if p.status == "approved"
        ],
        "experiments": experiments,
    }


def _improvement_spec(proposal, applies_to: list[str]) -> dict:
    normalized, errors = validate_improvement({
        "type": proposal.type, "deployment": proposal.deployment, "container": proposal.container,
        "key": proposal.key, "value": proposal.value, "patch": proposal.patch,
    })
    if errors:
        raise ValueError(f"승인 개선안 '{proposal.title}' 검증 실패: " + "; ".join(errors))
    return {**normalized, "id": f"imp-{proposal.id}", "title": proposal.title,
            "reason": proposal.rationale, "applies_to": list(applies_to)}


def _snapshot_from_yaml(app_name: str, selected_ids: list[str]) -> dict:
    if app_name != "order-resilience-lab":
        raise ValueError("최종 회귀 시나리오는 order-resilience-lab에서만 지원합니다")
    raw = yaml.safe_load((_SCENARIOS / "order-resilience-lab.yaml").read_text(encoding="utf-8"))
    selected = set(selected_ids)
    experiments = [item for item in raw["experiments"] if item["id"] in selected]
    if len(experiments) < 2 or len(experiments) != len(selected):
        raise ValueError("실행 가능한 실험을 2개 이상 선택해 주세요")
    for item in experiments:
        params, errors = validate_params(item["chaos_type"], item["params"])
        if errors:
            raise ValueError(" / ".join(errors))
        item["params"] = params
        selector = item.get("target_selector") or {}
        if set(selector) != {"app.kubernetes.io/name"} or not selector["app.kubernetes.io/name"]:
            raise ValueError("시나리오 대상 selector가 올바르지 않습니다")
        criteria = item.get("criteria") or {}
        if set(criteria) != _CRITERIA_KEYS or any(float(value) <= 0 for value in criteria.values()):
            raise ValueError(f"{item['id']} 시나리오 판정 기준이 올바르지 않습니다")
    improvements = []
    for item in raw.get("improvements") or []:
        normalized, errors = validate_improvement(item)
        if errors or not (set(item) - _IMPROVEMENT_META_KEYS) <= set(normalized):
            raise ValueError("허용되지 않은 개선 명세입니다")
        if selected.intersection(item["applies_to"]):
            improvements.append({**normalized, "id": item["id"], "title": item.get("title", item["reason"]),
                                 "reason": item["reason"], "applies_to": item["applies_to"]})
    return {**raw, "experiments": experiments, "improvements": improvements}


def run_regression(run_id: int) -> None:
    """개선 전과 개선 후에 동일한 시나리오를 실행하고 비교 스냅샷을 저장한다."""
    session = SessionLocal()
    try:
        run = session.get(ScenarioRun, run_id)
        if run is None or run.status != "queued":
            return
        run.status = "running"
        run.started_at = datetime.now(timezone.utc)
        session.commit()

        workload = make_k3s_workload()
        experiments = (run.scenario or {}).get("experiments") or []
        run.baseline_results = _run_suite(session, run, experiments, workload, "baseline")
        session.commit()
        run.improvement_changes = _apply_improvements(session, run, workload)
        session.commit()
        run.results = _run_suite(session, run, experiments, workload, "final")
        _rollback_improvements(run, workload)   # 보고서에 전후가 남으므로 세션 ns는 manifest 상태로 되돌린다
        run.comparison = compare_runs(run.baseline_results or [], run.results or [],
                                      run.improvement_changes or [])
        run.report_content = write_report({
            "run_id": run.id,
            "app_name": run.app.name,
            "namespace": run.preparation_session.namespace,
            "scenario_id": (run.scenario or {}).get("id"),
            "scenario_title": (run.scenario or {}).get("title"),
            "comparison": run.comparison,
        })
        run.status = "completed"
        run.error = ""
        _finish(session, run, "개선 전후 최종 회귀 검증이 완료됐습니다")
    except Exception as exc:
        logger.exception("final regression failed (run %s)", run_id)
        run = session.get(ScenarioRun, run_id)
        if run is not None:
            run.status = "failed"
            run.error = str(exc)
            _finish(session, run, "최종 회귀 검증을 완료하지 못했습니다")
    finally:
        session.close()


def _run_suite(session, run: ScenarioRun, experiments: list[dict], workload, round_name: str) -> list[dict]:
    results = []
    round_label = "개선 전 검증" if round_name == "baseline" else "개선 후 최종 회귀"
    for index, spec in enumerate(experiments):
        _set_progress(
            session, run, spec, "observing",
            f"{round_label}: 장애 전 상태를 관측하고 있습니다",
            round_name=round_name, current=index + 1, total=len(experiments),
        )
        result = _run_one(session, run, spec, workload, round_name)
        results.append(result)
        if round_name == "baseline":
            run.baseline_results = list(results)
        else:
            run.results = list(results)
        run.updated_at = datetime.now(timezone.utc)
        session.commit()
    return results


def _run_one(session, run: ScenarioRun, spec: dict, workload, round_name: str) -> dict:
    started_at = datetime.now(timezone.utc)
    namespace = run.preparation_session.namespace
    observation = run.scenario["observation"]
    chaos = make_chaos(run.app.env, namespace)
    crd_name = ""
    cleanup = False
    injection_confirmed = False
    fault_window_completed = False
    error = ""
    before_samples: list[dict] = []
    during_samples: list[dict] = []
    after_samples: list[dict] = []
    recovery_seconds = None
    experiment = Experiment(
        app_id=run.app_id,
        chaos_type=spec["chaos_type"],
        params={**spec["params"], "round": round_name},
        status="pending",
        namespace=namespace,
    )
    session.add(experiment)
    session.commit()
    try:
        before_samples = _collect_samples(workload, namespace, observation, count=3)
        crd_name = chaos.inject(
            namespace,
            run.app.name,
            spec["chaos_type"],
            spec["params"],
            target_selector=spec["target_selector"],
        )
        experiment.crd_name = crd_name
        experiment.status = "running"
        session.commit()
        _set_progress(session, run, spec, "running", "장애 구간의 요청과 워크로드 상태를 관측하고 있습니다",
                      round_name=round_name)
        duration = int(spec["params"].get("duration_s") or _PODKILL_GRACE_S)
        poll_count = max(_MIN_FAULT_SAMPLES, math.ceil(duration / _POLL_S))
        one_shot = spec["chaos_type"] in _ONE_SHOT
        recovered = False
        for poll_index in range(poll_count):
            phase = chaos.phase(spec["chaos_type"], crd_name)
            if phase in {"running", "recovered"}:
                injection_confirmed = True
            during_samples.append(take_sample(workload, namespace, observation))
            if phase == "recovered" and not one_shot:
                recovered = True
                break
            if poll_index + 1 < poll_count:
                time.sleep(_POLL_S)
        # 원샷 액션(pod-kill·container-kill)은 recovered 조건이 없다 — 주입 확인 + grace 동안 관측을 채운 뒤 종료
        if one_shot and injection_confirmed:
            recovered = True
        if not recovered:
            _set_progress(session, run, spec, "recovering", "장애 종료 상태를 확인하고 있습니다",
                          round_name=round_name)
            for _ in range(_RECOVER_POLLS):
                phase = chaos.phase(spec["chaos_type"], crd_name)
                if phase == "recovered":
                    injection_confirmed = True
                    recovered = True
                    break
                time.sleep(_POLL_S)
        fault_window_completed = recovered
        if not injection_confirmed:
            error = "장애 주입 완료 상태를 확인하지 못했습니다"
        elif not fault_window_completed:
            error = "Chaos 종료 상태를 확인하지 못했습니다"
    except Exception as exc:
        logger.exception("regression experiment failed (run %s, step %s)", run.id, spec["id"])
        error = str(exc)
    finally:
        _set_progress(session, run, spec, "cleanup", "장애 리소스를 정리하고 복구를 확인하고 있습니다",
                      round_name=round_name)
        if crd_name:
            try:
                chaos.delete(spec["chaos_type"], crd_name)
                cleanup = True
            except Exception as exc:
                logger.exception("regression cleanup failed (%s)", crd_name)
                error = str(exc)
        else:
            cleanup = True

    recovery_started = time.monotonic()
    recovery_polls = max(1, math.ceil(float(spec["criteria"]["max_recovery_seconds"]) / _POLL_S))
    try:
        for poll_index in range(recovery_polls):
            sample = take_sample(workload, namespace, observation)
            after_samples.append(sample)
            if sample["request_ok"] and sample["pods_ready"] >= int(spec["criteria"]["min_ready_pods"]):
                recovery_seconds = round(time.monotonic() - recovery_started, 1)
                break
            if poll_index + 1 < recovery_polls:
                time.sleep(_POLL_S)
    except Exception as exc:
        error = error or str(exc)

    before = summarize(before_samples)
    during = summarize(during_samples)
    after = summarize(after_samples)
    evaluation = evaluate_experiment(
        before=before,
        during=during,
        after=after,
        criteria=spec["criteria"],
        injection_confirmed=injection_confirmed,
        fault_window_completed=fault_window_completed,
        cleanup_completed=cleanup,
        recovery_seconds=recovery_seconds,
    )
    finished_at = datetime.now(timezone.utc)
    experiment.baseline_metrics = before
    experiment.fault_metrics = during
    experiment.recovery_metrics = {**after, "recovery_seconds": recovery_seconds}
    experiment.status = evaluation["verdict"]
    experiment.finished_at = finished_at
    session.commit()

    return {
        "experiment_id": experiment.id,
        "scenario_experiment_id": spec["id"],
        "round": round_name,
        "title": spec["title"],
        "chaos_type": spec["chaos_type"],
        "target_selector": spec["target_selector"],
        "params": spec["params"],
        "criteria": spec["criteria"],
        "crd_name": crd_name,
        "status": evaluation["verdict"],
        "validity": evaluation["validity"],
        "checks": evaluation["checks"],
        "failed_checks": evaluation["failed_checks"],
        "before": before,
        "during": during,
        "after": after,
        "recovery_seconds": recovery_seconds,
        "restart_delta": _restart_delta(before, after),
        "cleanup_completed": cleanup,
        "error": error,
        "evidence_ids": [
            f"run-{run.id}:{round_name}:{spec['id']}:before",
            f"run-{run.id}:{round_name}:{spec['id']}:fault",
            f"run-{run.id}:{round_name}:{spec['id']}:after",
        ],
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
    }


def _apply_improvements(session, run: ScenarioRun, workload) -> list[dict]:
    """승인 개선을 순서대로 적용(타입별 분기). 하나라도 실패하면 이미 적용한 변경을 역순 롤백 후 예외."""
    changes = []
    improvements = (run.scenario or {}).get("improvements") or []
    namespace = run.preparation_session.namespace
    for index, spec in enumerate(improvements):
        run.progress = {
            "round": "improvement",
            "current": index + 1,
            "total": len(improvements),
            "stage": "applying_improvement",
            "title": spec.get("title") or spec["reason"],
            "message": f"{spec['deployment']} 설정을 개선하고 rollout을 확인하고 있습니다",
        }
        run.updated_at = datetime.now(timezone.utc)
        session.commit()
        try:
            if spec["type"] == "manifest_patch":
                change = workload.patch_deployment(namespace, spec["deployment"], spec["patch"])
            else:
                change = workload.apply_deployment_env(
                    namespace, spec["deployment"], spec["container"], spec["key"], spec["value"])
            if change["before"] != change["after"]:
                changes.append({**change, "id": spec["id"], "title": spec.get("title", ""),
                                "reason": spec["reason"], "applies_to": spec["applies_to"]})
        except Exception:
            for applied in reversed(changes):
                try:
                    _rollback_change(workload, namespace, applied)
                except Exception:
                    logger.exception("improvement rollback failed (%s)", applied["id"])
            raise
    return changes


def _rollback_improvements(run: ScenarioRun, workload) -> None:
    """final 라운드 뒤 적용 개선을 역순 롤백 — 준비 세션을 재사용해도 다음 run의 baseline이 '개선 전'이도록.
    롤백 실패는 기록만(회귀 결과 자체는 유효)."""
    namespace = run.preparation_session.namespace
    for applied in reversed(run.improvement_changes or []):
        try:
            _rollback_change(workload, namespace, applied)
        except Exception:
            logger.exception("post-run improvement rollback failed (run %s, %s)", run.id, applied.get("id"))


def _rollback_change(workload, namespace: str, applied: dict) -> None:
    if applied["type"] == "manifest_patch":
        # before 프로젝션 = 롤백 패치 (strategic merge에서 null은 필드 삭제)
        workload.patch_deployment(namespace, applied["deployment"], applied["before"])
    else:
        workload.apply_deployment_env(
            namespace, applied["deployment"], applied["container"], applied["key"], applied["before"])


def _collect_samples(workload, namespace: str, observation: dict, count: int) -> list[dict]:
    return [take_sample(workload, namespace, observation) for _ in range(count)]


def _restart_delta(before: dict, after: dict) -> int | None:
    if before.get("restart_count") is None or after.get("restart_count") is None:
        return None
    return max(0, int(after["restart_count"]) - int(before["restart_count"]))


def _set_progress(session, run: ScenarioRun, spec: dict, stage: str, message: str,
                  *, round_name: str, current: int | None = None, total: int | None = None) -> None:
    progress = dict(run.progress or {})
    progress.update({"round": round_name, "experiment_id": spec["id"], "title": spec["title"],
                     "stage": stage, "message": message})
    if current is not None:
        progress["current"] = current
    if total is not None:
        progress["total"] = total
    run.progress = progress
    run.updated_at = datetime.now(timezone.utc)
    session.commit()


def _finish(session, run: ScenarioRun, message: str) -> None:
    run.progress = {
        "current": len(run.results or []),
        "total": len((run.scenario or {}).get("experiments") or []),
        "round": "final",
        "stage": run.status,
        "message": message,
    }
    run.finished_at = datetime.now(timezone.utc)
    run.updated_at = run.finished_at
    session.commit()
