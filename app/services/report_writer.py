"""확정된 최종 회귀 사실만 사용해 보고서 서술을 작성한다."""
from __future__ import annotations

import json
import re

import httpx

from app.config import settings
from app.services.improvement_specs import change_rows


_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "executive_summary", "key_findings", "improvement_explanation",
        "scenario_summaries", "residual_risks", "final_conclusion",
    ],
    "properties": {
        "executive_summary": {"type": "string"},
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "improvement_explanation": {"type": "array", "items": {"type": "string"}},
        "scenario_summaries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["id", "summary", "conclusion"],
                "properties": {
                    "id": {"type": "string"},
                    "summary": {"type": "string"},
                    "conclusion": {"type": "string"},
                },
            },
        },
        "residual_risks": {"type": "array", "items": {"type": "string"}},
        "final_conclusion": {"type": "string"},
    },
}


def write_report(facts: dict) -> dict:
    fallback = deterministic_report(facts)
    if not settings.openai_api_key:
        return {**fallback, "source": "deterministic", "model": ""}
    try:
        with httpx.Client(timeout=45) as client:
            response = client.post(
                "https://api.openai.com/v1/responses",
                headers={"Authorization": f"Bearer {settings.openai_api_key}"},
                json={
                    "model": settings.report_llm_model,
                    "reasoning": {"effort": settings.report_llm_reasoning_effort},
                    "input": [
                        {
                            "role": "developer",
                            "content": [{"type": "input_text", "text": (
                                "당신은 ChaosLab 최종 결과 보고서 작성자입니다. 입력 JSON의 확정 사실만 사용해 "
                                "간결하지만 충분한 한국어 보고서 문장을 작성하세요. 숫자, 원인, 조치, 판정을 "
                                "추가하거나 변경하지 마세요. 데이터가 없는 잔여 위험은 만들지 마세요."
                            )}],
                        },
                        {"role": "user", "content": [{"type": "input_text", "text": json.dumps(facts, ensure_ascii=False)}]},
                    ],
                    "text": {"format": {"type": "json_schema", "name": "chaoslab_report",
                                         "strict": True, "schema": _SCHEMA}},
                },
            )
            response.raise_for_status()
        content = json.loads(_response_text(response.json()))
        _validate_content(content, facts)
        return {**content, "source": "openai", "model": settings.report_llm_model}
    except (httpx.HTTPError, ValueError, KeyError, TypeError, json.JSONDecodeError):
        return {**fallback, "source": "deterministic", "model": ""}


def deterministic_report(facts: dict) -> dict:
    comparison = facts["comparison"]
    before = comparison["before"]
    after = comparison["after"]
    r = comparison["r"]
    r_sentence = "R 지수는 필수 관측값 부족으로 산정하지 않았습니다."
    if r["before"]["available"] and r["after"]["available"]:
        r_sentence = (
            f"R 지수는 개선 전 {r['before']['score']}점에서 개선 후 {r['after']['score']}점으로 "
            f"{_delta_text(r['delta'])}."
        )
    verdict = comparison["verdict"]
    verdict_text = {"passed": "전체 최종 회귀 통과", "failed": "최종 회귀 기준 미충족",
                    "inconclusive": "일부 시나리오 판정 불가"}[verdict]
    scenario_summaries = []
    residual_risks = []
    for scenario in comparison["scenarios"]:
        before_metrics = scenario["before_metrics"]
        after_metrics = scenario["after_metrics"]
        summary = (
            f"초기 판정은 {_verdict_ko(scenario['before_verdict'])}, 최종 판정은 "
            f"{_verdict_ko(scenario['after_verdict'])}입니다. 장애 구간 오류율은 "
            f"{_value(before_metrics['error_rate_pct'], '%')}에서 {_value(after_metrics['error_rate_pct'], '%')}로, "
            f"p95는 {_value(before_metrics['p95_latency_ms'], 'ms')}에서 "
            f"{_value(after_metrics['p95_latency_ms'], 'ms')}로 관측됐습니다."
        )
        conclusion = "동일 조건 재검증에서 개선이 확인됐습니다." if scenario["improved"] else (
            "동일 조건에서 최종 기준을 충족했습니다." if scenario["after_verdict"] == "passed"
            else "최종 기준 미충족 항목이 남아 있습니다."
        )
        scenario_summaries.append({"id": scenario["id"], "summary": summary, "conclusion": conclusion})
        if scenario["after_verdict"] != "passed":
            residual_risks.append(f"{scenario['title']}: {', '.join(scenario['failed_checks_after']) or '실험 유효성 확인 필요'}")
    changes = [
        f"{item['deployment']}의 {row['path']} 값을 {_change_value(row['before'])}에서 "
        f"{_change_value(row['after'])}로 변경하고 rollout Ready를 확인했습니다."
        for item in comparison["changes"]
        for row in change_rows(item, only_changed=True)
    ]
    return {
        "executive_summary": (
            f"{facts['app_name']}에 대해 동일한 {after['total']}개 시나리오를 개선 전과 개선 후에 실행했습니다. "
            f"최종 결과는 {verdict_text}이며, {r_sentence}"
        ),
        "key_findings": [
            f"시나리오 통과율은 {before['pass_rate_pct']}%에서 {after['pass_rate_pct']}%로 변경됐습니다.",
            f"장애 구간 평균 오류율은 {_value(before['error_rate_pct'], '%')}에서 {_value(after['error_rate_pct'], '%')}로 변경됐습니다.",
            f"평균 복구시간은 {_value(before['recovery_seconds'], '초')}에서 {_value(after['recovery_seconds'], '초')}로 변경됐습니다.",
        ],
        "improvement_explanation": changes,
        "scenario_summaries": scenario_summaries,
        "residual_risks": residual_risks,
        "final_conclusion": (
            f"{verdict_text}. 보고된 수치와 판정은 저장된 HTTP probe, Kubernetes 상태, "
            "장애 주입 및 정리 결과를 기준으로 확정했습니다."
        ),
    }


def _response_text(payload: dict) -> str:
    for item in payload.get("output") or []:
        if item.get("type") != "message":
            continue
        for content in item.get("content") or []:
            if content.get("type") == "output_text" and content.get("text"):
                return content["text"]
    raise ValueError("Responses API 응답에 구조화 출력이 없습니다")


def _validate_content(content: dict, facts: dict) -> None:
    required = set(_SCHEMA["required"])
    if set(content) != required:
        raise ValueError("보고서 필드가 계약과 다릅니다")
    expected_ids = {item["id"] for item in facts["comparison"]["scenarios"]}
    actual_ids = {item.get("id") for item in content["scenario_summaries"]}
    if actual_ids != expected_ids:
        raise ValueError("시나리오 ID가 실행 결과와 다릅니다")
    fact_numbers = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(facts, ensure_ascii=False))) | {"1", "0"}
    output_numbers = set(re.findall(r"\d+(?:\.\d+)?", json.dumps(content, ensure_ascii=False)))
    if not output_numbers <= fact_numbers:
        raise ValueError("보고서에 입력 근거에 없는 숫자가 포함됐습니다")


def _verdict_ko(value: str) -> str:
    return {"passed": "통과", "failed": "실패", "inconclusive": "판정 불가"}.get(value, value)


def _delta_text(value: float | None) -> str:
    if value is None:
        return "비교할 수 없습니다"
    if value > 0:
        return f"{value}점 상승했습니다"
    if value < 0:
        return f"{abs(value)}점 하락했습니다"
    return "변화가 없습니다"


def _value(value, suffix: str) -> str:
    return "관측 없음" if value is None else f"{value}{suffix}"


def _change_value(value) -> str:
    """전후 값 표기 — 없던 필드는 '없음', 객체(핸들러 등)는 compact JSON."""
    if value is None:
        return "없음"
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
    return str(value)
