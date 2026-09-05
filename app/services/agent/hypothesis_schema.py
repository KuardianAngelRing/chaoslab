"""가설 수립 계약 (스펙 2026-08-25 2차 개정 §1) — handoff_schema와 대칭.

2단 프로세스: generate/concretize 출력은 CandidateProposal(서사만, params 없음),
선택 후 detail 출력이 DetailingResult(params). params 검증은 chaos_specs가 담당.
"""
from pydantic import BaseModel, ConfigDict

HYPOTHESIS_SCHEMA_VERSION = "1.0"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 오타 필드가 조용히 통과하지 않게


class AllowedChaos(_Strict):
    """chaos_specs.CHAOS_SPECS 1종 대응 — 가드레일: 이 범위 안에서만 제안."""

    chaos_type: str                   # 슬러그 (예: network-delay, pod-failure)
    kind: str                         # Chaos Mesh CRD kind
    action: str
    label: str
    fields: dict                      # {name: {min, max, label} | {type: "str", label}}


class ManifestFinding(_Strict):
    """하이브리드 5 — 서버 정적 분석 요약 1건 (원문 대체 아님, 원문과 함께 제공)."""

    workload: str                     # Deployment 이름
    finding: str                      # 예: "replicas 1 — 단일 파드", "probe 없음"


class PastExperimentSummary(_Strict):
    """같은 앱 과거 실험 1건 — 중복 제안 회피."""

    chaos_type: str
    params: dict
    status: str
    r_index: float | None = None


class HypothesisInputPayload(_Strict):
    schema_version: str = HYPOTHESIS_SCHEMA_VERSION
    app: dict                         # name · env · port · health_path
    manifest_yaml: str                # k3s: 저장 원문 그대로 — 요약으로 정보 깎지 않음
    manifest_findings: list[ManifestFinding]
    allowed_chaos: list[AllowedChaos]
    goal_text: str = ""               # 검증 목표(선택)
    past_experiments: list[PastExperimentSummary]
    candidate_count: int              # 1~10


class CandidateProposal(_Strict):
    """1차(generate/concretize) 출력 1건 — 근거형 카드(ADR-0007) 필드, params 없음."""

    title: str
    chaos_type: str                   # 슬러그
    target_workload: str              # manifest 내 Deployment 이름
    hypothesis: str                   # 가설 한 줄 — 실패 예상형
    expected_impact: str


class DetailingResult(_Strict):
    """2차(detail) 출력 — 선택된 후보 1건의 params."""

    params: dict                      # chaos_specs.validate_params 통과 필수
    rationale: str = ""               # 값 선정 근거 한 줄(카드 미노출, 이력용)


# ── 3단 — 개선 제안 (설계 2026-09-05 §2) ──

class ImprovementInputPayload(_Strict):
    """propose_improvements 입력 — 핸드오프 계약 중 실측(phase_summaries)만 싣고
    k3s Stub 소스산(istio·events·logs)은 싣지 않는다(규칙 1: 페이로드 사실만 인용)."""

    schema_version: str = HYPOTHESIS_SCHEMA_VERSION
    app: dict                         # name · env · port · health_path
    manifest_yaml: str
    manifest_findings: list[ManifestFinding]
    candidate: dict                   # title · chaos_type · target_workload · hypothesis · params
    experiment: dict                  # id · status · r_index · started_at · finished_at
    phase_summaries: dict             # {baseline, fault, recovery} — 저장 *_metrics 그대로, 없으면 {}
    allowed_improvements: dict        # improvement_specs.ALLOWED_IMPROVEMENTS
    max_proposals: int                # 1~3


class ImprovementProposalOut(_Strict):
    """propose_improvements 출력 1건 — improvement_specs.validate_improvement 통과 필수."""

    title: str
    type: str                         # deployment_env | manifest_patch
    deployment: str
    container: str = ""
    key: str = ""
    value: str = ""
    patch: dict = {}
    rationale: str
    expected_effect: str
