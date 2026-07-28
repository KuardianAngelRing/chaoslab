# 설계 — Slice 2 마무리 (probe / 에러로깅 / env.example)

작성일: 2026-06-07 · 상태: 승인됨(구두) → 계획 진행

## 1. 목적

Slice 2 후속 잔여 3건을 정리해 up.sh 라이브 검증 전 코드 완결성을 높인다. 세 항목은 독립적·소규모.

1. **health probe** — actuator/HTTP 헬스 없는 SUT 앱도 뜨도록 TCP probe 분기.
2. **`_bootstrap` 에러 로깅** — bare except가 실패를 삼켜 원인 불명 → 로깅. 같은 패턴인 `_watch_build`도 포함.
3. **`.env.example` 정비** — 키 뒤 인라인 주석이 복사 시 dotenv 값으로 오해될 소지 제거.

## 2. 범위 / 비범위

**범위**: 위 3건 + `_bootstrap` 단위테스트 보강(현재 실행 커버리지 0 — advisor 지적).

**비범위**: 등록폼 healthPath UI 힌트(생략 결정), 상태값 세분화(ecr-failed/push-failed 등 — YAGNI), `probeType` 신규 필드(healthPath 재사용으로 대체).

## 3. 항목별 설계

### 3-1. Health probe — `healthPath` 비면 TCP (Iac-aws 차트만)

`helm/generic-app/templates/deployment.yaml`의 readiness/liveness probe를 `healthPath` 유무로 분기:
- `{{- if .Values.healthPath }}` → 기존 `httpGet`(path/port)
- `{{- else }}` → `tcpSocket`(port). timing(initialDelaySeconds/periodSeconds)은 양쪽 동일 유지.

**chaoslab 코드 변경 없음.** `render_values_yaml`이 이미 per-app `healthPath`를 values.yaml에 기록. actuator 없는 앱은 등록 시 healthPath를 빈 문자열로 두면 TCP probe로 기동. `framework_defaults`는 기본 path를 주므로(기본은 HTTP), TCP는 사용자가 명시적으로 비울 때만.

근거: 새 필드 없이 기존 필드 의미 확장 → 표면 최소. cloud-hub도 probe는 명시 정의(템플릿 중복 허용).

### 3-2. 에러 로깅 (chaoslab `app/routers/apps.py`)

모듈 상단에 `logger = logging.getLogger(__name__)` 추가.

- **`_bootstrap`**: `except Exception:` 블록에서 `logger.exception("bootstrap failed for app %s", name)` 후 `status = "register-failed"`(상태값 유지).
- **`_watch_build`**: `update_image_tag` 호출의 `except Exception: pass` → `logger.exception("deploy(update_image_tag) failed for app %s", app_name)`(배포 push 실패가 조용히 사라지지 않음). 상태 전이 로직은 변경 없음.

상태값은 그대로(register-failed/build-failed). 로그(traceback)가 원인 진단을 제공 → EC2 uvicorn 로그에서 확인 가능.

### 3-3. `.env.example` 정비 (chaoslab)

키 뒤 인라인 주석을 각 키 **위 줄**로 이동, real-모드 키는 빈 값 유지. 복사→`.env` 시 dotenv가 값을 오해하지 않게.
대상: `ECR_REGISTRY`, `IAC_AWS_REPO_PATH`, `GITHUB_TOKEN`(인라인 주석 보유). 나머지 라인은 그대로.

## 4. 변경 파일

| 파일 | 변경 |
|---|---|
| `Iac-aws helm/generic-app/templates/deployment.yaml` | readiness/liveness를 `healthPath` 유무로 httpGet/tcpSocket 분기 |
| `app/routers/apps.py` | `logging` 도입, `_bootstrap`·`_watch_build`의 삼킴 except에 `logger.exception` |
| `tests/test_apps.py` | `_bootstrap` 성공/실패 단위테스트(SessionLocal·make_gitops·make_k8s monkeypatch + spy, caplog) |
| `.env.example` | 인라인 주석 → 윗줄 분리, real 키 빈 값 |

## 5. _bootstrap 테스트 설계 (advisor 0커버리지 보강)

`_bootstrap`은 BackgroundTask에서 `SessionLocal`(파일 DB)을 쓰므로 route 경유로는 테스트 불가 → **직접 호출** + monkeypatch.

- **성공 경로**: in-memory 엔진에 App(plain+secret env) 한 행 → `app.routers.apps.SessionLocal`을 그 세션메이커로 patch, `make_gitops`/`make_k8s`를 spy로 patch → `_bootstrap("demo")` → k8s spy가 `(ns, "demo-env", {secret})`, gitops spy가 `(name, repo, fw, {plain}, "demo-env")`로 호출됐고 app.status=="ready" 검증.
- **실패 경로**: gitops spy의 `bootstrap_app`이 raise → `_bootstrap` 후 status=="register-failed" + `caplog`에 "bootstrap failed" 기록 검증.

## 6. 검증

- `helm template`로 두 케이스 렌더: healthPath 있음 → `httpGet`; `--set healthPath=""` → `tcpSocket`.
- `pytest` 전체 통과(_bootstrap 신규 테스트 포함). 실패 경로는 `caplog`로 로그 확인.

## 7. minimal 메모

probe는 차트 1파일 분기, 에러처리는 logger 도입+2곳, env.example은 주석 재배치. 신규 추상화·상태값·필드 없음.
