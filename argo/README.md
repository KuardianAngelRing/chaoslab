# argo/ — 빌드 파이프라인 (Slice 2b)

레포→ECR 이미지를 in-cluster(Argo Workflows + Kaniko)에서 빌드하는 재사용 파이프라인.
RealBuilder(2c)가 `build-and-push` WorkflowTemplate을 참조해 Workflow를 생성한다.

## 구성

| 파일 | 역할 |
|------|------|
| `build-workflowtemplate.yaml` | 재사용 빌드 정의: clone → Dockerfile 폴백 → Kaniko → ECR push |
| `apply.sh` | `docker/templates/` → ConfigMap + WorkflowTemplate 적용 |
| `build-example.yaml` | 수동 검증용 예시 Workflow |

## 빌드 흐름

```
Workflow(params: repo_url·revision·image·framework·dockerfile)
  └ initContainer(clone): git clone + checkout(revision)
        └ Dockerfile 없으면 → /templates/Dockerfile.<framework> 복사 (폴백)
  └ container(kaniko): --context=dir:///workspace --destination=<image> --cache=true
        └ SA argo-workflow → IRSA → ECR push (Kaniko 네이티브 ECR 인증)
```

- **Dockerfile 우선순위**: 레포에 `Dockerfile` 있으면 그걸 사용, 없으면 프레임워크 템플릿 폴백.
- **태그 = git SHA 8자** (push마다 다른 태그 → ArgoCD가 변경 감지).
- **캐시**: Kaniko `--cache=true` (ECR을 캐시 저장소로).

## 적용 (2a 적용 + 클러스터 기동 후)

```bash
./argo/apply.sh
```

## 수동 검증

```bash
# 대상 ECR 레포 준비
aws ecr create-repository --repository-name demo --region ap-northeast-2

# build-example.yaml 의 <ACCOUNT>/<owner>/<repo> 치환 후
kubectl create -f argo/build-example.yaml
kubectl -n argo get wf -w
# 성공 시 ECR에 demo:test01 이미지 push 확인:
aws ecr list-images --repository-name demo --region ap-northeast-2
```

> 전제: Slice 2a 적용(`up.sh`) — argo 네임스페이스 + Argo Workflows + `argo-workflow` SA(IRSA) 존재.
