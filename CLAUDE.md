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
pytest -q                        # 89 통과
```
`.env`는 `cp .env.example .env`면 충분(기본 `USE_REAL_SERVICES=false`=전부 Stub → 클러스터·AWS 없이 개발/테스트). 라이브 연동 값(ECR_REGISTRY·GITHUB_TOKEN 등)은 팀 내 개인 전달. `chaoslab.db`는 런타임 생성·gitignore.

## 진행 현황

- [x] **Slice 1 — 뼈대**: 6페이지 UI·HTMX 네비·SQLite/seed·Stub·SSE 배선
- [x] **Slice 2 — 빌드/배포** (라이브 검증 완료): 앱 등록→`_bootstrap`(ECR+ArgoCD App+values.yaml, 평문 env는 values·시크릿은 K8s Secret 직접 apply)→Kaniko 빌드→ECR→ArgoCD sync. 빌드 이력 모달·빌드 SSE·healthPath 유무 따라 httpGet/tcpSocket probe·카드 액션 4종(재빌드/재배포=rollout restart/배포중지=replicas 0/빌드중지=Argo shutdown). ⚠️ 시크릿 **값만** 바꿔 재등록하면 values diff 없어 sync 안 됨 → "재배포" 버튼이 해법.
- [x] **Slice 3 — 카오스** (구현 완료, stub 테스트만·라이브 미검증): 실험 폼→Chaos Mesh CRD 3종(network-delay·pod-kill·cpu-stress), `chaos_specs` 범위검증(latency 10–10000ms·cpu 1–100%·duration 30–1800s), 앱당 1개(409), `_watch_experiment`(duration→회복 확인→CRD 삭제→completed)·중지·SSE.
- [ ] **Slice 4 — 모니터링**: `RealPrometheus`(RED)·`RealLoki`(로그)·`RealK8s`(노드/Pod/컴포넌트) 실조회 + 차트 실데이터·SSE 갱신
- [ ] **Slice 5 — 결과/R지수**: baseline/fault/recovery 계산 + 추이·iteration 히스토리 (AI 루프 자체는 Phase 3)
- [ ] **DB Supabase 전환** (보고서 확정): up/down 시 EC2 로컬 SQLite 이력 유실 → 관리형 PostgreSQL로. 스키마 초안 `docs/supabase_schema.sql`
- [ ] **설정 페이지**: LLM/목표R/예산 저장 + 외부 통합 키

### 라이브 검증 시 선결사항 (Slice 2 후속 + Slice 3)

- **RBAC** — 대시보드 K8s 신원에 추가 필요: `sut_namespace` `secrets` create/update · `apps/deployments` patch(재배포) · `chaos-mesh.org` CRD create/get/delete(카오스) · `argo_namespace` `workflows` patch(빌드 중지)
- 라이브 기동 시 `argo/apply.sh`로 WorkflowTemplate 적용 필수
- Chaos Mesh 파드 Running 확인(`kubectl get pods -n chaos-mesh`) + 주입 대상 파드 존재
- 마이그레이션 없음: EC2 **비파괴** 재기동 시 구 `chaoslab.db`에 새 컬럼 없어 깨짐 → 재기동 전 DB 삭제(파괴 재생성이면 무해)

## 참조 / 컨벤션

- 스펙 `../Iac-aws/docs/phase2-dashboard.md` · 목업 `../Iac-aws/docs/graduation-dashboard-mockup.html` · 중간보고서 `docs/*.pdf`
- 설계/계획 문서: `docs/superpowers/specs/`·`plans/` (`YYYY-MM-DD-이름.md`, 슬라이스 작업 전 설계부터)
- 커밋: ✨기능 🐛버그 ♻️리팩 🔧설정 📝문서 ✅테스트 🔥삭제 · 파일단위 원자적
