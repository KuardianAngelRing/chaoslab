from app.services import interfaces, stubs
from app.services.interfaces import BuildRequest


def test_stubs_satisfy_protocols():
    b: interfaces.BuilderService = stubs.StubBuilder()
    req = BuildRequest(app_name="svc", repo_url="https://x/svc", framework="fastapi",
                       git_sha="abc123def456", image="reg/svc:abc123de")
    assert isinstance(b.trigger_build(req), str)
    assert b.build_status("wf") in {"pending", "running", "succeeded", "failed"}

    c: interfaces.ChaosService = stubs.StubChaos()
    assert isinstance(c.inject("ns", "app", "network-delay", {"delay": "1s"}), str)

    p: interfaces.PrometheusService = stubs.StubPrometheus()
    red = p.red_metrics("ns")
    assert {"rate", "error", "duration"} <= set(red)

    k: interfaces.K8sService = stubs.StubK8s()
    assert isinstance(k.nodes(), list)
    assert isinstance(k.components(), list)


def test_stub_local_k8s_overview_shape():
    lk: interfaces.LocalK8sService = stubs.StubLocalK8s()
    ov = lk.overview()
    assert {"cluster", "pod_count", "namespaces", "nodes", "components"} <= set(ov)
    assert {"name", "version", "arch", "access", "healthy"} <= set(ov["cluster"])
    for node in ov["nodes"]:
        assert {"name", "model", "role", "cpu_pct", "mem_pct", "temp_c", "status"} <= set(node)
    for comp in ov["components"]:
        assert {"name", "detail", "ns", "status"} <= set(comp)


def test_make_local_k8s_returns_stub_without_kubeconfig():
    from app.deps import make_local_k8s

    assert isinstance(make_local_k8s(), stubs.StubLocalK8s)


def test_stub_tunnel_contract():
    t: interfaces.TunnelService = stubs.StubTunnel()
    assert t.status()["state"] == "disabled"


def test_make_tunnel_returns_stub_singleton_without_ssh_host():
    from app import deps

    t1 = deps.make_tunnel()
    assert isinstance(t1, stubs.StubTunnel)
    assert deps.make_tunnel() is t1  # 생명주기 싱글턴


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
    name = stub.inject("sut", "demo", "network-delay", {"action": "delay"})
    assert isinstance(name, str) and name
    assert stub.phase("network-delay", name) == "recovered"
    assert stub.delete("network-delay", name) is None


def test_make_chaos_returns_stub_in_stub_mode():
    from app.deps import make_chaos
    from app.services.stubs import StubChaos

    assert isinstance(make_chaos(), StubChaos)


def test_stub_k3s_workload_contract():
    w: interfaces.K3sWorkloadService = stubs.StubK3sWorkload()
    assert w.deploy("ns", "kind: Deployment") is None
    assert w.wait_ready("ns") is True
    assert w.teardown("ns") is None


def test_make_chaos_routes_by_env(monkeypatch):
    """k3s + local_kubeconfig → 로컬 kubeconfig·ns 전체 selector로 바인딩된 Real."""
    from app.config import settings
    from app.deps import make_chaos
    from app.services.real.chaos import RealChaos

    assert isinstance(make_chaos("k3s", "chaoslab-x-1"), stubs.StubChaos)  # 미설정 → Stub

    monkeypatch.setattr(settings, "local_kubeconfig", "/tmp/k3s.yaml")
    chaos = make_chaos("k3s", "chaoslab-x-1")
    assert isinstance(chaos, RealChaos)
    assert chaos.namespace == "chaoslab-x-1"
    assert chaos.kubeconfig == "/tmp/k3s.yaml"
    assert chaos.label_selector is False
    assert isinstance(make_chaos("eks"), stubs.StubChaos)  # eks는 use_real_services 게이트
