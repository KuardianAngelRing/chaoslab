# EKS 앱 가설 경로 개방 — 가설 수립 → 단독 실험 → R지수 (2026-09-07)

## 목표 / 비범위

EKS 앱에도 「가설 수립 → 후보 선택 → detailing → 단독 실험 → R지수」 경로를 연다.
현재 이 경로는 `POST /hypothesis`의 k3s 게이트(422)로 EKS 앱이 실험을 시작할 방법 자체가 없다.

**비범위 (이번에 안 함):**
- 개선·최종 회귀·보고서의 EKS 지원 — UI에서 명확히 차단·안내만 한다.
  `POST /scenario-runs`(준비 세션 필수)와 preparations의 k3s 게이트(422)는 그대로 둔다.
- TrafficGenerator의 EKS 시작 — 라이브 검증은 Online Boutique(자체 loadgenerator)로 하므로 불필요.
- 메트릭·R지수 수집(`collect_experiment_metrics` + `RealPrometheus` Istio RED) — 이미 EKS에서 동작
  (08/13 라이브 검증). **수정 금지 영역.**

## 현재 구조 (근거)

- `routers/hypothesis.py:126` — `app.env != "k3s"`면 422. 이것만이 유일한 차단 지점
  (위저드는 `AppRepository.list_all()` 전체를 보여주므로 UI 변경 없이 EKS 앱 선택 가능).
- 가설 조립기(`agent/hypothesis_assembler.py`)는 `app.manifest` 원문 기반 — EKS 앱은 manifest가
  빈 문자열(GitOps values.yaml + generic-app 차트 배포)이라 findings·후보 대상이 나올 수 없다.
- 단독 실험의 EKS 분기는 이미 있다(`routers/experiments.py start_experiment` — sut ns 즉시 주입).
  단, `target_selector` 없이 주입하므로 `render_chaos_manifest`의 기본 `{"app": app_name}` 라벨을
  가정한다. Online Boutique 파드에는 `app: online-boutique` 라벨이 없으므로 이대로면
  **0개 파드 선택(Selected=False) → 5분 타임아웃 → 판정 불가** — 09/05 nginx에서 실증된 실패 모드.
- 조립 페이로드는 run 생성 시 `run.input_payload`에 스냅샷되고, 이후 generate/freeform/detailing이
  전부 `HypothesisInputPayload(**run.input_payload)`로 재사용한다 — 조립 지점만 바꾸면 하류는 무수정.
- `hypothesis_validation.validate_candidates`는 `target_workload`가 manifest에 존재하는지
  검사하지 않는다 → LLM이 없는 워크로드를 지목하는 경우가 실재하므로 주입 직전 가드 필요(§4).

## §1 EKS 매니페스트 소스 — `K8sService.dump_workloads`

`services/interfaces.py`의 `K8sService` Protocol에 메서드 1개 추가:

```python
def dump_workloads(self, namespace: str) -> str:
    """지정 ns의 Deployment·Service를 멀티 문서 YAML로 덤프 (노이즈 제거).

    가설 조립기가 EKS 앱의 manifest 자리에 넣는다. 실패 시 예외 — 호출자가 처리."""
```

- **Real** (`real/k8s.py`): `AppsV1Api.list_namespaced_deployment` + `CoreV1Api.list_namespaced_service`
  → `ApiClient().sanitize_for_serialization(obj)`로 정식 K8s JSON(camelCase) 변환 →
  노이즈 제거 후 `yaml.safe_dump_all`.
  - 제거: `status` 전체 · `metadata`의 `managedFields`/`creationTimestamp`/`resourceVersion`/`uid`/
    `generation`/`ownerReferences` · annotation `kubectl.kubernetes.io/last-applied-configuration`.
  - 유지: `spec` 전체(특히 Deployment `spec.selector.matchLabels` — §4의 근거) ·
    `metadata.name`/`labels`/나머지 annotations.
- **Stub** (`stubs.py`): 결정적 샘플 YAML — Deployment 2개 + Service 1개.
  - `frontend`: replicas 1 · probe 없음 · limits 없음 → `analyze_manifest` findings가 나와서
    StubHypothesisAgent 후보 대상이 `frontend`로 결정된다(기존 `_target` 로직 그대로).
  - `cartservice`: replicas 2 · probe 있음 (대비군).
  - matchLabels는 **의도적으로 `app.kubernetes.io/*` 규약을 안 따르는 값**(예: `app: frontend`) —
    "라벨 규약 가정 금지"를 테스트가 강제하도록.

## §2 조립기 — manifest 주입 지점만 개방

`assemble_hypothesis_input(session, app, goal_text, count, manifest_yaml=None)`:

- `manifest_yaml=None`(기본) → 기존 그대로 `app.manifest or ""` 사용. **k3s 경로 무변화.**
- EKS 앱이면 라우터(`create_run`)가 `deps.make_k8s().dump_workloads(settings.sut_namespace)`로
  덤프를 얻어 인자로 넘긴다 — 조립기는 순수 함수 유지, 외부 시스템 접근은 라우터+deps 팩토리
  한 곳 원칙 유지(DIP).
- 덤프가 들어오면 findings(`analyze_manifest`)·과거 실험 요약·allowed_chaos 등 나머지 조립은
  k3s와 완전히 동일 — `manifest_yaml` 자리에 덤프가 실릴 뿐.
- **덤프 ns = `settings.sut_namespace`.** 주입도 `settings.sut_namespace`에 하므로 selector의
  출처와 주입 대상이 같은 ns여야 어긋나지 않는다. (`App.namespace` 컬럼은 기본값 "default"인
  낡은 값이라 쓰지 않는다.)
- 실패 처리(`create_run`):
  - 덤프 예외(클러스터 접근 불가 등) → **502** "클러스터에서 워크로드를 읽지 못했습니다: {원인}".
  - 덤프에 Deployment 0개 → **422** "네임스페이스 {ns}에 Deployment가 없습니다".

## §3 422 게이트 해제 + 범위 밖 UI 차단·안내

- `hypothesis.py:126~129`의 k3s 게이트 제거.
- 워크플로우 셸(`experiment_detail.html`) — 가설 Run의 앱이 EKS면(`hypothesis_run.app.env`):
  - 3단계(verify)에서 개선 패널(`_hypothesis_improve.html`)과 "최종 회귀 시작" 조립 카드를
    렌더하지 않고, 대신 안내 카드 1장: **"EKS 앱은 단독 실험(2단계)까지 지원해요 —
    개선·최종 회귀 검증은 k3s 앱에서 사용할 수 있어요."** (배지 + muted 스타일, 버튼 없음)
  - 2단계(`_hypothesis_execute.html`) 하단의 "최종 회귀로" 버튼은 탭 이동일 뿐이므로 유지 —
    눌러도 3단계 안내 카드에 착지한다. (`data-regression-start`는 비가설 데모 셸 전용이라 무관.)
    4단계는 scenario_run이 없으면 원래 빈 상태라 추가 조치 없음.
- 서버 게이트는 기존 그대로: preparations(k3s 전용 422)·`POST /scenario-runs`(ready 준비 세션
  필수 → EKS는 세션을 만들 수 없어 자연 차단).

## §4 주입 selector 정합 — 덤프 matchLabels, 실패는 fail-fast

- `start_experiment(session, app, chaos_type, params, candidate_id=None, target_selector=None)`
  파라미터 1개 추가. EKS 즉시 주입 분기에서 `target_selector`를 `inject`에 전달.
- `_watch_detailing`(가설 경로)에서 EKS 앱이면:
  `workload_selector(run.input_payload["manifest_yaml"], candidate.target_workload)` —
  즉 **run 생성 시 클러스터에서 읽은 실제 matchLabels**를 쓴다. 라벨 규약 가정 없음.
- **fail-fast**: 위 결과가 `None`(후보 대상이 덤프에 없음 — LLM 오지목·워크로드 재생성 등)이면
  주입하지 않고 `RuntimeError("대상 워크로드 {name}의 selector를 클러스터 덤프에서 찾지 못했습니다…")`
  → 기존 예외 경로대로 후보 `detail_status="failed"` + 사유 표시. `{"app": app_name}` 폴백으로
  0개 파드에 주입하는 침묵 실패(09/05 실증)를 금지한다.
- 스냅샷 신선도: apps/v1 Deployment의 `spec.selector`는 **불변 필드**(API 서버가 변경 거부)라
  run 생성 시점 덤프가 낡을 수 없다. 유일한 잔여 케이스는 Deployment 삭제 후 재생성 —
  이 경우도 위 fail-fast로 안전하게 떨어진다.
- **k3s 경로 회귀 없음**: 폼 직접 경로(`POST /experiments`, candidate 없음)와 k3s 워처의
  기존 selector 계산(`app.manifest` 기반)은 코드 그대로 — EKS+가설 조합에서만 새 인자가 쓰인다.

## §5 테스트 (Stub 기반, 기존 263+ 통과 유지)

1. `test_stubs_contract`: `StubK8s.dump_workloads`가 파싱 가능한 멀티 문서 YAML이고
   Deployment에 `spec.selector.matchLabels`가 있다.
2. `test_hypothesis_assembler`: `manifest_yaml` 인자 주입 시 findings가 덤프 기반으로 나온다 ·
   미지정이면 기존과 동일(k3s 회귀 없음).
3. `test_hypothesis_api` (EKS 흐름 E2E — seed의 eks 앱 사용):
   - `POST /hypothesis` 200 (기존 400 소멸) → 워처 후 후보 생성, 대상=`frontend`(Stub 덤프 findings).
   - 후보 선택 → detailing → 실험 생성(`running`) — 이때 `inject`에 전달된 `target_selector`가
     덤프의 matchLabels와 일치(기록형 스텁/monkeypatch로 캡처).
   - 덤프에 없는 워크로드를 지목한 후보 선택 → `detail_status="failed"` + selector 사유.
   - 셸 렌더: EKS run의 3단계에 안내 카드 · 회귀 시작 버튼 disabled.
4. `create_run` 실패 처리: 덤프 예외 → 502 · Deployment 0개 → 422.
5. RealK8s 노이즈 제거는 순수 함수로 분리(`_strip_noise` 등)해 k8s SDK 없이 단위 테스트
   (`test_real_helpers` 패턴).

## §4b R지수·실시간 차트 관측 워크로드 (라이브에서 발견 — 09/07 추가 합의)

라이브 검증에서 R지수가 None으로 나왔다. 근본 원인: `metrics_collector`·실시간 스트림이
Istio를 `app.name`으로 조회(`destination_workload="online-boutique"`)하는데, 다중 서비스
SUT에는 그런 워크로드가 없다(실제 장애 대상은 후보의 `adservice`). 단일 서비스였던 8/13
검증에서는 `app.name`==워크로드였기에 우연히 맞았을 뿐 — 가설 경로가 이 동일성을 깬다.

- 관측 대상 워크로드를 한 곳에서 정하는 순수 헬퍼 `observed_workload_name(session, exp)`:
  후보가 있으면 `candidate.target_workload`, 없으면(폼 직접 경로) `app.name`.
- `collect_experiment_metrics`(R지수 집계)와 `experiment_metrics_stream`(2단계 실시간 차트)이
  이 헬퍼를 쓴다.
- **회귀 없음**: k3s의 `LocalPrometheus`는 `app_name`을 무시하고 ns 전체를 조회하므로 무영향.
  후보 없는 EKS 폼 경로는 `app.name` 유지. "수정 금지" 메트릭 영역이지만 목표의 "→ R지수"
  라인이 다중 서비스 SUT에서 실제로 닫히지 않아, 사용자 합의 후 최소 diff로 반영.

## §6 결정 필요 (합의 요청)

1. **`POST /hypothesis/{id}/improvements` EKS 서버 게이트**: 지시는 "셸 버튼 비활성 + 안내"지만,
   이 엔드포인트는 빈 `app.manifest`로 개선 입력을 조립하므로 curl로 치면 무의미한 동작을 한다.
   **422 한 줄 추가를 권장** — UI-only 지시의 범위를 넘으므로 확인 필요.
2. Stub 덤프의 워크로드 구성(frontend/cartservice — Online Boutique 축소판)이 적절한지.

## §7 라이브 검증 선결 체크리스트 (사용자가 up.sh로 직접)

- **RBAC (신규 · 미검증)**: 대시보드 K8s 신원에 sut ns의 `apps/deployments` **list/get** ·
  core `services` **list/get** 추가 (덤프용). ⚠️ 09/07 라이브는 terraform-admin kubeconfig로
  검증해 이 최소권한 자체는 아직 확인 안 됨 — 대시보드 ServiceAccount로 재검증 필요.
- **RBAC (기존 확인)**: sut ns `chaos-mesh.org` CRD create/get/delete.
- Chaos Mesh 파드 Running(`kubectl get pods -n chaos-mesh`) + 주입 대상 파드 존재.
- **DB: 컬럼 변경 없음 — 구 DB 삭제 불필요** (이번 작업은 모델 무수정).
- 부띠끄 검증 시 `.env` `SUT_NAMESPACE=online-boutique` 임시 전환(끝나면 `sut` 복귀 —
  CLAUDE.md 기존 주의사항). 부띠끄를 대시보드에 EKS 앱으로 등록(또는 seed 행 사용)한 상태여야
  가설 위저드에서 선택 가능.
- 관측 트래픽: 부띠끄 자체 loadgenerator 사용 — 대시보드는 EKS에서 트래픽을 만들지 않는다.

## 변경 파일 (예상)

| 파일 | 변경 |
|---|---|
| `services/interfaces.py` | `K8sService.dump_workloads` 추가 |
| `services/stubs.py` | `StubK8s.dump_workloads` 결정적 샘플 |
| `services/real/k8s.py` | `RealK8s.dump_workloads` + 노이즈 제거 순수 함수 |
| `services/agent/hypothesis_assembler.py` | `manifest_yaml` 선택 인자 |
| `routers/hypothesis.py` | k3s 게이트 제거 · EKS 덤프 조립 · (§6-1 합의 시) improvements 게이트 · detailing EKS selector |
| `routers/experiments.py` | `start_experiment`에 `target_selector` 인자 |
| `templates/pages/experiment_detail.html` · `partials/_hypothesis_improve.html` | EKS 안내 카드·버튼 차단 |
| `tests/*` | §5 신규 + 기존 통과 유지 |
