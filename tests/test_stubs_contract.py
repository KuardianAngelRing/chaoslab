from app.services import interfaces, stubs
from app.services.interfaces import BuildRequest


def test_stubs_satisfy_protocols():
    b: interfaces.BuilderService = stubs.StubBuilder()
    req = BuildRequest(app_name="svc", repo_url="https://x/svc", framework="fastapi",
                       git_sha="abc123def456", image="reg/svc:abc123de")
    assert isinstance(b.trigger_build(req), str)
    assert b.build_status("wf") in {"pending", "running", "succeeded", "failed"}

    c: interfaces.ChaosService = stubs.StubChaos()
    assert isinstance(c.inject("ns", "app", "NetworkChaos", {"delay": "1s"}), str)

    p: interfaces.PrometheusService = stubs.StubPrometheus()
    red = p.red_metrics("ns")
    assert {"rate", "error", "duration"} <= set(red)

    k: interfaces.K8sService = stubs.StubK8s()
    assert isinstance(k.nodes(), list)
    assert isinstance(k.components(), list)


def test_stub_loki_returns_lines():
    lines = stubs.StubLoki().tail("ns", limit=5)
    assert isinstance(lines, list) and len(lines) == 5


def test_stub_chaos_matches_new_protocol():
    from app.services.stubs import StubChaos

    stub = StubChaos()
    name = stub.inject("sut", "demo", "NetworkChaos", {"action": "delay"})
    assert isinstance(name, str) and name
    assert stub.phase("NetworkChaos", name) == "recovered"
    assert stub.delete("NetworkChaos", name) is None


def test_make_chaos_returns_stub_in_stub_mode():
    from app.deps import make_chaos
    from app.services.stubs import StubChaos

    assert isinstance(make_chaos(), StubChaos)


def test_stub_k8s_events_shape():
    """이벤트 피드 계약: source/reason/message/ts, ts는 naive UTC(DB datetime과 정렬 호환)."""
    from app.services.stubs import StubK8s

    events = StubK8s().events("online-boutique")
    assert len(events) >= 3
    for e in events:
        assert {"source", "reason", "message", "ts"} <= set(e)
        assert e["source"] in ("chaos", "k8s")
        assert e["ts"].tzinfo is None  # naive — DB datetime과 비교 가능해야 함
