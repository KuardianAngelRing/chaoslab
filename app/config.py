from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "ChaosLab"
    database_url: str = "sqlite:///./chaoslab.db"

    # 외부 시스템 (Slice 1 미사용, 구조만)
    k8s_context: str = ""
    prometheus_url: str = "http://localhost:9090"
    loki_url: str = "http://localhost:3100"

    # AI (Phase 3)
    anthropic_api_key: str = ""
    llm_model: str = "claude-sonnet-4-6"
    target_r: float = 0.7
    llm_budget_usd: float = 5.0        # 실험당 LLM 예산 상한 (Budget.remaining 계산)
    max_agent_iterations: int = 2      # 실험당 최대 개선 반복 (08/04 시안과 동일)

    # ── Slice 2c: 실제 빌드/배포 연동 ──
    # False(기본)면 Stub 사용 → 로컬/테스트는 클러스터·AWS 없이 동작.
    # EC2 운영 시 .env에서 true로 (deps.py가 Real 구현 주입).
    use_real_services: bool = False
    aws_region: str = "ap-northeast-2"
    ecr_registry: str = ""  # <account>.dkr.ecr.<region>.amazonaws.com (terraform output)
    iac_aws_repo_url: str = "https://github.com/KuardianAngelRing/Iac-aws"
    iac_aws_repo_path: str = ""  # EC2의 로컬 클론 경로 (예: /home/ec2-user/Iac-aws)
    github_token: str = ""  # Iac-aws push용 (크로스레포 쓰기)
    argo_namespace: str = "argo"
    sut_namespace: str = "sut"
    build_workflow_template: str = "build-and-push"

    # ── 로컬(라즈베리파이 k3s) 인프라 — 경로가 설정되면 Real 조회, 비면 Stub ──
    # use_real_services(AWS/EKS)와 독립. SSH 터널 선행 필요:
    #   ssh -f -N -L 6443:localhost:6443 masternode  (접속 정보는 팀 내 개인 전달)
    local_kubeconfig: str = ""  # 예: ~/projects/agent/k3s.yaml (server=https://127.0.0.1:6443)
    # SSH 터널 자동 관리 — 호스트가 설정되면 기동 시 앱이 터널을 열고 유지(끊기면 재접속).
    # 비면 수동 터널 전제. 포트가 이미 열려 있으면 외부 터널을 그대로 사용.
    local_ssh_host: str = ""       # 예: capstone.jun0.dev
    local_ssh_port: int = 22
    local_ssh_user: str = ""
    local_ssh_key_path: str = ""   # 예: ~/.ssh/id_rsa (비면 ssh 기본 키·agent)
    local_tunnel_port: int = 6443              # 로컬 포워딩 포트
    local_tunnel_target: str = "localhost:6443"  # 원격 측 대상
    local_cluster_name: str = "chaospilot-k3s"

    local_obs_namespace: str = "chaospilot-observability"
    local_chaos_namespace: str = "chaos-mesh"

    # ── 가설 수립 에이전트 (claude 구독제 CLI — ADR-0010) ──
    # use_real_services(AWS/EKS)와 독립 게이트 — 로컬에서 에이전트만 Real로 테스트 가능
    # (local_kubeconfig 선례와 동일 패턴). 선택형: "stub" | "claude" (추후 "codex" 등 추가).
    hypothesis_agent: str = "stub"
    claude_bin: str = "claude"
    hypothesis_model: str = ""          # 비면 CLI 기본 모델
    hypothesis_timeout_seconds: int = 180


settings = Settings()
