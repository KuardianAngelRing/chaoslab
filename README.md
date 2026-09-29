# ChaosLab

**카오스 엔지니어링 자동화 및 모니터링 플랫폼**

ChaosLab은 Kubernetes 애플리케이션의 장애 실험을 설계하고, 실제 장애를 주입한 뒤 관측 결과에 근거한 개선과 재검증을 연결하는 플랫폼입니다. 사용자는 AI가 제안한 실험 후보와 개선안을 선택하고, 플랫폼은 허용된 변경을 적용해 개선 전후의 결과를 R 지수와 보고서로 제공합니다.

프로그램 워크플로우는 다음과 같습니다.

**검증 목표 입력 → AI 가설 제안 → 사용자 선택 → 장애 주입·관측 → 개선안 승인 → 동일 조건 재검증 → 결과 보고서**

### 1. 프로젝트 배경

#### 1.1. 국내외 시장 현황 및 문제점

Kubernetes와 마이크로서비스 아키텍처는 서비스를 독립적으로 배포하고 확장하는 데 활용됩니다. 그러나 서비스 간 의존성이 복잡해지면 특정 Pod의 종료나 통신 지연이 다른 서비스로 전파될 수 있습니다. 정상 상태의 기능 테스트만으로는 이러한 장애 상황에서 서비스가 유지되는지 확인하기 어렵습니다.[1][2]

기존 카오스 엔지니어링 도구인 Chaos Mesh와 LitmusChaos는 장애 주입을 지원하지만, 검증할 가설을 정하고 관측 결과를 해석해 개선하는 과정에는 운영자의 전문 지식이 필요합니다. LLM을 활용한 선행 연구 ChaosEater는 이 과정을 자동화했으나, kind 기반 가상 클러스터에서의 검증을 관리형 클라우드와 독립된 물리 노드 환경으로 확장할 필요가 있습니다.[4]

ChaosLab은 이러한 도구와 연구 흐름에서 다음 문제에 집중했습니다.

- **실험 설계의 진입 장벽:** 앱 구성에 맞는 장애 대상과 조건을 사용자가 직접 정해야 합니다.
- **관측과 개선의 단절:** 오류율·응답 지연·복구 시간을 해석하고 설정 변경으로 연결하는 작업이 분리되어 있습니다.
- **변경 통제의 필요성:** AI가 제안한 설정을 실제 클러스터에 적용하려면 사용자 승인과 변경 범위 검증이 필요합니다.
- **비교 기준의 부족:** 개선 전후에 같은 장애 조건과 판정 기준을 사용하지 않으면 효과를 일관되게 비교하기 어렵습니다.

#### 1.2. 필요성과 기대효과

실제 사고 전에 장애를 재현하고 복구 과정을 검증하면 서비스의 취약한 지점을 미리 확인할 수 있습니다. ChaosLab은 가설 생성부터 결과 보고까지 연결하여 반복 실험에 필요한 수작업을 줄이고, 사용자가 변경의 근거와 효과를 함께 검토하도록 돕습니다. 기대효과는 실험 설계 부담 완화, 장애 전파와 복구 특성의 가시화, 동일 조건 재검증을 통한 개선 효과 확인입니다.

### 2. 개발 목표

#### 2.1. 목표 및 세부 내용

전체 목표는 **AWS EKS와 라즈베리파이 기반 k3s에서 장애 실험과 개선 과정을 자동화하고, 회복탄력성을 실측 데이터로 평가하는 것**입니다.

| 세부 목표 | 주요 내용 |
|---|---|
| 가설 수립 자동화 | 앱 구성·검증 목표·과거 이력을 기반으로 후보 생성, 사용자 선택 후 파라미터 구체화 |
| 장애 주입과 관측 | 장애 9종 지원, 기준·장애·회복 구간 저장, 실시간 메트릭 표시 |
| 회복탄력성 평가 | 단독 실험 R과 개선 전후 회귀 R-1.0 계산 |
| 승인형 개선과 재검증 | 개선안 승인·편집·제외, 허용 변경 적용, 동일 시나리오 재실행, 원상 복구 |
| 반복 가능한 실험 환경 | Terraform 기반 EKS 구축·삭제, k3s 실험별 전용 네임스페이스 배포 |

#### 2.2. 기존 서비스 대비 차별성

기존 장애 주입 도구 및 자동화 연구와 ChaosLab의 주요 차이는 다음과 같습니다.

| 비교 항목 | Chaos Mesh·LitmusChaos | ChaosEater | ChaosLab |
|---|---|---|---|
| 중심 역할 | 선언된 장애 실행 | LLM 기반 카오스 엔지니어링 사이클 자동화 | 실제 클러스터의 가설·실험·승인형 개선·재검증 연결 |
| 실험 환경 | Kubernetes 장애 주입 도구 | kind 기반 로컬 가상 클러스터 | AWS EKS 및 라즈베리파이 k3s |
| 판정 방식 | 별도 실험 설계·결과 해석 필요 | LLM이 생성한 검증 코드 중심 | 관측값과 고정 기준을 비교하는 플랫폼 코드 |
| 변경 통제 | 도구를 사용하는 운영 절차에 따름 | 자동 수정 중심 | 후보 선택, 개선 승인, 서버 측 허용 목록 |
| 결과 비교 | 사용자가 관측·평가 체계 구성 | 개별 검증 결과 중심 | 실험 R·회귀 R-1.0, 전후 변경값, HTML·PDF 보고서 |

LLM은 가설과 개선안을 생성하고 결과를 설명합니다. 장애 파라미터 검증, 회귀 판정, 변경 적용과 롤백은 플랫폼 코드가 담당합니다. 변경 가능한 항목을 제한하고 사용자의 승인 과정을 두어 자동화의 범위와 책임을 명확히 했습니다.

#### 2.3. 사회적 가치 도입 계획

- **서비스 신뢰성 향상:** 장애 대응을 사후 복구에만 의존하지 않고 사전 검증으로 보완하여 디지털 서비스의 연속성 향상에 기여하고자 합니다.
- **학습과 검증 기회 확대:** 내장 샘플, 스텁 모드, 라즈베리파이 실험 환경을 활용해 학생과 소규모 개발팀도 장애 실험 과정을 학습할 수 있도록 합니다.
- **자원 사용 효율화:** 필요할 때 실험 환경을 만들고 종료 후 자원을 정리하여 유휴 자원과 불필요한 운영 비용을 줄입니다.
- **책임 있는 AI 활용:** 사용자 승인, 변경 허용 목록, 실행 이력과 원상 복구 절차를 유지하여 AI 제안을 검토 가능한 형태로 제공합니다.

### 3. 시스템 설계

#### 3.1. 시스템 구성도

![ChaosLab 제어 서버와 SQLite, AWS EKS, 온프레미스 k3s의 연결 구조](docs/images/system-architecture.png)

제어 서버는 별도 메시지 큐 없이 백그라운드 태스크로 AI 호출과 실험 수명주기를 관리합니다. EKS는 system/workload 노드그룹을 분리해 관측 도구와 실험 대상을 분리하고, k3s는 마스터 1대와 워커 2대로 구성합니다.

#### 3.2. 사용 기술

| 영역 | 기술 | 용도 |
|---|---|---|
| 프론트엔드 | Jinja2, HTMX, Alpine.js | 서버 렌더링, 부분 화면 갱신, UI 상태 관리 |
| 스타일·차트 | Tailwind CSS, CSS 디자인 토큰, Chart.js | 화면 구성, 테마, 메트릭 시각화 |
| 백엔드 | Python 3.12, FastAPI, Uvicorn | API, 웹 서버, 백그라운드 작업 |
| 실시간 전송 | SSE, sse-starlette | 실험 상태 및 3초 주기 메트릭 전달 |
| 데이터·검증 | SQLite, SQLAlchemy, Pydantic | 10개 테이블의 실행 이력, 입력·출력 스키마 검증 |
| AI | Claude headless CLI, Python 워크플로우 | 가설 생성, 세부 조건 확정, 개선안 제안 |
| 보고서 | Jinja2, Chromium/Chrome, 선택적 OpenAI API | HTML·PDF 생성, 확정 사실에 근거한 서술 및 규칙 기반 대체 |
| 클라우드 | AWS EKS 1.31, EC2, ECR, Terraform 1.6 이상 | 클러스터·제어 서버·이미지 저장·IaC |
| 빌드·배포 | Argo Workflows, Kaniko, ArgoCD | 이미지 빌드, GitOps 배포 |
| 온프레미스 | Raspberry Pi, k3s, SSH 터널 | 물리 노드 실험 및 원격 API 접근 |
| 장애 주입 | Chaos Mesh 2.8.2 | NetworkChaos, PodChaos, StressChaos |
| 관측 | Istio 1.29.2, Prometheus, Grafana, Loki, Promtail | EKS 트래픽 메트릭, 메트릭·로그 수집과 조회 |
| 테스트 | pytest, FastAPI TestClient, 인메모리 SQLite | 외부 시스템을 스텁으로 대체한 자동화 검증 |

AI 에이전트는 Python 워크플로우와 Claude CLI 호출로 구성합니다. k3s는 Pod Ready 지표와 앱이 노출하는 HTTP 메트릭을 사용합니다. 표의 인프라 버전은 실제 연동을 검증한 환경 기준입니다.

### 4. 개발 결과

#### 4.1. 전체 시스템 흐름도

![가설 수립부터 실행·관측, 판정, 개선 승인, 회귀 재검증, 원상 복구까지의 흐름](docs/images/experiment-workflow.png)

k3s에서 가설 생성부터 개선 적용·회귀 검증까지 실행한 대표 사례입니다.

| 실험 대상·장애 | 승인한 개선 | 오류율 전 → 후 | 회귀 R-1.0 전 → 후 | 결과 |
|---|---|---|---|---|
| nginx · Pod 종료 | 복제본 증설, 준비 상태 검사 주기 단축 | 33% → 0% | 43.3(C) → 99.5(A) | 실패 → 통과 |
| order-resilience-lab · payment-api Pod 종료 | 결제 서비스 복제본 증설, order-api 재시도 적용 | 16.7% → 0% | 97.3 → 98.6 | 주문 경로 오류 감소 |

같은 장애 시나리오를 개선 전후에 실행해 비교했으며, 회귀 종료 후 설정 원복과 결과 보고서의 변경값 기록까지 확인했습니다. 결과는 부하와 트래픽 조건에 따라 달라질 수 있습니다.
지원 장애는 **9종**, 데이터 모델은 **10개 테이블**이며, EKS 환경 구축에는 약 **20~25분**이 소요됩니다. 자동화 테스트는 인메모리 DB와 스텁 서비스를 사용해 API·입력 검증·실험 수명주기·판정 로직을 확인합니다.

#### 4.2. 기능 설명 및 주요 기능 명세서

| 기능 | 입력 | 처리 내용 | 출력 |
|---|---|---|---|
| EKS 앱 등록·배포 | GitHub URL, 프레임워크, 배포 설정 | Kaniko 빌드, ECR 업로드, GitOps 설정 갱신, ArgoCD 동기화 | 앱 상태, 빌드 이력, 이미지 태그 |
| k3s 앱 등록 | Kubernetes manifest 또는 내장 샘플 | manifest·관측 대상 저장, 실험 시 전용 namespace 배포 | 등록 앱, 준비 상태 |
| 가설 생성 | 앱 구성, 검증 목표, 과거 실험 요약 | AI 후보 생성, 형식·대상·중복 검증 | 가설, 대상 워크로드, 예상 영향 |
| 후보 구체화 | 선택 후보 또는 직접 입력 시나리오 | 장애 파라미터 생성과 서버 허용 범위 검증 | 실행 가능한 실험 명세 |
| 장애 실험 | 장애 종류, 대상, 파라미터 | CRD 생성, 중복 실험 차단, 상태 감시·중지·정리 | 실험 상태, 주입·종료 이력 |
| 실시간 관측 | 실험 namespace·관측 Service | Prometheus 조회, 관측 요청 생성, SSE 갱신 | RPS, 오류율, p95/p99, Ready Pod, 구간 요약 |
| 개선 제안·승인 | 실험 결과, 원본 manifest, 사용자 결정 | 현재값·제안값·근거 표시, 승인·편집·제외 검증 | 승인된 개선 명세 |
| 최종 회귀 | 승인 후보, 준비 세션, 승인 개선 | 개선 전후 동일 시나리오 실행, 규칙 판정, 변경 롤백 | passed/failed/inconclusive, R-1.0, 실제 변경분 |
| 결과 보고서 | 확정된 판정·관측·변경값 | 서술 생성 및 사실 대조, LLM 미사용 시 규칙 기반 서술 | HTML·PDF 보고서 |
| 인프라 조회 | 실행 환경·접속 설정 | 노드·Pod·관측 도구 상태 조회 | 준비 상태, 자원 사용률, 확보 가능한 온도 지표 |

**AI 실험 후보 선택**

앱 구성에 근거한 가설, 장애 대상과 예상 영향을 비교해 실험을 선택합니다. 원하는 시나리오를 직접 입력해 후보를 추가할 수도 있습니다.

![장애 가설과 대상·예상 영향을 비교하고 직접 입력으로 후보를 추가하는 화면](docs/images/hypothesis-candidates.png)

**실시간 장애 관측**

장애 주입 중 Ready Pod, 응답 지연, 요청량과 오류율을 확인하고, 종료 후 구간별 요약을 비교합니다.

![payment-api 장애 실험의 Ready Pod·지연·트래픽 차트와 구간별 요약](docs/images/live-metrics.png)

**개선안 검토와 승인**

현재 설정과 제안값, 관측 근거를 확인한 뒤 적용할 항목을 승인합니다. 아래 예시는 order-api의 호출 재시도를 0회에서 2회로 늘리는 제안입니다.

![호출 재시도의 현재값과 제안값 및 개선안 승인 버튼](docs/images/improvement-approval.png)

**개선 전후 회귀 결과**

R 지수, 오류율, 지연시간과 실제 적용한 변경을 한 화면에서 확인합니다. order-resilience-lab의 별도 Pod 실패 실험으로, R-1.0이 32.4에서 98.9로 상승한 실행 예시입니다.

![회귀 R-1.0 32.4에서 98.9로 개선된 결과와 실제 적용된 설정 변경](docs/images/regression-result.png)

**지원 장애 유형**

| CRD | 장애 |
|---|---|
| NetworkChaos | 지연, 손실, 단절, 대역폭 제한 |
| PodChaos | Pod 강제 종료, Pod 실패, 컨테이너 강제 종료 |
| StressChaos | CPU 부하, 메모리 부하 |

**개선 적용 범위**

Deployment의 readiness/liveness probe, preStop, resources, replicas와 기존 환경변수를 대상으로 합니다. 사용자 승인 후 허용 목록 검증을 통과한 변경만 회귀용 환경에 적용하며, 저장한 원본 manifest를 영구 변경하지 않습니다.

**R 지수**

- **실험 R(0~1):** `0.4 × 가용성 + 0.3 × 지연 점수 + 0.3 × 복구 속도`. 가용성은 5xx 오류 비율, 지연은 기준 구간 대비 p99, 복구 속도는 300초 상한을 기준으로 계산합니다.
- **회귀 R-1.0(0~100):** `100 × (0.45P + 0.20E + 0.20H + 0.15T)`. P는 시나리오 통과율, E는 필수 항목 충족률, H는 오류율·p95 품질, T는 복구 시간 점수입니다. 85점 이상 A, 70점 이상 B, 70점 미만 C입니다.

두 지수는 플랫폼 자체 평가 기준이며 목적과 척도가 다릅니다. 관측 근거가 부족하면 미산정 또는 판정 불가로 표시하고, 종합 점수와 개별 오류율·판정을 함께 확인합니다.

**현재 한계와 후속 개발**

EKS 개선·회귀 연동, Istio 정책 자동 개선, 관리형 PostgreSQL 전환은 후속 과제입니다. HTTP 메트릭 미노출 앱과 짧은 관측 구간에서는 단독 실험 R 산정이 제한될 수 있습니다. 목적지 기준 오류율의 편향, 대표 경로 중심 트래픽의 한계, k3s NetworkChaos 간헐 주입 실패도 추가 검증이 필요합니다.

#### 4.3. 디렉토리 구조

```text
chaoslab/
├── app/
│   ├── main.py                 # FastAPI 앱·생명주기
│   ├── config.py               # 환경변수 설정
│   ├── deps.py                 # Stub / Real 서비스 팩토리
│   ├── rendering.py            # 전체·부분 페이지 렌더링
│   ├── db/                     # 모델·Repository·초기 데이터
│   ├── routers/                # 앱·실험·가설·준비 세션·회귀·보고서 API
│   ├── services/
│   │   ├── agent/              # AI 입출력 스키마·조립·검증
│   │   ├── real/               # Kubernetes·관측·Claude·SSH 실제 연동
│   │   ├── interfaces.py       # 외부 시스템 Protocol
│   │   ├── stubs.py            # 개발·테스트용 대체 구현
│   │   ├── regression.py       # 개선 전후 회귀 실행·롤백
│   │   ├── resilience.py       # 회귀 판정·R-1.0
│   │   ├── r_index.py          # 단독 실험 R
│   │   └── reports.py          # HTML·PDF 보고서
│   ├── samples/                # nginx·order-resilience-lab·시나리오
│   ├── templates/              # Jinja 페이지·부분 화면·보고서
│   └── static/                 # CSS·JavaScript
├── argo/                       # 빌드 WorkflowTemplate·적용 스크립트
├── docker/                     # 프레임워크별 Dockerfile 템플릿
├── docs/                       # ADR·설계·개발 계획
├── tests/                      # 자동화 테스트
├── .env.example                # 설정 예제
└── requirements.txt            # Python 의존성
```

#### 4.4. 산업체 멘토링 의견 및 반영 사항

산학협력 멘토링 의견을 반영해 AI 루프의 개발 우선순위와 실제 클러스터 검증을 강화했습니다.

| 멘토 의견 | 반영 사항 |
|---|---|
| ChaosEater와의 차별성을 명확히 제시 | 실제 EKS·물리 k3s 환경, 규칙 기반 판정, 사용자 승인·허용 목록, R 지수 비교의 네 축으로 정리 |
| 핵심 AI 루프의 구현 우선순위와 인력 보강 | 담당 인력을 1명에서 2명으로 늘리고, 전달 데이터 규약을 먼저 확정해 단계별 개발·통합 |
| R 지수를 전체 실험의 실측 데이터로 검증 | Online Boutique 지연 실험에서 3구간 관측과 R=0.7024 계산을 확인하고 두 환경으로 확대 |
| 장애 주입을 스텁뿐 아니라 실제 클러스터에서 검증 | EKS 지연 주입과 k3s 현장 배포 실험을 검증하고 스텁 → 라이브의 2단계 검증 적용 |
| 집중 개발 일정의 실현 가능성 보완 | RAG 골든셋·Istio 정책 개선 등을 후속 과제로 조정하고 승인형 개선·회귀·보고서 완성에 집중 |

### 5. 설치 및 실행 방법

#### 5.1. 설치절차 및 실행 방법

**로컬 스텁 모드**

Python **3.12**와 Git이 필요합니다. 스텁 모드는 실제 클러스터와 AI 계정 없이 화면·API 흐름을 확인하는 용도이며, 실제 장애 영향이나 개선 성능을 검증하는 환경은 아닙니다.

```bash
git clone https://github.com/KuardianAngelRing/chaoslab.git
cd chaoslab

python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt

# 최초 설정 시 실행. 기존 .env가 있다면 덮어쓰지 않고 필요한 값만 수정합니다.
cp -n .env.example .env
```

`.env`에서 아래 값을 확인합니다. 세 게이트는 서로 독립적이므로 `USE_REAL_SERVICES=false`만으로 k3s와 AI 호출까지 비활성화되지는 않습니다.

```dotenv
USE_REAL_SERVICES=false
LOCAL_KUBECONFIG=
LOCAL_SSH_HOST=
HYPOTHESIS_AGENT=stub
OPENAI_API_KEY=
```

```bash
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000
```

- 대시보드: <http://127.0.0.1:8000>
- 상태 확인: <http://127.0.0.1:8000/healthz>
- API 문서: <http://127.0.0.1:8000/docs>
- 기본 DB: 작업 디렉토리의 `chaoslab.db`. 앱 기동 시 테이블을 초기화하며 스텁 모드의 빈 앱 목록에는 예제 데이터를 넣습니다.
- 화면의 외부 CDN 자산을 불러오려면 인터넷 연결이 필요합니다.

자동화 테스트는 다음과 같이 실행합니다.

```bash
python -m pytest -q
```

**실제 k3s 및 AI 연결**

k3s 클러스터에 Chaos Mesh와 관측 스택을 준비하고, 실험용 namespace·워크로드·CRD를 생성·조회·변경·삭제할 수 있는 Kubernetes 권한이 필요합니다. 샘플 지표를 수집하려면 Prometheus의 앱 scrape 설정과 Pod Ready 지표도 준비되어야 합니다.

```dotenv
LOCAL_KUBECONFIG=/absolute/path/to/k3s.yaml
LOCAL_SSH_HOST=your-k3s-host
LOCAL_SSH_PORT=22
LOCAL_SSH_USER=your-user
LOCAL_SSH_KEY_PATH=/absolute/path/to/ssh-key
LOCAL_TUNNEL_PORT=6443
LOCAL_TUNNEL_TARGET=localhost:6443
LOCAL_OBS_NAMESPACE=chaospilot-observability
LOCAL_CHAOS_NAMESPACE=chaos-mesh

HYPOTHESIS_AGENT=claude
CLAUDE_BIN=claude
HYPOTHESIS_TIMEOUT_SECONDS=180
```

kubeconfig의 서버 주소는 터널 구성에 맞춰 `https://127.0.0.1:6443`을 사용합니다. SSH 호스트를 설정하면 앱이 터널을 관리하며, 이미 열린 터널이 있으면 재사용합니다. 수동 터널을 사용한다면 `LOCAL_SSH_HOST`를 비워 둡니다.

Claude CLI는 서버를 실행하는 사용자 계정에서 설치·로그인이 완료되어 `claude -p`를 사용할 수 있어야 합니다. 앱을 재시작한 뒤 Apps에서 `nginx` 또는 `order-resilience-lab`을 등록하고, 카오스 테스트에서 검증 목표를 입력합니다. 후보 선택, 실험 완료, 개선안 승인, 최종 회귀, 결과 확인 순으로 진행합니다.

**실제 EKS 연결**

[Iac-aws](https://github.com/KuardianAngelRing/Iac-aws)의 환경 구축 절차를 먼저 수행합니다. kubeconfig, ECR 접근 권한, GitOps 저장소 접근 권한, Argo Workflows·ArgoCD와 Chaos Mesh·관측 스택이 필요합니다. 주요 설정은 다음과 같습니다.

| 설정 | 내용 |
|---|---|
| `USE_REAL_SERVICES=true` | EKS 외부 서비스 실제 연동 |
| `K8S_CONTEXT`, `SUT_NAMESPACE` | 대상 Kubernetes 컨텍스트와 앱 namespace |
| `ECR_REGISTRY`, `AWS_REGION` | 빌드 이미지 저장 위치 |
| `IAC_AWS_REPO_PATH`, `IAC_AWS_REPO_URL`, `GITHUB_TOKEN` | GitOps 저장소와 접근 설정 |
| `PROMETHEUS_URL`, `LOKI_URL` | 제어 서버에서 접근할 관측 주소. 기본 포트는 9090, 3100 |

현재 kubeconfig가 의도한 EKS 클러스터를 가리키는지 확인한 뒤 빌드 템플릿을 적용합니다.

```bash
./argo/apply.sh
```

세부 빌드 구성은 [argo/README.md](argo/README.md)를 참고합니다. EKS 가설 경로는 해당 기능이 포함된 버전에서 사용할 수 있으며, EKS 개선·최종 회귀는 아직 지원 범위에 포함되지 않습니다.

**보고서 PDF**

서버에 Chromium 또는 Google Chrome 실행 파일이 있어야 합니다. 자동 탐색이 되지 않으면 `.env`에 `CHROMIUM_PATH=/absolute/path/to/chromium`을 설정합니다. 보고서 서술용 `OPENAI_API_KEY`는 선택 사항이며, 키가 없거나 호출·검증에 실패하면 규칙 기반 서술로 보고서를 생성합니다.

#### 5.2. 오류 발생 시 해결 방법

| 증상 | 확인 및 해결 방법 |
|---|---|
| Python 의존성 또는 SQLAlchemy 실행 오류 | Python 3.12로 가상환경을 만들었는지 확인하고 `requirements.txt`를 다시 설치합니다. |
| 8000번 포트를 사용할 수 없음 | 다른 서버의 사용 여부를 확인하거나 `--port 8001`로 실행합니다. |
| 로컬 인프라 연결 실패 | `LOCAL_KUBECONFIG`, SSH 접속, 터널 포트 6443, kubeconfig의 서버 주소를 확인합니다. |
| 워크로드가 준비되지 않거나 장애 주입 실패 | 실험 namespace의 Pod 상태·이벤트, 이미지 접근, RBAC, Chaos Mesh 상태를 확인합니다. |
| 실험이 완료됐으나 R지수가 산정 불가 | HTTP 메트릭 노출, 실제 관측 요청, scrape 상태·관측 구간을 확인합니다. nginx처럼 HTTP 지표가 없는 앱에서는 Ready Pod만 표시될 수 있습니다. |
| 가설·개선안 생성 실패 | `HYPOTHESIS_AGENT`, Claude CLI 경로, 실행 계정의 로그인, 호출 제한·타임아웃을 확인합니다. |
| PDF 다운로드 실패 | 서버가 Chromium/Chrome을 실행할 수 있는지 확인하고 `CHROMIUM_PATH`를 지정합니다. |
| 다중 Service 앱의 회귀 준비 실패 | 관측 진입 Service가 해석되는지 확인합니다. 내장 샘플은 재등록하면 현재 샘플 정의와 관측 대상이 반영됩니다. |
| 설정 변경 후에도 동작이 같음 | 서버를 재시작하고 `USE_REAL_SERVICES`, `LOCAL_KUBECONFIG`, `HYPOTHESIS_AGENT`를 각각 확인합니다. |

### 6. 소개 자료 및 시연 영상

#### 6.1. 프로젝트 소개 자료

[최종보고서 — 카오스 엔지니어링 자동화 및 모니터링 플랫폼](docs/chaoslab-final-report.docx)

#### 6.2. 시연 영상

[ChaosLab 시연 영상 보기](https://www.youtube.com/watch?v=3pqyrm2TV4I)

### 7. 팀 구성

#### 7.1. 팀원별 소개 및 역할 분담

| 팀원 | 담당 역할 |
|---|---|
| **이시웅** | 라즈베리파이 k3s 구축, SSH 터널·현장 배포, 실험 워크플로우 설계, 가설 및 개선 에이전트, 실시간 관측 및 UI/UX |
| **김태윤** | Terraform·EKS 인프라, GitOps 빌드·배포, 대시보드, AI 전달 데이터 규약, 실측 연동·R 지수, EKS 실험 경로 확장 |
| **양준영** | 최종 회귀 검증, 규칙 기반 판정, PDF 보고서, AI 루프 설계 및 대시보드 통합, 온프레미스 운영, 워크플로우 UI 시안 |

#### 7.2. 팀원 별 참여 후기

**이시웅**

라즈베리파이 기반 k3s 실험 환경과 SSH 터널을 구축하고 실험 워크플로우와 AI 가설, 개선 에이전트, 대시보드 UI/UX를 맡았습니다. 실제 물리 노드에서 장애를 주입하고 관측하면서, 애플리케이션 코드만으로는 알기 어려웠던 서비스 간 의존성과 장애 상황에서의 동작을 이해할 수 있었습니다. 
AI가 실험 가설이나 개선안을 생성하도록 만드는 과정에서는 그럴듯한 답변을 받는 것만으로는 충분하지 않다는 점을 배웠습니다. 제안한 장애가 실제 앱에 적용 가능한지 확인하고, 사용자가 대상과 예상 영향을 이해한 뒤 선택할 수 있어야 했습니다. 다양한 프롬프트를 주입해보며 어떤 것이 결과가 좋은지 평가 과정이 정말 어렵지만 그러기에 중요하다는 생각을 가지게 되었습니다. 개선안 역시 현재 설정과 제안값, 관측 근거를 함께 보여주고 승인한 항목만 적용하는 human in the loop 흐름으로 구성하면서, AI의 제안을 실제 시스템의 동작으로 연결하려면 검증과 사용자 판단이 중요하다는 것을 느꼈습니다.
실시간 관측 화면을 만들면서는 데이터를 보여주는 것과 사용자가 상황을 이해하도록 돕는 것이 다르다는 점도 배웠습니다. 장애 주입 전후의 요청량, 오류율, 응답 지연과 Pod 상태를 실험 단계에 맞춰 확인할 수 있도록 구성하며 화면 설계 역시 실험 결과를 해석하는 데 중요한 역할을 한다는 것을 알게 됐습니다. 인프라, AI, 관측, 사용자 경험을 따로 보지 않고 하나의 서비스로 생각해볼 수 있었던 프로젝트였습니다.

**김태윤**

저는 EKS 실험 환경을 Terraform으로 만들고 지우는 스크립트와 ChaosLab 플랫폼의 기본 구조, 장애 주입과 실측 기반 R 지수 계산, EKS 실험 경로를 맡았습니다. 졸업과제를 하며 크게 배운 건 테스트를 통과하는 것과 실제로 되는 것은 다르다는 점입니다. 스텁 환경에서는 멀쩡하던 기능이 진짜 클러스터에서는 계속 문제가 났고, 그래서 기능을 붙일 때마다 클러스터를 올려 직접 확인하고 그 결과를 팀 문서에 적어 두는 습관이 생겼습니다. 근거가 부족하면 산정 불가로 표시하고 회복이 확인되지 않은 실험은 실패로 기록하게 만들면서, 보기 좋은 숫자보다 근거 있는 숫자가 팀에 더 도움이 된다는 것도 느꼈습니다.
저장소를 인프라, 플랫폼, 실험 대상 앱으로 나누고 저는 클라우드 환경과 플랫폼 구조를, 다른 팀원들은 라즈베리파이 k3s 환경과 AI 개선 루프, 온프레미스 운영과 대시보드 통합을 맡았습니다. 같은 코드 위에서 일해야 했기 때문에 외부 시스템은 전부 인터페이스 뒤에 두고 스텁과 실제 구현을 한 곳에서 바꾸게 만들었고, 덕분에 클러스터가 없어도 누구나 로컬에서 개발하고 테스트할 수 있었습니다. 팀원이 파일 하나만 읽으면 작업을 시작할 수 있도록 프로젝트 상황과 구조를 담은 공유 문서를 레포에 두고, 설계 문서를 먼저 쓴 뒤 구현했으며, 서로 검증한 결과를 수치로 남겨 두니 말로 설명하는 시간이 크게 줄었습니다.
EKS에서 Istio 사이드카가 주입되지 않던 문제는 Terraform EKS 모듈의 기본 보안그룹이 컨트롤플레인에서 노드로 가는 포트를 일부만 열어 두어 webhook 호출이 오류 없이 타임아웃되던 것이 원인이었고, 보안그룹 규칙을 코드에 추가해 해결했습니다. 장애 주입 대상을 못 고르던 문제는 파드 라벨이 표준 규약을 따를 거라 가정한 탓이었는데, 매니페스트나 클러스터에서 실제 라벨을 읽어 겨냥하고 대상을 못 찾으면 바로 실패 처리하도록 바꿔 조용히 실패하는 경로를 없앴습니다.

**양준영**

이번 졸업과제를 통해 AI를 활용해 카오스 엔지니어링 과정을 자동화하는 시스템을 직접 설계하고 구현해볼 수 있었다. 평소 어렵게 느껴졌던 Kubernetes와 카오스 엔지니어링을 실제 클러스터에서 다루며, 장애를 발생시키고 관측한 결과를 분석해 다음 실험과 개선으로 이어가는 과정을 경험했다. 특히 AI 에이전트가 실험 도구 호출부터 메트릭 분석, 보고서 작성까지 수행하도록 구성하면서 AI를 단순한 기능이 아닌 전체 작업 흐름을 자동화하는 방식으로 활용해볼 수 있었다.
프로젝트를 진행하면서 처음 설계한 구조가 실제 환경에서는 예상대로 동작하지 않는 경우도 많았고, 팀원들과 인터페이스와 데이터 전달 방식을 조율하며 통합 테스트를 반복했다. 이를 통해 각자의 기능 구현뿐 아니라 서로의 역할과 전체 시스템의 흐름을 이해하는 것이 중요하다는 점을 배웠다.
처음 접하는 기술이 많아 어려움도 있었지만, 기존의 백엔드 개발을 넘어 인프라, 장애 대응, 관측, AI까지 직접 경험하며 개발을 바라보는 범위를 넓힐 수 있었던 프로젝트였다.

### 8. 참고 문헌 및 출처

프로젝트 설계와 구현에 참고한 연구 및 기술 문서입니다.

1. X. Zhou et al., “Fault Analysis and Debugging of Microservice Systems: Industrial Survey, Benchmark System, and Empirical Study,” *IEEE Transactions on Software Engineering*, 47(2), pp. 243–260, 2021.
2. A. Basiri et al., “Chaos Engineering,” *IEEE Software*, 33(3), pp. 35–41, 2016.
3. [Principles of Chaos Engineering](https://principlesofchaos.org).
4. D. Kikuta, H. Ikeuchi, and K. Tajiri, “LLM-Powered Fully Automated Chaos Engineering: Towards Enabling Anyone to Build Resilient Software Systems at Low Cost,” *IEEE/ACM ASE*, pp. 3861–3865, 2025. DOI: [10.1109/ASE63991.2025.00331](https://doi.org/10.1109/ASE63991.2025.00331).
5. H. Koziolek and N. Eskandani, “Lightweight Kubernetes Distributions: A Performance Comparison of MicroK8s, k3s, k0s, and MicroShift,” *ACM/SPEC ICPE*, pp. 17–29, 2023.
6. F. Beetz and S. Harrer, “GitOps: The Evolution of DevOps?,” *IEEE Software*, 39(4), pp. 70–75, 2022.
7. [Chaos Mesh Documentation](https://chaos-mesh.org/docs).
8. [Istio Documentation](https://istio.io/latest/docs).
9. T. Wilkie, [“The RED Method: How to Instrument Your Services,”](https://grafana.com/blog/2018/08/02/the-red-method-how-to-instrument-your-services/) Grafana Labs, 2018.
10. Kubernetes SIGs, [kind Documentation](https://kind.sigs.k8s.io/).
11. S. Yao et al., [“ReAct: Synergizing Reasoning and Acting in Language Models,”](https://arxiv.org/abs/2210.03629) *ICLR*, 2023.
12. KuardianAngelRing, [ChaosLab GitHub Repository](https://github.com/KuardianAngelRing/chaoslab), 2026.
