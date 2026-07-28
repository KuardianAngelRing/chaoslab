# CLAUDE.md — chaoslab

세션 시작 시 자동 로드. **팀 공유 문서(커밋됨)** — 개인 로컬 메모는 `CLAUDE.local.md`(gitignore)에.

## 행동 규칙 (최우선)

- **커밋·푸시는 명시 요청 시에만.** 임의로 하지 않는다.
- **설계 결정·접근 전환 전 `advisor` 호출.**
- **`docs/`는 커밋** — 설계 문서(specs/plans)·보고서·회의 자료는 레포에 올려 팀 공유 (private 레포).
- **요청된 것만 구현.** 추측성 추상화 금지. 여기서 SOLID = 모듈 경계(routers/services/db/templates) 준수 + 외부 시스템에 `Protocol` 부여(DIP). DRY = 반복 마크업만 매크로화.
- **Python 3.12 고정.** 3.14는 SQLAlchemy 2.0.36과 비호환. venv는 iCloud eviction 방지를 위해 `python3.12 -m venv .venv.nosync && ln -s .venv.nosync .venv` (2026-07-06: ~/Documents가 iCloud 동기화라 .venv 7,400여 파일이 evict돼 서버 기동이 무한 블록됐던 사고 재발 방지).

## 프로젝트

졸업과제 **KuardianAngelRing**의 대시보드+AI 레포. EC2 단일 FastAPI가 EKS에 카오스 주입 → 메트릭 수집·시각화 → (Phase 3) AI가 Istio 파라미터 자동 개선.
3-repo: `Iac-aws`(인프라/GitOps) · **`chaoslab`**(이 레포) · 사용자 앱(SUT).
스택: `FastAPI + Jinja + HTMX + Alpine + Chart.js` · **SQLite** · 자산 CDN · SSE(realtime/worker 없음).
R지수 = 0.4·가용성 + 0.3·레이턴시점수 + 0.3·복구속도.

## 아키텍처 핵심

- **render_page** (`app/rendering.py`): `HX-Request`로 풀 셸(`base.html`) vs 부분(`_partial.html`) 분기. 페이지는 `{% extends layout|default("base.html") %}`로 시작.
- **외부 시스템 = `Protocol`+`Stub`** (`services/interfaces.py`+`stubs.py`). 라우터는 인터페이스만 의존. **stub→real 교체는 `deps.py` 한 줄.**
- **소유 데이터 = SQLite + Repository** (apps/builds/experiments/agent_iterations). mock은 `db/seed.py` (템플릿 하드코딩 금지).
- nav는 `partials/_sidebar.html` 한 곳(`active_nav`), `app_count`는 `deps.get_app_count` 한 곳.

```
app/  main(lifespan seed)·config·deps·rendering
      routers/ pages·stream(SSE)·webhook(자리)
      services/ interfaces·stubs·agent/(Phase 3)
      db/ database·models·repositories·seed
      templates/ base·_partial·partials·macros·pages(6)
      static/ css/tds.css·js/app.js
tests/ hermetic (in-memory StaticPool + seed fixture)
```

## 실행

```bash
source .venv/bin/activate
uvicorn app.main:app --reload    # localhost:8000 (lifespan이 seed 자동)
pytest -q                        # 19 통과
```
`chaoslab.db`는 런타임 생성·gitignore (EC2 파괴 시 소실).

## Phase 2 진행 현황 / TODO

- [x] **Slice 1 — 걷는 뼈대**: 6페이지 UI·HTMX 네비·SQLite/seed·Stub·SSE 배선·테스트

- [x] **Slice 2 — 빌드/배포 (A)** ✅ **라이브 검증 완료 (2026-06-02)** — 트리거=수동 '빌드' 버튼. 근거: cloud-hub `doc/graduation-gitops-flow.md`(읽음)
  - [x] **2a 인프라(Iac-aws)**: ArgoCD+Argo Workflows+ECR IRSA+App-of-Apps+`helm/generic-app` — ✅ 파드 Running·App-of-Apps(root+demo) Synced/Healthy 확인
  - [x] **2b 빌드(chaoslab)**: `argo/build-and-push` WorkflowTemplate + `docker/templates/` — ✅ opus-backend(Spring/Java17) Kaniko 빌드→ECR push 확인
  - [x] **2c 대시보드**: RealGitOps·RealBuilder·앱등록 POST·빌드 watch·`deps.py` real — ✅ 등록→bootstrap→빌드→image tag 갱신→ArgoCD sync→실이미지 파드 기동 확인
  - [x] 라이브 검증: `up.sh` → demo 자동배포 → opus-backend 등록·빌드·배포 (Option A: 파드는 DB/시크릿 부재로 CrashLoop, 파이프라인 무결)

### 🔧 Slice 2 라이브 검증에서 나온 후속/개선 과제 (2026-06-02)
  - [x] **빌드 이력 UI** ✅ **구현 완료 (2026-06-06)** — 앱 카드 "이력" 버튼 → 공유 모달(`#dialog-builds`)에 HTMX로 `/apps/{id}/builds` 부분 렌더(`partials/_build_history.html`): 상태배지·sha8·시작·소요(`build_duration`)·workflow. 신규 `routers/builds.py`. 설계·계획 `docs/superpowers/*/2026-06-06-build-history-sse*`.
  - [x] **빌드 watch → SSE** ✅ **구현 완료 (2026-06-06)** — `GET /apps/{id}/builds/stream`(상태 전용 SSE, `App.status` DB 폴링→building 벗어나면 `completed`). `app.js watchBuilds()`가 building 카드만 EventSource 구독, completed 시 `htmx.ajax GET /apps`로 목록 새로고침(배지·sha 서버렌더 단일소스). `_watch_build`(Argo폴링)와 독립. **테스트:** 즉시-completed·시간전이 단위테스트(SessionLocal monkeypatch로 격리) 45통과. **단, 실제 브라우저 배지 live 전환은 up.sh 라이브에서 눈으로 검증.** 엣지: 빌드 완료 시 목록 새로고침이 열린 이력 모달을 닫음(용인).
  - [x] **health probe / actuator** ✅ **구현 완료 (2026-06-07)** — `generic-app/deployment.yaml`에서 `{{ if .Values.healthPath }}`로 분기: 값 있으면 `httpGet`, 비면 `tcpSocket`(port). chaoslab 코드 무변경(이미 per-app healthPath 기록) → actuator 없는 앱은 등록 시 healthPath 비우면 TCP probe로 기동. `helm template` 양 케이스 검증. Iac-aws 커밋 `17bbc14` push 완료(2026-07-06 확인).
  - [x] **⭐ 환경변수·시크릿 주입 (cloud-hub 방식)** ✅ **구현 완료 (2026-06-06)** — SUT 앱 설정을 이미지에 안 굽고 **등록 시 주입**. 흐름: 등록 폼 env/secret 입력(`app.js` vanilla 에디터·.env 붙여넣기·시크릿 자동감지) → `App.env_vars` JSON 컬럼(단일 진실원천, 편집=재등록 upsert) → `_bootstrap`이 `split_env`로 분리 → **평문**은 `gitops/apps/{app}/values.yaml` `env:`, **비밀**은 `RealK8s.apply_env_secret`로 클러스터 K8s Secret 직접 생성(public 레포라 git 미저장) → `generic-app` `deployment.yaml`의 `env`/`envFrom: secretRef` 렌더. 설계·계획: `docs/superpowers/specs|plans/2026-06-06-env-secret-injection*`.
    - cloud-hub와의 차이: cloud-hub는 Secret 매니페스트를 **private gitops 레포**에 커밋(`helm-chart.ts`). 우리는 public이라 **클러스터 직접 apply**로 대체(업계표준 12-factor 주입 원칙은 동일, GitOps 시크릿 정석인 SealedSecrets/SOPS는 졸과 범위서 생략).
    - 테스트: `pytest` 38 통과(`conftest` autouse로 항상 Stub 강제 — 로컬 `.env` USE_REAL 실호출 차단). 차트: `helm template` env/envFrom 렌더·하위호환 확인.
    - **라이브 선결(미완, up.sh 검증 시):** 대시보드 K8s 신원에 `sut_namespace` `secrets` create/update RBAC 부여 필요(RealBuilder는 `argo_namespace` Workflow 권한만). Iac-aws 차트는 push 완료(2026-07-06 확인).
    - ~~미검증 경로~~ ✅ **해소 (2026-06-07)**: `_bootstrap` 성공/실패 단위테스트 추가(`SessionLocal`·`make_gitops`·`make_k8s` monkeypatch + spy, caplog) → 배선 실행 커버됨. (아래 `_bootstrap 에러 처리` 항목과 함께 처리)
    - **라이브 동작 주의(up.sh):** ① 재등록 시 시크릿 전부 제거해도 옛 `{name}-env` Secret은 클러스터에 고아로 잔존(무해). ② `secretName`이 항상 `{name}-env`라 시크릿 **값만** 바꿔 재등록하면 values.yaml diff 없음→ArgoCD sync 안 됨→파드가 옛 값 유지(수동 재시작 필요). opus-backend 설정 맞춰갈 때 주의.
    - ~~**수동 정리 TODO:** 가짜 `payment-svc` ECR 레포~~ ✅ **정리 완료 (2026-07-07)** — `aws ecr delete-repository --repository-name payment-svc --force`. AWS 리소스 0개 확인(EKS·EC2·NAT·ECR 전부 없음).
  - [x] **`_bootstrap` 에러 처리** ✅ **구현 완료 (2026-06-07)** — `logging.getLogger(__name__)` 도입, `_bootstrap`·`_watch_build`의 삼킴 except → `logger.exception`(원인 traceback이 EC2/uvicorn 로그에 노출). 상태값은 유지(register-failed/build-failed). + `_bootstrap` 성공/실패 단위테스트.
  - [x] **`.env.example` 정비** ✅ **구현 완료 (2026-06-07)** — 인라인 주석을 각 키 윗줄로 분리, real 모드 키 빈 값. `dotenv_values` 파싱으로 ECR_REGISTRY/IAC_AWS_REPO_PATH/GITHUB_TOKEN 모두 `''` 확인.
  - [x] **앱 카드 드롭다운 액션 4종** ✅ **구현 완료 (2026-07-06)** — `...` 메뉴: 빌드/배포 히스토리·GitHub + **재빌드**(기존 POST build), **재배포**(`POST /apps/{id}/redeploy` — stopped면 gitops replicas 1 재개, 아니면 `RealK8s.restart_deployment` rollout restart → 시크릿 값만 변경 시 수동 재시작 문제의 해법), **배포 중지**(`POST /apps/{id}/deploy/stop` — `RealGitOps.set_replicas(0)` 커밋, selfHeal이라 직접 scale 불가), **빌드 중지**(`POST /apps/{id}/build/stop` — Argo `spec.shutdown=Stop` 패치, 상태 정리는 `_watch_build`에 위임). App.status에 `stopped` 추가(카드 "중지됨" 배지).
    - **라이브 선결(미완):** 대시보드 K8s 신원에 ① `sut_namespace` `apps/deployments` **patch**(재배포) ② `argo_namespace` `workflows` **patch**(빌드 중지) RBAC 추가 필요.

- [x] **Slice 3 — 카오스 (B)** ✅ **구현 완료 (2026-07-07)** · `RealChaos`
  - [x] "새 실험" 폼 POST → Chaos Mesh CRD (Network delay/Pod kill/Stress cpu) + `chaos_specs.validate_params` 범위검증(latency 10–10000ms·cpu 1–100%·duration 30–1800s) + 앱당 1개(409)
  - [x] 주입 watch(`_watch_experiment`: duration 대기→회복확인→CRD 삭제→completed, 매 폴링 DB status 재확인해 중지 시 조기종료)→SSE(`/experiments/{id}/stream`, builds/stream 미러) · 중지(`/experiments/{id}/stop`) · `kubernetes-py` CustomObjectsApi CRD 적용/삭제
  - 구조: `services/chaos_specs.py`(스키마·검증 순수함수) · `services/real/chaos.py`(CRD 렌더 순수함수 + RealChaos) · `routers/experiments.py`(생성·중지·SSE·워처) · `Experiment.crd_name` 컬럼 · UI 실배선(타입별 파라미터 패널·상태배지·중지·`watchExperiments` SSE). 설계·계획: `docs/superpowers/specs/2026-07-06-slice3-chaos-injection-design.md`·`plans/2026-07-07-slice3-chaos-injection.md`. 테스트 89 통과(stub 모드).
  - **라이브 선결(미완, up.sh 검증 시):** ① 대시보드 K8s 신원에 `sut_namespace` `chaos-mesh.org` CRD create/get/delete RBAC ② Chaos Mesh 파드 Running 확인(`kubectl get pods -n chaos-mesh`) ③ 주입 대상 파드 필요(comon-be `chaoslab-deploy` 브랜치 또는 demo) ④ `init_db`는 create_all만 → EC2 **비파괴** 재기동 시 기존 `chaoslab.db`에 `crd_name` 없어 깨짐(파괴 재생성이면 무해; 재기동 전 DB 삭제 확인) ⑤ seed running 실험 params가 구버전 키(delay/duration)라 기간 "—" 표시(mock 한정, real 무관)

- [ ] **Slice 4 — 모니터링 (C)** · `RealPrometheus`/`RealLoki`/`RealK8s`
  - [ ] Prometheus RED(9090)·Loki 로그(3100)·K8s 노드/Pod/컴포넌트 실조회
  - [ ] 차트 실데이터 + SSE 실시간 갱신

- [ ] **Slice 5 — 결과/R지수 (D)** *(AI 루프 자체는 Phase 3)*
  - [ ] R지수 계산(baseline/fault/recovery) + 추이·iteration 히스토리 실데이터

- [ ] **설정 (E)**: 설정 저장(LLM/목표R/예산) + 외부 통합 키
- [ ] **Iac-aws 변경**: `ecr.tf`(IRSA) · ArgoCD+Argo Workflows+App-of-Apps · `argocd/`+`gitops/` 구조 · `online-boutique.tf` 무력화 · EC2 `user_data`(chaoslab clone+기동) · SG 본인IP

> 권장 순서 A→B→C→D. A는 Iac-aws 변경과 맞물림.

## 참조 / 컨벤션

- 스펙 `../Iac-aws/docs/phase2-dashboard.md` · 목업 `../Iac-aws/docs/graduation-dashboard-mockup.html`
- 로컬 설계 `docs/superpowers/specs/`·`plans/`
- 커밋: ✨기능 🐛버그 ♻️리팩 🔧설정 📝문서 ✅테스트 🔥삭제 · 파일단위 원자적
