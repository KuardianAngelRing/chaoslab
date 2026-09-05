"""단독 실험(2단계) 동안 관측 Service에 주기적으로 요청을 보내는 트래픽 생성기.

회귀(3단계)는 `take_sample`이 샘플당 3회 요청하지만 단독 실험은 아무도 요청을 보내지 않아
Prometheus의 rps·오류율·레이턴시 시리즈가 빈 벡터였다(2026-09-06 설계 메모). 이 스레드는
부하만 만든다 — 결과는 저장하지 않고 카운트만 남기며, 관측·판정은 기존 소급 집계가 담당한다.
"""
from __future__ import annotations

import logging
import threading

logger = logging.getLogger(__name__)

DEFAULT_INTERVAL_S = 0.5   # ≈ 2 rps — API 서버 서비스 프록시·SSH 터널에 무시할 수준


class TrafficGenerator:
    """`workload.probe_http(namespace, service, path)`를 interval_s 간격으로 반복하는 데몬 스레드 1개."""

    def __init__(self, workload, namespace: str, observation: dict,
                 interval_s: float = DEFAULT_INTERVAL_S) -> None:
        self.workload = workload
        self.namespace = namespace
        self.service = observation["service"]
        self.path = observation.get("path") or "/"
        self.interval_s = max(0.05, float(interval_s))
        self.requests = 0
        self.failures = 0
        self._stop = threading.Event()
        self._thread = threading.Thread(
            target=self._run, name=f"live-traffic-{namespace}", daemon=True)

    def start(self) -> "TrafficGenerator":
        self._thread.start()
        return self

    def stop(self, timeout_s: float = 5.0) -> None:
        """중지 신호 후 스레드 종료 대기 — 진행 중인 요청 1회는 끝까지 기다린다(idempotent)."""
        self._stop.set()
        if self._thread.is_alive():
            self._thread.join(timeout_s)
        logger.info("live traffic stopped (%s/%s%s): %d requests, %d failures",
                    self.namespace, self.service, self.path, self.requests, self.failures)

    @property
    def running(self) -> bool:
        return self._thread.is_alive() and not self._stop.is_set()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                r = self.workload.probe_http(self.namespace, self.service, self.path)
                if not r.get("ok"):
                    self.failures += 1
            except Exception:  # noqa: BLE001 — 부하 생성 실패가 실험 워처를 깨뜨리면 안 된다
                self.failures += 1
            self.requests += 1
            self._stop.wait(self.interval_s)
