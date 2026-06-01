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
    framework: Mapped[str] = mapped_column(String(50))
    health_path: Mapped[str] = mapped_column(String(100), default="/healthz")
    port: Mapped[int] = mapped_column(Integer, default=8080)
    namespace: Mapped[str] = mapped_column(String(100), default="default")
    image_repo: Mapped[str] = mapped_column(String(300), default="")
    current_sha: Mapped[str] = mapped_column(String(40), default="")
    status: Mapped[str] = mapped_column(String(30), default="unknown")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=_now)

    builds: Mapped[list["Build"]] = relationship(back_populates="app")
    experiments: Mapped[list["Experiment"]] = relationship(back_populates="app")


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
