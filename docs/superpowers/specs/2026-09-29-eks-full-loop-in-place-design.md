# EKS 전체 루프 — 개선안 → in-place 최종 회귀 → 보고서 (2026-09-29)

## 목표 / 비범위

09/07 설계는 EKS 앱을 「가설 수립 → 단독 실험 → R지수」(2단계)까지만 열고 3·4단계(개선안·최종 회귀·보고서)는
k3s 전용으로 남겼다. 졸업과제 시연에서 EKS(Online Boutique)로도 루프 전체가 닫혀야 하므로 3·4단계를 EKS에 연다.

**비범위**
- Istio timeout/retry/circuitBreaker 개선 타입(`istio_patch`) — 화이트리스트는 기존 2종(`manifest_patch`·`deployment_env`) 그대로.
- EKS 앱의 격리 복제 배포(전용 ns에 덤프 재배포) — 부띠끄 12개 서비스·사이드카·부하기를 덤프만으로 재현하기 어렵다.
- 등록형(generic-app) EKS 앱의 라이브 검증 — 코드 경로는 같지만 이번 검증은 부띠끄로만.

## 라이브에서 확인한 전제 (2026-09-29)

- **API 서버 서비스 프록시가 EKS에서 막혀 있었다.** k3s 회귀가 관측 요청에 쓰는
  `connect_get_namespaced_service_proxy_with_path`가 타임아웃 — 원인은 terraform-aws-modules/eks 기본 노드 SG가
  컨트롤플레인→노드를 15017/6443/8443/9443/10250만 허용해서. Iac-aws `1-base/eks.tf`
  `node_security_group_additional_rules`에 `ingress_cluster_to_node_all`(protocol -1, source_cluster_security_group)을
  추가(커밋 `main`)했고, 살아 있는 클러스터에는 같은 규칙을 AWS CLI로 넣어 frontend `/` 12KB를 54ms에 받는 것을 확인.
  ⚠️ 1-base `terraform apply`는 `most_recent` AMI 드리프트로 EC2 교체가 섞여 있어 하지 않았다(팀 백로그: AMI 고정).
- PeerAuthentication 없음(PERMISSIVE) — 프록시의 평문 요청을 사이드카가 받는다.
- 부띠끄 Deployment는 replicas 1·readiness/liveness timeoutSeconds 1 — 개선안이 겨냥할 약점이 실재한다.

## 접근 — 실제 네임스페이스 in-place (채택)

EKS 앱의 준비 세션은 **배포 없이 `SUT_NAMESPACE`를 그대로 가리키는 즉시 ready 세션**이다. 회귀 두 라운드와 개선 패치가
라이브 Deployment에 적용되고, final 라운드가 끝나면(예외로 끝나도) 역순 롤백으로 원상 복구한다. k3s 경로는 코드 그대로.

대안(격리 복제)은 비범위 이유로 보류. in-place의 위험(라이브 SUT 변경)은 §4의 이중 가드와 전 경로 롤백으로 상쇄한다.

## §1 워크로드 서비스 — `RealEksWorkload` + `make_workload(env)`

- `services/real/eks_workload.py`: `RealEksWorkload(RealK3sWorkload)`.
  - `_api_client`: `real/kube.py`의 `load_kube(settings)`(incluster → kubeconfig `k8s_context`) + `client.ApiClient()`.
  - `deploy` → `NotImplementedError("EKS 앱은 in-place — 배포하지 않는다")`.
  - `teardown` → **no-op**(로그만). 라이브 ns 삭제를 구현 수준에서 원천 차단(가드 1).
  - `readiness`·`probe_http`·`apply_deployment_env`·`patch_deployment`는 상속(동일 K8s API).
- `deps.make_workload(env)`: `"k3s"` → 기존 `make_k3s_workload()`; 그 외 → `use_real_services`면 `RealEksWorkload`, 아니면
  `StubK3sWorkload`. Protocol 이름 `K3sWorkloadService`는 유지(개명은 노이즈).
- 호출 지점 교체: `regression.run_regression`, `preparations`(create의 스냅샷·teardown), 나머지 k3s 전용(실험 워처 현장 배포)은 그대로.

## §2 준비 세션 — EKS는 즉시 ready

`routers/preparations.py`
- `create_preparation`: `app.env != "k3s"`이면 manifest 요구 없이 `namespace = settings.sut_namespace`,
  `status="ready"`, `progress={"stage": "in_place", "message": "...실제 네임스페이스에서 그대로 검증...", + readiness 스냅샷}`
  (스냅샷 실패는 무시 — 세션은 ready). 이전 ready 세션은 기존처럼 cancelled로 닫되 **비-k3s는 `_teardown_session`을
  스케줄하지 않는다**(가드 2). `_teardown_session` 자체도 `app.env != "k3s"`면 return.
- `start_preparation`: 이미 `ready`인 비-k3s 세션이면 409 대신 payload 반환(멱등). 기존 JS `startPreparation`이 스트림을 연 뒤
  `/start`를 POST하고 실패를 곧 준비 실패로 보기 때문 — JS 무수정.
- SSE 스트림은 ready를 즉시 `completed`로 흘리므로 `waitPreparation` → `startScenarioRun` 흐름이 그대로 이어진다.

## §3 회귀 조립 — 매니페스트 원천은 run의 클러스터 덤프

`services/regression.py`
- `manifest_for(run, app)` = `run.input_payload["manifest_yaml"]`(있으면) 아니면 `app.manifest or ""`. EKS는 run 생성 시
  `dump_workloads`로 찍은 스냅샷이 곧 매니페스트(09/07 §2와 동일 원칙), k3s는 기존과 동일 값.
- `scenario_snapshot_from_hypothesis`: `workload_selector(manifest, target)`·`observation_for_app(app, manifest)` 모두 위 원천.
  **EKS에서 selector가 None이면 ValueError**(fail-fast) — None을 그대로 두면 ns 전체 `mode: one` 주입이 부띠끄의 임의 파드를
  죽인다. k3s는 기존 폴백(None=전용 ns 전체) 유지.
- `observation_for_app(app, manifest_yaml=None)`: `App.observe_service` 우선, 없으면 `entry_service(manifest, app.name)`.
  부띠끄 행은 `observe_service="frontend"`를 데이터로 채운다(등록형 generic-app은 Service 이름=앱명이라 자동 해석).
- `run_regression`: `workload = make_workload(run.app.env)`. **예외 경로 롤백**: `_apply_improvements`·final 도중 예외가 나도
  `run.improvement_changes`를 best-effort 역순 롤백(k3s에도 무해한 강화).
- `_run_one`의 `make_chaos(run.app.env, namespace)`는 EKS에서 `RealChaos(settings)`(sut_namespace 바인딩) — 세션 ns가
  `settings.sut_namespace`라 assert가 성립한다.

## §4 개선안 — EKS 게이트 해제

`routers/hypothesis.py`
- `propose_improvements`의 `app.env != "k3s"` 422 제거. 조립기(`assemble_improvement_input`)는 이미 `input_payload.manifest_yaml`을
  쓰므로 덤프 기반으로 제안된다.
- `_improvement_cards(proposals, manifest)`의 "현재(manifest)" 미리보기도 `manifest_for(run, app)` 값으로.
- 화이트리스트·검증·승인/편집/reopen·`POST /scenario-runs`의 미결 제안 422는 그대로.

## §5 UI 문구 — 환경별 한 줄

`experiment_detail.html` 3단계: `hyp_eks` 안내 카드 분기 삭제, k3s와 같은 패널 렌더. 문구만 `hypothesis_run.app.env`로 분기 —
- 조립 카드: k3s "전용 namespace에 앱을 다시 준비한 뒤 …" / EKS "`{ns}` 네임스페이스에서 그대로(in-place) 실행 — 개선은 회귀가
  끝나면 원래대로 롤백돼요".
- 준비 패널 항목: k3s "전용 namespace 생성 및 manifest 적용" / EKS "실제 네임스페이스 사용(배포 없음)".
- `_hypothesis_improve.html`: "개선은 검증 전용 namespace에만 적용…" / EKS "개선은 실제 네임스페이스에 적용되고 회귀가 끝나면 롤백돼요".

## §6 한계 (보고서 독자를 위한 명시)

- `readiness(namespace)`가 ns 전체 파드 기준이라 12개 서비스 ns에서는 `min_ready_pods`·회복 판정이 느슨하다(요청 성공 여부가
  사실상 회복 판정). 대상 selector로 좁히는 것은 백로그.
- 회귀 관측 요청은 API 서버 프록시 → 파드 인바운드(사이드카 경유, reporter=destination 기록). 부띠끄 자체 부하기와 섞여 R지수의
  Istio 지표에는 영향이 없다(회귀 판정은 Prometheus가 아니라 `observations`·`resilience.compare_runs`).
- 개선 패치는 Helm(terraform)으로 설치된 부띠끄 Deployment에 직접 들어간다. ArgoCD 관리 대상이 아니라 self-heal 되돌림은 없고,
  down.sh가 전부 지우므로 terraform 드리프트도 문제 없다. 등록형 앱(ArgoCD selfHeal)은 회귀 중 되돌림 가능성 → 백로그.

## §7 테스트 (Stub, 기존 276 유지)

1. `test_deps_factories`: `make_workload("k3s")`/`("eks")` 라우팅(Stub 모드) · real 모드 EKS는 `RealEksWorkload`.
2. `test_real_helpers`: `RealEksWorkload.teardown` no-op · `deploy` 예외 (SDK 미접속).
3. `test_preparations`: EKS 앱 create → 즉시 ready·namespace=sut_namespace·teardown 태스크 0 · 이전 ready EKS 세션 취소 시
   teardown 미스케줄 · `/start` 멱등 200.
4. `test_scenario_runs`: EKS run의 스냅샷이 덤프에서 selector·Service를 해석 · selector 미해결 ValueError · `run_regression`(EKS,
   기록형 Stub)에서 패치 적용→final 뒤 롤백 · final 예외 시에도 롤백.
5. `test_improvements_api`: EKS run `POST …/improvements` 200(422 소멸) · 카드 미리보기 덤프 값.
6. `test_hypothesis_api`: EKS run 3단계 렌더에 안내 카드 없음·회귀 조립 카드 있음.

## §8 라이브 검증 계획 (부띠끄)

새 가설 run: 직접 입력 "frontend pod-kill" → 2단계 완료 시 자동 갱신 확인 → 개선안 생성(claude) → replicas 1→2 등 승인 →
"최종 회귀 시작"(즉시 ready 세션) → baseline(failed 예상) → 패치 rollout → final(passed 기대) → 롤백 확인(`kubectl get deploy`) →
보고서 HTML/PDF.

## 변경 파일

| 파일 | 변경 |
|---|---|
| `services/real/eks_workload.py` | 신규 `RealEksWorkload` |
| `deps.py` | `make_workload(env)` |
| `routers/preparations.py` | EKS 즉시 ready · teardown 가드 · start 멱등 |
| `services/regression.py` | `manifest_for` · 덤프 기반 selector/Service · EKS fail-fast · `make_workload` · 예외 경로 롤백 |
| `routers/hypothesis.py` | improvements 422 제거 · 카드 미리보기 덤프 |
| `templates/pages/experiment_detail.html` · `partials/_hypothesis_improve.html` | 안내 카드 삭제 · 환경별 문구 |
| `tests/*` | §7 |
