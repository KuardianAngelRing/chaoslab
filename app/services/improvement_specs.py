"""개선 명세 화이트리스트 검증 — chaos_specs와 같은 순수 함수 (설계 2026-09-05 §3).

타입 2종: deployment_env(환경변수 1개) · manifest_patch(Deployment 루트 strategic merge patch —
probe·preStop·resources·replicas만). env는 manifest_patch에서 거부(타입 간 경로 중복 없음).
Istio timeout/retry/circuitBreaker는 EKS 전용 — Real 소스 연결 시 istio_patch 타입으로 추가.
"""
from __future__ import annotations

import copy
import re

IMPROVEMENT_TYPES = ("deployment_env", "manifest_patch")

_ENV_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_QUANTITY_RE = re.compile(r"^\d+(\.\d+)?(m|Mi|Gi|M|G|Ki|k)?$")
_PROBE_INT_FIELDS = {"initialDelaySeconds", "periodSeconds", "timeoutSeconds",
                     "successThreshold", "failureThreshold"}
_PROBE_HANDLERS = ("httpGet", "tcpSocket", "exec")
_PRESTOP_HANDLERS = ("sleep", "exec")
_CONTAINER_KEYS = {"readinessProbe", "livenessProbe", "lifecycle", "resources"}
_MAX_VALUE_LEN = 200

# 에이전트 페이로드에 실리는 선언형 요약(allowed_chaos 대응) — 규칙 변경 시 여기도 함께.
ALLOWED_IMPROVEMENTS = {
    "deployment_env": {
        "label": "환경변수 값 변경",
        "fields": {"deployment": "Deployment 이름", "container": "컨테이너 이름",
                   "key": "이미 정의된 환경변수 이름(대문자·숫자·_)", "value": "새 값(문자열, 200자 이하)"},
    },
    "manifest_patch": {
        "label": "Deployment 매니페스트 패치 (strategic merge patch, Deployment 루트 기준)",
        "allowed_paths": {
            "spec.replicas": "정수 1~10",
            "spec.template.spec.containers[].name": "필수 — 매칭 키",
            "spec.template.spec.containers[].readinessProbe | livenessProbe":
                "initialDelaySeconds·periodSeconds·timeoutSeconds·successThreshold·failureThreshold(정수 1~300)"
                " + 핸들러 httpGet{path,port} / tcpSocket{port} / exec{command[]} 중 최대 1개"
                " (probe가 없던 컨테이너에 추가할 때는 핸들러 필수)",
            "spec.template.spec.containers[].lifecycle.preStop": "sleep{seconds 1~60} 또는 exec{command[]} 중 1개",
            "spec.template.spec.containers[].resources.requests | limits": "cpu·memory (k8s quantity: 100m, 256Mi, 0.5, 1Gi)",
        },
        "forbidden": "env(→ deployment_env 타입 사용)·image·command·args·strategy·volumes 등 그 외 전부",
    },
}


def validate_improvement(raw: dict) -> tuple[dict, list[str]]:
    """원시 명세 → (정규화 명세, 오류). 오류가 있으면 정규화 결과는 신뢰하지 않는다."""
    if not isinstance(raw, dict):
        return {}, ["개선 명세가 객체가 아님"]
    errors: list[str] = []
    kind = raw.get("type")
    if kind not in IMPROVEMENT_TYPES:
        return {}, [f"지원하지 않는 개선 타입 '{kind}'"]
    deployment = str(raw.get("deployment") or "").strip()
    if not deployment:
        errors.append("deployment 이름이 비어 있음")
    container = str(raw.get("container") or "").strip()
    normalized = {"type": kind, "deployment": deployment, "container": container}

    if kind == "deployment_env":
        key = str(raw.get("key") or "").strip()
        value = raw.get("value")
        if not container:
            errors.append("deployment_env는 container 이름이 필요함")
        if not _ENV_KEY_RE.match(key):
            errors.append(f"환경변수 이름 형식 오류 '{key}'")
        if value is None or not isinstance(value, (str, int, float)):
            errors.append("value는 문자열이어야 함")
        elif len(str(value)) > _MAX_VALUE_LEN:
            errors.append(f"value는 {_MAX_VALUE_LEN}자 이하")
        normalized.update({"key": key, "value": "" if value is None else str(value), "patch": {}})
        return normalized, errors

    patch = raw.get("patch")
    if not isinstance(patch, dict) or not patch:
        return normalized, errors + ["patch는 비어 있지 않은 객체여야 함"]
    clean, patch_errors = _validate_patch(patch)
    errors.extend(patch_errors)
    normalized.update({"key": "", "value": "", "patch": clean})
    return normalized, errors


def _validate_patch(patch: dict) -> tuple[dict, list[str]]:
    errors: list[str] = []
    extra = set(patch) - {"spec"}
    if extra:
        errors.append(f"허용되지 않은 최상위 키 {sorted(extra)}")
    spec = patch.get("spec")
    if not isinstance(spec, dict) or not spec:
        return {}, errors + ["patch.spec이 비어 있음"]
    extra = set(spec) - {"replicas", "template"}
    if extra:
        errors.append(f"허용되지 않은 spec 키 {sorted(extra)}")
    clean: dict = {"spec": {}}
    if "replicas" in spec:
        replicas = spec["replicas"]
        if not isinstance(replicas, int) or isinstance(replicas, bool) or not 1 <= replicas <= 10:
            errors.append("spec.replicas는 1~10 정수")
        else:
            clean["spec"]["replicas"] = replicas
    if "template" in spec:
        containers = (((spec.get("template") or {}).get("spec") or {}).get("containers"))
        template_extra = set(spec.get("template") or {}) - {"spec"}
        pod_extra = set((spec.get("template") or {}).get("spec") or {}) - {"containers"}
        if template_extra or pod_extra:
            errors.append(f"허용되지 않은 template 키 {sorted(template_extra | pod_extra)}")
        if not isinstance(containers, list) or not containers:
            errors.append("containers는 비어 있지 않은 배열")
        else:
            clean_containers = []
            for item in containers:
                c, c_errors = _validate_container(item)
                errors.extend(c_errors)
                clean_containers.append(c)
            clean["spec"]["template"] = {"spec": {"containers": clean_containers}}
    if not clean["spec"]:
        errors.append("patch에 변경 내용이 없음")
    return clean, errors


def _validate_container(item) -> tuple[dict, list[str]]:
    errors: list[str] = []
    if not isinstance(item, dict) or not str(item.get("name") or "").strip():
        return {}, ["containers 항목에 name 필요"]
    name = str(item["name"]).strip()
    clean: dict = {"name": name}
    extra = set(item) - _CONTAINER_KEYS - {"name"}
    if extra:
        errors.append(f"컨테이너 {name}: 허용되지 않은 키 {sorted(extra)}"
                      + (" (env는 deployment_env 타입으로)" if "env" in extra else ""))
    for probe_key in ("readinessProbe", "livenessProbe"):
        if probe_key in item:
            probe, p_errors = _validate_probe(item[probe_key], f"{name}.{probe_key}")
            errors.extend(p_errors)
            clean[probe_key] = probe
    if "lifecycle" in item:
        lifecycle, l_errors = _validate_lifecycle(item["lifecycle"], name)
        errors.extend(l_errors)
        clean["lifecycle"] = lifecycle
    if "resources" in item:
        resources, r_errors = _validate_resources(item["resources"], name)
        errors.extend(r_errors)
        clean["resources"] = resources
    if len(clean) == 1:
        errors.append(f"컨테이너 {name}: 변경 내용이 없음")
    return clean, errors


def _validate_probe(probe, where: str) -> tuple[dict, list[str]]:
    if not isinstance(probe, dict) or not probe:
        return {}, [f"{where}: probe는 비어 있지 않은 객체"]
    errors: list[str] = []
    clean: dict = {}
    handlers = [h for h in _PROBE_HANDLERS if h in probe]
    extra = set(probe) - _PROBE_INT_FIELDS - set(_PROBE_HANDLERS)
    if extra:
        errors.append(f"{where}: 허용되지 않은 키 {sorted(extra)}")
    if len(handlers) > 1:
        errors.append(f"{where}: 핸들러는 1개만 ({handlers})")
    for field in _PROBE_INT_FIELDS & set(probe):
        value = probe[field]
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 300:
            errors.append(f"{where}.{field}: 1~300 정수")
        else:
            clean[field] = value
    for handler in handlers:
        body, h_errors = _validate_handler(handler, probe[handler], f"{where}.{handler}")
        errors.extend(h_errors)
        clean[handler] = body
    return clean, errors


def _validate_handler(handler: str, body, where: str) -> tuple[dict, list[str]]:
    if not isinstance(body, dict):
        return {}, [f"{where}: 객체여야 함"]
    if handler == "httpGet":
        path, port = body.get("path", "/"), body.get("port")
        extra = set(body) - {"path", "port"}
        errors = [f"{where}: 허용되지 않은 키 {sorted(extra)}"] if extra else []
        if not isinstance(path, str) or not path.startswith("/"):
            errors.append(f"{where}.path: '/'로 시작하는 문자열")
        if not _valid_port(port):
            errors.append(f"{where}.port: 1~65535 정수 또는 포트 이름")
        return {"path": path, "port": port}, errors
    if handler == "tcpSocket":
        extra = set(body) - {"port"}
        errors = [f"{where}: 허용되지 않은 키 {sorted(extra)}"] if extra else []
        if not _valid_port(body.get("port")):
            errors.append(f"{where}.port: 1~65535 정수 또는 포트 이름")
        return {"port": body.get("port")}, errors
    command = body.get("command")
    extra = set(body) - {"command"}
    errors = [f"{where}: 허용되지 않은 키 {sorted(extra)}"] if extra else []
    if not isinstance(command, list) or not command or not all(isinstance(c, str) for c in command):
        errors.append(f"{where}.command: 문자열 배열")
    return {"command": command}, errors


def _validate_lifecycle(lifecycle, name: str) -> tuple[dict, list[str]]:
    where = f"{name}.lifecycle"
    if not isinstance(lifecycle, dict) or set(lifecycle) != {"preStop"}:
        return {}, [f"{where}: preStop만 허용"]
    pre_stop = lifecycle["preStop"]
    if not isinstance(pre_stop, dict):
        return {}, [f"{where}.preStop: 객체여야 함"]
    handlers = [h for h in _PRESTOP_HANDLERS if h in pre_stop]
    errors: list[str] = []
    if set(pre_stop) - set(_PRESTOP_HANDLERS) or len(handlers) != 1:
        return {}, [f"{where}.preStop: sleep 또는 exec 중 정확히 1개"]
    handler = handlers[0]
    if handler == "sleep":
        seconds = (pre_stop["sleep"] or {}).get("seconds") if isinstance(pre_stop["sleep"], dict) else None
        if not isinstance(seconds, int) or isinstance(seconds, bool) or not 1 <= seconds <= 60:
            errors.append(f"{where}.preStop.sleep.seconds: 1~60 정수")
        return {"preStop": {"sleep": {"seconds": seconds}}}, errors
    body, h_errors = _validate_handler("exec", pre_stop["exec"], f"{where}.preStop.exec")
    return {"preStop": {"exec": body}}, h_errors


def _validate_resources(resources, name: str) -> tuple[dict, list[str]]:
    where = f"{name}.resources"
    if not isinstance(resources, dict) or not resources:
        return {}, [f"{where}: 비어 있지 않은 객체"]
    errors: list[str] = []
    clean: dict = {}
    extra = set(resources) - {"requests", "limits"}
    if extra:
        errors.append(f"{where}: 허용되지 않은 키 {sorted(extra)}")
    for bucket in ("requests", "limits"):
        if bucket not in resources:
            continue
        values = resources[bucket]
        if not isinstance(values, dict) or not values:
            errors.append(f"{where}.{bucket}: 비어 있지 않은 객체")
            continue
        extra = set(values) - {"cpu", "memory"}
        if extra:
            errors.append(f"{where}.{bucket}: cpu·memory만 허용 {sorted(extra)}")
        clean[bucket] = {}
        for key in ("cpu", "memory"):
            if key in values:
                quantity = str(values[key])
                if not _QUANTITY_RE.match(quantity):
                    errors.append(f"{where}.{bucket}.{key}: quantity 형식 오류 '{quantity}'")
                clean[bucket][key] = quantity
    return clean, errors


def _valid_port(port) -> bool:
    if isinstance(port, bool):
        return False
    if isinstance(port, int):
        return 1 <= port <= 65535
    return isinstance(port, str) and bool(re.match(r"^[a-z0-9-]{1,15}$", port))


# ── 경로 표현 · 프로젝션 (UI diff · 보고서 표 · 롤백 패치 공용) ──

def flatten_patch(patch: dict) -> list[str]:
    """patch의 리프 경로 목록 — 컨테이너는 name으로 표기 (예: spec.template.spec.containers[nginx].readinessProbe.periodSeconds).
    핸들러(httpGet/tcpSocket/exec/sleep)는 한 덩어리로 취급한다."""
    out: list[str] = []
    _walk(patch, "", out)
    return out


_ATOMIC_KEYS = {"httpGet", "tcpSocket", "exec", "sleep"}


def _walk(node, prefix: str, out: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            if key in _ATOMIC_KEYS or not isinstance(value, (dict, list)):
                out.append(path)
            else:
                _walk(value, path, out)
    elif isinstance(node, list):
        for item in node:
            if isinstance(item, dict) and "name" in item:
                sub = {k: v for k, v in item.items() if k != "name"}
                _walk(sub, f"{prefix}[{item['name']}]", out)
            else:
                out.append(prefix)


def project(deployment: dict, patch: dict) -> dict:
    """patch와 같은 모양으로 deployment(dict)에서 현재 값을 뽑는다 — 없는 경로는 None.
    strategic merge patch에서 null은 필드 삭제이므로, 이 결과가 곧 롤백 패치다."""
    return _project_node(deployment or {}, patch)


def _project_node(source, patch):
    if isinstance(patch, dict):
        if not isinstance(source, dict):
            source = {}
        out = {}
        for key, value in patch.items():
            if key in _ATOMIC_KEYS or not isinstance(value, (dict, list)):
                out[key] = copy.deepcopy(source.get(key))
            else:
                out[key] = _project_node(source.get(key), value)
        return out
    if isinstance(patch, list):
        by_name = {c.get("name"): c for c in (source or []) if isinstance(c, dict)} \
            if isinstance(source, list) else {}
        out = []
        for item in patch:
            if isinstance(item, dict) and "name" in item:
                projected = _project_node(by_name.get(item["name"]), {k: v for k, v in item.items() if k != "name"})
                out.append({"name": item["name"], **projected})
            else:
                out.append(copy.deepcopy(item))
        return out
    return copy.deepcopy(source)


def value_at(node, path: str):
    """flatten_patch 경로 1개의 값을 읽는다 (프로젝션·패치 양쪽에 사용)."""
    cur = node
    for token in re.findall(r"[^.\[\]]+|\[[^\]]+\]", path):
        if token.startswith("["):
            name = token[1:-1]
            cur = next((c for c in (cur or []) if isinstance(c, dict) and c.get("name") == name), None)
        else:
            cur = (cur or {}).get(token) if isinstance(cur, dict) else None
        if cur is None:
            return None
    return cur


def change_rows(change: dict, only_changed: bool = False) -> list[dict]:
    """개선 변경 기록 → [{path, before, after}] — env·patch 공통 표시 형태.
    only_changed=True면 전후가 같은 행(패치가 기존 값을 그대로 다시 쓴 경로)은 뺀다 — 보고서용.
    전부 같으면(no-op) 원래 행을 그대로 돌려줘 '무엇을 시도했는지'는 남긴다."""
    if change.get("type") == "deployment_env" or change.get("key"):  # 구형 기록(type 없음)도 env
        rows = [{"path": f"env.{change.get('key', '')}", "before": change.get("before"),
                 "after": change.get("after")}]
    else:
        patch = change.get("patch") or change.get("after") or {}
        before, after = change.get("before") or {}, change.get("after") or patch
        rows = [{"path": path, "before": value_at(before, path), "after": value_at(after, path)}
                for path in flatten_patch(patch)]
    if only_changed:
        changed = [r for r in rows if r["before"] != r["after"]]
        return changed or rows
    return rows


def manifest_workloads(manifest_yaml: str) -> dict[str, dict]:
    """manifest의 Deployment {name: doc} — 검증(존재 확인)·미리보기(전 값)에 사용."""
    import yaml

    try:
        docs = list(yaml.safe_load_all(manifest_yaml or ""))
    except yaml.YAMLError:
        return {}
    return {
        (d.get("metadata") or {}).get("name"): d
        for d in docs
        if isinstance(d, dict) and d.get("kind") == "Deployment" and (d.get("metadata") or {}).get("name")
    }


def container_names(deployment: dict) -> list[str]:
    containers = ((((deployment or {}).get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers") or []
    return [c.get("name") for c in containers if isinstance(c, dict) and c.get("name")]


def preview_rows(spec: dict, manifest_yaml: str) -> list[dict]:
    """제안 카드용 '전(manifest 원문) → 후(제안)' 행 — 적용 전이라 manifest에서 전 값을 읽는다."""
    doc = manifest_workloads(manifest_yaml).get(spec.get("deployment")) or {}
    if spec.get("type") == "deployment_env":
        before = None
        containers = ((((doc.get("spec") or {}).get("template") or {}).get("spec") or {}).get("containers") or [])
        for c in containers:
            if isinstance(c, dict) and c.get("name") == spec.get("container"):
                before = next((e.get("value") for e in c.get("env") or []
                               if isinstance(e, dict) and e.get("name") == spec.get("key")), None)
        return [{"path": f"env.{spec.get('key', '')}", "before": before, "after": spec.get("value")}]
    patch = spec.get("patch") or {}
    return change_rows({"type": "manifest_patch", "patch": patch, "before": project(doc, patch), "after": patch})
