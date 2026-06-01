#!/usr/bin/env bash
# 빌드 파이프라인을 클러스터(argo 네임스페이스)에 설치.
#  1) docker/templates/Dockerfile.* → dockerfile-templates ConfigMap (폴백용)
#  2) build-and-push WorkflowTemplate
# 전제: 2a 적용됨(argo 네임스페이스 + Argo Workflows + argo-workflow SA), kubectl 컨텍스트 = chaos-eks
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== dockerfile-templates ConfigMap (docker/templates/) ==="
kubectl create configmap dockerfile-templates -n argo \
  --from-file="$DIR/../docker/templates/" \
  --dry-run=client -o yaml | kubectl apply -f -

echo "=== build-and-push WorkflowTemplate ==="
kubectl apply -n argo -f "$DIR/build-workflowtemplate.yaml"

echo "✅ 빌드 파이프라인 적용 완료 (argo 네임스페이스)"
