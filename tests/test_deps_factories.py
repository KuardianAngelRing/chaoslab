"""팩토리 stub 모드 검증 + real 모듈 import 무결성 (네트워크 호출 없음)."""
from app.config import settings
from app.deps import make_handoff_source, make_loki, make_prometheus
from app.services.stubs import StubHandoffSource, StubLoki, StubPrometheus


def test_factories_return_stubs_in_stub_mode():
    assert isinstance(make_prometheus(), StubPrometheus)
    assert isinstance(make_prometheus("k3s"), StubPrometheus)   # local_kubeconfig 비면 k3s도 Stub
    assert isinstance(make_loki(), StubLoki)
    assert isinstance(make_handoff_source(), StubHandoffSource)


def test_real_modules_importable():
    """lazy import 대상 모듈이 문법·의존성 수준에서 깨지지 않았는지."""
    from app.services.real import handoff_source, kube, loki, prometheus  # noqa: F401
    from app.services.real import local_prometheus  # noqa: F401


def test_make_prometheus_routes_k3s_by_local_kubeconfig(monkeypatch):
    """k3s는 use_real_services와 무관하게 local_kubeconfig 게이트(make_chaos와 동일 규칙)."""
    from app.services.real.local_prometheus import LocalPrometheus

    monkeypatch.setattr(settings, "local_kubeconfig", "/tmp/k3s.yaml")
    assert isinstance(make_prometheus("k3s"), LocalPrometheus)
    assert isinstance(make_prometheus("eks"), StubPrometheus)   # eks는 여전히 use_real_services 게이트


def test_make_workload_routes_by_env(monkeypatch):
    """회귀·준비 세션 워크로드 팩토리(설계 2026-09-29 §1) — k3s는 local_kubeconfig 게이트, eks는 use_real_services 게이트."""
    from app.deps import make_workload
    from app.services.stubs import StubK3sWorkload

    assert isinstance(make_workload("k3s"), StubK3sWorkload)
    assert isinstance(make_workload("eks"), StubK3sWorkload)
    monkeypatch.setattr(settings, "use_real_services", True)
    from app.services.real.eks_workload import RealEksWorkload

    assert isinstance(make_workload("eks"), RealEksWorkload)
    assert isinstance(make_workload("k3s"), StubK3sWorkload)   # k3s는 여전히 local_kubeconfig 게이트
