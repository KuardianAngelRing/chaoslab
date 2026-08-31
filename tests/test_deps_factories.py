"""팩토리 stub 모드 검증 + real 모듈 import 무결성 (네트워크 호출 없음)."""
from app.deps import make_handoff_source, make_loki, make_prometheus
from app.services.stubs import StubHandoffSource, StubLoki, StubPrometheus


def test_factories_return_stubs_in_stub_mode():
    assert isinstance(make_prometheus(), StubPrometheus)
    assert isinstance(make_loki(), StubLoki)
    assert isinstance(make_handoff_source(), StubHandoffSource)


def test_real_modules_importable():
    """lazy import 대상 모듈이 문법·의존성 수준에서 깨지지 않았는지."""
    from app.services.real import handoff_source, kube, loki, prometheus  # noqa: F401
