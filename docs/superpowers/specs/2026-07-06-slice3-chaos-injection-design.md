# Slice 3 — 카오스 주입 설계 (2026-07-06)

## 목표

"새 실험" 폼에서 등록된 앱에 Chaos Mesh 장애를 주입하고, 주입~회복 생명주기를
대시보드에서 추적한다. 메트릭 수집·R지수 계산은 Slice 4·5 — **이 슬라이스에서
실험 = "주입 → duration 경과 → 회복 → 정리"까지다.**

## 확정 결정

| 결정 | 내용 |
|---|---|
| 생명주기 | **자동 완료 + 정리** — 주입 성공 → `running`, duration 경과·회복 확인 → CRD 삭제 + `completed`. 백그라운드 watcher가 처리 (빌드 watch와 동일 패턴). 클러스터에 쓰레기 안 남김 |
| 파라미터 | **최소셋** — Network=delay(지연 ms 10–10,000) · Pod=pod-kill(원샷, duration 없음) · Stress=CPU(load 1–100%) + 공통 duration 30–1,800초 |
| 동시 실험 | **앱당 1개** — 같은 앱에 `pending/running` 실험 있으면 409. 다른 앱끼리는 병렬 허용 |
| 접근 방식 | **빌드 파이프라인 패턴 미러링** — POST → DB row → inject → 백그라운드 폴링 watcher → SSE는 DB 폴링 (`builds/stream` 미러). worker 없는 SSE 스택 유지 |

기각한 대안: kubernetes watch API 스트림(복잡도 대비 이득 없음, 기존 패턴과 이질적),
Chaos Mesh Workflow CRD(오버킬).

## 1. 파라미터 스키마·검증

`app/services/chaos_specs.py` (순수 자료구조 + 순수 함수, IO 없음):

```python
CHAOS_SPECS = {
    "NetworkChaos": {
        "action": "delay",
        "fields": {
            "latency_ms": {"min": 10, "max": 10_000, "label": "지연 (ms)"},
            "duration_s": {"min": 30, "max": 1_800, "label": "지속 (초)"},
        },
    },
    "PodChaos": {
        "action": "pod-kill",
        "fields": {},           # 원샷 — duration 없음
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
    """폼 입력 → (정규화된 params, 오류 메시지 리스트). 오류 있으면 params 무효."""
```

- 검증: 타입 존재, 필드 정수 변환, min/max 범위. 서버 검증이 진실원천,
  클라이언트 min/max 속성은 UX 보조.
- 정규화된 `params` 예: `{"action": "delay", "latency_ms": 200, "duration_s": 300}`
  → `Experiment.params` JSON에 그대로 저장 (대시보드 카드가 라벨 매핑 표시).

## 2. CRD 렌더링 (순수 함수)

`app/services/real/chaos.py` 상단에 `build_workflow_manifest` 스타일로:

```python
def render_chaos_manifest(chaos_type, name, namespace, app_name, params) -> dict
```

- `metadata.generateName: exp-{app_name}-` / `metadata.namespace: <sut_namespace>`
- `spec.selector: {namespaces: [sut], labelSelectors: {app: app_name}}`
  (generic-app 차트가 붙이는 `app: <이름>` 라벨), `spec.mode: all`
- 타입별 spec:
  - NetworkChaos: `action: delay`, `delay.latency: "{latency_ms}ms"`, `duration: "{duration_s}s"`
  - PodChaos: `action: pod-kill` (duration 없음)
  - StressChaos: `stressors.cpu: {workers: 1, load: cpu_load}`, `duration: "{duration_s}s"`

## 3. 인터페이스 확장 (`services/interfaces.py`)

```python
class ChaosService(Protocol):
    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict) -> str:
        """Chaos CRD 생성. CRD 이름 반환."""
    def phase(self, chaos_type: str, crd_name: str) -> str:
        """injecting | running | recovered (CRD conditions 기반)."""
    def delete(self, chaos_type: str, crd_name: str) -> None: ...
```

- 기존 시그니처에서 `app_name`(selector용)과 `chaos_type`(plural 결정용) 추가.
  사용처는 Stub뿐이라 안전한 변경.
- `RealChaos`: `CustomObjectsApi`로 `chaos-mesh.org/v1alpha1`
  `networkchaoses|podchaoses|stresschaoses` CRUD (sut 네임스페이스).
  phase는 CRD `status.conditions`의 `AllInjected`/`AllRecovered`로 판정.
- `StubChaos`: inject → 고정 이름 반환, phase → "recovered", delete → no-op.

## 4. 라우터 + 워처 (`routers/experiments.py` 신설)

- `POST /experiments` — Form(app_id, chaos_type, 필드들):
  1. 앱 존재 확인(404), `validate_params`(422 + 오류 메시지 partial),
  2. 해당 앱에 `pending/running` 실험 있으면 409,
  3. Experiment row `pending` → `chaos.inject()` → `running` + `crd_name` 저장
     (실패 시 `inject-failed` + `logger.exception`),
  4. `background.add_task(_watch_experiment, exp_id)` → experiments 목록 렌더 반환.
- `_watch_experiment` (5초 폴링, 상한 ~35분):
  - pod-kill: 주입 확인 후 30초 유예 → 삭제 + `completed`
  - delay/cpu: duration 경과 + `recovered` 확인 → 삭제 + `completed`
  - 폴링 중 오류/상한 초과 → CRD 삭제 시도 + `failed`
- `POST /experiments/{id}/stop` — running만 허용(아니면 409): CRD 삭제 → `stopped`.
- `GET /experiments/{id}/stream` — `builds/stream` 미러: DB status 폴링,
  running 벗어나면 `completed` 이벤트 후 종료.
- `Experiment` 모델에 `crd_name` 컬럼 1개 추가 (String, default "").

## 5. UI (experiments.html 실배선)

- "새 실험" 다이얼로그: 대상 앱 = 등록 앱 목록 서버 렌더(하드코딩 제거),
  타입 select 변경 시 해당 파라미터 필드만 표시(기존 탭/wiz 스타일 JS 위임),
  입력에 min/max 속성. 검증 실패 시 서버 오류 메시지 표시.
- 실험 테이블: 실데이터(이미 DB 기반), running 행에 "중지" 버튼,
  상태 배지 pending/running/completed/stopped/failed/inject-failed.
- `app.js`: `watchBuilds` 패턴 미러 `watchExperiments()` — running 행만
  EventSource 구독, 종료 시 `htmx.ajax`로 목록 새로고침.
- 필터의 하드코딩 앱 목록 → 실데이터. 대시보드 최근 실험 카드는 자동 반영.

## 6. 테스트

- `validate_params` 경계값(min/max/비정수/미지원 타입) 단위.
- `render_chaos_manifest` 3타입 렌더 순수함수 단위.
- POST: 성공(stub) / 검증 실패 422 / 동일 앱 중복 409 / 없는 앱 404.
- stop: running→stopped / running 아니면 409.
- `_watch_experiment`: recovered→completed, 오류→failed (SessionLocal·make_chaos monkeypatch — `_bootstrap` 테스트 스타일).
- SSE: 즉시-completed 전이 (`builds/stream` 테스트 미러).

## 라이브 선결 (up.sh 검증 시)

- 대시보드 K8s 신원에 sut 네임스페이스 `chaos-mesh.org` CRD **create/get/list/delete** RBAC.
- Chaos Mesh 파드 Running 확인 (`kubectl get pods -n chaos-mesh`) — 6/2 검증 때 직접 확인 기록 없음.
- 주입 대상 파드가 있어야 실험 가능 → comon-be(chaoslab-deploy 브랜치) 또는 demo 앱 사용.

## 범위 제외 (YAGNI)

- 메트릭 수집·R지수 계산 (Slice 4·5), Chaos Mesh Workflow/스케줄, jitter/loss/memory
  등 추가 액션, 실험 복제/재실행, Chaos Mesh 대시보드 연동.
