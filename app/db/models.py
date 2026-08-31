from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.database import Base


def _now() -> datetime:
    return datetime.now(timezone.utc)


class App(Base):
    __tablename__ = "apps"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    repo_url: Mapped[str] = mapped_column(String(300))
    branch: Mapped[str] = mapped_column(String(100), default="main")
    framework: Mapped[str] = mapped_column(String(50))
    health_path: Mapped[str] = mapped_column(String(100), default="/healthz")
    port: Mapped[int] = mapped_column(Integer, default=8080)
    namespace: Mapped[str] = mapped_column(String(100), default="default")
    env: Mapped[str] = mapped_column(String(10), default="eks")  # "eks" | "k3s" (ADR-0002: 환경은 앱 속성)
    manifest: Mapped[str] = mapped_column(Text, default="")  # k3s 전용 — 등록=저장만, 배포는 실험 시 (ADR-0009)
    image_repo: Mapped[str] = mapped_column(String(300), default="")
    current_sha: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    env_vars: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    builds: Mapped[list["Build"]] = relationship(back_populates="app")
    experiments: Mapped[list["Experiment"]] = relationship(back_populates="app")
    preparation_sessions: Mapped[list["ExperimentSession"]] = relationship(back_populates="app")
    scenario_runs: Mapped[list["ScenarioRun"]] = relationship(back_populates="app")


class Build(Base):
    __tablename__ = "builds"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    image_tag: Mapped[str] = mapped_column(String(40), default="")
    workflow_name: Mapped[str] = mapped_column(String(120), default="")
    log_ref: Mapped[str] = mapped_column(String(200), default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    app: Mapped["App"] = relationship(back_populates="builds")


class Experiment(Base):
    __tablename__ = "experiments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    chaos_type: Mapped[str] = mapped_column(String(40))
    params: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(30), default="pending")
    crd_name: Mapped[str] = mapped_column(String(120), default="")
    namespace: Mapped[str] = mapped_column(String(120), default="")  # k3s 현장 배포 전용 ns (ADR-0009)
    candidate_id: Mapped[int | None] = mapped_column(  # 승인된 가설 후보 (가설↔결과 추적)
        ForeignKey("experiment_candidates.id"), nullable=True)
    baseline_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    fault_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    recovery_metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    baseline_r: Mapped[float | None] = mapped_column(Float, nullable=True)
    r_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    target_r: Mapped[float] = mapped_column(Float, default=0.7)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    app: Mapped["App"] = relationship(back_populates="experiments")
    iterations: Mapped[list["AgentIteration"]] = relationship(back_populates="experiment")
    handoffs: Mapped[list["AgentHandoff"]] = relationship(back_populates="experiment")


class ExperimentSession(Base):
    """2단계 실행에 필요한 k3s 환경의 수명주기. 단일 Chaos Experiment와 분리한다."""
    __tablename__ = "experiment_sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    objective: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(30), default="queued")
    namespace: Mapped[str] = mapped_column(String(120), default="")
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    app: Mapped["App"] = relationship(back_populates="preparation_sessions")


class ScenarioRun(Base):
    """준비된 환경에서 수행하는 최종 회귀 1회."""
    __tablename__ = "scenario_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    preparation_session_id: Mapped[int] = mapped_column(ForeignKey("experiment_sessions.id"))
    status: Mapped[str] = mapped_column(String(30), default="queued")
    scenario: Mapped[dict] = mapped_column(JSON, default=dict)
    progress: Mapped[dict] = mapped_column(JSON, default=dict)
    baseline_results: Mapped[list] = mapped_column(JSON, default=list)
    results: Mapped[list] = mapped_column(JSON, default=list)
    improvement_changes: Mapped[list] = mapped_column(JSON, default=list)
    comparison: Mapped[dict] = mapped_column(JSON, default=dict)
    report_content: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
    started_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    app: Mapped["App"] = relationship(back_populates="scenario_runs")
    preparation_session: Mapped["ExperimentSession"] = relationship()


class AgentIteration(Base):
    __tablename__ = "agent_iterations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    iteration: Mapped[int] = mapped_column(Integer)
    observer_output: Mapped[str] = mapped_column(Text, default="")
    analyst_output: Mapped[str] = mapped_column(Text, default="")
    recommender_output: Mapped[str] = mapped_column(Text, default="")
    params_before: Mapped[dict] = mapped_column(JSON, default=dict)
    params_after: Mapped[dict] = mapped_column(JSON, default=dict)
    r_index: Mapped[float | None] = mapped_column(Float, nullable=True)
    verdict: Mapped[str] = mapped_column(String(30), default="")
    llm_cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    experiment: Mapped["Experiment"] = relationship(back_populates="iterations")


class AgentHandoff(Base):
    """AI Agent 전달 페이로드 스냅샷 — 계약 검증된 JSON을 통째로 저장."""

    __tablename__ = "agent_handoffs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    experiment_id: Mapped[int] = mapped_column(ForeignKey("experiments.id"))
    schema_version: Mapped[str] = mapped_column(String(10), default="1.0")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    experiment: Mapped["Experiment"] = relationship(back_populates="handoffs")


class HypothesisRun(Base):
    """가설 수립 요청 (GLOSSARY) — 입력 페이로드 스냅샷 + 모델 스냅샷(하이브리드 4)."""

    __tablename__ = "hypothesis_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("apps.id"))
    goal_text: Mapped[str] = mapped_column(Text, default="")
    candidate_count: Mapped[int] = mapped_column(Integer, default=5)
    status: Mapped[str] = mapped_column(String(30), default="generating")  # generating | ready | failed
    error: Mapped[str] = mapped_column(Text, default="")
    freeform_status: Mapped[str] = mapped_column(String(30), default="")  # "" | generating | failed
    freeform_error: Mapped[str] = mapped_column(Text, default="")
    input_payload: Mapped[dict] = mapped_column(JSON, default=dict)  # 재현·디버깅용 스냅샷
    model_name: Mapped[str] = mapped_column(String(100), default="")
    cli_version: Mapped[str] = mapped_column(String(50), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    app: Mapped["App"] = relationship()
    candidates: Mapped[list["ExperimentCandidate"]] = relationship(back_populates="run")


class ExperimentCandidate(Base):
    """실험 후보 — 1차(서사)는 생성 시, params는 선택 후 detailing이 채움."""

    __tablename__ = "experiment_candidates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey("hypothesis_runs.id"))
    title: Mapped[str] = mapped_column(String(200))
    chaos_type: Mapped[str] = mapped_column(String(40))  # chaos_specs 슬러그
    target_workload: Mapped[str] = mapped_column(String(120))
    hypothesis: Mapped[str] = mapped_column(Text, default="")
    expected_impact: Mapped[str] = mapped_column(Text, default="")
    source: Mapped[str] = mapped_column(String(20), default="agent")  # agent | user_input
    detail_status: Mapped[str] = mapped_column(String(20), default="proposed")  # proposed | detailing | detailed | failed
    params: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # detailing 성공 시
    detail_rationale: Mapped[str] = mapped_column(Text, default="")
    error: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    run: Mapped["HypothesisRun"] = relationship(back_populates="candidates")
