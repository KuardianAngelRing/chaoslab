# 회귀 판정 기준 튜닝 · 개선 승인 단계 — 팀 결정 메모 (2026-09-05)

> **결정(2026-09-05): 권장 조합 A1 + B1 + B3 채택** — 같은 날 반영 완료.
> - A1 `real/chaos.py` `render_chaos_manifest`: PodChaos(pod-kill·pod-failure·container-kill) `mode: one`, Network/Stress는 `all`.
> - B1 `observations.py`: 샘플당 요청 3회(`REQUESTS_PER_SAMPLE`), 오류율·p95·상태코드는 요청 수 기준. `regression._run_one`: 장애 구간 최소 6샘플(`_MIN_FAULT_SAMPLES`), 원샷 액션도 grace 동안 계속 관측.
> - B3 `r_index.compute`: 장애 구간 트래픽 근거(rps·5xx·상태코드 분포)가 없으면 `r=None`(`traffic_observed`·`reason` 추가), 항목 점수는 유지. 2단계 카드는 종료 후 None을 "산정 불가"로 표시.
> - `DEFAULT_CRITERIA`·`evaluate_experiment`는 변경 없음(구조 원인 제거로 충분).
> - 라이브 재검증(ScenarioRun 6, 09/05): nginx pod-kill baseline·final 모두 passed — 장애 구간 6샘플/18요청 오류 0%, 최소 Ready 1, 회복 1.1s/1.0s. 이전 run 5(failed, 오류 50%·Ready 0)와 대비.

## 1. 왜 회귀가 계속 failed인가 — 원인은 튜닝이 아니라 구조

09/05 nginx pod-kill 회귀(ScenarioRun 5)와 08/31 order-resilience-lab(ScenarioRun 2·3) 실데이터:

| 라운드 | during 오류율 | during p95 | during 최소 Ready | 회복 | failed_checks |
|---|---|---|---|---|---|
| baseline | 100% | 80ms | **0** | 6.1s | error_rate · ready_pods · post_recovered |
| final | 50% | 101ms | **0** | 0.7s | error_rate · ready_pods |

기준 `DEFAULT_CRITERIA` = 오류율 ≤20% · p95 ≤1500ms · 회복 ≤30s · **Ready ≥1**.

핵심: `real/chaos.py`가 Chaos Mesh CRD를 **`mode: all`**로 만들고(라인 46), 가설 경로 selector는 ns 전체(또는 워크로드 matchLabels 전체)다. 즉 pod-kill은 **레플리카 2개를 동시에 죽인다** → 장애 구간 Ready 0 · 요청 전부 실패는 설계상 필연이며, 어떤 개선(env·타임아웃)으로도 `ready_pods ≥ 1`을 만족시킬 수 없다. 오류율도 장애 구간 샘플이 2~3개뿐이라 1건 실패 = 33~50%로 튄다.

→ "기준값을 앱별로 받자"는 이 문제를 풀지 못한다. 결정할 것은 **(A) 장애 강도**와 **(B) 판정 구간·샘플 수**다.

## 2. 선택지

### A. 장애 강도 — pod-kill 대상 수

| 안 | 내용 | 장점 | 단점 |
|---|---|---|---|
| **A1 (권장)** | pod-kill · container-kill · pod-failure는 `mode: one`(또는 `fixed-percent: 50`) — 레플리카 ≥2인 워크로드에서 "1개 손실에도 서비스 유지"를 검증 | 카오스 엔지니어링의 표준 시나리오, `min_ready_pods=1`이 의미를 갖고 개선 효과(preStop·readiness 튜닝)가 판정에 드러난다 | 레플리카 1 워크로드는 여전히 Ready 0 — 그 경우 A2 병행 |
| A2 | `mode: all` 유지, 판정을 **회복 구간(after) 중심**으로 — during 검사는 정보성으로 강등 | 코드 변경 최소(`evaluate_experiment` checks 조정) | "장애 중에 서비스가 버텼는가"라는 원래 질문에 답하지 못함. R지수 P·E 항이 거의 항상 통과라 변별력 감소 |
| A3 | 가설 detailing이 `mode`도 파라미터로 산출(`chaos_specs`에 `mode` 필드) | 가장 유연 | 스펙·검증·UI 확장 필요, 지금 필요한 건 기본값 |

### B. 판정 구간·샘플 수

| 안 | 내용 |
|---|---|
| **B1 (권장)** | during 샘플을 최소 6개(30초/5초)로 보장 — 원샷 액션은 주입 확인 즉시 종료하지 말고 `_PODKILL_GRACE_S` 동안 계속 샘플링. 오류율은 샘플 비율이 아니라 **요청 성공률**로 (샘플당 요청 1회 → 3회) |
| B2 | 오류율 기준을 앱별 폼 입력으로(가설 detailing 산출값) — `criteria`를 후보가 채움. A1·B1 뒤에 해도 늦지 않음 |
| B3 | **무트래픽·HTTP 메트릭 미노출 실험은 R지수 미산정** — k3s 실측 연결 후 nginx는 오류율 0·p99 0 → 가용성·레이턴시 항이 자동 만점(≈0.99). `r_index.compute`에 `rps_max == 0 and http_5xx_count == 0`이면 `r=None`(판정 불가) 반환. Stub 값 0.72와의 혼동도 함께 정리 |

## 3. 권장 조합과 반영 순서

1. **A1 + B1 + B3** — 파일: `real/chaos.py`(mode) · `regression._run_one`(샘플링) · `resilience.evaluate_experiment`(요청 성공률) · `r_index.compute`(미산정 조건). 각 파일 1곳씩, 테스트 `test_scenario_runs`·`test_r_index` 갱신.
2. 반영 후 nginx(레플리카 2) 회귀 재실행 → baseline이 passed 근처로 오면 개선 단계(§4)가 "차이"를 만들 자리가 생긴다.

## 4. 개선 단계 승인 UI(휴먼인더루프) — 설계 초안

현재 3단계 회귀는 baseline과 final을 **같은 조건**으로 돌린다(`improvements: []`). 채워야 할 흐름:

```
2단계 실험 종료 → [AI 개선안 생성] → 객관식 카드(1~3개) → 사용자 승인/편집 → 3단계 회귀(baseline → 개선 적용 → final)
```

- **데이터**: `HypothesisRun`에 `ImprovementProposal`(1:N) — `type`("deployment_env" | "manifest_patch") · `deployment` · `patch`(JSON) · `rationale` · `status`(proposed/approved/rejected) · `expected_effect`. 승인분만 `scenario_snapshot_from_hypothesis`의 `improvements`로 흘린다.
- **생성**: `HypothesisAgentService`에 `propose_improvements(handoff, experiment)` 추가 — 입력은 기존 핸드오프 계약(`GET /experiments/{id}/handoffs/latest`) + 실험 fault/recovery 요약. Stub은 고정 2안, claude는 CLI 프롬프트(가설 생성과 동일 검증+교정 1회 패턴).
- **적용**: `regression._apply_improvements`는 `deployment_env`만 지원 → `manifest_patch` 타입 추가(`K3sWorkloadService.patch_workload(namespace, kind, name, json_patch)` — strategic merge patch, 롤백은 원본 보관). 허용 범위는 중간보고서 확정대로 **Istio timeout/retry/circuitBreaker + Deployment probe/preStop/resources**로 화이트리스트(`improvement_specs.py`, chaos_specs와 같은 순수 검증).
- **UI**: 셸 2단계와 3단계 사이에 "개선안" 서브스텝(`_hypothesis_improve.html`) — 후보 선택 탭과 동일한 radio/checkbox 카드 + 근거 + diff 미리보기. 승인 없이 "개선 없이 회귀"도 허용(지금 동작 유지).
- **의존**: §3의 판정 조정이 먼저여야 개선 전후 차이가 판정에 나타난다.

## 5. 정리 대상(코드 무관)

- `hypothesis_runs` id 2·3 `goal_text` mojibake — 08/31 curl 인코딩 문제. 로컬 DB 행이므로 삭제 또는 무시.
- k3s `chaoslab-session-nginx-5` · `chaoslab-session-order-resilience-lab-10` ns 잔존 — 다음 준비 세션 생성 시 앱이 정리.
