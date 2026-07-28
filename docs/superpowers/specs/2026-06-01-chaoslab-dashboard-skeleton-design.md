# ChaosLab 대시보드 — 걷는 뼈대 (Slice 1) 설계

> **레포**: `chaoslab` (신규, FastAPI 대시보드 + Phase 3 AI 루프)
> **상위 스펙**: `Iac-aws/docs/phase2-dashboard.md` (Phase 2 전체 — 본 문서는 그 첫 슬라이스)
> **목업**: `Iac-aws/docs/graduation-dashboard-mockup.html` (ChaosLab, TDS 디자인, 2135줄)
> **작성일**: 2026-06-01

---

## 1. 배경 & 범위

Phase 2 전체(빌드/배포 A · 카오스 B · 모니터링 C · 결과/AI D · 설정 E + Iac-aws 6개 변경)는 단일 플랜으로는 너무 크다. 이 문서는 **첫 슬라이스 = "걷는 뼈대(walking skeleton)"** 만 다룬다.

### 완료 기준 (Definition of Done)
- `uvicorn app.main:app` 한 번으로 기동.
- 목업과 **동일한 비주얼**의 6개 화면이 렌더된다: `/`, `/apps`, `/experiments`, `/experiments/{id}`, `/infra`, `/settings`.
- 네비게이션은 **HTMX 부분 스왑**으로 동작하고, 직접 URL 접근/새로고침도 풀페이지로 동작한다.
- 모든 데이터는 **mock**: 우리가 소유한 도메인 데이터는 실제 SQLite + seed, 외부 시스템 호출은 인터페이스 뒤 스텁.
- light/dark 테마 토글, 탭 전환, 모달, 유저 메뉴가 동작한다.
- SSE 라이브 갱신 **배선**이 존재한다(하트비트/mock 틱).
- 라우트 스모크 / Repository / 스텁 계약 테스트가 통과한다.

### 명시적 비범위 (YAGNI — 다음 슬라이스)
실제 Kaniko/Argo 빌드, Chaos Mesh CRD 주입, 실제 Prometheus/Loki 쿼리, 실제 K8s API, AI 루프 로직, 인증, Iac-aws 변경(ECR/argocd/user_data). 이들은 각각 후속 슬라이스로 분리한다.

### 확정 결정 (Slice 1)
- (a) Slice 1에 **실제 SQLite + Repository + seed** 포함 — 데이터 모델이 확정이고 SQLite가 가벼워서 일찍 도입.
- (b) Tailwind / Chart.js / iconify는 **CDN 유지** — 목업 1:1 포팅에 가장 빠름. Tailwind 빌드 전환은 후속 과제로 메모.

---

## 2. 설계 원칙 — SOLID / DRY 의 구체적 의미

> ⚠️ 상위 CLAUDE.md의 "불필요한 추상화 금지"와 충돌하지 않도록, 이 프로젝트에서 SOLID/DRY는 다음만 의미한다:

- **SOLID** = `phase2-dashboard.md`가 이미 정의한 모듈 경계(routers / services / db / templates)를 지키고, 외부 시스템 서비스에 **깔끔한 인터페이스(Protocol)** 를 줘서 Phase 3·실연동이 라우터 수정 없이 끼워지게 하는 것. → 즉 **의존성 역전(DIP)** 이 핵심.
- **추측 추상 레이어를 미리 쌓지 않는다.** 인터페이스는 "외부 시스템 = 나중에 stub→real 교체" 경계에만 둔다. 1회성 마크업/로직은 인라인.
- **DRY** = 목업이 6번 복붙한 사이드바·반복 컴포넌트를 Jinja 상속/매크로로 1곳에 모으는 것. 단, **진짜 반복되는 것만** 매크로화.

---

## 3. 아키텍처

```
┌──────────────────────────────────────────────┐
│  EC2 — 단일 FastAPI 프로세스                    │
│   • Jinja + HTMX UI                            │
│   • 라이브 갱신 → FastAPI SSE (Slice 1: mock 틱) │
│   • SQLite (로컬 파일) — apps/builds/exp/iter    │
│   • 외부 시스템 = Protocol + Stub 구현            │
└──────┬─────────────────────────────────────────┘
       │ (Slice 1에서는 호출 안 함 — 스텁)
       ▼  EKS / Prometheus / Loki / Chaos Mesh ...
```

### 레포 구조
```
app/
├── main.py            # FastAPI 앱 생성, 라우터/정적/템플릿 마운트
├── config.py          # pydantic-settings (.env): DB 경로, K8s/PROM/LOKI URL, LLM 키
├── deps.py            # DI 와이어링 (Depends): Repository, Stub 서비스 주입
├── rendering.py       # render_page(request, template, ctx) — HX-Request 분기
├── routers/
│   ├── pages.py       # GET / /apps /experiments /experiments/{id} /infra /settings
│   ├── apps.py        # 앱 카드 목록/모달 (스텁 액션)
│   ├── experiments.py # 실험 목록/상세 탭 (스텁 액션)
│   ├── stream.py      # SSE 엔드포인트 (mock 틱)
│   └── webhook.py     # 자리만 (스텁)
├── services/
│   ├── interfaces.py  # Protocol: Builder, GitOps, Chaos, Prometheus, Loki, K8s
│   ├── stubs.py       # StubBuilder, StubChaos, ... mock 데이터 반환
│   └── agent/         # Phase 3 자리 (빈 인터페이스만)
├── db/
│   ├── database.py    # SQLite 엔진/세션
│   ├── models/        # apps, builds, experiments, agent_iterations
│   ├── repositories/  # AppRepo, BuildRepo, ExperimentRepo, IterationRepo
│   └── seed.py        # 대표 mock 행 삽입 (목업 화면 채우기)
├── templates/
│   ├── base.html              # 셸 (사이드바+헤더+테마+모달컨테이너+스크립트)
│   ├── partials/_sidebar.html # nav 1곳 정의, active_nav 변수로 활성화
│   ├── macros/components.html # kpi_card, badge, app_card, experiment_row, tab_nav
│   └── pages/                 # dashboard/apps/experiments/experiment_detail/infra/settings
└── static/
    ├── css/tds.css   # 목업 <style> 296줄 추출 = 디자인 토큰 단일 출처
    └── js/app.js     # 테마 토글, 유저 메뉴, 탭 전환, HTMX 설정, Chart 초기화 헬퍼
requirements.txt · .env.example · README.md · tests/
```

---

## 4. 템플릿 레이어 (DRY)

- `base.html`: 블록 `page_title` · `content` · `scripts`. 사이드바/헤더/모달 컨테이너/CDN 스크립트 포함.
- `partials/_sidebar.html`: nav 5항목(대시보드 / Apps[카운트] / 카오스 테스트[라이브 점] / EKS 인프라 / 설정)을 한 번만 정의. 각 페이지가 `active_nav`를 넘겨 활성 표시.
- `macros/components.html`: **반복되는 것만** — `kpi_card(icon, label, value, delta)`, `badge(text, variant)`, `app_card(app)`, `experiment_row(exp)`, `tab_nav(tabs, active)`.
- TDS 토큰/컴포넌트 CSS(296줄)는 `static/css/tds.css`로 추출. 변수: `--primary/--background/--card/...`, light/`[data-theme="dark"]` 오버라이드. 컴포넌트: `.tds-card/.tds-btn-*/.tds-input/.tds-badge/.tabs/.dialog/.progress`.

## 5. 렌더링 패턴 — HTMX 풀/부분 (SRP)

- 각 페이지 = `pages/{name}.html`(base 상속). content는 별도 파셜로 분리하거나 블록으로.
- `rendering.render_page(request, template, ctx)`:
  - `HX-Request` 헤더 있음 → **content 파셜만** 반환 (`hx-target="#main-content"`, `hx-swap="innerHTML"`).
  - 없음(직접 URL/새로고침) → **base + content 풀페이지** 반환.
- 이 분기 로직이 라우터마다 복붙되지 않도록 한 곳(헬퍼)에 둔다.
- 사이드바 nav 항목은 `hx-get` + `hx-push-url`로 URL 동기화.

## 6. 백엔드 — SOLID via 인터페이스

- **외부 시스템 서비스**(Builder/GitOps/Chaos/Prometheus/Loki/K8s)는 각각 `services/interfaces.py`의 `Protocol`로 계약 정의 + `services/stubs.py`에 `StubXxx` 구현(mock 반환).
- 라우터는 **인터페이스에만 의존**. `deps.py`에서 FastAPI `Depends`로 주입 → 후속 슬라이스에서 `RealXxx`로 교체 시 라우터 무수정.
- **우리가 소유한 데이터**(apps/builds/experiments/agent_iterations)는 실제 SQLite + Repository 패턴. mock은 `seed.py`가 대표 행으로 채움(템플릿에 하드코딩 금지).

### 데이터 모델 (SQLite — phase2 문서 기준)
| 테이블 | 주요 컬럼 |
|--------|----------|
| `apps` | name, repo_url, framework, health_path, port, namespace, image_repo, current_sha, status |
| `builds` | app_id, status, image_tag(git SHA), workflow_name, log_ref, started_at, finished_at |
| `experiments` | app_id, chaos_type, params, status, baseline/fault/recovery_metrics, baseline_r, r_index, target_r, started_at, finished_at |
| `agent_iterations` | experiment_id, iteration, observer/analyst/recommender 출력, params_before/after, r_index, verdict, llm_cost_usd |

## 7. SSE 배관 스텁

`routers/stream.py`의 `/stream` SSE 엔드포인트 + `app.js`의 EventSource 연결. Slice 1에서는 mock 틱/하트비트만 push해 라이브 갱신 배선이 존재하고 테스트 가능. 실제 이벤트 소스(빌드 진행, 실험 메트릭)는 후속 슬라이스.

## 8. 정적 자산 / 설정 / 실행

- 자산: Tailwind / Chart.js / iconify **CDN 유지**(목업 1:1). Tailwind 빌드 전환은 후속.
- `config.py`: pydantic-settings로 `.env` 읽기(DB 경로, K8s 컨텍스트, PROM/LOKI URL, LLM 키). 스텁은 대부분 미사용이나 구조는 미리 셋업.
- `.gitignore`: Iac-aws 컨벤션 정렬 — `docs/*`(설계문서 로컬 보관, `docs/assets/`만 push)·`.env`/`*.pem`/`*.key`/`kubeconfig`/`.DS_Store`/`*.db`/`CLAUDE.md`/`.omc/` 무시.
- 실행: `requirements.txt` + `.env.example` + `README`(기동법).

## 9. 테스트

- 라우트 스모크: 6개 라우트 각각 200, HX 파셜 vs 풀페이지 분기 검증.
- Repository CRUD: 각 Repo의 기본 동작.
- **스텁 계약 테스트**: 각 `StubXxx`가 대응 `Protocol`을 만족하는지(후속 `RealXxx`도 동일 계약 강제).
- 가볍게 유지 — 골격 검증 목적.

---

## 10. 후속 슬라이스 (참고 — 본 스펙 범위 아님)

1. **빌드/배포(A)** — Argo Workflows + Kaniko + ECR + GitOps push. ⚠️ cloud-hub `graduation-gitops-flow.md` + 실제 `Iac-aws/argocd/`·`terraform/` 내용에 근거해 설계할 것(요약만으로 추정 금지).
2. **카오스 수행(B)** — Chaos Mesh CRD 주입(실제 K8s).
3. **모니터링(C)** — 실제 Prometheus/Loki 쿼리 + RED 메트릭.
4. **결과/AI(D)** — R지수 계산 + Phase 3 AI 루프(`app/services/agent/`).
5. **Iac-aws 변경** — ECR repo, argocd App-of-Apps, EC2 user_data clone.
