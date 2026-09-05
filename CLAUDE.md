# CLAUDE.md — chaoslab

세션 시작 시 자동 로드. **팀 공유 문서(커밋됨).** 새 세션(Claude Code/Codex)과 팀원이 이 파일만 읽으면 작업 시작 가능한 것이 목표.

## 행동 규칙 (최우선)

- **커밋·푸시는 명시 요청 시에만.** 임의로 하지 않는다.
- **설계 결정·접근 전환 전 상의.** (에이전트 세션이면 advisor/planner 호출, 사람이면 팀 논의)
- **요청된 것만 구현.** 추측성 추상화 금지. 여기서 SOLID = 모듈 경계(routers/services/db/templates) 준수 + 외부 시스템에 `Protocol` 부여(DIP). DRY = 반복 마크업만 매크로화.
- **`docs/`는 커밋** — 설계 문서(specs/plans)·보고서·회의 자료 팀 공유 (private 레포). 단 `.env`·`*.db`·kubeconfig·`.pem`은 절대 커밋 금지.
- **Python 3.12 고정** (3.14는 SQLAlchemy 2.0.36 비호환). macOS `~/Documents`가 iCloud 동기화면 venv 파일이 evict돼 기동이 무한 블록되므로 `python3.12 -m venv .venv.nosync && ln -s .venv.nosync .venv`.

## 프로젝트

부산대 졸업과제 **카엔링(KuardianAngelRing)** — "카오스 엔지니어링 자동화 및 모니터링 플랫폼".
장애 주입→관측→분석→개선→재검증 루프를 LLM 에이전트로 자동화하고, 회복탄력성을 **R지수**(= 0.4·가용성 + 0.3·레이턴시점수 + 0.3·복구속도)로 정량화한다.

- **3-repo**: `Iac-aws`(Terraform 인프라 + GitOps 배포 정의) · **`chaoslab`(이 레포 — EC2 단일 FastAPI 대시보드 + AI 루프)** · 사용자 앱(SUT)
- **팀 역할**: 김태윤(클라우드 실험 환경·플랫폼 = 이 레포/Iac-aws) · 이시웅(온프레미스 라즈베리파이 k3s + AI 루프) · 양준영(온프레미스 운영·AI 루프·대시보드 통합)
- **확정 사항** (중간보고서, `docs/`): SUT=Online Boutique(11 MSA)+사용자 앱 등록 · AI 개선 범위=Istio timeout/retry/circuitBreaker(허용범위 사전 검증) · LLM 에이전트=LangGraph 워크플로우형 · 관측=Prometheus/Loki/Promtail/Istio(분산 트레이싱 제외) · EKS 1.31 + Chaos Mesh 2.8.2 + Istio 1.29.2 · `up.sh`(~25분 구축)/`down.sh`(비용 0원)
- **스택**: `FastAPI + Jinja + HTMX + Alpine + Chart.js` · SQLite(→Supabase 전환 확정, 아래 TODO) · 자산 CDN · SSE(워커·메시지큐 없음 — 단일 프로세스 + 백그라운드 태스크)

## 아키텍처

- **렌더링** (`app/rendering.py` `render_page`): `HX-Request` 헤더로 풀 셸(`base.html`) vs 부분(`_partial.html`) 분기. 페이지 템플릿은 `{% extends layout|default("base.html") %}`로 시작. 사이드바 네비는 `hx-get`→`#main-content` 스왑.
- **외부 시스템 = `Protocol` + Stub/Real** (`services/interfaces.py`): `BuilderService`(Argo Workflows) · `GitOpsService`(Iac-aws values.yaml 커밋/푸시 = 배포 트리거) · `ChaosService`(Chaos Mesh CRD) · `K8sService` · `PrometheusService` · `LokiService`. 라우터는 인터페이스에만 의존, **Stub↔Real 전환은 `deps.py`의 `make_*` 팩토리 한 곳**(`settings.use_real_services` 플래그, Real은 lazy import). 백그라운드 태스크도 `make_*` 재사용.
- **소유 데이터 = SQLite + Repository** (`db/models.py`): `App`(env_vars JSON 포함) → `Build` · `Experiment`(baseline/fault/recovery metrics, r_index, crd_name) → `AgentIteration`(Phase 3). mock 데이터는 `db/seed.py`에서만 (템플릿 하드코딩 금지). `init_db`는 `create_all`만 — 마이그레이션 없음.
- **워처 + SSE 패턴** (builds·experiments 공통): POST 액션 → 백그라운드 워처가 외부 시스템 폴링하며 DB status 갱신(매 폴링 DB 재확인으로 중지 시 조기종료) → 별도 **상태 전용 SSE**(`/…/stream`, DB 폴링)를 `app.js`의 `watchBuilds()`/`watchExperiments()`가 EventSource 구독 → 종료 상태 오면 `htmx.ajax`로 목록 재요청(**배지·값은 항상 서버 렌더가 단일 소스**).
- **한 곳 원칙**: nav 활성화=`partials/_sidebar.html`(`active_nav`) · 사이드바 앱 카운트=`deps.get_app_count` · 카오스 파라미터 스키마·범위검증=`services/chaos_specs.py`(순수함수).

```
app/  main.py(lifespan에서 init_db+seed) · config.py(pydantic-settings, .env) · deps.py · rendering.py
      routers/   pages · apps(등록/빌드/재배포/중지) · builds(이력·SSE) · experiments(생성·중지·SSE·워처) · stream
      services/  interfaces(Protocol) · stubs · chaos_specs(순수 검증) · real/(builder·gitops·k8s·chaos) · agent/(Phase 3)
      db/        database · models · repositories · seed
      templates/ base · _partial · partials/(_sidebar·_build_history·_deploy_history) · macros/components · pages(6)
      static/    css/tds.css · js/app.js
argo/     build-and-push WorkflowTemplate (+apply.sh)
docker/   프레임워크별 Dockerfile 템플릿
tests/    hermetic — in-memory SQLite(StaticPool) + seed fixture, conftest autouse로 항상 Stub 강제
```

## 디자인 시스템 (tds.css)

- **색은 전부 CSS 변수** — 하드코딩 금지. 라이트/다크는 `<html data-theme>` 속성으로 전환(`app.js` 토글, 차트도 재렌더). 주요 토큰: `--primary`(라이트 `#004b3e` 딥그린 / 다크 `#00b894`) · `--card` `--border` `--muted` `--muted-foreground` · 시맨틱 `--success/--warning/--danger/--info`. 인라인은 `style="color: var(--muted-foreground)"` 패턴.
- **레이아웃**: Tailwind CDN 유틸 + `tds.css` 커스텀 클래스 조합. 폰트 Pretendard/Noto Sans KR, 코드·sha는 `.mono`.
- **컴포넌트 클래스**: `tds-card`(radius 1.5rem, `hover-lift` 옵션) · `tds-btn-primary`/`tds-btn-muted`(높이 2.75rem, radius 1rem) · `tds-input` · `tds-badge`+`badge-{success|warning|danger|info|muted}` · 탭 `tab-trigger`(underline+primary) · 드롭다운 `card-menu` · 모달 `dialog-backdrop`/`dialog-card`(위저드는 `data-wizard` 높이 고정+코너 리사이즈 그립) · `progress-track/fill` · 검증 툴팁 `field-tooltip`.
- **Jinja 매크로** (`macros/components.html`): `badge` · `framework_icon`(감지 실패 시 docker 아이콘) · `kpi_card` · `app_card`. 반복 마크업은 여기로.
- **아이콘**: `<iconify-icon>`(UI는 `solar:*`, 기술로고는 `logos:*`) + 토스페이스 이모지(`.tossface`).
- **app.js 패턴**: 전역 리스너 1개짜리 **이벤트 위임**(메뉴·탭·테마·다이얼로그) — 요소별 리스너 부착 금지(HTMX 스왑에도 동작 유지). 등록 모달은 3-step 위저드(클라 show/hide, submit은 마지막 1회).

## 실행

```bash
source .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload    # localhost:8000 (lifespan이 seed 자동)
pytest -q                        # 171 통과
```
`.env`는 `cp .env.example .env`면 충분(기본 `USE_REAL_SERVICES=false`=전부 Stub → 클러스터·AWS 없이 개발/테스트). 라이브 연동 값(ECR_REGISTRY·GITHUB_TOKEN 등)은 팀 내 개인 전달. `chaoslab.db`는 런타임 생성·gitignore.

## 진행 현황

- [x] **Slice 1 — 뼈대**: 6페이지 UI·HTMX 네비·SQLite/seed·Stub·SSE 배선
- [x] **Slice 2 — 빌드/배포** (라이브 검증 완료): 앱 등록→`_bootstrap`(ECR+ArgoCD App+values.yaml, 평문 env는 values·시크릿은 K8s Secret 직접 apply)→Kaniko 빌드→ECR→ArgoCD sync. 빌드 이력 모달·빌드 SSE·healthPath 유무 따라 httpGet/tcpSocket probe·카드 액션 4종(재빌드/재배포=rollout restart/배포중지=replicas 0/빌드중지=Argo shutdown). ⚠️ 시크릿 **값만** 바꿔 재등록하면 values diff 없어 sync 안 됨 → "재배포" 버튼이 해법.
- [x] **Slice 3 — 카오스** (k3s 라이브 검증 완료 08/19 · EKS는 미검증): 실험 폼→Chaos Mesh CRD 3종(network-delay·pod-kill·cpu-stress), `chaos_specs` 범위검증(latency 10–10000ms·cpu 1–100%·duration 30–1800s), 앱당 1개(409), `_watch_experiment`(duration→회복 확인→CRD 삭제→completed, 회복 미확인이면 failed)·중지·SSE.
- [x] **로컬(k3s) 연결 — SSH 터널 + 현장 배포 실험** (08/18–19, ADR-0009): `App.env`("eks"/"k3s", ADR-0002 백로그 해소)·`App.manifest`·`Experiment.namespace` 컬럼 추가 · k3s 등록=manifest 저장만(`registered`) · 실험 시 전용 ns(`chaoslab-{app}-{exp_id}`) 배포→ready→주입(ns 전체 selector)→관측→CRD·ns 삭제(`K3sWorkloadService`) · SSH 터널은 앱이 자동 관리(`TunnelService`, `LOCAL_SSH_*` 설정 시 기동에서 열고 끊기면 재접속) · 로컬 인프라 탭 실데이터(`LocalK8sService`, `LOCAL_KUBECONFIG` 게이트). ⚠️ 라즈베리파이 클러스터에서 **NetworkChaos는 chaos-daemon iptables 적용 실패**로 주입 안 됨(PodChaos는 정상) — 클러스터 측 조치 필요. 단 08/31 재검증에서는 재현 안 됨(delay 주입이 관측에 정상 반영) — 간헐 이슈 가능성.
- [x] **AI 전달 데이터 인터페이스** (08/04 회의): 노션 §2 계약(`services/agent/handoff_schema.py`, `schema_version` 1.0) · `agent_handoffs` 스냅샷 테이블 · 조립기(저장 metrics 우선, 외부산은 `HandoffSourceService` Stub — Real은 Slice 4·5) · REST CRUD(`routers/handoffs.py`, AI 루프 소비 지점은 `GET /experiments/{id}/handoffs/latest`, 계약 열람은 `/docs`)
- [x] **장애 유형 9종 확장** (08/25, 가설 수립 선행 작업): `chaos_specs`를 슬러그 키로 전환(`chaos_type`가 이제 "network-delay"류 슬러그 — kind·action은 스펙에서 해석) · NetworkChaos delay/loss/partition/bandwidth · PodChaos pod-kill/pod-failure/container-kill(`container_name` str 필드) · StressChaos cpu/memory. `render_chaos_manifest` action 분기·라우터 폼 필드·시드 갱신. ⚠️ 구 DB의 chaos_type("NetworkChaos"류)은 무효 — 재기동 전 DB 삭제.
- [x] **가설 수립 단계** (08/25 구현 · 라이브 검증 완료 — stub 08/31, `claude -p` 09/01): 스펙 2차 개정(detailing 2단 + 하이브리드 1~5, `docs/superpowers/specs/2026-08-25-hypothesis-stage-design.md`)대로 배선 완료 — 계약(`hypothesis_schema.py`) · 조립기(manifest 원문+정적 분석 findings+과거 이력) · `HypothesisRun`/`ExperimentCandidate`(+`Experiment.candidate_id`) · `HypothesisAgentService`(Stub + `ClaudeCliHypothesisAgent`) · 공통 검증+교정 재시도 1회(`hypothesis_validation.py`) · `routers/hypothesis.py`(생성→SSE→선택→detailing→`start_experiment` 이어달리기) · 위저드 제출 실배선 · seed·테스트. 활성화는 `.env` `HYPOTHESIS_AGENT=claude`. 09/01 라이브(k3s nginx, CLI 2.1.251): 후보 3종 생성(규칙 준수·fault 중복 없음)→container-kill 선택→detailing(params·rationale)→실험 completed(R=0.7221), `claude_agent.py` 무수정·교정 재시도 미발동. ⚠️ 재기동 전 구 DB 삭제 필수(컬럼·chaos_type 슬러그 변경).
- [x] **Slice 4 — 실측 연동** (라이브 검증 2026-08-13 완료 — 부띠끄 frontend delay 200ms: p99 49.7→3176.6ms, 회복 2.3s, R=0.7024 공식 검산 일치, 핸드오프 실데이터 확인): 실험 완료 시 Prometheus 소급 집계(기준선=주입 전 5분/장애/회복)를 계약 형태로 `*_metrics` 저장 + `r_index` 실계산(`services/r_index.py`, 복구 상한 300s) · Real 4종(`real/prometheus·loki·handoff_source` + `RealK8s` nodes/pods/components) · kubeconfig 공용화(`real/kube.py`, `k8s_context` 지원) · Iac-aws: sut Istio 스크레이프 + generic-app DestinationRule. 차트 실데이터·SSE 갱신 등 화면 배선은 팀원 영역으로 이관
- [x] **3-PR 통합 + k3s 라이브 재검증** (08/31, upstream PR #9 머지 = #5 실측 연동 + #7 가설 수립 + #8 시나리오 회귀·보고서, pytest 198 통과): nginx 가설(stub)→pod-kill 실험 completed+R지수 저장 · order-resilience-lab 개선 전후 회귀 6분 완주(개선 env 실적용 확인 — 이 클러스터에선 개선 효과 미관측, 판정 failed는 샘플/기준 튜닝 문제로 팀 논의 필요) · 라이브 버그 3건 수정(원샷 pod-kill·container-kill 회복 판정 · k3s 프록시 서비스 포트 명시 · 프록시 응답 dict-repr 파싱 오판)
- [x] **후보 선택 탭 ↔ 가설 수립 라우터 배선** (09/02, `docs/superpowers/specs/2026-09-02-plan-tab-hypothesis-wiring-design.md`, pytest 200 통과 · Stub 브라우저 스모크 완료): 워크플로우 셸(`experiment_detail.html`)을 `HypothesisRun` 앵커로도 렌더(`GET /hypothesis/{id}?view=plan|execute`, `hypothesis.html` 삭제) · 1단계=`partials/_hypothesis_plan.html`(후보 radio 단일 선택→`/select`, 직접 입력→`/freeform`, 배너는 조립 근거만) · 2단계=`partials/_hypothesis_execute.html`(승인 후보 실험 카드: params·rationale·상태·R지수, `data-running-exp-refresh`로 SSE 갱신) · SSE `completed` redirect → `?view=execute` · 실험 목록 `demo_runs`→가설 Run 행+KPI 실값(`pages.experiments_context`). 회귀 경로 통합은 09/05 항목, 위저드 `order-resilience-lab` 분기 제거는 09/06 항목 참조. 테스트 인프라: sse-starlette 전역 `AppStatus.should_exit_event`를 conftest에서 매 테스트 초기화.
- [x] **가설 경로 ↔ 최종 회귀·보고서 통합** (09/05, `docs/superpowers/specs/2026-09-05-hypothesis-regression-integration-design.md`, pytest 203 통과 · Stub curl 검증): 승인(detailed) 후보를 회귀 시나리오로 조립(`regression.scenario_snapshot_from_hypothesis`, `DEFAULT_CRITERIA` 한 곳 · improvements 빈 리스트=보고서에 "적용된 개선 없음") · `ScenarioRun.hypothesis_run_id` 컬럼 + `latest_for_hypothesis` · `POST /scenario-runs`에 `hypothesis_run_id` 폼(있으면 `selected_ids` 무시) · 셸 가설 경로: 실험 종료→3단계(verify, "최종 회귀 시작" = `startPreparation` ready 대기→`startScenarioRun`)→4단계(`?view=result` R지수 전후·보고서 HTML/PDF 링크) · 실험 목록 행 3/4·4/4. `order-resilience-lab` YAML 경로(`_snapshot_from_yaml`)는 그대로.
- [x] **실험 진행 중 실시간 메트릭 스트림** (09/05, `docs/superpowers/specs/2026-09-05-live-metrics-stream-design.md`): `PrometheusService.live_snapshot`(rps·오류율·p95/p99·ready, Stub은 결정적 시퀀스 · Real은 `live_queries()` 즉시 쿼리) · `GET /experiments/{id}/metrics/stream`(3초, `metric`→`completed`) · 2단계 실행 카드 차트 2개(`watchLiveMetrics`, rolling 60틱) + 종료 시 fault/recovery 요약 표. k3s 실측 연결은 아래 09/05 항목. `app.js` 수정 시 `base.html`의 `?v=` 캐시 버스팅 갱신 필수.
- [x] **nginx 전 흐름 k3s 라이브 검증** (09/05, pytest 210): 위저드→`claude` 후보 5종→pod-kill 선택→실험 completed(R=0.7229, 실시간 차트 갱신 확인)→3단계 "최종 회귀 시작"(준비 세션 ready→회귀 26초 완주)→4단계 R 29.7→41.3·보고서 HTML/PDF 다운로드. 라이브 버그 1건 수정: 가설 경로 selector가 `app.kubernetes.io/name`을 가정해 nginx(`app=nginx`)에서 Chaos Mesh `Selected=False`→5분 타임아웃(판정 불가) — 매니페스트 `matchLabels` 파싱(`regression.workload_selector`)으로 교정. ⚠️ 판정은 failed(장애 중 오류율 50%·ready 파드 기준 미충족) — 개선 명세 없는 동일 조건 2라운드라 당연한 결과이며 `DEFAULT_CRITERIA` 튜닝·Phase 3 개선 루프가 채울 자리.
- [x] **k3s Prometheus 실측 연결 + UX 잔여** (09/05, `docs/superpowers/specs/2026-09-05-k3s-prometheus-live-metrics-design.md`, pytest 222): `make_prometheus(env)` — k3s는 `LOCAL_KUBECONFIG` 게이트로 `LocalPrometheus`(`real/local_prometheus.py`, k8s API 서비스 프록시 `chaospilot-observability/prometheus:9090` — 터널 6443 하나로 접근, Istio 없음 → ns 전체 `kube_pod_status_ready` + 앱이 노출하는 `chaospilot_http_*`) · 수집기가 `exp.namespace`(k3s 전용 ns)로 조회하도록 교정 · 샘플 `order-resilience-lab.yaml`에 `prometheus.io/*` 스크레이프 어노테이션. 라이브(nginx pod-kill exp 32): Ready 0→2 실측·회복 6.2s. UX: status SSE 중간 전환(deploying→running)에도 view 재요청 · 2단계 카드 "실험 중지"(`POST /experiments/{id}/stop`에 `next` 폼 → `HX-Location` 복귀) · 라이브 차트 색 스크립터블(다크 토글 반영) · HTTP 메트릭 미노출 앱 안내 문구. ⚠️ nginx처럼 HTTP 메트릭이 없으면 rps/오류율/p95는 None(차트 공백)이고 R지수는 가용성·레이턴시 항이 자동 만점(exp 32 R=0.9938) — ChaosPilot 앱 메트릭도 히스토그램 버킷이 없어 p95/p99는 k3s에서 항상 없음. 회귀 판정 failed 원인(`mode: all` pod-kill → Ready 0 필연)과 선택지는 `docs/superpowers/specs/2026-09-05-regression-criteria-decision-memo.md`.
- [x] **회귀 판정 구조 교정 (메모 권장안 A1+B1+B3 채택)** (09/05, pytest 228): PodChaos CRD `mode: one`(레플리카 1개 손실 검증 — Network/Stress는 `all`) · 관측 샘플당 요청 3회 + 오류율·p95를 요청 수 기준(`observations.py`) · 장애 구간 최소 6샘플, 원샷 액션도 grace 동안 관측(`regression._MIN_FAULT_SAMPLES`) · 장애 구간 트래픽 없으면 `r_index.compute` `r=None`(카드 "산정 불가"). `DEFAULT_CRITERIA` 불변. 라이브 재검증(ScenarioRun 6, HYP-8 nginx pod-kill, 준비 세션 5 재사용): CRD `mode=one`으로 파드 1개만 종료 → baseline·final 모두 **passed**(장애 구간 18요청 오류 0%·최소 Ready 1·회복 1.1s/1.0s, R 99.2→99.3). 이전 run 5는 failed(오류율 50%·Ready 0)였다.
- [x] **개선 단계(휴먼인더루프, Phase 3 착수)** (09/05, `docs/superpowers/specs/2026-09-05-improvement-stage-design.md`, pytest 244): 2단계 실험 종료 → 3단계 상단 패널 `partials/_hypothesis_improve.html` "개선안 생성"(`POST /hypothesis/{id}/improvements`, `HypothesisAgentService.propose_improvements` Stub 2안/`claude`) → 카드(checkbox·manifest 현재값 vs 제안 diff·근거) → 승인/편집/제외(`…/improvements/approve`, `…/reopen`) → 회귀 시작. `ImprovementProposal` 테이블(+`hypothesis_runs.improvement_status/error`는 `_upgrade_hypothesis_runs` ALTER — 구 DB 삭제 불필요) · 화이트리스트 `services/improvement_specs.py`(`manifest_patch`=probe·preStop·resources·replicas, `deployment_env`=기존 env — Istio는 EKS 전용 백로그) · `K3sWorkloadService.patch_deployment`(strategic merge, `before` 프로젝션이 곧 롤백 패치) · `regression._apply_improvements` 타입 분기+역순 롤백 · 미결 제안 있으면 `POST /scenario-runs` 422·버튼 disabled · 보고서 표/문장은 `change_rows(only_changed)` 경로별 전후. 라이브(HYP-6 nginx pod-kill, ScenarioRun 7, `claude`): 제안 3종(replicas 3·readinessProbe 단축·resources — 근거에 실측 503 298건·회복 8.7s 인용) → readinessProbe만 승인 → 세션 6 Deployment에 `periodSeconds 3→2·failureThreshold 3→2` 실적용 확인(kubectl generation 2) → baseline·final passed, R 99.3→99.4, 보고서 HTML/PDF 전후 표. ⚠️ 개선은 회귀 전용 ns에만 적용되고 앱 manifest는 불변(영구 반영·구조화 편집기·개선 반복 루프는 백로그).
- [x] **nginx 내장 샘플 + 위저드 단일 경로 + 회귀 관측 Service 교정** (09/06, pytest 250): k3s 내장 샘플에 `nginx` 추가(`sample_apps.py`·위저드 카드, 라디오 `data-sample-*`로 이름·경로 동기화) · 새 실험 위저드의 `order-resilience-lab` 전용 분기 제거 → 모든 앱이 `POST /hypothesis` 가설 경로(구 YAML 셸 `/experiments/{1,2,3}`은 데모 URL로만 잔존) · **`App.observe_service`** 컬럼(`_upgrade_apps` ALTER — 구 DB 삭제 불필요): 가설 경로 회귀의 관측 요청 대상 Service. 샘플은 registry 값(order-resilience-lab=`checkout-api`, nginx=`nginx`), 직접 manifest는 등록 시 `regression.entry_service`로 추론(앱명과 같은 Service → 단일 Service → 없으면 빈 값), 미해결이면 `POST /scenario-runs` 422. 라이브(HYP-11 order-resilience-lab, ScenarioRun 11, 세션 9 재사용): 기준선 9/9 200(이전 run 10은 `order-resilience-lab` Service 부재로 9/9 404) → baseline·final **passed**, 보고서 HTML/PDF OK. ⚠️ 준비 세션을 재사용하면 이전 run의 개선이 남아 있어(성공 시 롤백 없음) baseline이 "개선 전"이 아님 — run 11의 `improvement_changes`가 `[]`인 이유. 깨끗한 전후 비교는 새 준비 세션으로. 구 앱 행은 `observe_service`가 빈 값이라 다중 Service 앱은 샘플 재등록(동명 앱 갱신)으로 채울 것.
- [x] **샘플 2종 "약점 있는 기준선" 재설계 — 개선 효과가 판정·R지수·보고서에 드러나게** (09/06, pytest 253): 두 샘플 모두 `replicas: 2` + PodChaos `mode: one`이라 기준선부터 오류 0%여서 어떤 개선도 효과가 안 보였음. nginx=`replicas 1`·readinessProbe 10s/10s · order-resilience-lab=payment-api `replicas 1`(단일 장애점) + app.py 목업 회복 로직 `UPSTREAM_RETRIES`(재시도)·`OPTIONAL_UPSTREAMS`(degraded 200) env(기본 꺼짐, checkout/order-api에 선언 → `deployment_env`로 켤 수 있음). 🐛 order-api `UPSTREAMS`가 flow 매핑 안 쉼표로 잘려 **라이브에서도 catalog-api만 호출**하고 있었음(payment 장애가 주문에 무영향이던 근본 원인) → 따옴표. Stub `propose_improvements`를 manifest 약점 기반 결정적 제안(replicas<2→3 · probe 주기>3s→2s/없으면 추가 · 대상을 부르는 워크로드 `UPSTREAM_RETRIES` 0→2 · 채움 preStop)으로 교체. 단독 실험(2단계)도 후보 `target_workload`의 matchLabels로 주입(`routers/experiments.py`, 이전엔 ns 전체라 무관한 파드가 죽음). 회귀 final 뒤 개선 **역순 롤백**(`regression._rollback_improvements`, 세션 재사용 시 baseline 오염 방지 — 보고서엔 전후 유지). 라이브(`claude`, 세션 10·11 신규): nginx HYP-14 pod-kill → 제안(replicas 2·probe 단축·resources) 2건 승인 → ScenarioRun 13 **failed(오류 33%·Ready 0, R 43.3 C) → passed(0%, R 99.5 A)**. order-resilience-lab HYP-13 payment-api pod-kill → 제안(payment replicas 2·order-api UPSTREAM_RETRIES 2·DEPENDENCY_HEALTHCHECKS 0) 2건 승인 → ScenarioRun 12 오류 16.7%→0%, R 97.3→98.6(pod-kill 원샷이라 기준선도 20% 임계 안 → passed/passed, `improved: true`). 롤백 후 클러스터 replicas 1·env 0 복귀 확인, 보고서 HTML/PDF에 변경 표·문장 반영.
- [ ] **Slice 5 — 결과/R지수**: baseline/fault/recovery 계산 + 추이·iteration 히스토리 (AI 루프 자체는 Phase 3)
- [ ] **DB Supabase 전환** (보고서 확정): up/down 시 EC2 로컬 SQLite 이력 유실 → 관리형 PostgreSQL로. 스키마 초안 `docs/supabase_schema.sql`
- [ ] **설정 페이지**: LLM/목표R/예산 저장 + 외부 통합 키

### 라이브 검증 시 선결사항 (Slice 2 후속 + Slice 3)

- **RBAC** — 대시보드 K8s 신원에 추가 필요: `sut_namespace` `secrets` create/update · `apps/deployments` patch(재배포) · `chaos-mesh.org` CRD create/get/delete(카오스) · `argo_namespace` `workflows` patch(빌드 중지)
- 라이브 기동 시 `argo/apply.sh`로 WorkflowTemplate 적용 필수
- Chaos Mesh 파드 Running 확인(`kubectl get pods -n chaos-mesh`) + 주입 대상 파드 존재
- 마이그레이션 없음: EC2 **비파괴** 재기동 시 구 `chaoslab.db`에 새 컬럼 없어 깨짐 → 재기동 전 DB 삭제(파괴 재생성이면 무해). 09/05 `scenario_runs.hypothesis_run_id`는 `database._upgrade_scenario_runs`가 ALTER로 보완하므로 구 DB 삭제 불필요.
- ⚠️ **`~/Documents/Iac-aws`의 git은 iCloud 오염**(HEAD.lock이 삭제해도 부활 → 커밋 불가). **terraform 상태·GitOps 클론의 단일 진실원천은 `~/dev/Iac-aws`** (2026-08-13 이후) — **up.sh/down.sh는 반드시 `~/dev/Iac-aws`에서 실행** (Documents 쪽 상태 파일은 리소스 0으로 낡음 → 거기서 down.sh 하면 아무것도 안 지워짐)
- Prometheus/Loki 접근은 EC2 SSH 터널보다 **로컬 `kubectl port-forward`가 안정적** (svc/kube-prometheus-stack-prometheus 9090, svc/loki 3100 — monitoring ns)
- 부띠끄 대상 검증 시 `.env`의 `SUT_NAMESPACE=online-boutique`는 **임시** — 정상 플로우(앱 등록·빌드)는 `sut`로 되돌릴 것. 부띠끄는 generic-app 배포가 아니라 VS/DR이 없어 핸드오프 `istio_config`가 빈 문자열(계약 허용)

## 참조 / 컨벤션

- 스펙 `../Iac-aws/docs/phase2-dashboard.md` · 목업 `../Iac-aws/docs/graduation-dashboard-mockup.html` · 중간보고서 `docs/*.pdf`
- 설계/계획 문서: `docs/superpowers/specs/`·`plans/` (`YYYY-MM-DD-이름.md`, 슬라이스 작업 전 설계부터)
- 커밋: ✨기능 🐛버그 ♻️리팩 🔧설정 📝문서 ✅테스트 🔥삭제 · 파일단위 원자적
