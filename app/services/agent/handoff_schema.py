"""AI Agent 전달 데이터 계약 (Phase 3 공통 인터페이스).

08/04 회의 노션 「카오스 테스트 — 모니터링 표시 데이터 & AI Agent 전달 데이터」 §2 매핑.
전달 시점: 기준선/장애/회복 단계 요약 3벌 + 추가 자료 8종을 회복 종료 후 한 번에.
이 모델의 JSON Schema가 팀 공유 계약 — /docs 에 자동 노출된다.
"""
from pydantic import BaseModel, ConfigDict, Field

SCHEMA_VERSION = "1.0"


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")  # 오타 필드가 조용히 통과하지 않게


class PhaseSummary(_Strict):
    """단계별 지표 요약 (노션 §2-①). 키는 화면 지표와 같은 원천의 집계값."""

    rps_avg: float
    rps_min: float
    rps_max: float
    error_rate_avg: float        # %
    error_rate_peak: float       # %
    http_5xx_count: int
    status_code_dist: dict[str, int]
    latency_p50_avg_ms: float
    latency_p50_peak_ms: float
    latency_p95_avg_ms: float
    latency_p95_peak_ms: float
    latency_p99_avg_ms: float
    latency_p99_peak_ms: float
    min_ready_pods: int
    restart_count: int
    recovery_seconds: float | None = None  # recovery 단계만 채움


class PhaseSummaries(_Strict):
    baseline: PhaseSummary
    fault: PhaseSummary
    recovery: PhaseSummary


class ExperimentInfo(_Strict):
    """실험 정보 + 파라미터 허용 범위 — 개선안이 범위를 벗어나지 않게."""

    id: int
    app_name: str
    namespace: str
    chaos_type: str
    status: str
    params: dict
    allowed_ranges: dict  # chaos_specs.CHAOS_SPECS[chaos_type]["fields"]
    started_at: str | None
    finished_at: str | None


class IstioConfig(_Strict):
    """AI가 고칠 대상 원본 — timeout·retry(VS), circuit breaker(DR)."""

    virtual_service_yaml: str
    destination_rule_yaml: str


class DeploymentInfo(_Strict):
    replicas: int
    probes: dict
    resources: dict


class K8sEvent(_Strict):
    timestamp: str
    type: str
    reason: str
    object: str
    message: str


class RIndexBreakdown(_Strict):
    """R = 0.4·가용성 + 0.3·레이턴시점수 + 0.3·복구속도 — 항목별 내역."""

    availability: float
    latency_score: float
    recovery_score: float
    weights: dict[str, float] = Field(
        default_factory=lambda: {"availability": 0.4, "latency": 0.3, "recovery": 0.3}
    )
    baseline_r: float | None
    current_r: float | None
    target_r: float


class ImprovementAttempt(_Strict):
    """이전 개선 시도 1건 (AgentIteration 대응) — 같은 개선을 반복하지 않게."""

    iteration: int
    params_before: dict
    params_after: dict
    r_index: float | None
    verdict: str


class Budget(_Strict):
    llm_cost_used_usd: float
    llm_cost_remaining_usd: float
    iterations_remaining: int


class AgentHandoffPayload(_Strict):
    schema_version: str = SCHEMA_VERSION
    experiment: ExperimentInfo
    phase_summaries: PhaseSummaries
    istio_config: IstioConfig
    deployment_info: DeploymentInfo
    k8s_events: list[K8sEvent]
    error_log_samples: list[str] = Field(default_factory=list, max_length=20)
    r_index: RIndexBreakdown
    improvement_history: list[ImprovementAttempt]
    budget: Budget
