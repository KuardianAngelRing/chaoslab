"""TrafficGenerator — 단독 실험 중 관측 Service에 보내는 부하 스레드."""
import threading
import time

from app.services.live_traffic import TrafficGenerator


class _CountingWorkload:
    def __init__(self, fail_every: int = 0, raise_every: int = 0):
        self.calls = []
        self.fail_every = fail_every
        self.raise_every = raise_every
        self.lock = threading.Lock()

    def probe_http(self, namespace, service, path):
        with self.lock:
            self.calls.append((namespace, service, path))
            n = len(self.calls)
        if self.raise_every and n % self.raise_every == 0:
            raise RuntimeError("tunnel down")
        ok = not (self.fail_every and n % self.fail_every == 0)
        return {"status_code": 200 if ok else 503, "ok": ok, "latency_ms": 5.0, "error": ""}


def _wait_until(cond, timeout_s=3.0):
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_traffic_generator_probes_observation_target_until_stopped():
    wl = _CountingWorkload()
    obs = {"service": "checkout-api", "path": "/orders", "expected_status": 200}
    gen = TrafficGenerator(wl, "chaoslab-lab-3", obs, interval_s=0.01).start()
    assert gen.running
    assert _wait_until(lambda: gen.requests >= 5)
    gen.stop()
    assert not gen.running
    seen = gen.requests
    time.sleep(0.05)
    assert gen.requests == seen                       # 중지 후 더 이상 요청하지 않음
    assert set(wl.calls) == {("chaoslab-lab-3", "checkout-api", "/orders")}


def test_traffic_generator_counts_failures_and_swallows_exceptions():
    wl = _CountingWorkload(fail_every=2, raise_every=3)
    gen = TrafficGenerator(wl, "ns", {"service": "svc"}, interval_s=0.01).start()  # path 기본 "/"
    assert _wait_until(lambda: gen.requests >= 12)
    gen.stop()
    assert wl.calls[0][2] == "/"
    assert gen.failures >= 4                          # 503과 예외 모두 실패로 계수, 스레드는 죽지 않음
    assert gen.requests >= 12


def test_traffic_generator_stop_is_idempotent_and_safe_before_start():
    gen = TrafficGenerator(_CountingWorkload(), "ns", {"service": "svc"})
    gen.stop()                                        # start 전 stop — 예외 없음
    gen.stop()
    assert gen.requests == 0 and not gen.running
