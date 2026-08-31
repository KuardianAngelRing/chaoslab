"""최종 회귀 시나리오 계약과 순차 실행."""
from __future__ import annotations

import logging
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import yaml

from app.db.database import SessionLocal
from app.db.models import Experiment, ScenarioRun
from app.deps import make_chaos, make_k3s_workload
from app.services.chaos_specs import validate_params
from app.services.observations import summarize, take_sample
from app.services.report_writer import write_report
from app.services.resilience import compare_runs, evaluate_experiment

logger = logging.getLogger(__name__)

_SCENARIOS = Path(__file__).parents[1] / "samples" / "scenarios"
_POLL_S = 5
_PODKILL_GRACE_S = 30
_RECOVER_POLLS = 60
_CRITERIA_KEYS = {
    "max_error_rate_pct", "max_p95_latency_ms", "max_recovery_seconds", "min_ready_pods",
}
_IMPROVEMENT_KEYS = {
    "id", "type", "deployment", "container", "key", "value", "reason", "applies_to",
}


def scenario_snapshot(app_name: str, selected_ids: list[str]) -> dict:
    """등록된 시나리오에서 사용자가 고른 실험과 허용된 개선만 원래 순서로 고정한다."""
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
        if set(item) != _IMPROVEMENT_KEYS or item.get("type") != "deployment_env":
            raise ValueError("허용되지 않은 개선 명세입니다")
        if selected.intersection(item["applies_to"]):
            improvements.append(item)
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
        poll_count = max(1, math.ceil(duration / _POLL_S))
        recovered = False
        for poll_index in range(poll_count):
            phase = chaos.phase(spec["chaos_type"], crd_name)
            if phase in {"running", "recovered"}:
                injection_confirmed = True
            during_samples.append(take_sample(workload, namespace, observation))
            if phase == "recovered":
                recovered = True
                break
            # 원샷 액션(pod-kill·container-kill)은 recovered 조건이 없어 주입 확인으로 종료
            if spec["chaos_type"] in ("pod-kill", "container-kill") and injection_confirmed:
                recovered = True
                break
            if poll_index + 1 < poll_count:
                time.sleep(_POLL_S)
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
    changes = []
    improvements = (run.scenario or {}).get("improvements") or []
    for index, spec in enumerate(improvements):
        run.progress = {
            "round": "improvement",
            "current": index + 1,
            "total": len(improvements),
            "stage": "applying_improvement",
            "title": spec["reason"],
            "message": f"{spec['deployment']} 설정을 개선하고 rollout을 확인하고 있습니다",
        }
        run.updated_at = datetime.now(timezone.utc)
        session.commit()
        try:
            change = workload.apply_deployment_env(
                run.preparation_session.namespace,
                spec["deployment"],
                spec["container"],
                spec["key"],
                spec["value"],
            )
            if change["before"] != change["after"]:
                changes.append({**change, "id": spec["id"], "reason": spec["reason"],
                                "applies_to": spec["applies_to"]})
        except Exception:
            for applied in reversed(changes):
                try:
                    workload.apply_deployment_env(
                        run.preparation_session.namespace,
                        applied["deployment"], applied["container"], applied["key"], applied["before"],
                    )
                except Exception:
                    logger.exception("improvement rollback failed (%s)", applied["id"])
            raise
    return changes


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
