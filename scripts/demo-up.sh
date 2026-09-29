#!/usr/bin/env bash
# EKS 시연 로컬 기동 — Iac-aws `scripts/up.sh`가 끝난 뒤 한 번 실행한다.
#   1) argo 빌드 파이프라인 적용(argo/apply.sh)   2) Prometheus port-forward 루프(9090)
#   3) 부띠끄 App 행 등록(전용 live DB)            4) 실서비스 모드로 uvicorn 기동
# .env는 건드리지 않는다 — 실서비스 값은 환경변수 override로만 넘긴다(pydantic-settings 우선순위).
# 전제: kubectl 컨텍스트 = chaos-eks(up.sh가 설정), .venv 준비, claude CLI 로그인.
# 종료: scripts/demo-down.sh (로컬 프로세스 정리, --destroy면 Iac-aws down.sh까지)
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="/opt/homebrew/bin:$PATH"
cd "$DIR"

SUT_NS="${SUT_NAMESPACE:-online-boutique}"
DB_URL="${DATABASE_URL:-sqlite:///./chaoslab-live.db}"   # 개발 DB(chaoslab.db, mock seed)와 분리
PORT="${PORT:-8000}"
LOG_DIR="${LOG_DIR:-/tmp/chaoslab-demo}"
mkdir -p "$LOG_DIR"

echo "=== 사전 확인 ==="
for cmd in kubectl curl claude; do
  command -v "$cmd" >/dev/null || { echo "❌ '$cmd' 없음"; exit 1; }
done
[ -x .venv/bin/uvicorn ] || { echo "❌ .venv 없음 — CLAUDE.md 실행 절차로 venv 먼저"; exit 1; }
kubectl config current-context 2>/dev/null | grep -q chaos-eks || { echo "❌ kubectl 컨텍스트가 chaos-eks가 아님 — Iac-aws up.sh 먼저"; exit 1; }
kubectl get ns "$SUT_NS" >/dev/null 2>&1 || { echo "❌ 네임스페이스 $SUT_NS 없음"; exit 1; }
echo "  ok (ns=$SUT_NS, db=$DB_URL)"

echo "=== [1/4] argo 빌드 파이프라인 ==="
bash argo/apply.sh

echo "=== [2/4] Prometheus port-forward 루프 (localhost:9090) ==="
pkill -f "port-forward svc/kube-prometheus-stack-prometheus" 2>/dev/null || true
nohup bash -c 'export PATH="/opt/homebrew/bin:$PATH"; while true; do kubectl port-forward svc/kube-prometheus-stack-prometheus -n monitoring 9090:9090 >/dev/null 2>&1; sleep 2; done' \
  > "$LOG_DIR/pf-prometheus.log" 2>&1 &
for _ in $(seq 1 30); do curl -sf -m 2 http://localhost:9090/-/ready >/dev/null 2>&1 && break; sleep 2; done
curl -sf -m 2 http://localhost:9090/-/ready >/dev/null 2>&1 && echo "  Prometheus ready" \
  || echo "  ⚠️ 9090 응답 없음 — kubectl get pods -n monitoring 확인 (루프는 계속 재시도)"

echo "=== [3/4] 부띠끄 App 행 ==="
DATABASE_URL="$DB_URL" USE_REAL_SERVICES=true SUT_NAMESPACE="$SUT_NS" .venv/bin/python scripts/register_boutique.py

echo "=== [4/4] uvicorn (실서비스 모드, http://localhost:$PORT) ==="
pkill -f "uvicorn app.main:app" 2>/dev/null || true
sleep 1
DATABASE_URL="$DB_URL" USE_REAL_SERVICES=true SUT_NAMESPACE="$SUT_NS" \
HYPOTHESIS_AGENT="${HYPOTHESIS_AGENT:-claude}" HYPOTHESIS_MODEL="${HYPOTHESIS_MODEL:-sonnet}" \
  nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port "$PORT" > "$LOG_DIR/uvicorn.log" 2>&1 &
for _ in $(seq 1 20); do curl -sf -m 2 "http://localhost:$PORT/healthz" >/dev/null 2>&1 && break; sleep 1; done
curl -sf -m 2 "http://localhost:$PORT/healthz" >/dev/null 2>&1 || { echo "❌ uvicorn 기동 실패 — $LOG_DIR/uvicorn.log"; exit 1; }

ELB="$(kubectl get svc frontend-external -n "$SUT_NS" -o jsonpath='{.status.loadBalancer.ingress[0].hostname}' 2>/dev/null || true)"
echo ""
echo "══════════════════════════════════════════════"
echo "   ✅ 시연 준비 완료"
echo "══════════════════════════════════════════════"
echo "   대시보드:   http://localhost:$PORT   (앱 online-boutique 등록됨)"
echo "   부띠끄:     http://${ELB:-<frontend-external ELB 대기 중>}"
echo "   로그:       $LOG_DIR/uvicorn.log · $LOG_DIR/pf-prometheus.log"
echo "   시연 순서:  새 실험 위저드 → 직접 입력 'frontend pod-kill' → 후보 선택 → 2단계 완료"
echo "               → 개선안 생성 → 'frontend 파드 2개' 승인 → 최종 회귀 시작 → 4단계 보고서"
echo "   종료:       scripts/demo-down.sh [--destroy]"
echo "══════════════════════════════════════════════"
