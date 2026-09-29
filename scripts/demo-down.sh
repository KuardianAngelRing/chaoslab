#!/usr/bin/env bash
# 시연 로컬 프로세스 정리(uvicorn·port-forward). `--destroy`면 Iac-aws down.sh까지 실행(비용 0원).
set -euo pipefail
export PATH="/opt/homebrew/bin:$PATH"
IAC="${IAC_AWS_REPO_PATH:-$HOME/dev/Iac-aws}"

pkill -f "uvicorn app.main:app" 2>/dev/null && echo "uvicorn 종료" || echo "uvicorn 없음"
pkill -f "port-forward svc/kube-prometheus-stack-prometheus" 2>/dev/null && echo "port-forward 종료" || echo "port-forward 없음"

if [ "${1:-}" = "--destroy" ]; then
  [ -x "$IAC/scripts/down.sh" ] || { echo "❌ $IAC/scripts/down.sh 없음 (IAC_AWS_REPO_PATH 확인 — Documents 쪽 클론은 상태가 낡아 금지)"; exit 1; }
  echo "=== Iac-aws down.sh ($IAC) ==="
  (cd "$IAC" && echo yes | bash scripts/down.sh)
  echo "=== 잔여 확인 ==="
  R=ap-northeast-2
  echo "  eks=$(aws eks list-clusters --region $R --query 'length(clusters)' --output text) ec2=$(aws ec2 describe-instances --region $R --filters Name=instance-state-name,Values=running --query 'length(Reservations[].Instances[])' --output text) nat=$(aws ec2 describe-nat-gateways --region $R --filter Name=state,Values=available --query 'length(NatGateways)' --output text) elb=$(aws elb describe-load-balancers --region $R --query 'length(LoadBalancerDescriptions)' --output text)"
fi
