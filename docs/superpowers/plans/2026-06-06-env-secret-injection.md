# env/secret 주입 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** SUT 앱 등록 시 env/secret을 입력받아, 비밀 아님은 gitops values.yaml로, 비밀은 K8s Secret으로 주입해 컨테이너가 설정을 주입받게 한다(이미지에 굽지 않음).

**Architecture:** 등록폼 → `App.env_vars`(JSON 컬럼, 단일 진실원천) → `_bootstrap`이 DB에서 읽어 `split_env`로 평문/비밀 분리 → 평문은 `GitOpsService`(values.yaml), 비밀은 `K8sService.apply_env_secret`(클러스터 직접). generic-app 차트가 `env`/`envFrom`으로 렌더. 편집 = 재등록(upsert).

**Tech Stack:** FastAPI · SQLAlchemy 2.0(SQLite) · Jinja/HTMX · vanilla JS · kubernetes-py · Helm(Iac-aws generic-app)

> **선결 메모:** 로컬 `chaoslab.db`는 기존 테이블에 `env_vars` 컬럼이 없다. SQLAlchemy `create_all`은 ALTER 안 함 → 실행 전 로컬 `chaoslab.db` 삭제(런타임 재생성·gitignore). 테스트는 in-memory라 영향 없음.

---

### Task 1: `App.env_vars` JSON 컬럼

**Files:**
- Modify: `app/db/models.py:13-29` (App 모델)
- Test: `tests/test_models.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_models.py`:
```python
"""App.env_vars JSON 컬럼 — 등록 시 env/secret 보관."""
from app.db.models import App


def test_app_has_env_vars_default_empty(db_session):
    app = App(name="demo", repo_url="https://github.com/x/demo", framework="fastapi")
    db_session.add(app)
    db_session.commit()
    assert app.env_vars == []


def test_app_env_vars_roundtrip(db_session):
    rows = [{"key": "DB_HOST", "value": "mysql", "is_secret": False},
            {"key": "JWT_SECRET", "value": "s3cr3t", "is_secret": True}]
    app = App(name="demo2", repo_url="https://github.com/x/d2", framework="spring",
              env_vars=rows)
    db_session.add(app)
    db_session.commit()
    db_session.refresh(app)
    assert app.env_vars[1]["key"] == "JWT_SECRET"
    assert app.env_vars[1]["is_secret"] is True
```

`tests/conftest.py`에 `db_session` 픽스처 추가(기존 in-memory 엔진 재사용):
```python
@pytest.fixture
def db_session():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    try:
        yield s
    finally:
        s.close()
```

- [ ] **Step 2: 실패 확인**

Run: `cd /Users/taeyunemacbook/Documents/chaoslab && source .venv/bin/activate && pytest tests/test_models.py -v`
Expected: FAIL — `App`에 `env_vars` 없음 (`TypeError: 'env_vars' is an invalid keyword argument`)

- [ ] **Step 3: 컬럼 추가**

`app/db/models.py` App 모델, `created_at` 줄 위에 추가:
```python
    env_vars: Mapped[list] = mapped_column(JSON, default=list)
```
(`JSON`은 이미 import됨.)

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_models.py -v`
Expected: PASS (2개)

- [ ] **Step 5: 커밋**

```bash
git add app/db/models.py tests/test_models.py tests/conftest.py
git commit -m "✨ App.env_vars JSON 컬럼 — env/secret 보관"
```

---

### Task 2: Protocol 시그니처 (interfaces)

**Files:**
- Modify: `app/services/interfaces.py:27-34` (GitOpsService), `:57-66` (K8sService)

- [ ] **Step 1: EnvVar 타입 + 시그니처 변경**

`app/services/interfaces.py` 상단 import 아래에 추가:
```python
from typing import Protocol, TypedDict


class EnvVar(TypedDict):
    key: str
    value: str
    is_secret: bool
```
(기존 `from typing import Protocol` 줄을 위 형태로 교체.)

`GitOpsService.bootstrap_app` 시그니처 교체:
```python
class GitOpsService(Protocol):
    def bootstrap_app(self, name: str, repo_url: str, framework: str,
                      env: dict[str, str], secret_name: str) -> None:
        """ECR 레포 + ArgoCD Application + values.yaml(평문 env·secretName 포함) 커밋/푸시."""
        ...

    def update_image_tag(self, name: str, image: str) -> None:
        """gitops values.yaml 의 image를 갱신하고 커밋/푸시 (= 배포 트리거)."""
        ...
```

`K8sService`에 메서드 추가(맨 위에):
```python
class K8sService(Protocol):
    def apply_env_secret(self, namespace: str, name: str, data: dict[str, str]) -> None:
        """앱 시크릿을 K8s Secret(Opaque)으로 생성/갱신 (git에 안 들어감)."""
        ...

    def nodes(self) -> list[dict]:
        ...
    # (pods/components 기존 그대로)
```

- [ ] **Step 2: import 깨짐 없는지 빠른 확인**

Run: `python -c "import app.services.interfaces"`
Expected: 에러 없음

- [ ] **Step 3: 커밋**

```bash
git add app/services/interfaces.py
git commit -m "✨ GitOpsService.bootstrap_app(env/secret_name) + K8sService.apply_env_secret 계약"
```

---

### Task 3: Stub 시그니처 맞춤

**Files:**
- Modify: `app/services/stubs.py:13-18` (StubGitOps), `:39-56` (StubK8s)

- [ ] **Step 1: StubGitOps.bootstrap_app 시그니처 교체**

`app/services/stubs.py` StubGitOps:
```python
class StubGitOps:
    def bootstrap_app(self, name: str, repo_url: str, framework: str,
                      env: dict, secret_name: str) -> None:
        return None

    def update_image_tag(self, name: str, image: str) -> None:
        return None
```

- [ ] **Step 2: StubK8s에 apply_env_secret 추가** (class 맨 위 메서드로)

```python
class StubK8s:
    def apply_env_secret(self, namespace: str, name: str, data: dict) -> None:
        return None

    def nodes(self) -> list[dict]:
        # (기존 그대로)
```

- [ ] **Step 3: 기존 테스트 깨짐 없는지**

Run: `pytest tests/test_real_helpers.py -q`
Expected: PASS (시그니처 변경은 stub 모드 라우트에 아직 영향 없음 — 다음 태스크에서 호출부 수정)

- [ ] **Step 4: 커밋**

```bash
git add app/services/stubs.py
git commit -m "✨ Stub: GitOps/K8s env·secret 시그니처 맞춤 (no-op)"
```

---

### Task 4: gitops 순수 헬퍼 (split_env, render env/secret) + RealGitOps

**Files:**
- Modify: `app/services/real/gitops.py:63-75` (render_values_yaml), `:120-136` (bootstrap_app), 헬퍼 추가
- Test: `tests/test_real_helpers.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_real_helpers.py` 하단에 추가(import에 `split_env` 포함):
```python
from app.services.real.gitops import split_env  # 기존 import 블록에 추가


def test_split_env_separates_secret():
    rows = [{"key": "DB_HOST", "value": "mysql", "is_secret": False},
            {"key": "JWT", "value": "x", "is_secret": True},
            {"key": "", "value": "skip", "is_secret": False}]  # 빈 키 무시
    plain, secret = split_env(rows)
    assert plain == {"DB_HOST": "mysql"}
    assert secret == {"JWT": "x"}


def test_render_values_yaml_with_env_and_secret():
    text = render_values_yaml("demo", "reg/demo:abc12345", 8080, "/healthz",
                              env={"DB_HOST": "mysql:3306"}, secret_name="demo-env")
    assert 'DB_HOST: "mysql:3306"' in text
    assert "secretName: demo-env" in text
    assert "env:" in text


def test_render_values_yaml_no_env_omits_blocks():
    text = render_values_yaml("demo", "reg/demo:abc12345", 8080, "/healthz")
    assert "env:" not in text
    assert "secretName" not in text


def test_set_image_in_values_preserves_env():
    before = render_values_yaml("demo", "reg/demo:placeholder", 8080, "/healthz",
                                env={"DB_HOST": "mysql"}, secret_name="demo-env")
    after = set_image_in_values(before, "reg/demo:newsha99")
    assert "image: reg/demo:newsha99" in after
    assert 'DB_HOST: "mysql"' in after
    assert "secretName: demo-env" in after
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_real_helpers.py -v -k "split_env or with_env or omits or preserves"`
Expected: FAIL — `ImportError: cannot import name 'split_env'` / `render_values_yaml() got unexpected keyword 'env'`

- [ ] **Step 3: 헬퍼 구현**

`app/services/real/gitops.py`, `derive_app_name` 아래에 추가:
```python
def split_env(env_vars: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """[{key,value,is_secret}] → (평문 {K:V}, 비밀 {K:V}). 빈 키는 무시."""
    plain: dict[str, str] = {}
    secret: dict[str, str] = {}
    for e in env_vars or []:
        key = (e.get("key") or "").strip()
        if not key:
            continue
        (secret if e.get("is_secret") else plain)[key] = e.get("value", "")
    return plain, secret


def _yaml_quote(v: str) -> str:
    """env 값을 안전한 더블쿼트 스칼라로 (콜론·슬래시·특수문자 포함 대비)."""
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'
```

`render_values_yaml` 함수 전체 교체:
```python
def render_values_yaml(name: str, image: str, port: int, health_path: str,
                       env: dict[str, str] | None = None, secret_name: str = "") -> str:
    lines = [f"name: {name}", f"image: {image}", f"port: {port}",
             f"healthPath: {health_path}", "replicas: 1"]
    if env:
        lines.append("env:")
        lines += [f"  {k}: {_yaml_quote(v)}" for k, v in env.items()]
    if secret_name:
        lines.append(f"secretName: {secret_name}")
    lines += ["istio:", "  enabled: true", "  timeout: 3s", "  retries:",
              "    attempts: 2", "    perTryTimeout: 1s"]
    return "\n".join(lines) + "\n"
```

`RealGitOps.bootstrap_app` 시그니처/본문 교체(평문 env·secret_name을 values.yaml에 기록; 비밀 apply는 라우터가 K8s로):
```python
    def bootstrap_app(self, name: str, repo_url: str, framework: str,
                      env: dict[str, str], secret_name: str) -> None:
        self._ensure_ecr_repo(name)
        port, health = framework_defaults(framework)
        placeholder = f"{self.s.ecr_registry}/{name}:placeholder"

        app_file = self.repo / "argocd" / "apps" / f"{name}.yaml"
        values_file = self.repo / "gitops" / "apps" / name / "values.yaml"
        app_file.parent.mkdir(parents=True, exist_ok=True)
        values_file.parent.mkdir(parents=True, exist_ok=True)
        app_file.write_text(
            render_application_yaml(name, self.s.iac_aws_repo_url, self.s.sut_namespace)
        )
        values_file.write_text(
            render_values_yaml(name, placeholder, port, health, env, secret_name)
        )

        self._git("add", "argocd/apps", "gitops/apps")
        self._git("commit", "-m", f"feat: register {name}")
        self._push()
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_real_helpers.py -v`
Expected: PASS (기존 + 신규 전부; `test_render_values_yaml_roundtrip` 4-인자 호출도 기본값으로 통과)

- [ ] **Step 5: 커밋**

```bash
git add app/services/real/gitops.py tests/test_real_helpers.py
git commit -m "✨ split_env + render_values_yaml env/secret 블록 + RealGitOps 반영"
```

---

### Task 5: RealK8s (시크릿 apply)

**Files:**
- Create: `app/services/real/k8s.py`

- [ ] **Step 1: 파일 작성** (RealBuilder의 `_api` 패턴 재사용, CoreV1Api)

`app/services/real/k8s.py`:
```python
"""RealK8s — 클러스터 직접 쓰기 (운영, use_real_services=true).

Slice 2 범위: apply_env_secret만. nodes/pods/components는 Slice 4에서 추가.
k8s SDK는 메서드 안에서 lazy import → stub/테스트는 의존성 불필요.
"""
from __future__ import annotations


class RealK8s:
    def __init__(self, settings):
        self.s = settings

    def _api(self):
        from kubernetes import client, config  # lazy

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        return client.CoreV1Api()

    def apply_env_secret(self, namespace: str, name: str, data: dict[str, str]) -> None:
        """Opaque Secret 생성, 이미 있으면 교체(idempotent)."""
        from kubernetes import client
        from kubernetes.client.rest import ApiException

        api = self._api()
        body = client.V1Secret(
            metadata=client.V1ObjectMeta(name=name),
            string_data={str(k): str(v) for k, v in data.items()},
            type="Opaque",
        )
        try:
            api.create_namespaced_secret(namespace=namespace, body=body)
        except ApiException as e:
            if e.status == 409:
                api.replace_namespaced_secret(name=name, namespace=namespace, body=body)
            else:
                raise
```

- [ ] **Step 2: import 확인**

Run: `python -c "import app.services.real.k8s"`
Expected: 에러 없음 (kubernetes는 lazy라 import 시점엔 불필요)

- [ ] **Step 3: 커밋**

```bash
git add app/services/real/k8s.py
git commit -m "✨ RealK8s.apply_env_secret — Opaque Secret 생성/교체 (idempotent)"
```

---

### Task 6: deps make_k8s 토글

**Files:**
- Modify: `app/deps.py:44-49`

- [ ] **Step 1: make_k8s 추가 + get_k8s 위임**

`app/deps.py`에서 `get_k8s` 교체 + 위에 `make_k8s` 추가:
```python
def make_k8s() -> interfaces.K8sService:
    if settings.use_real_services:
        from app.services.real.k8s import RealK8s  # lazy: k8s SDK
        return RealK8s(settings)
    return stubs.StubK8s()


def get_k8s() -> interfaces.K8sService:
    return make_k8s()
```

- [ ] **Step 2: 확인**

Run: `python -c "from app.deps import make_k8s; print(type(make_k8s()).__name__)"`
Expected: `StubK8s`

- [ ] **Step 3: 커밋**

```bash
git add app/deps.py
git commit -m "✨ deps.make_k8s — Stub↔RealK8s 한 줄 토글"
```

---

### Task 7: 라우터 — env_json 파싱·upsert·_bootstrap DB 읽기

**Files:**
- Modify: `app/routers/apps.py:31-68` (register_app, _bootstrap), import
- Test: `tests/test_apps.py`

- [ ] **Step 1: 실패 테스트 추가**

`tests/test_apps.py` 하단에 추가:
```python
import json

from app.db.repositories import AppRepository
from app.routers.apps import parse_env_json


def test_parse_env_json_normalizes():
    raw = json.dumps([
        {"key": "DB_HOST", "value": "mysql", "is_secret": False},
        {"key": "  ", "value": "skip", "is_secret": False},   # 빈 키 제거
        {"key": "JWT", "value": "x", "is_secret": True},
    ])
    out = parse_env_json(raw)
    assert out == [
        {"key": "DB_HOST", "value": "mysql", "is_secret": False},
        {"key": "JWT", "value": "x", "is_secret": True},
    ]


def test_parse_env_json_broken_returns_empty():
    assert parse_env_json("not json") == []
    assert parse_env_json("") == []


def test_register_app_stores_env_vars(client):
    resp = client.post("/apps", data={
        "repo_url": "https://github.com/foo/env-svc", "framework": "spring",
        "health_path": "/actuator/health", "port": "8080",
        "env_json": json.dumps([{"key": "DB_HOST", "value": "mysql", "is_secret": False}]),
    })
    assert resp.status_code == 200
    # 직접 DB 확인 (override된 세션 재사용)
    from app.main import app as fastapi_app
    from app.db.database import get_session
    gen = fastapi_app.dependency_overrides[get_session]()
    session = next(gen)
    try:
        rec = next(a for a in AppRepository(session).list_all() if a.name == "env-svc")
        assert rec.env_vars == [{"key": "DB_HOST", "value": "mysql", "is_secret": False}]
    finally:
        gen.close()


def test_reregister_replaces_env_vars(client):
    base = {"repo_url": "https://github.com/foo/up-svc", "framework": "spring",
            "health_path": "/h", "port": "8080"}
    client.post("/apps", data={**base, "env_json": json.dumps(
        [{"key": "A", "value": "1", "is_secret": False}])})
    client.post("/apps", data={**base, "env_json": json.dumps(
        [{"key": "B", "value": "2", "is_secret": True}])})
    from app.main import app as fastapi_app
    from app.db.database import get_session
    gen = fastapi_app.dependency_overrides[get_session]()
    session = next(gen)
    try:
        rec = next(a for a in AppRepository(session).list_all() if a.name == "up-svc")
        assert rec.env_vars == [{"key": "B", "value": "2", "is_secret": True}]
    finally:
        gen.close()
```

- [ ] **Step 2: 실패 확인**

Run: `pytest tests/test_apps.py -v`
Expected: FAIL — `ImportError: cannot import name 'parse_env_json'` 및 신규 테스트 실패

- [ ] **Step 3: 라우터 구현**

`app/routers/apps.py` import에 추가:
```python
import json
from app.deps import get_app_count, make_builder, make_gitops, make_k8s
from app.services.real.gitops import derive_app_name, split_env  # 순수 함수
```

`parse_env_json` 추가(파일 상단, `router = APIRouter()` 아래):
```python
def parse_env_json(raw: str) -> list[dict]:
    """env_json(폼) → [{key,value,is_secret}] 정규화. 깨진 입력은 빈 리스트."""
    try:
        data = json.loads(raw or "[]")
    except (ValueError, TypeError):
        return []
    out: list[dict] = []
    if isinstance(data, list):
        for e in data:
            if isinstance(e, dict) and (e.get("key") or "").strip():
                out.append({"key": e["key"].strip(),
                            "value": e.get("value", ""),
                            "is_secret": bool(e.get("is_secret"))})
    return out
```

`register_app` 전체 교체(upsert + env_json):
```python
@router.post("/apps")
def register_app(
    request: Request,
    background: BackgroundTasks,
    repo_url: str = Form(...),
    framework: str = Form(...),
    health_path: str = Form("/healthz"),
    port: int = Form(8080),
    env_json: str = Form("[]"),
    session: Session = Depends(get_session),
):
    name = derive_app_name(repo_url)
    env_vars = parse_env_json(env_json)
    repo = AppRepository(session)
    existing = next((a for a in repo.list_all() if a.name == name), None)
    if existing is None:
        repo.create(
            name=name, repo_url=repo_url, framework=framework,
            health_path=health_path, port=port,
            namespace=settings.sut_namespace, status="registering",
            env_vars=env_vars,
        )
    else:
        existing.repo_url = repo_url
        existing.framework = framework
        existing.health_path = health_path
        existing.port = port
        existing.env_vars = env_vars
        existing.status = "registering"
        session.commit()
    background.add_task(_bootstrap, name)
    return _apps_response(request, session)
```

`_bootstrap` 전체 교체(DB에서 env 읽고 K8s/GitOps 호출):
```python
def _bootstrap(name: str) -> None:
    """DB env 기반: 비밀→K8s Secret, 평문→values.yaml. 완료 시 status 갱신."""
    gitops = make_gitops()
    k8s = make_k8s()
    s = SessionLocal()
    try:
        app = next((a for a in AppRepository(s).list_all() if a.name == name), None)
        if app is None:
            return
        plain, secret = split_env(app.env_vars or [])
        secret_name = f"{name}-env" if secret else ""
        try:
            if secret:
                k8s.apply_env_secret(app.namespace, secret_name, secret)
            gitops.bootstrap_app(name, app.repo_url, app.framework, plain, secret_name)
            status = "ready"
        except Exception:
            status = "register-failed"
        app.status = status
        s.commit()
    finally:
        s.close()
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_apps.py -v`
Expected: PASS (기존 3개 + 신규 4개)

- [ ] **Step 5: 커밋**

```bash
git add app/routers/apps.py tests/test_apps.py
git commit -m "✨ 등록 env_json 파싱·upsert + _bootstrap DB 읽어 K8s/GitOps 주입"
```

---

### Task 8: UI — 등록 다이얼로그 env 섹션 + app.js 에디터

**Files:**
- Modify: `app/templates/pages/apps.html:157-165` (Port 행 아래에 env 섹션 + hidden 필드)
- Modify: `app/static/js/app.js` (env 에디터 헬퍼)

- [ ] **Step 1: apps.html에 env 섹션 추가**

`app/templates/pages/apps.html`, Port 입력 `<div class="grid grid-cols-2 gap-3">...</div>` 블록(157-160줄) **바로 아래**에 삽입:
```html
      <div>
        <div class="flex items-center justify-between mb-1.5">
          <label class="text-xs font-bold block">환경변수 / 시크릿 <span style="color: var(--muted-foreground);">(선택)</span></label>
          <button type="button" class="text-xs font-bold" style="color: var(--primary);" onclick="envAddRow()">+ 추가</button>
        </div>
        <div id="env-rows" class="space-y-2"></div>
        <details class="mt-2">
          <summary class="text-xs cursor-pointer" style="color: var(--muted-foreground);">.env 붙여넣기</summary>
          <textarea id="env-paste" rows="3" class="tds-input mono text-xs mt-1.5" placeholder="KEY=VALUE 줄단위"></textarea>
          <button type="button" class="tds-btn-muted text-xs mt-1.5" onclick="envParsePaste()">적용</button>
        </details>
        <p class="text-xs mt-1.5" style="color: var(--muted-foreground);">키에 TOKEN/SECRET/PASSWORD/KEY 포함 시 🔒시크릿으로 자동 표시(K8s Secret으로 주입, git 미저장).</p>
        <input type="hidden" name="env_json" id="env-json" value="[]" />
      </div>
```

- [ ] **Step 2: app.js에 env 에디터 추가**

`app/static/js/app.js` 끝에 추가:
```javascript
// ── 등록 폼 env/secret 에디터 (vanilla, HTMX 스왑 안전: 위임 + onclick 전역) ──
const ENV_SECRET_RE = /(TOKEN|SECRET|PASSWORD|KEY)/i;

function envRowHtml(key = '', value = '', secret = false) {
  return `<div class="env-row flex items-center gap-2">
    <input class="env-key tds-input mono text-xs" placeholder="KEY" value="${escapeAttr(key)}" />
    <input class="env-val tds-input mono text-xs" placeholder="value" value="${escapeAttr(value)}" />
    <label class="flex items-center gap-1 text-xs whitespace-nowrap" title="시크릿">
      <input type="checkbox" class="env-secret" ${secret ? 'checked' : ''} />🔒
    </label>
    <button type="button" class="tds-btn-muted text-xs px-2" onclick="this.closest('.env-row').remove(); envSync()">✕</button>
  </div>`;
}

function escapeAttr(s) { return String(s).replace(/&/g, '&amp;').replace(/"/g, '&quot;').replace(/</g, '&lt;'); }

function envAddRow(key = '', value = '', secret = false) {
  const box = document.getElementById('env-rows');
  if (!box) return;
  box.insertAdjacentHTML('beforeend', envRowHtml(key, value, secret));
  envSync();
}

function envParsePaste() {
  const ta = document.getElementById('env-paste');
  if (!ta) return;
  ta.value.split('\n').forEach((line) => {
    const i = line.indexOf('=');
    if (i < 1) return;
    const key = line.slice(0, i).trim();
    const val = line.slice(i + 1).trim();
    if (key) envAddRow(key, val, ENV_SECRET_RE.test(key));
  });
  ta.value = '';
}

function envSync() {
  const json = document.getElementById('env-json');
  if (!json) return;
  const rows = [...document.querySelectorAll('#env-rows .env-row')].map((r) => ({
    key: r.querySelector('.env-key').value.trim(),
    value: r.querySelector('.env-val').value,
    is_secret: r.querySelector('.env-secret').checked,
  })).filter((e) => e.key);
  json.value = JSON.stringify(rows);
}

// 행 입력 시마다 hidden 동기화 + 키 입력 시 시크릿 자동 감지(미수정 시)
document.addEventListener('input', (e) => {
  if (!e.target.closest('#env-rows')) return;
  if (e.target.classList.contains('env-key')) {
    const row = e.target.closest('.env-row');
    const cb = row.querySelector('.env-secret');
    if (!cb.dataset.touched) cb.checked = ENV_SECRET_RE.test(e.target.value);
  }
  envSync();
});
document.addEventListener('change', (e) => {
  if (e.target.classList && e.target.classList.contains('env-secret')) {
    e.target.dataset.touched = '1';  // 수동 토글 후엔 자동감지 중단
    envSync();
  }
});
```

- [ ] **Step 3: 수동 확인 (서버 기동)**

Run: `uvicorn app.main:app --reload` 후 브라우저 `localhost:8000/apps` → "새 앱 등록" → "+ 추가"로 행 추가, `.env` 붙여넣기 적용, `JWT_SECRET` 입력 시 🔒 자동 체크 확인. 등록 제출 후 앱 목록 정상 렌더 확인.
Expected: 행 추가/삭제·자동 시크릿 감지·등록 동작. 콘솔 에러 없음.

- [ ] **Step 4: 회귀 테스트**

Run: `pytest -q`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add app/templates/pages/apps.html app/static/js/app.js
git commit -m "✨ 등록 폼 env/secret 에디터 (행 추가·.env 붙여넣기·시크릿 자동감지)"
```

---

### Task 9: Iac-aws generic-app 차트 — env/envFrom

**Files:**
- Modify: `/Users/taeyunemacbook/Documents/Iac-aws/helm/generic-app/templates/deployment.yaml`
- Modify: `/Users/taeyunemacbook/Documents/Iac-aws/helm/generic-app/values.yaml`

> **주의:** 별도 레포(Iac-aws). 커밋은 chaoslab과 분리. 이 태스크는 chaoslab 테스트와 무관(라이브에서 검증).

- [ ] **Step 1: values.yaml 기본값 추가**

`/Users/taeyunemacbook/Documents/Iac-aws/helm/generic-app/values.yaml`, `replicas: 1` 줄 아래에 추가:
```yaml

# 앱별 env(평문) / secret(K8s Secret 참조). gitops/apps/{app}/values.yaml 가 override.
env: {}            # { KEY: "value" }
secretName: ""     # 비어있으면 envFrom 생략
```

- [ ] **Step 2: deployment.yaml에 env/envFrom 렌더**

`/Users/taeyunemacbook/Documents/Iac-aws/helm/generic-app/templates/deployment.yaml`, container의 `ports:` 블록 **위**(`image:` 줄 아래)에 삽입:
```yaml
          {{- if .Values.env }}
          env:
            {{- range $k, $v := .Values.env }}
            - name: {{ $k }}
              value: {{ $v | quote }}
            {{- end }}
          {{- end }}
          {{- if .Values.secretName }}
          envFrom:
            - secretRef:
                name: {{ .Values.secretName }}
          {{- end }}
```

- [ ] **Step 3: Helm 렌더 검증 (helm 설치돼 있으면)**

Run: `helm template /Users/taeyunemacbook/Documents/Iac-aws/helm/generic-app --set secretName=demo-env --set env.DB_HOST=mysql | grep -A3 -E "env:|envFrom:"`
Expected: `env:`에 `name: DB_HOST` / `envFrom:`에 `secretRef: name: demo-env` 출력. (helm 미설치면 시각 검토로 대체.)

기본값(override 없음) 렌더도 확인:
Run: `helm template /Users/taeyunemacbook/Documents/Iac-aws/helm/generic-app | grep -E "env:|envFrom:" || echo "no env/envFrom (정상)"`
Expected: env/envFrom 미출력(하위호환).

- [ ] **Step 4: Iac-aws 커밋** (해당 레포에서)

```bash
git -C /Users/taeyunemacbook/Documents/Iac-aws add helm/generic-app/templates/deployment.yaml helm/generic-app/values.yaml
git -C /Users/taeyunemacbook/Documents/Iac-aws commit -m "✨ generic-app: env/envFrom(secretRef) 렌더 — SUT 설정 주입"
```

---

### Task 10: 전체 검증 + CLAUDE.md 진행현황 갱신

**Files:**
- Modify: `CLAUDE.md` (Slice 2 후속 과제 ⭐ 체크)

- [ ] **Step 1: 전체 테스트**

Run: `cd /Users/taeyunemacbook/Documents/chaoslab && source .venv/bin/activate && pytest -q`
Expected: 전체 PASS (기존 19 + 신규)

- [ ] **Step 2: 로컬 DB 재생성 확인** (env_vars 컬럼)

Run: `rm -f chaoslab.db && python -c "from app.main import app"` 후 `uvicorn app.main:app` 기동 → `/apps` 정상.
Expected: 컬럼 누락 에러 없음.

- [ ] **Step 3: CLAUDE.md 갱신**

`CLAUDE.md`의 `⭐ 환경변수·시크릿 주입` 항목 `[ ]`→`[x]`로 바꾸고 한 줄 메모(구현 완료, 라이브 RBAC 선결 남음) 추가.

- [ ] **Step 4: 커밋**

```bash
git add CLAUDE.md
git commit -m "📝 Slice 2 후속: env/secret 주입 구현 완료 반영"
```

---

## 라이브 검증 체크리스트 (EC2/EKS, 본 플랜 이후 별도)

- [ ] 대시보드 K8s 신원에 `sut_namespace` `secrets` create/update RBAC 부여
- [ ] `USE_REAL_SERVICES=true`로 opus-backend 재등록(datasource/redis/JWT env 입력)
- [ ] `{app}-env` Secret 생성 + values.yaml `env`/`secretName` 커밋 확인
- [ ] ArgoCD sync → 파드가 env/secret 주입받아 기동(Option B healthy) 확인
