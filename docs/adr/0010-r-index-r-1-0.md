# ADR-0010: 최종 회귀 R 지수 R-1.0

- 상태: 승인
- 적용 범위: `ScenarioRun` 개선 전 검증과 최종 회귀 비교

## 결정

R 지수는 동일한 시나리오 집합의 개선 전·후 결과를 각각 다음 식으로 계산한다.

```text
R = 100 × (0.45P + 0.20E + 0.20H + 0.15T)
```

- `P`: 전체 시나리오 중 `passed` 비율
- `E`: 각 시나리오의 필수 복원력 판정 항목 중 충족한 비율
- `H`: 실제 요청 오류율과 p95 응답시간의 품질 점수 평균
  - 오류율 점수: `1 - min(error_rate_pct / 100, 1)`
  - 응답시간 점수: `1 - min(p95_latency_ms / (2 × max_p95_latency_ms), 1)`
- `T`: 실제 복구시간 점수 평균
  - `1 - min(recovery_seconds / max_recovery_seconds, 1)`

각 구성점수는 0~1 범위로 제한하고 최종 R은 소수점 첫째 자리까지 저장한다. 등급은 A(85 이상), B(70 이상), C(70 미만)로 표시한다.

필수 관측, 장애 주입 확인 또는 정리가 누락되어 하나라도 `inconclusive`이면 해당 회차의 R은 산정하지 않는다. 누락값을 추정하거나 stub 값을 대체하지 않는다.

## 근거 데이터

R 계산에는 `ScenarioRun.baseline_results`와 `ScenarioRun.results`에 저장된 실제 HTTP probe, Pod Ready, restart, 복구시간 및 결정론적 판정만 사용한다. LLM은 R 계산과 판정을 변경할 수 없고 확정된 결과의 설명만 작성한다.
