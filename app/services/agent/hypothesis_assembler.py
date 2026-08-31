"""가설 입력 페이로드 조립 — k3s는 저장 manifest 기반이라 순수 함수적(외부 조회 없음).

App 행 + CHAOS_SPECS + 같은 앱 과거 실험 + manifest 정적 분석(하이브리드 5)만으로
조립. EKS 조립기(git/values 기반)는 추후 — 계약은 환경 중립.
"""
from __future__ import annotations

import yaml
from sqlalchemy.orm import Session

from app.db.models import App
from app.services.agent.hypothesis_schema import (
    AllowedChaos,
    HypothesisInputPayload,
    ManifestFinding,
    PastExperimentSummary,
)
from app.services.chaos_specs import CHAOS_SPECS

_MAX_PAST = 10


def analyze_manifest(manifest_yaml: str) -> list[ManifestFinding]:
    """Deployment별 약점 요약 — replicas 1 · probe 없음 · resource limit 없음.

    원문을 대체하지 않는다(하이브리드 5) — 페이로드에 원문과 함께 실린다.
    """
    if not manifest_yaml.strip():
        return []
    try:
        docs = list(yaml.safe_load_all(manifest_yaml))
    except yaml.YAMLError:
        return [ManifestFinding(workload="(manifest)",
                                finding="YAML 파싱 실패 — 원문만 참고할 것")]
    findings: list[ManifestFinding] = []
    for doc in docs:
        if not isinstance(doc, dict) or doc.get("kind") != "Deployment":
            continue
        name = (doc.get("metadata") or {}).get("name") or "(이름 없음)"
        spec = doc.get("spec") or {}
        replicas = spec.get("replicas", 1)
        if isinstance(replicas, int) and replicas <= 1:
            findings.append(ManifestFinding(
                workload=name,
                finding=f"replicas {replicas} — 파드가 1개뿐이라 파드 장애 시 무중단 여력이 없음"))
        containers = (((spec.get("template") or {}).get("spec") or {})
                      .get("containers")) or []
        for c in containers:
            if not isinstance(c, dict):
                continue
            cname = c.get("name", "?")
            if not c.get("livenessProbe") and not c.get("readinessProbe"):
                findings.append(ManifestFinding(
                    workload=name,
                    finding=f"컨테이너 {cname}: probe 없음 — 멈춰도 자동으로 감지·교체되지 않음"))
            if not (c.get("resources") or {}).get("limits"):
                findings.append(ManifestFinding(
                    workload=name,
                    finding=f"컨테이너 {cname}: resource limit 없음 — CPU·메모리 폭주를 막지 못함"))
    return findings


def allowed_chaos_list() -> list[AllowedChaos]:
    """CHAOS_SPECS에서 자동 파생 — 유형 확장 시 에이전트 제안 폭도 자동 확대."""
    return [
        AllowedChaos(chaos_type=slug, kind=spec["kind"], action=spec["action"],
                     label=spec["label"], fields=spec["fields"])
        for slug, spec in CHAOS_SPECS.items()
    ]


def assemble_hypothesis_input(session: Session, app: App, goal_text: str = "",
                              candidate_count: int = 5) -> HypothesisInputPayload:
    count = max(1, min(int(candidate_count if candidate_count is not None else 5), 10))
    past = [
        PastExperimentSummary(chaos_type=e.chaos_type, params=e.params,
                              status=e.status, r_index=e.r_index)
        for e in sorted(app.experiments, key=lambda e: e.id, reverse=True)[:_MAX_PAST]
    ]
    return HypothesisInputPayload(
        app={"name": app.name, "env": app.env, "port": app.port,
             "health_path": app.health_path},
        manifest_yaml=app.manifest or "",
        manifest_findings=analyze_manifest(app.manifest or ""),
        allowed_chaos=allowed_chaos_list(),
        goal_text=goal_text or "",
        past_experiments=past,
        candidate_count=count,
    )
