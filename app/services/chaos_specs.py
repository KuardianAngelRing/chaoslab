"""카오스 타입별 파라미터 스키마 + 범위검증. 순수 자료구조·순수 함수 (IO 없음).

키는 슬러그(chaos_type로 DB 저장) — Chaos Mesh CRD kind 하나에 여러 action이
있으므로 kind가 아니라 (kind, action) 쌍을 슬러그로 식별한다 (2026-08-25 확장).
필드 rule: {min, max, label} = 정수 범위 · {type: "str", label} = 문자열(비어있으면 안 됨).
"""

_DURATION = {"min": 30, "max": 1_800, "label": "지속 (초)"}

CHAOS_SPECS: dict[str, dict] = {
    # --- NetworkChaos ---
    "network-delay": {
        "kind": "NetworkChaos", "action": "delay", "label": "네트워크 지연",
        "fields": {
            "latency_ms": {"min": 10, "max": 10_000, "label": "지연 (ms)"},
            "duration_s": _DURATION,
        },
    },
    "network-loss": {
        "kind": "NetworkChaos", "action": "loss", "label": "패킷 유실",
        "fields": {
            "loss_percent": {"min": 1, "max": 100, "label": "유실률 (%)"},
            "duration_s": _DURATION,
        },
    },
    "network-partition": {
        "kind": "NetworkChaos", "action": "partition", "label": "네트워크 단절",
        "fields": {"duration_s": _DURATION},
    },
    "network-bandwidth": {
        "kind": "NetworkChaos", "action": "bandwidth", "label": "대역폭 제한",
        "fields": {
            "rate_mbps": {"min": 1, "max": 1_000, "label": "대역폭 (Mbps)"},
            "duration_s": _DURATION,
        },
    },
    # --- PodChaos ---
    "pod-kill": {
        "kind": "PodChaos", "action": "pod-kill", "label": "파드 강제 종료",
        "fields": {},  # 원샷 — duration 없음
    },
    "pod-failure": {
        "kind": "PodChaos", "action": "pod-failure", "label": "파드 불능",
        "fields": {"duration_s": _DURATION},
    },
    "container-kill": {
        "kind": "PodChaos", "action": "container-kill", "label": "컨테이너 강제 종료",
        "fields": {
            "container_name": {"type": "str", "label": "컨테이너 이름"},
        },  # 원샷 — duration 없음
    },
    # --- StressChaos ---
    "cpu-stress": {
        "kind": "StressChaos", "action": "cpu", "label": "CPU 스트레스",
        "fields": {
            "cpu_load": {"min": 1, "max": 100, "label": "CPU 부하 (%)"},
            "duration_s": _DURATION,
        },
    },
    "memory-stress": {
        "kind": "StressChaos", "action": "memory", "label": "메모리 스트레스",
        "fields": {
            "memory_mb": {"min": 16, "max": 2_048, "label": "메모리 (MiB)"},
            "duration_s": _DURATION,
        },
    },
}


def kind_of(chaos_type: str) -> str:
    """슬러그 → Chaos Mesh CRD kind. 미지원 슬러그면 KeyError."""
    return CHAOS_SPECS[chaos_type]["kind"]


def validate_params(chaos_type: str, form: dict) -> tuple[dict, list[str]]:
    """폼 입력 → (정규화 params, 오류 리스트). 오류가 있으면 params는 빈 dict."""
    spec = CHAOS_SPECS.get(chaos_type)
    if spec is None:
        return {}, [f"지원하지 않는 카오스 종류예요: {chaos_type}"]

    params: dict = {"action": spec["action"]}
    errors: list[str] = []
    for name, rule in spec["fields"].items():
        raw = form.get(name, "")
        if rule.get("type") == "str":
            value = str(raw).strip()
            if not value:
                errors.append(f"{rule['label']}: 입력해 주세요")
                continue
            if len(value) > 63:
                errors.append(f"{rule['label']}: 63자 이하로 입력해 주세요")
                continue
            params[name] = value
            continue
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
