# 가설 수립 에이전트 비교 — chaoslab 스펙 vs ChaosPilot upstream (2026-08-25)

**세션 인계 문서.** 다른 기기/세션에서 이어갈 수 있도록 비교 결과·권고·미결 결정을 기록한다.

## 현재 상태 (어디까지 했나)

1. **grill 세션 완료** — 가설 수립 단계 설계 확정: `2026-08-25-hypothesis-stage-design.md`(같은 폴더) + ADR-0010(LangGraph 폐기, 퓨어 Python + claude 구독제 `claude -p`) + GLOSSARY("가설 수립"·"가설 수립 요청" 등재).
2. **ChaosPilot(구 agent 레포) upstream/main과 비교 완료** — 아래 결과.
3. **✅ 결정 완료 (2026-08-25, 시웅)**: 하이브리드안 **1~5 전부 채택**. 단, 본 문서의 "미이식 권고"와 달리 **선택 후 detailing 2차 호출 구조도 채택**(후보=서사만, params는 선택 후 `detail` 호출로 구체화). 장애 유형도 9종으로 확장(선행 작업 완료 — network-delay·loss·partition·bandwidth / pod-kill·pod-failure·container-kill / cpu-stress·memory-stress). 스펙 문서 2차 개정 반영 완료 → 구현 단계.

## 비교 기준

- 우리: `docs/superpowers/specs/2026-08-25-hypothesis-stage-design.md`
- ChaosPilot: `KuardianAngelRing/agent` **upstream/main = 커밋 `72379a1`** (Qwen vLLM 전환 이후). 로컬 체크아웃(`~/projects/agent`)은 이보다 뒤처져 있으니 재검증 시 `git fetch upstream` 후 `git show upstream/main:<path>`로 볼 것.

## 핵심 비교

| 축 | chaoslab 스펙 | ChaosPilot upstream/main |
|---|---|---|
| LLM | claude 구독제 CLI 단발 호출 | 자체 Qwen vLLM 35B(`cp.jun0.dev/v1`), 2-pass 제한 추론(draft 512tok→finalize), JSON 스키마 강제 미사용(펜스 벗기기+`json.loads`가 유일 방어선) |
| 후보의 주체 | **LLM이 대상·유형·params 전부 선택**(chaos_specs 범위 검증) | **서버 결정론 코드가 대상·유형 확정**(`llm_client.py:348-404` directives: 우선순위·기회 점수·fault 중복 금지), LLM은 서사만 채움 |
| 입력 | manifest **원문** + 허용 범위 + 검증 목표 + **과거 실험 이력** | 후보 프롬프트에 manifest 원문 **미포함**(화이트리스트 요약·findings만, `_candidate_context`). 과거 이력 반영 **없음**(무상태, seed 고정이라 재실행해도 같은 후보) |
| params 시점 | 생성 시점 포함 → 선택 후 LLM 재호출 없음 | 후보엔 params 금지 → 선택 후 detailing 2차 호출(chaos_yaml) + 7단 검증 + repair 최대 3회. 최종 CR은 서버가 덮어씀 |
| 실패 모드 | 후보 단위 폐기 + 전멸 시 교정 재시도 1회 | **all-or-nothing** — JSON 깨지면 후보 전체 실패, 재시도 없음 |
| 진행 표시 | 상태 SSE(generating/ready/failed)만 | 추론 델타 SSE 실시간 스트리밍 + 단계별 진행률(broker 직송 + DB 폴링 2채널) |
| 라이브 전제 | 없음 — k3s 현장 배포라 가설 시점에 앱 미기동 | 라이브 클러스터 조회 + eligible target 게이트(ready pod 필수) |
| 비용/취소/재현성 | 구독제 정액 · Run 중지 시 조기종료 · (권고: 모델 스냅샷 기록) | 토큰/비용 추적 없음 · 취소 API 없음 · `model_snapshot` 기록 있음 |

## 판단

- ChaosPilot의 무거운 결정론 골격은 **약한 모델(35B)+취약한 JSON 파싱에 대한 보상 장치**다. 우리는 강한 모델 + `chaos_specs` 서버 검증이 있으므로 manifest 원문 + LLM 전체 선택권이 유효하고 더 단순하다.
- 그들의 라이브 조회·eligible 게이트는 우리 k3s 현장 배포 모델(ADR-0009)과 구조적으로 불일치.
- 그들의 무상태 후보 생성은 약점 — 우리의 과거 이력 반영이 우위.
- **결론(권고): 골격은 우리 스펙 유지, ChaosPilot의 품질 장치만 이식하는 하이브리드.**

## 권고 하이브리드안 — 이식 목록 (⏳ 승인 대기)

승인 시 `2026-08-25-hypothesis-stage-design.md`의 §1(계약)·§3(서비스 검증)·§2(저장)에 반영:

1. **프롬프트 규칙 5종** (ChaosPilot `llm_client.py:331-342`에서 검증된 문구):
   ① 근거는 제공된 사실만 인용, 수치·장애이력 날조 금지 ② 매출 손실·데이터 유실 등 임팩트 환각 차단 ③ 비전문가용 한국어(Pod·PDB 등 용어 미설명 사용 금지 — 승인 게이트를 판단으로 만드는 ADR-0007 정신) ④ 제공된 개선 수단으로 고칠 수 있는 약점만 제안("전부 죽이면 당연히 죽는다" 류 배제) ⑤ 가설은 실패 예상형.
2. **다양성·중복**: 프롬프트에 fault 유형 중복 금지 + 서버 검증에 `(대상 워크로드, chaos_type)` 중복 후보 폐기 추가.
3. **품질 게이트**: 서사 필드(제목·가설·예상 영향) 최소 길이 검증을 3단 검증에 추가.
4. **`HypothesisRun`에 모델 스냅샷 컬럼**(모델명·CLI 버전) — 재현성.
5. (선택) **manifest 정적 분석 요약** — replica 1·probe 없음·resource limit 없음 findings를 서버가 뽑아 원문과 *함께* 페이로드에 제공(원문 대체 아님).

**이식하지 않기로 권고**: 결정론 directives · 선택 후 detailing 2차 호출 · 2-pass 제한 추론 · 라이브 eligible 게이트. **후속 증분으로 보류**: 추론 실시간 스트리밍(`claude -p --output-format stream-json`) — UX 좋지만 첫 슬라이스엔 과함.

**Slice 5 참고 메모**: ChaosPilot은 network/stress 실험을 SLI 판정 수단(서비스 바인딩+헬스체크) 있을 때만 생성한다. 우리도 network-delay 성패 판정에서 같은 문제를 만난다.

## 다음 세션이 할 일 (순서)

1. 이 문서 + `2026-08-25-hypothesis-stage-design.md` 읽기.
2. 시웅에게 **하이브리드안 1~5 채택 여부**(특히 5번 포함 여부) 확인 → 스펙 문서 갱신.
3. 스펙 순서대로 구현: 계약(`hypothesis_schema.py`) → 저장(models·repositories) → 서비스(Protocol+Stub+`ClaudeCliHypothesisAgent`) → 라우터+워처+SSE → UI 배선 → 시드·테스트.
4. 구현 후 첫 기동 전 `chaoslab.db` 삭제 필요(`Experiment.candidate_id` 컬럼 추가로 구 DB 깨짐).
