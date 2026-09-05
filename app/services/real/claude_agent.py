"""ClaudeCliHypothesisAgent — claude 구독제 CLI(`claude -p`) 단발 호출 (ADR-0010).

도구 없이 순수 추론: 페이로드 JSON + 출력 스키마 명세를 stdin으로 넘기고 JSON만
받는다. 클러스터 자격증명 미전달. 검증·재시도는 hypothesis_validation(공통)이 담당
— 여기는 호출·파싱만. 라이브 검증 전(플래그·출력 형식은 CLI 버전에 따라 조정 여지).
"""
from __future__ import annotations

import json
import subprocess

from app.services.agent.hypothesis_schema import (
    CandidateProposal,
    HypothesisInputPayload,
    ImprovementInputPayload,
)

# 하이브리드 1 — ChaosPilot에서 검증된 프롬프트 규칙 5종 + fault 중복 금지(하이브리드 2)
_RULES = """규칙 (반드시 지킬 것):
1. 근거는 제공된 페이로드의 사실만 인용한다. 수치·장애 이력·시스템 특성을 지어내지 않는다.
2. 매출 손실·데이터 유실 같은 확인 불가능한 임팩트를 단정하지 않는다.
3. 비전문가가 읽는 한국어로 쓴다. Pod·PDB 같은 용어를 설명 없이 쓰지 않는다.
4. 제공된 개선 수단으로 고칠 수 있는 약점만 제안한다. "전부 죽이면 당연히 죽는다"류 자명한 실험은 제외한다.
5. 가설은 실패 예상형으로 쓴다 (예: "…하면 …이 실패할 것이다").
6. 같은 fault 유형(chaos_type)을 여러 후보에 중복 사용하지 않는다."""

_CANDIDATE_SCHEMA = """각 후보는 다음 키만 갖는 JSON 객체다 (params 금지 — 수치는 선택 후 별도 단계):
{"title": "짧은 제목", "chaos_type": "allowed_chaos의 chaos_type 중 하나",
 "target_workload": "manifest의 Deployment 이름", "hypothesis": "실패 예상형 가설 한 문장",
 "expected_impact": "예상 영향 한두 문장"}"""

_IMPROVEMENT_SCHEMA = """각 제안은 다음 키만 갖는 JSON 객체다:
{"title": "짧은 제목(예: readinessProbe 주기 단축)", "type": "deployment_env" 또는 "manifest_patch",
 "deployment": "manifest의 Deployment 이름", "container": "컨테이너 이름(replicas만 바꾸면 빈 문자열)",
 "key": "deployment_env일 때 환경변수 이름(아니면 빈 문자열)", "value": "deployment_env일 때 새 값(아니면 빈 문자열)",
 "patch": manifest_patch일 때 Deployment 루트 기준 strategic merge patch 객체(아니면 {}),
 "rationale": "phase_summaries·manifest 사실을 인용한 근거 한두 문장", "expected_effect": "기대 효과 한두 문장"}
patch는 allowed_improvements에 열거된 경로만 담는다. probe가 없던 컨테이너에 probe를 추가할 때는 핸들러(httpGet/tcpSocket)를 포함한다.
deployment_env는 manifest에 이미 정의된 환경변수만 바꾼다. 같은 (deployment, 경로)를 두 제안에 중복하지 않는다."""

# 순수 추론 강제 — 도구 전면 차단
_DISALLOWED_TOOLS = "Bash,Edit,Write,NotebookEdit,Read,Glob,Grep,WebFetch,WebSearch,Task"


class ClaudeCliHypothesisAgent:
    def __init__(self, settings):
        self.s = settings
        self._model_name = ""
        self._cli_version = ""

    # ── CLI 호출 ──
    def _invoke(self, prompt: str) -> str:
        cmd = [self.s.claude_bin, "-p", "--output-format", "json",
               "--disallowedTools", _DISALLOWED_TOOLS]
        if self.s.hypothesis_model:
            cmd += ["--model", self.s.hypothesis_model]
        proc = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                              timeout=self.s.hypothesis_timeout_seconds)
        if proc.returncode != 0:
            raise RuntimeError(
                f"claude CLI 실패 (exit {proc.returncode}): {proc.stderr.strip()[:500]}")
        data = json.loads(proc.stdout)
        if data.get("is_error"):
            raise RuntimeError(f"claude CLI 오류 응답: {str(data.get('result'))[:500]}")
        model_usage = data.get("modelUsage") or {}
        if model_usage:
            self._model_name = next(iter(model_usage))
        return data.get("result", "")

    @staticmethod
    def _parse_json(text: str):
        """모델이 코드펜스로 감싼 경우 벗기고 파싱."""
        t = text.strip()
        if t.startswith("```"):
            t = t.split("\n", 1)[1] if "\n" in t else ""
            if t.rstrip().endswith("```"):
                t = t.rstrip()[:-3]
        return json.loads(t)

    def _payload_block(self, payload: HypothesisInputPayload) -> str:
        return "입력 페이로드:\n" + json.dumps(payload.model_dump(), ensure_ascii=False)

    @staticmethod
    def _feedback_block(feedback: str) -> str:
        if not feedback:
            return ""
        return f"\n\n직전 출력이 검증에 실패했다. 사유를 고쳐 다시 출력하라: {feedback}"

    # ── HypothesisAgentService ──
    def generate(self, payload: HypothesisInputPayload, feedback: str = "") -> list:
        prompt = (
            "너는 카오스 엔지니어링 실험 설계자다. 아래 앱 정보를 근거로 "
            f"실험 후보 {payload.candidate_count}개를 제안하라.\n\n"
            f"{_RULES}\n\n{_CANDIDATE_SCHEMA}\n\n"
            "출력은 후보 JSON 객체들의 배열 하나만. 다른 텍스트 금지.\n\n"
            f"{self._payload_block(payload)}{self._feedback_block(feedback)}"
        )
        return self._parse_json(self._invoke(prompt))

    def concretize(self, payload: HypothesisInputPayload, user_text: str,
                   feedback: str = "") -> dict:
        prompt = (
            "너는 카오스 엔지니어링 실험 설계자다. 사용자가 요청한 시나리오를 "
            "실험 후보 1개로 구체화하라.\n\n"
            f"사용자 요청: {user_text}\n\n"
            f"{_RULES}\n\n{_CANDIDATE_SCHEMA}\n\n"
            "출력은 후보 JSON 객체 하나만. 다른 텍스트 금지.\n\n"
            f"{self._payload_block(payload)}{self._feedback_block(feedback)}"
        )
        return self._parse_json(self._invoke(prompt))

    def detail(self, payload: HypothesisInputPayload, candidate: CandidateProposal,
               feedback: str = "") -> dict:
        spec = next((a for a in payload.allowed_chaos
                     if a.chaos_type == candidate.chaos_type), None)
        fields = spec.fields if spec else {}
        prompt = (
            "너는 카오스 엔지니어링 실험 설계자다. 선택된 실험 후보의 주입 파라미터를 "
            "확정하라.\n\n"
            f"선택된 후보: {json.dumps(candidate.model_dump(), ensure_ascii=False)}\n"
            f"허용 파라미터({candidate.chaos_type}): {json.dumps(fields, ensure_ascii=False)}\n\n"
            f"{_RULES}\n\n"
            '출력은 {"params": {필드명: 값}, "rationale": "값 선정 근거 한 문장"} JSON 객체 '
            "하나만. params의 필드는 허용 파라미터에 있는 것 전부이며 min~max 범위를 "
            "지킨다. 다른 텍스트 금지.\n\n"
            f"{self._payload_block(payload)}{self._feedback_block(feedback)}"
        )
        return self._parse_json(self._invoke(prompt))

    def propose_improvements(self, payload: ImprovementInputPayload, feedback: str = "") -> list:
        prompt = (
            "너는 카오스 엔지니어링 개선 설계자다. 아래 실험 결과(phase_summaries)와 manifest를 근거로 "
            f"이 앱의 회복탄력성을 높일 개선안을 최대 {payload.max_proposals}개 제안하라. "
            "개선은 실험 전용 namespace의 Deployment에 적용돼 같은 장애를 다시 주입해 검증된다.\n\n"
            f"{_RULES}\n\n{_IMPROVEMENT_SCHEMA}\n\n"
            "출력은 제안 JSON 객체들의 배열 하나만. 다른 텍스트 금지.\n\n"
            f"입력 페이로드:\n{json.dumps(payload.model_dump(), ensure_ascii=False)}"
            f"{self._feedback_block(feedback)}"
        )
        return self._parse_json(self._invoke(prompt))

    def snapshot(self) -> dict:
        """하이브리드 4 — 재현성용 모델·CLI 버전 스냅샷."""
        if not self._cli_version:
            try:
                out = subprocess.run([self.s.claude_bin, "--version"],
                                     capture_output=True, text=True, timeout=15)
                self._cli_version = out.stdout.strip()[:50]
            except Exception:
                self._cli_version = "unknown"
        return {"model_name": self._model_name, "cli_version": self._cli_version}
