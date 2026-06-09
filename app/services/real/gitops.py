"""RealGitOps — Iac-aws 크로스레포 쓰기 + ECR 레포 생성 (운영, use_real_services=true).

순수 렌더 함수(render_*/set_image_in_values/derive_app_name)는 IO 없이 단위 테스트 가능.
boto3/git 호출은 메서드 안에서만 → stub 모드/테스트는 의존성 불필요.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path


def derive_app_name(repo_url: str) -> str:
    """GitHub URL 마지막 세그먼트 → 소문자 kebab 앱 이름."""
    tail = repo_url.rstrip("/").split("/")[-1]
    if tail.endswith(".git"):
        tail = tail[:-4]
    name = re.sub(r"[^a-z0-9-]+", "-", tail.lower()).strip("-")
    return name or "app"


def split_env(env_vars: list[dict]) -> tuple[dict[str, str], dict[str, str]]:
    """[{key,value,is_secret}] → (평문 {K:V}, 비밀 {K:V}). 빈 키는 무시."""
    plain: dict[str, str] = {}
    secret: dict[str, str] = {}
    for e in env_vars or []:
        key = (e.get("key") or "").strip()
        if not key:
            continue
        (secret if e.get("is_secret") else plain)[key] = e.get("value", "")
    return plain, secret


def _yaml_quote(v: str) -> str:
    """env 값을 안전한 더블쿼트 스칼라로 (콜론·슬래시·특수문자 포함 대비)."""
    s = str(v).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
    return f'"{s}"'


def render_application_yaml(name: str, iac_repo_url: str, sut_namespace: str) -> str:
    """ArgoCD Application (multi-source: generic-app chart + gitops values)."""
    return f"""apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: {name}
  namespace: argocd
spec:
  project: default
  sources:
    - repoURL: {iac_repo_url}
      targetRevision: main
      path: helm/generic-app
      helm:
        valueFiles:
          - $values/gitops/apps/{name}/values.yaml
    - repoURL: {iac_repo_url}
      targetRevision: main
      ref: values
  destination:
    server: https://kubernetes.default.svc
    namespace: {sut_namespace}
  syncPolicy:
    automated:
      prune: true
      selfHeal: true
"""


def render_values_yaml(name: str, image: str, port: int, health_path: str,
                       env: dict[str, str] | None = None, secret_name: str = "") -> str:
    lines = [f"name: {name}", f"image: {image}", f"port: {port}",
             f"healthPath: {health_path}", "replicas: 1"]
    if env:
        lines.append("env:")
        lines += [f"  {k}: {_yaml_quote(v)}" for k, v in env.items()]
    if secret_name:
        lines.append(f"secretName: {secret_name}")
    lines += ["istio:", "  enabled: true", "  timeout: 3s", "  retries:",
              "    attempts: 2", "    perTryTimeout: 1s"]
    return "\n".join(lines) + "\n"


def set_image_in_values(values_text: str, new_image: str) -> str:
    """values.yaml 의 'image:' 줄만 새 이미지로 교체 (다른 줄 보존)."""
    return re.sub(
        r"^image:.*$",
        f"image: {new_image}",
        values_text,
        count=1,
        flags=re.MULTILINE,
    )


class RealGitOps:
    def __init__(self, settings):
        self.s = settings
        self.repo = Path(settings.iac_aws_repo_path)

    # ── git ──
    def _git(self, *args: str) -> None:
        subprocess.run(["git", "-C", str(self.repo), *args], check=True)

    def _push(self) -> None:
        url = self.s.iac_aws_repo_url
        if self.s.github_token and url.startswith("https://"):
            url = url.replace("https://", f"https://{self.s.github_token}@", 1)
        self._git("pull", "--ff-only")  # 최신 반영 후 push (경합 최소화)
        subprocess.run(
            ["git", "-C", str(self.repo), "push", url, "HEAD:main"], check=True
        )

    # ── ECR ──
    def _ensure_ecr_repo(self, name: str) -> None:
        import boto3  # lazy
        from botocore.exceptions import ClientError

        ecr = boto3.client("ecr", region_name=self.s.aws_region)
        try:
            ecr.create_repository(repositoryName=name)
        except ClientError as e:
            if e.response["Error"]["Code"] != "RepositoryAlreadyExistsException":
                raise

    # ── GitOpsService 인터페이스 ──
    def bootstrap_app(self, name: str, repo_url: str, port: int, health: str,
                      env: dict[str, str], secret_name: str) -> None:
        self._ensure_ecr_repo(name)
        placeholder = f"{self.s.ecr_registry}/{name}:placeholder"

        app_file = self.repo / "argocd" / "apps" / f"{name}.yaml"
        values_file = self.repo / "gitops" / "apps" / name / "values.yaml"
        app_file.parent.mkdir(parents=True, exist_ok=True)
        values_file.parent.mkdir(parents=True, exist_ok=True)
        app_file.write_text(
            render_application_yaml(name, self.s.iac_aws_repo_url, self.s.sut_namespace)
        )
        values_file.write_text(
            render_values_yaml(name, placeholder, port, health, env, secret_name)
        )

        self._git("add", "argocd/apps", "gitops/apps")
        self._git("commit", "-m", f"feat: register {name}")
        self._push()

    def update_image_tag(self, name: str, image: str) -> None:
        values_file = self.repo / "gitops" / "apps" / name / "values.yaml"
        values_file.write_text(set_image_in_values(values_file.read_text(), image))
        self._git("add", f"gitops/apps/{name}/values.yaml")
        self._git("commit", "-m", f"deploy: {name} → {image.rsplit(':', 1)[-1]}")
        self._push()


def resolve_head_sha(repo_url: str, branch: str = "HEAD") -> str:
    """원격 저장소 기본 브랜치(HEAD)의 commit SHA (수동 빌드 트리거 시 태그용).

    기본값 HEAD = 저장소의 기본 브랜치(main/develop/master 무관). 특정 브랜치명도 허용.
    """
    ref = "HEAD" if branch == "HEAD" else f"refs/heads/{branch}"
    out = subprocess.run(
        ["git", "ls-remote", repo_url, ref],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    return out.split()[0] if out else ""
