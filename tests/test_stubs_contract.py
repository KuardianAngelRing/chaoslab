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
    assert set(p.live_snapshot("ns", "app")) == set(stubs.LIVE_SNAPSHOT_KEYS)

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


def test_stub_live_series_is_deterministic_and_moves():
    # 순수 함수: 정상(0~4) → 악화(5~14) → 회복(15~) — 같은 tick은 같은 값, 단계별 값이 실제로 움직인다
    keys = set(stubs.LIVE_SNAPSHOT_KEYS) - {"ts"}
    for t in range(0, 30):
        snap = stubs._stub_live_series(t)
        assert set(snap) == keys
        assert snap == stubs._stub_live_series(t)
    normal, fault, recovered = (stubs._stub_live_series(t) for t in (2, 12, 25))
    assert fault["error_rate_pct"] > normal["error_rate_pct"]
    assert fault["p99_ms"] > normal["p99_ms"] and fault["ready_pods"] < normal["ready_pods"]
    assert recovered["error_rate_pct"] == normal["error_rate_pct"] == 0.3
    assert recovered["ready_pods"] == 3


def test_stub_prometheus_live_snapshot_advances_per_call():
    p = stubs.StubPrometheus()
    a, b = p.live_snapshot("ns", "app"), p.live_snapshot("ns", "app")
    assert "T" in a["ts"]  # ISO 8601
    assert {k: a[k] for k in a if k != "ts"} == stubs._stub_live_series(0)
    assert {k: b[k] for k in b if k != "ts"} == stubs._stub_live_series(1)


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


def test_stub_k3s_workload_patch_deployment_projects_before_after():
    from app.services.improvement_specs import project

    w = stubs.StubK3sWorkload()
    patch = {"spec": {"replicas": 3, "template": {"spec": {"containers": [{
        "name": "app", "lifecycle": {"preStop": {"sleep": {"seconds": 5}}}}]}}}}
    change = w.patch_deployment("ns", "api", patch)
    assert change["type"] == "manifest_patch" and change["rollout_ready"] is True
    assert change["before"] == project({}, patch) and change["after"] == patch
    again = w.patch_deployment("ns", "api", {"spec": {"replicas": 4}})
    assert again["before"] == {"spec": {"replicas": 3}}      # 누적 적용 상태에서 전 값
    restored = w.patch_deployment("ns", "api", change["before"])  # before = 롤백 패치(null → 삭제)
    assert restored["after"]["spec"]["replicas"] is None


def test_stub_hypothesis_agent_proposals_pass_validation():
    from app.services.agent.hypothesis_schema import ImprovementInputPayload
    from app.services.agent.hypothesis_validation import validate_proposals
    from app.services.improvement_specs import ALLOWED_IMPROVEMENTS

    manifest = ("apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: web\nspec:\n  template:\n"
                "    spec:\n      containers:\n        - name: srv\n          image: x\n"
                "          readinessProbe:\n            httpGet: {path: /, port: 80}\n")
    payload = ImprovementInputPayload(
        app={"name": "web", "env": "k3s", "port": 80, "health_path": "/"}, manifest_yaml=manifest,
        manifest_findings=[], candidate={"target_workload": "web"}, experiment={"id": 1},
        phase_summaries={}, allowed_improvements=ALLOWED_IMPROVEMENTS, max_proposals=3)
    raw = stubs.StubHypothesisAgent().propose_improvements(payload)
    proposals, errors = validate_proposals(raw, manifest)
    assert errors == [] and [p.title for p in proposals] == ["readinessProbe 주기 단축", "종료 전 유예(preStop sleep)"]
    assert proposals[0].patch["spec"]["template"]["spec"]["containers"][0]["readinessProbe"] == {
        "periodSeconds": 2, "failureThreshold": 2}                      # 기존 probe → 핸들러 없이 주기만
    # manifest에 없는 워크로드만 담긴 출력 → 전멸
    assert validate_proposals([{**raw[0], "deployment": "ghost"}], manifest) == ([], [
        "제안 1: manifest에 없는 Deployment 'ghost'"])
