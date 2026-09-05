"""후보·detailing 검증 + 교정 재시도 러너 — Stub·Real 동일 적용 (서비스 밖 공통 함수).

생성 검증(스펙 §3): pydantic → chaos_type 존재 → (대상, 유형) 중복 폐기(하이브리드 2)
→ 서사 최소 길이(하이브리드 3) → 생존 1개 이상. 전멸 시 에러 요약을 feedback으로
1회만 재호출. detailing 검증: pydantic → chaos_specs.validate_params, 동일 재시도 1회.
"""
from __future__ import annotations

import json

from pydantic import ValidationError

from app.services.agent.hypothesis_schema import (
    CandidateProposal,
    DetailingResult,
    ImprovementProposalOut,
)
from app.services.chaos_specs import CHAOS_SPECS, validate_params
from app.services.improvement_specs import (
    container_names,
    manifest_workloads,
    validate_improvement,
)

_MIN_TITLE = 4
_MIN_NARRATIVE = 10


class HypothesisValidationError(RuntimeError):
    """재시도 후에도 유효 출력이 없을 때 — 워처가 failed 처리."""


def validate_candidates(raw_list, existing_pairs: set | frozenset = frozenset(),
                        ) -> tuple[list[CandidateProposal], list[str]]:
    """원시 출력 → (생존 후보, 폐기 사유). 후보 단위 폐기 — all-or-nothing 아님."""
    if not isinstance(raw_list, list):
        return [], ["출력이 JSON 배열이 아님"]
    survivors: list[CandidateProposal] = []
    errors: list[str] = []
    seen = set(existing_pairs)
    for i, raw in enumerate(raw_list, start=1):
        try:
            c = CandidateProposal.model_validate(raw)
        except ValidationError as e:
            first = e.errors()[0]
            errors.append(f"후보 {i}: 형식 오류 — {first.get('loc')} {first.get('msg')}")
            continue
        if c.chaos_type not in CHAOS_SPECS:
            errors.append(f"후보 {i}: 지원하지 않는 chaos_type '{c.chaos_type}'")
            continue
        key = (c.target_workload, c.chaos_type)
        if key in seen:
            errors.append(f"후보 {i}: (대상, 유형) 중복 — {key}")
            continue
        if (len(c.title.strip()) < _MIN_TITLE
                or len(c.hypothesis.strip()) < _MIN_NARRATIVE
                or len(c.expected_impact.strip()) < _MIN_NARRATIVE):
            errors.append(f"후보 {i}: 서사 필드(제목·가설·예상 영향)가 너무 짧음")
            continue
        seen.add(key)
        survivors.append(c)
    return survivors, errors


def run_generation(agent, payload) -> list[CandidateProposal]:
    """generate 호출 + 검증. 전멸 시 교정 재시도 1회, 재실패면 예외."""
    raw = agent.generate(payload)
    candidates, errors = validate_candidates(raw)
    if candidates:
        return candidates
    raw = agent.generate(payload, feedback="; ".join(errors) or "유효한 후보가 없었음")
    candidates, errors = validate_candidates(raw)
    if not candidates:
        raise HypothesisValidationError("후보 전멸: " + ("; ".join(errors) or "출력 없음"))
    return candidates


def run_concretize(agent, payload, user_text: str,
                   existing_pairs: set) -> CandidateProposal:
    """직접 입력 → 후보 1개 구체화. 기존 후보와의 (대상, 유형) 중복도 폐기 기준."""
    raw = agent.concretize(payload, user_text)
    candidates, errors = validate_candidates([raw], existing_pairs)
    if candidates:
        return candidates[0]
    raw = agent.concretize(payload, user_text,
                           feedback="; ".join(errors) or "유효한 후보가 없었음")
    candidates, errors = validate_candidates([raw], existing_pairs)
    if not candidates:
        raise HypothesisValidationError("직접 입력 후보 실패: " + ("; ".join(errors) or "출력 없음"))
    return candidates[0]


def _validate_detail(chaos_type: str, raw) -> tuple[dict, str, list[str]]:
    try:
        d = DetailingResult.model_validate(raw)
    except ValidationError as e:
        first = e.errors()[0]
        return {}, "", [f"형식 오류 — {first.get('loc')} {first.get('msg')}"]
    params, errors = validate_params(chaos_type, d.params)
    return params, d.rationale, errors


def run_detailing(agent, payload, candidate: CandidateProposal) -> tuple[dict, str]:
    """detail 호출 + params 범위 검증 → (정규화 params, rationale). 재시도 1회."""
    raw = agent.detail(payload, candidate)
    params, rationale, errors = _validate_detail(candidate.chaos_type, raw)
    if not errors:
        return params, rationale
    raw = agent.detail(payload, candidate, feedback="; ".join(errors))
    params, rationale, errors = _validate_detail(candidate.chaos_type, raw)
    if errors:
        raise HypothesisValidationError("params 검증 실패: " + "; ".join(errors))
    return params, rationale


# ── 3단 — 개선 제안 검증 (설계 2026-09-05 §2) ──

def validate_proposals(raw_list, manifest_yaml: str, max_proposals: int = 3,
                       ) -> tuple[list[ImprovementProposalOut], list[str]]:
    """원시 출력 → (생존 제안, 폐기 사유). 제안 단위 폐기: pydantic → 화이트리스트 →
    manifest에 deployment·container 존재 → (deployment, type, key|patch 지문) 중복."""
    if not isinstance(raw_list, list):
        return [], ["출력이 JSON 배열이 아님"]
    workloads = manifest_workloads(manifest_yaml)
    survivors: list[ImprovementProposalOut] = []
    seen: set = set()
    errors: list[str] = []
    for i, raw in enumerate(raw_list, start=1):
        try:
            p = ImprovementProposalOut.model_validate(raw)
        except ValidationError as e:
            first = e.errors()[0]
            errors.append(f"제안 {i}: 형식 오류 — {first.get('loc')} {first.get('msg')}")
            continue
        normalized, spec_errors = validate_improvement(p.model_dump())
        if spec_errors:
            errors.append(f"제안 {i}: " + "; ".join(spec_errors))
            continue
        doc = workloads.get(normalized["deployment"])
        if doc is None:
            errors.append(f"제안 {i}: manifest에 없는 Deployment '{normalized['deployment']}'")
            continue
        names = set(container_names(doc))
        if normalized["container"] and normalized["container"] not in names:
            errors.append(f"제안 {i}: {normalized['deployment']}에 없는 컨테이너 '{normalized['container']}'")
            continue
        for c in ((normalized.get("patch") or {}).get("spec") or {}).get("template", {}) \
                .get("spec", {}).get("containers", []):
            if c["name"] not in names:
                errors.append(f"제안 {i}: {normalized['deployment']}에 없는 컨테이너 '{c['name']}'")
                break
        else:
            fingerprint = (normalized["deployment"], normalized["type"],
                           normalized["key"] or json.dumps(normalized["patch"], sort_keys=True))
            if fingerprint in seen:
                errors.append(f"제안 {i}: 중복 제안 — {fingerprint[:2]}")
                continue
            if len(p.title.strip()) < _MIN_TITLE or len(p.rationale.strip()) < _MIN_NARRATIVE:
                errors.append(f"제안 {i}: 제목·근거가 너무 짧음")
                continue
            seen.add(fingerprint)
            survivors.append(ImprovementProposalOut(**{**p.model_dump(), **normalized}))
    return survivors[:max_proposals], errors


def run_proposing(agent, payload) -> list[ImprovementProposalOut]:
    """propose_improvements 호출 + 검증. 전멸 시 교정 재시도 1회, 재실패면 예외."""
    raw = agent.propose_improvements(payload)
    proposals, errors = validate_proposals(raw, payload.manifest_yaml, payload.max_proposals)
    if proposals:
        return proposals
    raw = agent.propose_improvements(payload, feedback="; ".join(errors) or "유효한 제안이 없었음")
    proposals, errors = validate_proposals(raw, payload.manifest_yaml, payload.max_proposals)
    if not proposals:
        raise HypothesisValidationError("개선 제안 전멸: " + ("; ".join(errors) or "출력 없음"))
    return proposals
