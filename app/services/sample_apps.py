"""번들 k3s 예제 앱 registry. 브라우저는 식별자만 보내고 서버가 YAML을 소유한다."""
from __future__ import annotations

from pathlib import Path


_SAMPLES_DIR = Path(__file__).resolve().parents[1] / "samples" / "k3s"
SAMPLE_APPS = {
    "order-resilience-lab": {
        "name": "order-resilience-lab",
        "health_path": "/orders",
        "observe_service": "checkout-api",   # 5개 Service 중 진입점 — 회귀 관측 요청 대상
        "manifest": _SAMPLES_DIR / "order-resilience-lab.yaml",
    },
    "nginx": {
        "name": "nginx",
        "health_path": "/",
        "observe_service": "nginx",
        "manifest": _SAMPLES_DIR / "nginx.yaml",
    },
}


def get_sample_app(sample_id: str) -> dict | None:
    """허용된 예제만 반환한다. 임의 경로나 브라우저 YAML을 샘플로 취급하지 않는다."""
    sample = SAMPLE_APPS.get(sample_id)
    if sample is None:
        return None
    return {**sample, "manifest_text": sample["manifest"].read_text(encoding="utf-8")}
