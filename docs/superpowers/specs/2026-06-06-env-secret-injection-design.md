# 설계 — SUT 앱 env/secret 주입 (Slice 2 후속 ⭐)

작성일: 2026-06-06 · 상태: 승인 대기

## 1. 목적

SUT 앱(예: opus-backend Spring)이 **healthy하게 부팅(Option B)** 하도록, 앱 설정
(datasource URL·redis host·JWT/OAuth 시크릿)을 **이미지에 굽지 않고 등록 시 주입**한다.
현재(2026-06-02 라이브 검증)는 주입 메커니즘이 없어 시크릿/DB 부재로 SUT가 CrashLoop(Option A) 상태다.

healthy 부팅은 값을 한 번에 못 맞추는 **반복 작업**이므로, 설계가 "편집"을 일급으로 지원해야 한다.
단, 별도 편집 UI는 만들지 않고 **편집 = 재등록**으로 해결한다(YAGNI).

## 2. 범위 / 비범위

**범위**: 등록 시 env/secret 입력 → DB 저장 → 비밀 아님은 gitops values.yaml, 비밀은 K8s Secret →
generic-app 차트가 `env`/`envFrom`으로 컨테이너에 주입.

**비범위(이번 아님)**: 빌드이력 UI·빌드 watch→SSE·`_bootstrap` 에러 세분화·`.env.example` 정비
(별개 Slice 2 후속 과제). 시크릿 값 readback/조회 화면. SealedSecrets/SOPS 등 외부 시크릿 관리.

## 3. 핵심 설계 결정

1. **DB = 단일 진실원천.** `register_app`이 `App.env_vars`를 **upsert**(생성 or 갱신)하고,
   `_bootstrap`은 폼 인자가 아니라 **DB 행에서** env를 읽는다(이미 status 갱신차 행을 로드 중 → 1줄 변경).
   → 값 정정 후 재등록해도 DB↔클러스터 drift 없음. 편집 UI 불필요.
2. **"values 평문 금지" 준수.** Iac-aws는 public 졸과 레포라 시크릿을 git에 넣을 수 없다.
   비밀 값은 대시보드가 **K8s Secret으로 직접 apply**, gitops values.yaml엔 `secretName`만 기록.
   - **cloud-hub와의 차이(정직한 정정):** cloud-hub는 `kind: Secret` 매니페스트(`stringData`에 실제 값)를
     **private gitops 레포에 커밋**한다(`src/shared/lib/deploy/helm-chart.ts:758`, 값은 DB 암호화 저장 후 생성 시 복호화).
     주입 패턴(이미지에 안 굽고 K8s Secret+`envFrom`)은 동일하나, **시크릿 목적지가 다르다**(cloud-hub=private git, chaoslab=클러스터 직접).
   - **업계 표준 대비:** "설정/시크릿을 런타임 주입"은 12-factor/K8s 정석이 맞다. 단 GitOps 시크릿의 정석은
     SealedSecrets/SOPS/External Secrets로 git에 *암호화* 저장하는 것이며, 본 설계의 직접 apply는 **졸과 규모에 맞춘 실용적 간소화**다.
3. **시크릿 seam = K8sService.** 시크릿 apply는 git 쓰기가 아니라 K8s 쓰기 → 기존 `StubK8s` Protocol
   뒤에 둔다. 최소 `RealK8s.apply_env_secret`만 추가. Slice 4 RealK8s가 이를 **확장**(리팩터 아님).
4. **시크릿 readback 금지.** 등록 폼은 입력 전용. 저장된 시크릿 값을 화면에 다시 뿌리지 않는다.
5. **차트 하위호환.** `{{- if .Values.env }}` + `secretName: ""` 기본값 → 기존 앱 렌더 변화 없음.

## 4. 데이터 흐름

```
등록 다이얼로그 (key/value/🔒secret 행 + .env 붙여넣기 + 자동 secret 감지)
   └─ Alpine → env_json hidden 필드: [{key, value, is_secret}]
POST /apps
   ├─ App.env_vars(JSON 컬럼) upsert
   └─ background: _bootstrap(name)
        _bootstrap: DB 행 로드 → env_vars 분리
           ├─ is_secret=false → gitops/apps/{app}/values.yaml  env: {KEY: VALUE}
           └─ is_secret=true  → K8sService.apply_env_secret(ns, {app}-env, {...})
        values.yaml에 secretName: {app}-env (비밀 있을 때만)
generic-app 차트(Iac-aws):
   deployment.yaml → env:(평문) + envFrom: secretRef {app}-env (비밀)
ArgoCD sync → Pod가 env/secret 주입받아 기동
```

순서 보장: bootstrap에서 **K8s Secret apply → values.yaml 커밋/푸시** 순. ArgoCD sync 시점엔 Secret이 이미 존재.

## 5. 변경 파일

| 파일 | 변경 |
|---|---|
| `app/db/models.py` | `App.env_vars: Mapped[list] = mapped_column(JSON, default=list)` (`Experiment.params` 패턴) |
| `app/routers/apps.py` | `register_app`에 `env_json: str = Form("[]")` → 파싱·upsert; `_bootstrap(name)`이 DB에서 env 읽어 gitops/k8s 호출 |
| `app/services/interfaces.py` | `GitOpsService.bootstrap_app(name, repo_url, framework, env)` 시그니처; `K8sService.apply_env_secret(namespace, name, data)`; `EnvVar` TypedDict/dataclass |
| `app/services/stubs.py` | StubGitOps/StubK8s 시그니처 맞춤 (no-op) |
| `app/services/real/gitops.py` | `render_values_yaml(name, image, port, health, env, secret_name)` — env 블록·secretName 추가(순수함수) |
| `app/services/real/k8s.py` (신규) | `RealK8s.apply_env_secret` — kubernetes client로 Secret create/patch (RealBuilder 클라이언트 셋업 패턴 재사용) |
| `app/deps.py` | `make_k8s()` real 분기 추가 (한 줄 토글 패턴) |
| `Iac-aws helm/generic-app/templates/deployment.yaml` | container에 `env:`(range) + `envFrom: secretRef`(secretName 있을 때) |
| `Iac-aws helm/generic-app/values.yaml` | `env: {}`, `secretName: ""` 기본값 |
| `app/templates/pages/apps.html` | 등록 다이얼로그에 env 섹션(Alpine 동적 행 + `.env` 붙여넣기 + 자동 secret 감지) |
| `tests/` | `render_values_yaml`(env 포함)·env_json 파싱 순수함수 테스트 |

## 6. 인터페이스 스케치

```python
# interfaces.py
class EnvVar(TypedDict):
    key: str
    value: str
    is_secret: bool

class GitOpsService(Protocol):
    def bootstrap_app(self, name: str, repo_url: str, framework: str,
                      env: list[EnvVar]) -> None: ...
    def update_image_tag(self, name: str, image: str) -> None: ...

class K8sService(Protocol):  # 기존 + 추가
    def apply_env_secret(self, namespace: str, name: str, data: dict[str, str]) -> None: ...
```

```yaml
# gitops/apps/{app}/values.yaml (env/secret 있을 때)
env:
  SPRING_DATASOURCE_URL: jdbc:mysql://mysql.default:3306/opus
  SPRING_REDIS_HOST: redis.default
secretName: opus-backend-env   # 비밀 없으면 줄 생략
```

```yaml
# generic-app/templates/deployment.yaml (container 추가분)
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

## 7. UI (cloud-hub EnvVarsEditor 축소)

등록 다이얼로그 하단 "환경변수 / 시크릿" 섹션:
- 동적 행: `key` · `value` · 🔒secret 토글 · 삭제 버튼, "+ 추가"
- **`.env` 붙여넣기**: textarea → `KEY=VALUE` 줄단위 파싱해 행 채움
- **자동 secret 감지**: 키에 `TOKEN|SECRET|PASSWORD|KEY` 포함 시 secret 자동 표시(수정 가능)
- **vanilla JS(이벤트 위임)** 로 행 변경 시마다 `#env-json` hidden 필드 동기화 → HTMX가 그대로 전송.
  base.html은 현재 Alpine 미로드(Chart.js/HTMX만)이고 기존 코드가 vanilla(`openDialog`)라 일관성·HTMX 스왑 안전성 위해 vanilla 채택.

readback 안 함(시크릿 값 재표시 금지). 재등록 시 폼은 비어서 시작(전체 교체 시맨틱).

## 8. 테스트

- `render_values_yaml` env/secretName 포함 시 블록 생성 검증(순수함수, IO 없음).
- env_json 파싱 헬퍼: 정상/빈/깨진 JSON → 안전 처리.
- `register_app` POST(env_json 포함) → App.env_vars 저장 + 재등록 시 갱신(upsert) 검증(stub 모드, hermetic).
- StubGitOps/StubK8s no-op 시그니처 호환.
- Helm은 단위테스트 안 함(렌더는 ArgoCD/라이브에서 확인).

## 9. 라이브 검증 선결 (스펙 차단 아님)

- 대시보드 K8s 신원에 `sut_namespace` **secrets create/update RBAC** 부여 필요
  (RealBuilder는 `argo_namespace` Workflow 권한만 → 별도 권한).
- `sut_namespace` 사전 존재(2c에서 확인).

## 10. minimal 원칙 메모

chaoslab은 cloud-hub보다 훨씬 단순한 졸과 구조다. cloud-hub의 편집/벌크삭제/export/암호화/멀티테넌트는
가져오지 않는다. **등록폼 1곳 + JSON 컬럼 1개 + 차트 분기 + RealK8s 메서드 1개**가 전부다.
