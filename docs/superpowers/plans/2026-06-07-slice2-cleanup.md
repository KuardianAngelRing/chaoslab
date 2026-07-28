# Slice 2 마무리 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Slice 2 잔여 3건 정리 — actuator 없는 앱용 TCP probe 분기, `_bootstrap`/`_watch_build` 에러 로깅(+`_bootstrap` 단위테스트), `.env.example` 주석 정비.

**Architecture:** probe는 Iac-aws `generic-app` 차트 1파일에서 `healthPath` 유무로 httpGet/tcpSocket 분기(chaoslab 코드 무변경 — 이미 per-app healthPath 기록). 에러 로깅은 `app/routers/apps.py`에 `logging` 도입 후 2곳의 삼킴 except에 `logger.exception`. `_bootstrap`은 BackgroundTask에서 `SessionLocal`을 쓰므로 직접 호출+monkeypatch로 단위 테스트.

**Tech Stack:** FastAPI · SQLAlchemy(SQLite) · Helm(Iac-aws generic-app) · pytest(caplog)

> 커밋은 chaoslab/Iac-aws 각 레포에서 분리. 푸시는 명시 요청 시에만(이 플랜은 푸시 안 함).

---

### Task 1: `.env.example` 주석 정비

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: 인라인 주석 → 윗줄 분리**

`.env.example`의 다음 세 줄(현재 키 뒤에 인라인 주석):
```
ECR_REGISTRY=                       # <account>.dkr.ecr.ap-northeast-2.amazonaws.com (terraform output ecr_registry)
IAC_AWS_REPO_URL=https://github.com/KuardianAngelRing/Iac-aws
IAC_AWS_REPO_PATH=                  # EC2 로컬 클론 경로 (예: /home/ec2-user/Iac-aws)
GITHUB_TOKEN=                       # Iac-aws push용 (크로스레포 쓰기)
```
을 아래로 교체(주석을 각 키 위 줄로 이동, real 키는 빈 값 유지; `IAC_AWS_REPO_URL`은 값이 있으니 그대로):
```
# <account>.dkr.ecr.ap-northeast-2.amazonaws.com (terraform output ecr_registry)
ECR_REGISTRY=
IAC_AWS_REPO_URL=https://github.com/KuardianAngelRing/Iac-aws
# EC2 로컬 클론 경로 (예: /home/ec2-user/Iac-aws)
IAC_AWS_REPO_PATH=
# Iac-aws push용 (크로스레포 쓰기)
GITHUB_TOKEN=
```

- [ ] **Step 2: 복사 시뮬레이션 검증**

`.env.example`을 임시 파일로 dotenv 파싱해 real 키가 빈 값인지 확인:
Run:
```bash
cd /Users/taeyunemacbook/Documents/chaoslab && source .venv/bin/activate && python -c "
from dotenv import dotenv_values
v = dotenv_values('.env.example')
for k in ['ECR_REGISTRY','IAC_AWS_REPO_PATH','GITHUB_TOKEN']:
    print(k, '=', repr(v.get(k)))
    assert v.get(k) == '', f'{k} not empty: {v.get(k)!r}'
print('OK: real 키 모두 빈 값')
"
```
Expected: 세 키 모두 `''`, `OK: real 키 모두 빈 값`.

- [ ] **Step 3: 회귀 + 커밋**

Run: `pytest -q` → all pass (변경 무관하지만 확인).
```bash
git add .env.example
git commit -m "🔧 .env.example: 인라인 주석 윗줄 분리 (dotenv 값 오해 방지)"
```

---

### Task 2: 에러 로깅 (`_bootstrap`·`_watch_build`) + `_bootstrap` 단위테스트

**Files:**
- Modify: `app/routers/apps.py`
- Test: `tests/test_apps.py`

- [ ] **Step 1: 실패 테스트 작성** — `tests/test_apps.py` 상단 import 블록에 추가(파일 맨 위 docstring 아래, 기존 `import json` 옆):
```python
import logging

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db.database import Base
from app.db.models import App
from app.routers.apps import _bootstrap
```
그리고 파일 하단에 헬퍼+테스트 추가:
```python
class _SpyGitOps:
    def __init__(self):
        self.calls = []

    def bootstrap_app(self, name, repo_url, framework, env, secret_name):
        self.calls.append((name, repo_url, framework, env, secret_name))

    def update_image_tag(self, name, image):
        pass


class _FailGitOps(_SpyGitOps):
    def bootstrap_app(self, *a, **k):
        raise RuntimeError("push failed")


class _SpyK8s:
    def __init__(self):
        self.calls = []

    def apply_env_secret(self, namespace, name, data):
        self.calls.append((namespace, name, data))


def _engine_with_app(env_vars):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    s = Session()
    s.add(App(name="demo", repo_url="https://github.com/x/demo", framework="spring",
              namespace="sut", env_vars=env_vars, status="registering"))
    s.commit()
    s.close()
    return Session


def test_bootstrap_success_splits_and_sets_ready(monkeypatch):
    Session = _engine_with_app([
        {"key": "DB_HOST", "value": "mysql", "is_secret": False},
        {"key": "JWT", "value": "x", "is_secret": True},
    ])
    monkeypatch.setattr("app.routers.apps.SessionLocal", Session)
    gitops, k8s = _SpyGitOps(), _SpyK8s()
    monkeypatch.setattr("app.routers.apps.make_gitops", lambda: gitops)
    monkeypatch.setattr("app.routers.apps.make_k8s", lambda: k8s)

    _bootstrap("demo")

    assert k8s.calls == [("sut", "demo-env", {"JWT": "x"})]
    assert gitops.calls == [
        ("demo", "https://github.com/x/demo", "spring", {"DB_HOST": "mysql"}, "demo-env")
    ]
    s = Session()
    app = next(a for a in AppRepository(s).list_all() if a.name == "demo")
    s.close()
    assert app.status == "ready"


def test_bootstrap_failure_logs_and_sets_register_failed(monkeypatch, caplog):
    Session = _engine_with_app([{"key": "DB_HOST", "value": "mysql", "is_secret": False}])
    monkeypatch.setattr("app.routers.apps.SessionLocal", Session)
    monkeypatch.setattr("app.routers.apps.make_gitops", lambda: _FailGitOps())
    monkeypatch.setattr("app.routers.apps.make_k8s", lambda: _SpyK8s())

    with caplog.at_level(logging.ERROR):
        _bootstrap("demo")

    s = Session()
    app = next(a for a in AppRepository(s).list_all() if a.name == "demo")
    s.close()
    assert app.status == "register-failed"
    assert "bootstrap failed" in caplog.text
```
(`AppRepository`는 test_apps.py에 이미 import됨.)

- [ ] **Step 2: 실패 확인**

Run: `source .venv/bin/activate && pytest tests/test_apps.py -v -k bootstrap`
Expected: `test_bootstrap_failure_logs_and_sets_register_failed` FAIL — `caplog.text`에 "bootstrap failed" 없음(현재 로깅 없음). 성공 테스트는 통과할 수 있음(기존 동작이 이미 맞으므로) — 핵심은 실패 테스트가 로깅 부재로 실패하는 것.

- [ ] **Step 3: 로깅 구현** — `app/routers/apps.py`. 파일 상단 import에 `import logging` 추가(기존 `import time` 옆). `router = APIRouter()` 줄 아래에 추가:
```python
logger = logging.getLogger(__name__)
```

`_bootstrap`의 except 블록을 교체. 현재:
```python
        try:
            if secret:
                k8s.apply_env_secret(app.namespace, secret_name, secret)
            gitops.bootstrap_app(name, app.repo_url, app.framework, plain, secret_name)
            status = "ready"
        except Exception:
            status = "register-failed"
```
교체 후:
```python
        try:
            if secret:
                k8s.apply_env_secret(app.namespace, secret_name, secret)
            gitops.bootstrap_app(name, app.repo_url, app.framework, plain, secret_name)
            status = "ready"
        except Exception:
            logger.exception("bootstrap failed for app %s", name)
            status = "register-failed"
```

`_watch_build`의 update_image_tag except를 교체. 현재:
```python
            try:
                gitops.update_image_tag(app_name, image)
            except Exception:
                pass
```
교체 후:
```python
            try:
                gitops.update_image_tag(app_name, image)
            except Exception:
                logger.exception("deploy(update_image_tag) failed for app %s", app_name)
```

- [ ] **Step 4: 통과 확인**

Run: `pytest tests/test_apps.py -v -k bootstrap` → 2 PASS. 이어 `pytest -q` → 전체 PASS.

- [ ] **Step 5: 커밋**

```bash
git add app/routers/apps.py tests/test_apps.py
git commit -m "🐛 _bootstrap·_watch_build 삼킴 except 로깅 + _bootstrap 성공/실패 테스트"
```

---

### Task 3: Health probe — `healthPath` 비면 TCP (Iac-aws 차트)

**Files:**
- Modify: `/Users/taeyunemacbook/Documents/Iac-aws/helm/generic-app/templates/deployment.yaml`

> 별도 레포(Iac-aws). 커밋은 chaoslab과 분리. chaoslab 테스트와 무관(helm 렌더로 검증).

- [ ] **Step 1: probe 분기 구현** — `deployment.yaml`의 현재 probe 블록:
```yaml
          readinessProbe:
            httpGet:
              path: {{ .Values.healthPath }}
              port: {{ .Values.port }}
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: {{ .Values.healthPath }}
              port: {{ .Values.port }}
            initialDelaySeconds: 15
            periodSeconds: 20
```
을 아래로 교체(healthPath 있으면 httpGet, 비면 tcpSocket):
```yaml
          {{- if .Values.healthPath }}
          readinessProbe:
            httpGet:
              path: {{ .Values.healthPath }}
              port: {{ .Values.port }}
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            httpGet:
              path: {{ .Values.healthPath }}
              port: {{ .Values.port }}
            initialDelaySeconds: 15
            periodSeconds: 20
          {{- else }}
          readinessProbe:
            tcpSocket:
              port: {{ .Values.port }}
            initialDelaySeconds: 5
            periodSeconds: 10
          livenessProbe:
            tcpSocket:
              port: {{ .Values.port }}
            initialDelaySeconds: 15
            periodSeconds: 20
          {{- end }}
```

- [ ] **Step 2: helm 렌더 검증 (양 케이스)**

Run:
```bash
cd /Users/taeyunemacbook/Documents/Iac-aws
echo "--- http (기본 healthPath=/healthz) ---"
helm template helm/generic-app | grep -E "httpGet|tcpSocket|path:|readinessProbe|livenessProbe"
echo "--- tcp (healthPath 빈값) ---"
helm template helm/generic-app --set healthPath="" | grep -E "httpGet|tcpSocket|readinessProbe|livenessProbe"
```
Expected:
- http 케이스: `httpGet` + `path: /healthz` 출현, `tcpSocket` 없음.
- tcp 케이스: `tcpSocket` 출현(readiness/liveness 각 1), `httpGet` 없음.
(helm 미설치 시: 시각 검토로 if/else 블록 균형·들여쓰기 확인.)

- [ ] **Step 3: env/envFrom 회귀 확인** — 이전 작업(env 주입)이 깨지지 않았는지:
Run: `helm template helm/generic-app --set env.DB_HOST=mysql --set secretName=demo-env | grep -E "env:|envFrom:|secretRef"`
Expected: `env:`·`envFrom:`·`secretRef` 정상 출현.

- [ ] **Step 4: Iac-aws 커밋** (해당 레포)

```bash
git -C /Users/taeyunemacbook/Documents/Iac-aws add helm/generic-app/templates/deployment.yaml
git -C /Users/taeyunemacbook/Documents/Iac-aws commit -m "✨ generic-app: healthPath 비면 TCP probe (actuator 없는 앱 대응)"
```

---

### Task 4: 전체 검증 + CLAUDE.md 갱신

**Files:**
- Modify: `CLAUDE.md` (gitignore — 로컬, 커밋 안 함)

- [ ] **Step 1: 전체 테스트**

Run: `cd /Users/taeyunemacbook/Documents/chaoslab && source .venv/bin/activate && pytest -q`
Expected: 전체 PASS (기존 45 + `_bootstrap` 2 = 47).

- [ ] **Step 2: CLAUDE.md 갱신** — Slice 2 후속의 `health probe / actuator`·`_bootstrap 에러 처리`·`.env.example 정비` 세 항목을 `[x]`로 바꾸고 한 줄씩 완료 메모 추가. (gitignore라 커밋 안 함.)

- [ ] **Step 3: 마무리 메모** — 최종 요약 시: probe 분기·에러 로깅·env.example은 단위/렌더 검증 완료. 실제 actuator-없는 앱의 TCP probe 기동, 로그 출력은 up.sh 라이브에서 확인.
