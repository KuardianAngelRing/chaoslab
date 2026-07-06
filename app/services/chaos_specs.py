"""카오스 타입별 파라미터 스키마 + 범위검증. 순수 자료구조·순수 함수 (IO 없음)."""

CHAOS_SPECS: dict[str, dict] = {
    "NetworkChaos": {
        "action": "delay",
        "fields": {
            "latency_ms": {"min": 10, "max": 10_000, "label": "지연 (ms)"},
            "duration_s": {"min": 30, "max": 1_800, "label": "지속 (초)"},
        },
    },
    "PodChaos": {
        "action": "pod-kill",
        "fields": {},  # 원샷 — duration 없음
    },
    "StressChaos": {
        "action": "cpu",
        "fields": {
            "cpu_load": {"min": 1, "max": 100, "label": "CPU 부하 (%)"},
            "duration_s": {"min": 30, "max": 1_800, "label": "지속 (초)"},
        },
    },
}


def validate_params(chaos_type: str, form: dict) -> tuple[dict, list[str]]:
    """폼 입력 → (정규화 params, 오류 리스트). 오류가 있으면 params는 빈 dict."""
    spec = CHAOS_SPECS.get(chaos_type)
    if spec is None:
        return {}, [f"지원하지 않는 카오스 종류예요: {chaos_type}"]

    params: dict = {"action": spec["action"]}
    errors: list[str] = []
    for name, rule in spec["fields"].items():
        raw = form.get(name, "")
        try:
            value = int(str(raw).strip())
        except (ValueError, TypeError):
            errors.append(f"{rule['label']}: 숫자로 입력해 주세요")
            continue
        if not (rule["min"] <= value <= rule["max"]):
            errors.append(f"{rule['label']}: {rule['min']}~{rule['max']} 범위로 입력해 주세요")
            continue
        params[name] = value
    return ({}, errors) if errors else (params, [])
