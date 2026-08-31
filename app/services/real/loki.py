"""Loki 실조회 — query_range 기반 로그 tail + 에러 로그 선별(중복 제거)."""
from datetime import datetime, timedelta, timezone

import httpx

_TIMEOUT_S = 10.0
_LOOKBACK_MIN = 5


def parse_streams(resp: dict) -> list[str]:
    """query_range 응답 → (ts, line) 평탄화 후 최신순 라인 리스트."""
    entries: list[tuple[str, str]] = []
    for stream in resp.get("data", {}).get("result", []):
        for ts, line in stream.get("values", []):
            entries.append((ts, line))
    entries.sort(key=lambda e: e[0], reverse=True)
    return [line for _, line in entries]


class RealLoki:
    def __init__(self, settings):
        self.s = settings

    def _query(self, logql: str, limit: int) -> list[str]:
        end = datetime.now(timezone.utc)
        start = end - timedelta(minutes=_LOOKBACK_MIN)
        r = httpx.get(f"{self.s.loki_url}/loki/api/v1/query_range", params={
            "query": logql, "limit": limit, "direction": "backward",
            "start": int(start.timestamp() * 1e9), "end": int(end.timestamp() * 1e9),
        }, timeout=_TIMEOUT_S)
        r.raise_for_status()
        return parse_streams(r.json())

    def tail(self, namespace: str, limit: int = 100) -> list[str]:
        return self._query(f'{{namespace="{namespace}"}}', limit)

    def error_logs(self, namespace: str, app_name: str, limit: int = 20) -> list[str]:
        lines = self._query(
            f'{{namespace="{namespace}", app="{app_name}"}} |~ "(?i)(error|exception|fail)"',
            limit * 5)
        seen: list[str] = []
        for line in lines:
            if line not in seen:
                seen.append(line)
            if len(seen) >= limit:
                break
        return seen
