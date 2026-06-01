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


settings = Settings()
