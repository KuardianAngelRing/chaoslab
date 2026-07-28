# Slice 3 카오스 주입 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "새 실험" 폼에서 등록 앱에 Chaos Mesh 장애(delay/pod-kill/cpu)를 주입하고, 백그라운드 watcher가 회복 확인 후 CRD를 정리·완료 처리하며, SSE로 화면이 실시간 갱신된다.

**Architecture:** 빌드 파이프라인 패턴 미러링 — POST → DB row → `inject()` → 백그라운드 폴링 watcher(5초) → CRD 삭제 + status 갱신, SSE는 DB 폴링(`builds/stream` 미러). 검증·CRD 렌더는 순수 함수로 분리.

**Tech Stack:** FastAPI + SQLAlchemy + Jinja/HTMX, kubernetes-py(CustomObjectsApi, lazy import), sse-starlette. Chaos Mesh 2.8.2 (`chaos-mesh.org/v1alpha1`).

**설계서:** `docs/superpowers/specs/2026-07-06-slice3-chaos-injection-design.md`

## Global Constraints

- 테스트는 항상 Stub 모드 (conftest autouse가 `use_real_services=False` 강제). Real 클래스의 k8s SDK는 lazy import — 테스트에서 SDK 불필요.
- 파라미터 범위: latency_ms 10–10000, cpu_load 1–100, duration_s 30–1800 (설계서 값 그대로).
- 동시 실험: 같은 앱에 status가 `pending`/`running`인 실험 있으면 409.
- 커밋: gitmoji + 파일단위 원자적 (이 플랜 승인 = 태스크별 커밋 승인, push는 별도 요청 시).
- pytest 실행은 `.venv.nosync/bin/python -m pytest` (iCloud 이슈로 `.venv` 심링크 불안정).
- `docs/`·`CLAUDE.md`는 gitignore — 커밋 대상 아님.

---

### Task 1: 파라미터 스키마 + 검증 (`chaos_specs.py`)

**Files:**
- Create: `app/services/chaos_specs.py`
- Test: `tests/test_chaos_specs.py`

**Interfaces:**
- Produces: `CHAOS_SPECS: dict` (템플릿·라우터가 사용), `validate_params(chaos_type: str, form: dict) -> tuple[dict, list[str]]` — 성공 시 `({"action": ..., 필드들}, [])`, 실패 시 `({}, ["오류문구", ...])`.

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_chaos_specs.py
"""CHAOS_SPECS 범위검증 — 순수 함수, IO 없음."""
from app.services.chaos_specs import CHAOS_SPECS, validate_params


def test_network_delay_valid():
    params, errors = validate_params("NetworkChaos", {"latency_ms": "200", "duration_s": "300"})
    assert errors == []
    assert params == {"action": "delay", "latency_ms": 200, "duration_s": 300}


def test_pod_kill_no_fields():
    params, errors = validate_params("PodChaos", {})
    assert errors == []
    assert params == {"action": "pod-kill"}


def test_stress_cpu_valid():
    params, errors = validate_params("StressChaos", {"cpu_load": "80", "duration_s": "60"})
    assert errors == []
    assert params == {"action": "cpu", "cpu_load": 80, "duration_s": 60}


def test_out_of_range_rejected():
    _, errors = validate_params("NetworkChaos", {"latency_ms": "5", "duration_s": "300"})
    assert any("지연" in e for e in errors)          # min 10 미만
    _, errors = validate_params("NetworkChaos", {"latency_ms": "200", "duration_s": "9999"})
    assert any("지속" in e for e in errors)          # max 1800 초과


def test_non_integer_rejected():
    _, errors = validate_params("StressChaos", {"cpu_load": "abc", "duration_s": "60"})
    assert errors


def test_unknown_type_rejected():
    _, errors = validate_params("DiskChaos", {})
    assert errors


def test_specs_have_labels_for_ui():
    for spec in CHAOS_SPECS.values():
        for field in spec["fields"].values():
            assert {"min", "max", "label"} <= set(field)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv.nosync/bin/python -m pytest tests/test_chaos_specs.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.chaos_specs`

- [ ] **Step 3: 구현**

```python
# app/services/chaos_specs.py
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
```

- [ ] **Step 4: 통과 확인**

Run: `.venv.nosync/bin/python -m pytest tests/test_chaos_specs.py -q`
Expected: 7 passed

- [ ] **Step 5: 커밋**

```bash
git add app/services/chaos_specs.py tests/test_chaos_specs.py
git commit -m "✨ 카오스 파라미터 스키마(CHAOS_SPECS) + 범위검증 순수함수"
```

---

### Task 2: CRD 렌더 순수함수 + RealChaos (`real/chaos.py`)

**Files:**
- Create: `app/services/real/chaos.py`
- Test: `tests/test_real_helpers.py` (기존 파일에 추가)

**Interfaces:**
- Consumes: Task 1의 params 형태 (`{"action": "delay", "latency_ms": 200, "duration_s": 300}` 등)
- Produces: `render_chaos_manifest(chaos_type: str, namespace: str, app_name: str, params: dict) -> dict`, `CHAOS_PLURALS: dict[str, str]`, `class RealChaos` — `inject(namespace, app_name, chaos_type, params) -> str` / `phase(chaos_type, crd_name) -> str` / `delete(chaos_type, crd_name) -> None`

- [ ] **Step 1: 실패하는 테스트 작성 (tests/test_real_helpers.py 끝에 추가)**

```python
def test_render_chaos_manifest_network_delay():
    from app.services.real.chaos import render_chaos_manifest

    m = render_chaos_manifest("NetworkChaos", "sut", "demo",
                              {"action": "delay", "latency_ms": 200, "duration_s": 300})
    assert m["kind"] == "NetworkChaos"
    assert m["metadata"]["generateName"] == "exp-demo-"
    assert m["metadata"]["namespace"] == "sut"
    assert m["spec"]["selector"] == {"namespaces": ["sut"], "labelSelectors": {"app": "demo"}}
    assert m["spec"]["mode"] == "all"
    assert m["spec"]["action"] == "delay"
    assert m["spec"]["delay"] == {"latency": "200ms"}
    assert m["spec"]["duration"] == "300s"


def test_render_chaos_manifest_pod_kill_has_no_duration():
    from app.services.real.chaos import render_chaos_manifest

    m = render_chaos_manifest("PodChaos", "sut", "demo", {"action": "pod-kill"})
    assert m["kind"] == "PodChaos"
    assert m["spec"]["action"] == "pod-kill"
    assert "duration" not in m["spec"]


def test_render_chaos_manifest_stress_cpu():
    from app.services.real.chaos import render_chaos_manifest

    m = render_chaos_manifest("StressChaos", "sut", "demo",
                              {"action": "cpu", "cpu_load": 80, "duration_s": 60})
    assert m["kind"] == "StressChaos"
    assert m["spec"]["stressors"] == {"cpu": {"workers": 1, "load": 80}}
    assert m["spec"]["duration"] == "60s"
```

- [ ] **Step 2: 실패 확인**

Run: `.venv.nosync/bin/python -m pytest tests/test_real_helpers.py -q`
Expected: FAIL — `ModuleNotFoundError: app.services.real.chaos`

- [ ] **Step 3: 구현**

```python
# app/services/real/chaos.py
"""RealChaos — Chaos Mesh CRD 주입/조회/삭제 (운영, use_real_services=true).

render_chaos_manifest는 순수 함수(테스트 가능). k8s 호출은 메서드 안에서 lazy import.
"""
from __future__ import annotations

_GROUP = "chaos-mesh.org"
_VERSION = "v1alpha1"

CHAOS_PLURALS = {
    "NetworkChaos": "networkchaos",
    "PodChaos": "podchaos",
    "StressChaos": "stresschaos",
}


def render_chaos_manifest(chaos_type: str, namespace: str, app_name: str, params: dict) -> dict:
    """Chaos Mesh CRD 매니페스트. selector는 generic-app 차트의 `app:` 라벨."""
    spec: dict = {
        "selector": {"namespaces": [namespace], "labelSelectors": {"app": app_name}},
        "mode": "all",
        "action": params["action"],
    }
    if chaos_type == "NetworkChaos":
        spec["delay"] = {"latency": f"{params['latency_ms']}ms"}
    elif chaos_type == "StressChaos":
        del spec["action"]  # StressChaos는 action 대신 stressors
        spec["stressors"] = {"cpu": {"workers": 1, "load": params["cpu_load"]}}
    if "duration_s" in params:
        spec["duration"] = f"{params['duration_s']}s"
    return {
        "apiVersion": f"{_GROUP}/{_VERSION}",
        "kind": chaos_type,
        "metadata": {"generateName": f"exp-{app_name}-", "namespace": namespace},
        "spec": spec,
    }


class RealChaos:
    def __init__(self, settings):
        self.s = settings

    def _api(self):
        from kubernetes import client, config  # lazy

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.CustomObjectsApi()

    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict) -> str:
        manifest = render_chaos_manifest(chaos_type, namespace, app_name, params)
        resp = self._api().create_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=namespace,
            plural=CHAOS_PLURALS[chaos_type], body=manifest,
        )
        return resp["metadata"]["name"]

    def phase(self, chaos_type: str, crd_name: str) -> str:
        """status.conditions 기반: AllRecovered=True → recovered, AllInjected=True → running, 그 외 injecting."""
        obj = self._api().get_namespaced_custom_object(
            group=_GROUP, version=_VERSION, namespace=self.s.sut_namespace,
            plural=CHAOS_PLURALS[chaos_type], name=crd_name,
        )
        conditions = {c.get("type"): c.get("status") for c in (obj.get("status") or {}).get("conditions", [])}
        if conditions.get("AllRecovered") == "True":
            return "recovered"
        if conditions.get("AllInjected") == "True":
            return "running"
        return "injecting"

    def delete(self, chaos_type: str, crd_name: str) -> None:
        from kubernetes.client.rest import ApiException  # lazy

        try:
            self._api().delete_namespaced_custom_object(
                group=_GROUP, version=_VERSION, namespace=self.s.sut_namespace,
                plural=CHAOS_PLURALS[chaos_type], name=crd_name,
            )
        except ApiException as e:
            if e.status != 404:  # 이미 없으면 idempotent 성공
                raise
```

주의: `inject`는 CRD를 **대상 앱과 같은 네임스페이스**(호출자가 넘긴 namespace)에 만들고, `phase`/`delete`는 `settings.sut_namespace`를 쓴다 — 호출자(라우터)는 항상 `settings.sut_namespace`를 넘기므로 동일 값이다.

- [ ] **Step 4: 통과 확인**

Run: `.venv.nosync/bin/python -m pytest tests/test_real_helpers.py -q`
Expected: 전부 passed (기존 + 신규 3)

- [ ] **Step 5: 커밋**

```bash
git add app/services/real/chaos.py tests/test_real_helpers.py
git commit -m "✨ RealChaos: Chaos Mesh CRD 렌더 순수함수 + inject/phase/delete"
```

---

### Task 3: ChaosService Protocol·Stub·deps 갱신

**Files:**
- Modify: `app/services/interfaces.py` (ChaosService)
- Modify: `app/services/stubs.py` (StubChaos)
- Modify: `app/deps.py` (`make_chaos` 신설, `get_chaos` 위임)
- Test: `tests/test_stubs_contract.py` (기존 계약 테스트가 새 시그니처를 커버하는지 확인·보강)

**Interfaces:**
- Produces: `ChaosService.inject(namespace, app_name, chaos_type, params) -> str`, `.phase(chaos_type, crd_name) -> str`, `.delete(chaos_type, crd_name) -> None`, `deps.make_chaos() -> ChaosService`
- Consumes: Task 2의 `RealChaos` (시그니처 동일)

- [ ] **Step 1: 실패하는 테스트 작성 (tests/test_stubs_contract.py에 추가)**

```python
def test_stub_chaos_matches_new_protocol():
    from app.services.stubs import StubChaos

    stub = StubChaos()
    name = stub.inject("sut", "demo", "NetworkChaos", {"action": "delay"})
    assert isinstance(name, str) and name
    assert stub.phase("NetworkChaos", name) == "recovered"
    assert stub.delete("NetworkChaos", name) is None


def test_make_chaos_returns_stub_in_stub_mode():
    from app.deps import make_chaos
    from app.services.stubs import StubChaos

    assert isinstance(make_chaos(), StubChaos)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv.nosync/bin/python -m pytest tests/test_stubs_contract.py -q`
Expected: FAIL — inject() 인자 개수 불일치 / make_chaos 없음

- [ ] **Step 3: 구현**

`app/services/interfaces.py`의 ChaosService를 교체:

```python
class ChaosService(Protocol):
    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict) -> str:
        """Chaos CRD 생성 (selector = app 라벨). CRD 이름 반환."""
        ...

    def phase(self, chaos_type: str, crd_name: str) -> str:
        """injecting | running | recovered (CRD conditions 기반)."""
        ...

    def delete(self, chaos_type: str, crd_name: str) -> None:
        ...
```

`app/services/stubs.py`의 StubChaos를 교체:

```python
class StubChaos:
    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict) -> str:
        return f"exp-{app_name}-stub"

    def phase(self, chaos_type: str, crd_name: str) -> str:
        return "recovered"

    def delete(self, chaos_type: str, crd_name: str) -> None:
        return None
```

`app/deps.py` — `make_k8s` 아래에 추가하고, 기존 `get_chaos`를 위임으로 교체:

```python
def make_chaos() -> interfaces.ChaosService:
    if settings.use_real_services:
        from app.services.real.chaos import RealChaos  # lazy: k8s SDK
        return RealChaos(settings)
    return stubs.StubChaos()
```

```python
def get_chaos() -> interfaces.ChaosService:
    return make_chaos()
```

- [ ] **Step 4: 전체 테스트 통과 확인**

Run: `.venv.nosync/bin/python -m pytest -q`
Expected: 전부 passed (기존 StubChaos 사용처는 없음 — seed/라우터 미사용 확인됨)

- [ ] **Step 5: 커밋**

```bash
git add app/services/interfaces.py app/services/stubs.py app/deps.py tests/test_stubs_contract.py
git commit -m "♻️ ChaosService 계약 확장(inject에 app_name·phase 신설) + make_chaos 팩토리"
```

---

### Task 4: Experiment 모델에 crd_name 컬럼

**Files:**
- Modify: `app/db/models.py` (Experiment)
- Test: `tests/test_models.py` (기존 파일에 추가)

**Interfaces:**
- Produces: `Experiment.crd_name: str` (default "") — Task 5 라우터·워처가 사용

- [ ] **Step 1: 실패하는 테스트 작성 (tests/test_models.py에 추가)**

```python
def test_experiment_has_crd_name_default_empty(db_session):
    from app.db.repositories import AppRepository, ExperimentRepository

    app = AppRepository(db_session).create(name="x", repo_url="", framework="docker")
    exp = ExperimentRepository(db_session).create(app_id=app.id, chaos_type="PodChaos")
    assert exp.crd_name == ""
```

(주: `db_session` 픽스처 이름·AppRepository.create 시그니처는 기존 tests/test_models.py 상단의 다른 테스트와 동일하게 맞춘다 — 파일 열어 기존 픽스처 사용 방식 그대로 따를 것.)

- [ ] **Step 2: 실패 확인**

Run: `.venv.nosync/bin/python -m pytest tests/test_models.py -q`
Expected: FAIL — `crd_name` AttributeError

- [ ] **Step 3: 구현 — models.py Experiment에 한 줄 추가 (status 줄 아래)**

```python
    crd_name: Mapped[str] = mapped_column(String(120), default="")
```

(마이그레이션 불필요 — `chaoslab.db`는 런타임 생성·gitignore라 재기동 시 새 스키마로 생성됨.)

- [ ] **Step 4: 통과 확인**

Run: `.venv.nosync/bin/python -m pytest -q`
Expected: 전부 passed

- [ ] **Step 5: 커밋**

```bash
git add app/db/models.py tests/test_models.py
git commit -m "✨ Experiment.crd_name 컬럼 (주입된 Chaos CRD 추적)"
```

---

### Task 5: 실험 라우터 + 워처 + SSE (`routers/experiments.py`)

**Files:**
- Create: `app/routers/experiments.py`
- Modify: `app/main.py` (라우터 등록)
- Test: `tests/test_experiments.py` (신규)

**Interfaces:**
- Consumes: `validate_params`(Task 1), `make_chaos`(Task 3), `Experiment.crd_name`(Task 4)
- Produces: `POST /experiments`(Form: app_id, chaos_type, latency_ms?, duration_s?, cpu_load?), `POST /experiments/{id}/stop`, `GET /experiments/{id}/stream`. 상태값: `pending → running → completed | failed | stopped | inject-failed`

- [ ] **Step 1: 실패하는 테스트 작성**

```python
# tests/test_experiments.py
"""실험 생성/중지/워처/SSE — stub 모드(기본)."""
import json
import logging

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.repositories import AppRepository, ExperimentRepository


def test_create_experiment_success(client):
    resp = client.post("/experiments", data={
        "app_id": "1", "chaos_type": "NetworkChaos",
        "latency_ms": "200", "duration_s": "30",
    })
    assert resp.status_code == 200
    assert "NetworkChaos" in resp.text  # 실험 목록 리렌더


def test_create_experiment_validation_error_422(client):
    resp = client.post("/experiments", data={
        "app_id": "1", "chaos_type": "NetworkChaos",
        "latency_ms": "5", "duration_s": "30",  # latency min 10 미만
    })
    assert resp.status_code == 422


def test_create_experiment_conflict_409_when_app_busy(client):
    # seed의 online-boutique(1)에는 running 실험이 이미 있음
    # → seed running 실험이 없는 앱을 찾아 검증하는 대신, seed 그대로 이용
    resp = client.post("/experiments", data={
        "app_id": "1", "chaos_type": "PodChaos",
    })
    assert resp.status_code == 409


def test_create_experiment_unknown_app_404(client):
    resp = client.post("/experiments", data={"app_id": "99999", "chaos_type": "PodChaos"})
    assert resp.status_code == 404


def test_stop_running_experiment(client):
    # seed 실험 1번이 running
    resp = client.post("/experiments/1/stop")
    assert resp.status_code == 200
    assert "중지됨" in resp.text


def test_stop_non_running_409(client):
    client.post("/experiments/1/stop")            # running → stopped
    assert client.post("/experiments/1/stop").status_code == 409


def _engine_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def test_watch_experiment_completes_and_cleans(monkeypatch):
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(name="demo", repo_url="", framework="docker")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="PodChaos", params={"action": "pod-kill"},
        status="running", crd_name="exp-demo-abc")
    exp_id = exp.id
    s.close()

    deleted = []

    class _SpyChaos:
        def phase(self, chaos_type, crd_name):
            return "recovered"
        def delete(self, chaos_type, crd_name):
            deleted.append((chaos_type, crd_name))

    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda: _SpyChaos())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)

    _watch_experiment(exp_id)

    s = Session()
    exp = ExperimentRepository(s).get(exp_id)
    assert exp.status == "completed"
    assert exp.finished_at is not None
    s.close()
    assert deleted == [("PodChaos", "exp-demo-abc")]


def test_watch_experiment_failure_marks_failed(monkeypatch, caplog):
    from app.routers.experiments import _watch_experiment

    Session = _engine_session()
    s = Session()
    app = AppRepository(s).create(name="demo", repo_url="", framework="docker")
    exp = ExperimentRepository(s).create(
        app_id=app.id, chaos_type="NetworkChaos",
        params={"action": "delay", "latency_ms": 200, "duration_s": 30},
        status="running", crd_name="exp-demo-abc")
    exp_id = exp.id
    s.close()

    class _BoomChaos:
        def phase(self, chaos_type, crd_name):
            raise RuntimeError("boom")
        def delete(self, chaos_type, crd_name):
            return None

    monkeypatch.setattr("app.routers.experiments.SessionLocal", Session)
    monkeypatch.setattr("app.routers.experiments.make_chaos", lambda: _BoomChaos())
    monkeypatch.setattr("app.routers.experiments.time.sleep", lambda n: None)

    with caplog.at_level(logging.ERROR):
        _watch_experiment(exp_id)

    s = Session()
    assert ExperimentRepository(s).get(exp_id).status == "failed"
    s.close()
    assert "experiment watch failed" in caplog.text


def test_experiment_stream_completed_immediately(client, monkeypatch):
    # seed 실험 1을 stopped로 만들고 스트림 접속 → 즉시 completed 이벤트
    client.post("/experiments/1/stop")
    with client.stream("GET", "/experiments/1/stream") as r:
        body = "".join(chunk for chunk in r.iter_text())
    assert "completed" in body
```

(주: `client` 픽스처의 stream 사용법·monkeypatch 대상은 `tests/test_stream.py`·`tests/test_builds.py`의 기존 SSE 테스트를 먼저 열어 같은 방식으로 맞출 것. `/experiments/{id}/stream`의 SessionLocal도 builds와 같이 모듈 전역 import이므로 client 픽스처의 override와 분리된 DB를 본다 — 그래서 위 stream 테스트는 builds 테스트처럼 monkeypatch로 `app.routers.experiments.SessionLocal`을 테스트 세션으로 바꿔야 한다.)

- [ ] **Step 2: 실패 확인**

Run: `.venv.nosync/bin/python -m pytest tests/test_experiments.py -q`
Expected: FAIL — `ModuleNotFoundError: app.routers.experiments`

- [ ] **Step 3: 구현**

```python
# app/routers/experiments.py
"""실험 생성/중지/watch/SSE — 빌드 파이프라인 패턴 미러."""
from __future__ import annotations

import asyncio
import json
import logging
import time
from datetime import datetime, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request
from sqlalchemy.orm import Session
from sse_starlette.sse import EventSourceResponse

from app.config import settings
from app.db.database import SessionLocal, get_session
from app.db.models import Experiment
from app.db.repositories import AppRepository, ExperimentRepository
from app.deps import get_app_count, make_chaos
from app.rendering import render_page
from app.services.chaos_specs import validate_params

router = APIRouter()
logger = logging.getLogger(__name__)

_POLL_S = 5           # watcher 폴링 간격
_RECOVER_CAP = 60     # duration 후 회복 대기 상한 (5s × 60 = 5분)
_PODKILL_GRACE_S = 30  # pod-kill 원샷 유예


def _experiments_response(request: Request, session: Session):
    exps = ExperimentRepository(session).list_all()
    apps = AppRepository(session).list_all()
    return render_page(
        request, "pages/experiments.html",
        {"active_nav": "experiments", "app_count": len(apps),
         "experiments": exps, "apps": apps},
    )


@router.post("/experiments")
def create_experiment(
    request: Request,
    background: BackgroundTasks,
    app_id: int = Form(...),
    chaos_type: str = Form(...),
    latency_ms: str = Form(""),
    duration_s: str = Form(""),
    cpu_load: str = Form(""),
    session: Session = Depends(get_session),
):
    app = AppRepository(session).get(app_id)
    if app is None:
        raise HTTPException(status_code=404, detail="app not found")

    params, errors = validate_params(chaos_type, {
        "latency_ms": latency_ms, "duration_s": duration_s, "cpu_load": cpu_load,
    })
    if errors:
        raise HTTPException(status_code=422, detail=" / ".join(errors))

    busy = [e for e in app.experiments if e.status in ("pending", "running")]
    if busy:
        raise HTTPException(status_code=409, detail="이 앱에 진행 중인 실험이 있어요")

    exp = ExperimentRepository(session).create(
        app_id=app.id, chaos_type=chaos_type, params=params, status="pending")
    try:
        crd = make_chaos().inject(settings.sut_namespace, app.name, chaos_type, params)
        exp.crd_name = crd
        exp.status = "running"
        session.commit()
    except Exception:
        logger.exception("chaos inject failed (app %s, type %s)", app.name, chaos_type)
        exp.status = "inject-failed"
        session.commit()
        return _experiments_response(request, session)

    background.add_task(_watch_experiment, exp.id)
    return _experiments_response(request, session)


def _watch_experiment(exp_id: int) -> None:
    """duration 경과·회복 확인 → CRD 삭제 + completed. 오류/상한 → failed."""
    chaos = make_chaos()
    s = SessionLocal()
    try:
        exp = s.get(Experiment, exp_id)
        if exp is None:
            return
        chaos_type, crd_name = exp.chaos_type, exp.crd_name
        duration = int(exp.params.get("duration_s") or _PODKILL_GRACE_S)

        status = "completed"
        try:
            waited = 0
            while waited < duration:          # 장애 지속 구간
                time.sleep(_POLL_S)
                waited += _POLL_S
            for _ in range(_RECOVER_CAP):     # 회복 대기 (최대 5분)
                if chaos.phase(chaos_type, crd_name) == "recovered":
                    break
                time.sleep(_POLL_S)
            chaos.delete(chaos_type, crd_name)
        except Exception:
            logger.exception("experiment watch failed (exp %s)", exp_id)
            try:
                chaos.delete(chaos_type, crd_name)
            except Exception:
                logger.exception("chaos cleanup failed (exp %s)", exp_id)
            status = "failed"

        exp = s.get(Experiment, exp_id)
        if exp and exp.status == "running":   # stop이 먼저 처리했으면 덮어쓰지 않음
            exp.status = status
            exp.finished_at = datetime.now(timezone.utc)
            s.commit()
    finally:
        s.close()


@router.post("/experiments/{exp_id}/stop")
def stop_experiment(
    exp_id: int,
    request: Request,
    background: BackgroundTasks,
    session: Session = Depends(get_session),
):
    exp = ExperimentRepository(session).get(exp_id)
    if exp is None:
        raise HTTPException(status_code=404, detail="experiment not found")
    if exp.status != "running":
        raise HTTPException(status_code=409, detail="진행 중인 실험이 아니에요")

    exp.status = "stopped"
    exp.finished_at = datetime.now(timezone.utc)
    session.commit()
    background.add_task(_delete_crd_task, exp.chaos_type, exp.crd_name)
    return _experiments_response(request, session)


def _delete_crd_task(chaos_type: str, crd_name: str) -> None:
    try:
        make_chaos().delete(chaos_type, crd_name)
    except Exception:
        logger.exception("chaos delete failed (%s/%s)", chaos_type, crd_name)


@router.get("/experiments/{exp_id}/stream")
async def experiment_stream(exp_id: int, request: Request):
    """Experiment.status DB 폴링 — running을 벗어나면 completed 이벤트 후 종료 (builds/stream 미러)."""
    async def gen():
        last = None
        for _ in range(1260):  # ~42분 (2s 간격) > watcher 상한
            if await request.is_disconnected():
                break
            s = SessionLocal()
            try:
                exp = s.get(Experiment, exp_id)
                status = exp.status if exp else None
            finally:
                s.close()
            if status != last:
                yield {"event": "status", "data": json.dumps({"status": status})}
                last = status
            if status != "running":
                yield {"event": "completed", "data": json.dumps({"status": status})}
                break
            await asyncio.sleep(2)

    return EventSourceResponse(gen())
```

`app/main.py` — import와 include에 experiments 추가:

```python
from app.routers import apps, builds, experiments, pages, stream
```
```python
app.include_router(experiments.router)
```

(주: `pages.py`의 `GET /experiments` 페이지 라우트와 이 라우터의 `POST /experiments`는 메서드가 달라 충돌 없음. `GET /experiments/{id}`(상세, pages.py)와 `GET /experiments/{id}/stream`은 경로가 달라 충돌 없음 — 단 include 순서상 pages가 먼저 등록돼 있어도 FastAPI는 완전 일치 경로를 우선한다.)

- [ ] **Step 4: 통과 확인**

Run: `.venv.nosync/bin/python -m pytest -q`
Expected: 전부 passed

- [ ] **Step 5: 커밋**

```bash
git add app/routers/experiments.py app/main.py tests/test_experiments.py
git commit -m "✨ 실험 라우터: 생성(검증·409)·중지·watch 워처·상태 SSE"
```

---

### Task 6: UI 실배선 (experiments.html + pages.py + app.js)

**Files:**
- Modify: `app/templates/pages/experiments.html` (다이얼로그·테이블·필터 전면 교체)
- Modify: `app/routers/pages.py` (`experiments_page` ctx에 `apps` 추가)
- Modify: `app/static/js/app.js` (`watchExperiments`, 타입 선택 토글)
- Test: `tests/test_experiments.py` (페이지 렌더 검증 추가)

**Interfaces:**
- Consumes: Task 5의 엔드포인트, Task 1의 `CHAOS_SPECS` 범위값(min/max 속성은 수동 기입 — 템플릿에서 스키마 import 없이 값 복사, 진실원천은 서버 검증)

- [ ] **Step 1: 실패하는 테스트 작성 (tests/test_experiments.py에 추가)**

```python
def test_experiments_page_shows_real_apps_and_no_mock(client):
    resp = client.get("/experiments")
    assert resp.status_code == 200
    assert "online-boutique" in resp.text      # 실제 등록 앱이 select에
    assert "spring-boot-demo" not in resp.text  # 하드코딩 mock 제거
    assert "총 12건" not in resp.text           # 가짜 카운트 제거
    assert 'name="chaos_type"' in resp.text
    assert "실험 중지" in resp.text              # running 행 중지 버튼 (seed 1건 running)
```

- [ ] **Step 2: 실패 확인**

Run: `.venv.nosync/bin/python -m pytest tests/test_experiments.py -q`
Expected: 마지막 테스트 FAIL (mock 문구 잔존)

- [ ] **Step 3: pages.py 수정 — experiments_page에 apps 전달**

기존:
```python
    exps = ExperimentRepository(session).list_all()
    ctx = {"active_nav": "experiments", "app_count": app_count, "experiments": exps}
```
교체:
```python
    exps = ExperimentRepository(session).list_all()
    apps = AppRepository(session).list_all()
    ctx = {"active_nav": "experiments", "app_count": app_count,
           "experiments": exps, "apps": apps}
```
(실제 기존 코드 형태는 파일을 열어 확인하고 동일 위치에 `apps`만 추가한다.)

- [ ] **Step 4: experiments.html 수정**

4a. **필터** — 앱 select의 하드코딩 option들을 다음으로 교체, 우측 "총 12건"은 실카운트로:

```html
      <select class="tds-input text-sm h-10 w-40">
        <option>모든 앱</option>
        {% for a in apps %}<option>{{ a.name }}</option>{% endfor %}
      </select>
```
```html
    <span class="text-xs" style="color: var(--muted-foreground);">총 {{ experiments|length }}건</span>
```

4b. **테이블** — 시작 시각·기간 실데이터, 상태 배지 매핑 교체, 마지막 셀에 running이면 중지 버튼:

시작 시각 셀(기존 `—`)을:
```html
          <td class="px-6 py-4 text-xs"><span class="font-mono" style="color: var(--muted-foreground);">{{ exp.started_at.strftime("%m/%d %H:%M") }}</span></td>
```
기간 셀(기존 `—`)을:
```html
          <td class="px-6 py-4 mono">{{ exp.params.duration_s ~ "s" if exp.params.duration_s else "—" }}</td>
```
상태 셀 배지 블록 전체를:
```html
          <td class="px-6 py-4">
            {% if exp.status == "running" %}
            <span class="tds-badge badge-warning"><span class="w-1.5 h-1.5 rounded-full pulse-dot" style="background: var(--warning);"></span>주입 중</span>
            {% elif exp.status == "pending" %}
            <span class="tds-badge badge-muted">대기중</span>
            {% elif exp.status == "completed" %}
            <span class="tds-badge badge-success">완료</span>
            {% elif exp.status == "stopped" %}
            <span class="tds-badge badge-muted">중지됨</span>
            {% elif exp.status in ("failed", "inject-failed") %}
            <span class="tds-badge badge-danger">실패</span>
            {% else %}
            <span class="tds-badge badge-info">{{ exp.status }}</span>
            {% endif %}
          </td>
```
마지막 셀(chevron)을:
```html
          <td class="px-6 py-4">
            {% if exp.status == "running" %}
            <button class="tds-btn-muted text-xs h-8 px-3" title="실험 중지"
                    data-running-exp="{{ exp.id }}"
                    onclick="event.stopPropagation()"
                    hx-post="/experiments/{{ exp.id }}/stop" hx-target="#main-content" hx-swap="innerHTML">
              <iconify-icon icon="solar:stop-circle-bold" width="14"></iconify-icon>
              실험 중지
            </button>
            {% else %}
            <iconify-icon icon="lucide:chevron-right" width="18" style="color: var(--muted-foreground);"></iconify-icon>
            {% endif %}
          </td>
```
페이지 하단의 가짜 페이지네이션 블록(`7건 표시 · 전체 12건` ~ 이전/1/2/다음 버튼 div)은 **통째로 삭제**.

4c. **다이얼로그** — `dialog-newExperiment` 내부를 실제 form으로 전면 교체:

```html
<div class="dialog-backdrop" id="dialog-newExperiment">
  <div class="dialog-card">
    <div class="px-6 pt-6 pb-4 flex items-center justify-between">
      <div class="flex items-center gap-2">
        <span class="tossface">🧪</span>
        <h2 class="font-extrabold text-xl">새 실험 시작</h2>
      </div>
      <button class="p-1 rounded-lg hover:bg-muted" onclick="closeDialog('newExperiment')">
        <iconify-icon icon="lucide:x" width="20"></iconify-icon>
      </button>
    </div>
    <form hx-post="/experiments" hx-target="#main-content" hx-swap="innerHTML" class="flex-1 min-h-0 flex flex-col">
    <div class="flex-1 overflow-auto px-6 pb-6 space-y-4">
      <div>
        <label class="text-sm font-bold mb-2 block">대상 앱</label>
        <select name="app_id" class="tds-input" required>
          {% for a in apps %}<option value="{{ a.id }}">{{ a.name }}</option>{% endfor %}
        </select>
      </div>
      <div>
        <label class="text-sm font-bold mb-2 block">카오스 종류</label>
        <div class="grid grid-cols-3 gap-2">
          <label class="tds-card p-3 cursor-pointer text-center hover-lift chaos-type-card">
            <input type="radio" name="chaos_type" value="NetworkChaos" class="sr-only" checked />
            <iconify-icon icon="solar:wifi-router-minimalistic-bold" width="28" class="mx-auto mb-1"></iconify-icon>
            <div class="text-xs font-bold">NetworkChaos</div>
            <div class="text-[10px]" style="color: var(--muted-foreground);">지연 주입</div>
          </label>
          <label class="tds-card p-3 cursor-pointer text-center hover-lift chaos-type-card">
            <input type="radio" name="chaos_type" value="PodChaos" class="sr-only" />
            <iconify-icon icon="solar:box-bold" width="28" class="mx-auto mb-1"></iconify-icon>
            <div class="text-xs font-bold">PodChaos</div>
            <div class="text-[10px]" style="color: var(--muted-foreground);">파드 강제종료</div>
          </label>
          <label class="tds-card p-3 cursor-pointer text-center hover-lift chaos-type-card">
            <input type="radio" name="chaos_type" value="StressChaos" class="sr-only" />
            <iconify-icon icon="solar:cpu-bold" width="28" class="mx-auto mb-1"></iconify-icon>
            <div class="text-xs font-bold">StressChaos</div>
            <div class="text-[10px]" style="color: var(--muted-foreground);">CPU 부하</div>
          </label>
        </div>
      </div>
      <div class="grid grid-cols-2 gap-3" data-chaos-fields="NetworkChaos">
        <div><label class="text-sm font-bold mb-2 block">지연 (ms)</label>
          <input name="latency_ms" type="number" min="10" max="10000" value="200" class="tds-input mono" /></div>
        <div><label class="text-sm font-bold mb-2 block">지속 (초)</label>
          <input name="duration_s" type="number" min="30" max="1800" value="300" class="tds-input mono" /></div>
      </div>
      <div class="hidden p-3 rounded-2xl text-sm" style="background: var(--muted); color: var(--muted-foreground);" data-chaos-fields="PodChaos">
        파드를 즉시 1회 종료해요. 복구 속도(재기동)를 관찰하는 실험이라 추가 설정이 없어요
      </div>
      <div class="hidden grid grid-cols-2 gap-3" data-chaos-fields="StressChaos">
        <div><label class="text-sm font-bold mb-2 block">CPU 부하 (%)</label>
          <input name="cpu_load" type="number" min="1" max="100" value="80" class="tds-input mono" /></div>
        <div><label class="text-sm font-bold mb-2 block">지속 (초)</label>
          <input name="duration_s" type="number" min="30" max="1800" value="300" class="tds-input mono" disabled /></div>
      </div>
      <div class="p-3 rounded-2xl flex items-start gap-2" style="background: var(--primary-soft);">
        <span class="tossface">🤖</span>
        <div class="text-xs" style="color: var(--primary-soft-foreground);">
          <span class="font-bold">AI Agent 자동 개선</span>은 Phase 3에서 연결돼요 — 지금은 주입·회복까지만 수행해요
        </div>
      </div>
    </div>
    <div class="px-6 py-4 flex gap-2 justify-end border-t" style="border-color: var(--border);">
      <button type="button" class="tds-btn-muted text-sm" onclick="closeDialog('newExperiment')">닫기</button>
      <button type="submit" class="tds-btn-primary text-sm">
        <iconify-icon icon="solar:bug-bold" width="14"></iconify-icon>
        실험 시작할게요
      </button>
    </div>
    </form>
  </div>
</div>
```

(주: StressChaos 패널의 duration 입력은 `disabled`로 두고 NetworkChaos 패널 것과 이름이 겹치므로, 아래 JS 토글에서 **보이는 패널의 input만 enable**한다 — disabled input은 폼 제출에서 제외되는 표준 동작을 이용해 이름 충돌을 피한다.)

- [ ] **Step 5: app.js에 타입 토글 + 실험 SSE watch 추가 (watchBuilds 아래)**

```javascript
// ── 새 실험 다이얼로그: 카오스 타입 선택 → 해당 파라미터 패널만 표시 ──
function chaosTypeSync(root) {
  const checked = root.querySelector('input[name="chaos_type"]:checked');
  if (!checked) return;
  root.querySelectorAll('.chaos-type-card').forEach((card) => {
    const on = card.querySelector('input').checked;
    card.style.borderColor = on ? 'var(--primary)' : '';
    card.style.background = on ? 'var(--primary-soft)' : '';
  });
  root.querySelectorAll('[data-chaos-fields]').forEach((panel) => {
    const on = panel.dataset.chaosFields === checked.value;
    panel.classList.toggle('hidden', !on);
    panel.querySelectorAll('input').forEach((i) => { i.disabled = !on; });
  });
}
document.addEventListener('change', (e) => {
  if (e.target.name === 'chaos_type') chaosTypeSync(e.target.closest('form'));
});
document.body.addEventListener('htmx:afterSwap', () => {
  document.querySelectorAll('#dialog-newExperiment form').forEach(chaosTypeSync);
});
document.addEventListener('DOMContentLoaded', () => {
  document.querySelectorAll('#dialog-newExperiment form').forEach(chaosTypeSync);
});

// ── 실험 상태 watch (running 행만 EventSource, 종료 시 목록 새로고침) ──
const _expStreams = new Set();
function watchExperiments() {
  document.querySelectorAll('[data-running-exp]').forEach((el) => {
    const id = el.dataset.runningExp;
    if (_expStreams.has(id)) return;
    _expStreams.add(id);
    const es = new EventSource(`/experiments/${id}/stream`);
    es.addEventListener('completed', () => {
      es.close(); _expStreams.delete(id);
      if (window.htmx) htmx.ajax('GET', '/experiments', { target: '#main-content', swap: 'innerHTML' });
    });
    es.onerror = () => { es.close(); _expStreams.delete(id); };
  });
}
document.addEventListener('DOMContentLoaded', watchExperiments);
document.body.addEventListener('htmx:afterSwap', watchExperiments);
```

- [ ] **Step 6: 전체 테스트 통과 확인**

Run: `.venv.nosync/bin/python -m pytest -q`
Expected: 전부 passed

- [ ] **Step 7: 수동 확인 (stub 모드)**

```bash
.venv.nosync/bin/uvicorn app.main:app --reload
```
브라우저 `localhost:8000/experiments`: ① 다이얼로그에서 타입 전환 시 패널 전환, ② PodChaos 제출 → 테이블에 running 행 + "실험 중지" 버튼, ③ 30초 후(stub도 watcher가 유예 후 완료) 자동으로 완료 배지 전환(SSE), ④ 중지 버튼 동작.

- [ ] **Step 8: 커밋**

```bash
git add app/templates/pages/experiments.html app/routers/pages.py app/static/js/app.js tests/test_experiments.py
git commit -m "✨ 카오스 테스트 UI 실배선: 실험 폼(타입별 패널)·상태배지·중지·SSE 갱신"
```

---

### Task 7: 문서 갱신 (커밋 없음 — gitignore)

**Files:**
- Modify: `CLAUDE.md` (Slice 3 항목을 ✅로, 라이브 선결 추가)

- [ ] **Step 1: CLAUDE.md의 Slice 3 블록을 완료 표기로 교체**

```markdown
- [x] **Slice 3 — 카오스 (B)** ✅ **구현 완료 (2026-07-07)** · `RealChaos`
  - [x] "새 실험" 폼 POST → Chaos Mesh CRD (Network delay/Pod kill/Stress cpu) + `chaos_specs.validate_params` 범위검증 + 앱당 1개(409)
  - [x] 주입 watch(`_watch_experiment`: duration→회복확인→CRD 삭제→completed)→SSE(`/experiments/{id}/stream`) · 중지(`/experiments/{id}/stop`)
  - 설계·계획: `docs/superpowers/specs/2026-07-06-slice3-chaos-injection-design.md` · `plans/2026-07-07-slice3-chaos-injection.md`
  - **라이브 선결(미완, up.sh 검증 시):** ① 대시보드 K8s 신원에 `sut_namespace` `chaos-mesh.org` CRD create/get/delete RBAC ② Chaos Mesh 파드 Running 확인(`kubectl get pods -n chaos-mesh`) ③ 주입 대상 파드 필요(comon-be `chaoslab-deploy` 또는 demo)
```

- [ ] **Step 2: 완료 보고** — 테스트 수·수동 확인 결과를 사용자에게 요약.

---

## Self-Review 결과

- **스펙 커버리지**: 스키마/검증(T1) · CRD 렌더+RealChaos(T2) · 인터페이스/Stub/deps(T3) · crd_name(T4) · 라우터/워처/stop/SSE(T5) · UI/SSE 클라이언트(T6) · 문서(T7) — 설계서 6개 절 전부 대응. 라이브 선결은 코드 밖(Iac-aws)이라 문서화만.
- **플레이스홀더**: 없음 (모든 스텝에 실코드/실명령).
- **타입 일관성**: `inject(namespace, app_name, chaos_type, params)`·`phase(chaos_type, crd_name)`·`delete(chaos_type, crd_name)`가 T2(Real)/T3(Protocol·Stub)/T5(호출부)에서 동일. 상태값 문자열 `pending/running/completed/failed/stopped/inject-failed`가 T5(라우터)와 T6(배지)에서 동일.
