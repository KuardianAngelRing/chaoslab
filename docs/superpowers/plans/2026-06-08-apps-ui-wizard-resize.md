# Apps 탭 UI 정비 — 위저드 · 리사이즈 · 브랜치 배선 (2026-06-08)

졸과 전제: SUT 앱은 **Dockerfile을 직접 보유**. 사내 표준/자동 Dockerfile 주입 안내 제거.

## 범위 (최소 변경)

### 1. 헤더·안내 정리 — `app/templates/pages/apps.html`
- 부제(13) → 격식: "GitHub 저장소 URL 하나만 등록하면 컨테이너 이미지 빌드부터 EKS 배포까지 자동으로 진행됩니다."
- "사내 표준 안내" 박스(21–31) **삭제**.
- 모달 내 "사내 표준… Dockerfile 자동 주입" info 박스(194–197) **삭제**.
- 빈 카드 부제(114) 문구 일관 정리.

### 2. 모달 3-step 위저드 — `apps.html` + `app.js`
단일 `<form hx-post="/apps">` 유지. 3 step div show/hide, 마지막에 1회 submit.
- Step 1 — GitHub URL + 프레임워크 카드. repo_url 비면 "다음" 비활성.
- Step 2 — 브랜치(default main) + Health Path + Port.
- Step 3 — 환경변수 에디터(기존 그대로).
- 상단 스텝 인디케이터(●─●─●). `openDialog('newApp')` 시 step 1로 리셋.

### 3. 우측 가장자리 드래그 리사이즈 — `tds.css` + `app.js`
- `.dialog-card`에 우측 핸들. `max-width` 오버라이드.
- flex-center 보정: `newWidth = startWidth + 2*delta`.
- 폭은 **app.js 모듈 변수**에 저장 → HTMX 스왑 유지, 풀 리프레시 시 초기화.
- `openDialog`에서 재적용.

### 4. 브랜치 배선 — `models.py` · `apps.py`
- `App.branch` 컬럼 (default `"main"`). chaoslab.db 런타임 생성·gitignore → 마이그레이션 불필요.
- `register_app`: `branch: str = Form("main")` → create/upsert 반영.
- `build_app`: `resolve_head_sha(app.repo_url, app.branch)`.
- 테스트: register가 branch 저장하는지 1개.

## 비범위 (요청된 것만)
- 프레임워크→health/port 자동채움 등 미요청 폴리시 금지.
- ArgoCD targetRevision은 IaC 레포(main) — 무관, 미변경.
