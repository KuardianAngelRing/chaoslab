from app.services import interfaces, stubs


def test_stubs_satisfy_protocols():
    b: interfaces.BuilderService = stubs.StubBuilder()
    assert isinstance(b.trigger_build(1, "abc123"), str)
    assert b.build_status("wf") in {"pending", "running", "succeeded", "failed"}

    c: interfaces.ChaosService = stubs.StubChaos()
    assert isinstance(c.inject("ns", "NetworkChaos", {"delay": "1s"}), str)

    p: interfaces.PrometheusService = stubs.StubPrometheus()
    red = p.red_metrics("ns")
    assert {"rate", "error", "duration"} <= set(red)

    k: interfaces.K8sService = stubs.StubK8s()
    assert isinstance(k.nodes(), list)
    assert isinstance(k.components(), list)


def test_stub_loki_returns_lines():
    lines = stubs.StubLoki().tail("ns", limit=5)
    assert isinstance(lines, list) and len(lines) == 5
