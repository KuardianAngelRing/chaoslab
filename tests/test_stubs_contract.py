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


def test_stub_prometheus_phase_summary_matches_contract():
    from datetime import datetime, timezone

    from app.services.agent.handoff_schema import PhaseSummary

    p = stubs.StubPrometheus()
    t = datetime(2026, 8, 13, tzinfo=timezone.utc)
    for phase in ("baseline", "fault", "recovery"):
        s = PhaseSummary(**p.phase_summary("sut", "demo", phase, t, t))
        if phase == "recovery":
            assert s.recovery_seconds is not None


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
