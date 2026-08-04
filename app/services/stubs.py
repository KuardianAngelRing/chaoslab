"""Slice 1 스텁 — mock 데이터 반환. 외부 시스템 호출 없음. 운영은 services/real/ 사용."""
from datetime import datetime, timedelta, timezone

from app.services.interfaces import BuildRequest


class StubBuilder:
    def trigger_build(self, req: BuildRequest) -> str:
        return f"build-{req.app_name}-{req.git_sha[:8]}"

    def build_status(self, workflow_name: str) -> str:
        return "succeeded"

    def stop_build(self, workflow_name: str) -> None:
        return None


class StubGitOps:
    def bootstrap_app(self, name: str, repo_url: str, port: int, health: str,
                      env: dict, secret_name: str) -> None:
        return None

    def update_image_tag(self, name: str, image: str) -> None:
        return None

    def set_replicas(self, name: str, replicas: int) -> None:
        return None


class StubChaos:
    def inject(self, namespace: str, app_name: str, chaos_type: str, params: dict) -> str:
        return f"exp-{app_name}-stub"

    def phase(self, chaos_type: str, crd_name: str) -> str:
        return "recovered"

    def delete(self, chaos_type: str, crd_name: str) -> None:
        return None


class StubPrometheus:
    def red_metrics(self, namespace: str) -> dict:
        return {"rate": 42.0, "error": 1.8, "duration": 380.0}


class StubLoki:
    def tail(self, namespace: str, limit: int = 100) -> list[str]:
        return [f"[{namespace}] mock log line {i}" for i in range(limit)]


class StubK8s:
    def apply_env_secret(self, namespace: str, name: str, data: dict) -> None:
        return None

    def restart_deployment(self, namespace: str, name: str) -> None:
        return None

    def nodes(self) -> list[dict]:
        return [
            {"name": "ng-ondemand-1", "type": "m5.large", "status": "Ready", "role": "platform"},
            {"name": "ng-spot-1", "type": "m5.xlarge", "status": "Ready", "role": "workload"},
            {"name": "ng-spot-2", "type": "m5.xlarge", "status": "Ready", "role": "workload"},
        ]

    def pods(self, namespace: str) -> list[dict]:
        return [
            {"name": "frontend-7d9", "namespace": namespace, "status": "Running", "restarts": 0},
            {"name": "cartservice-5fc", "namespace": namespace, "status": "Running", "restarts": 1},
        ]

    def components(self) -> list[dict]:
        names = ["Prometheus", "Grafana", "Loki", "Chaos Mesh", "ArgoCD"]
        return [{"name": n, "status": "Healthy"} for n in names]

    def events(self, namespace: str) -> list[dict]:
        # ts는 naive UTC — DB(DateTime 컬럼)의 naive datetime과 정렬 병합되므로 tzinfo를 붙이지 않는다
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        return [
            {"source": "chaos", "reason": "Applied",
             "message": f"NetworkChaos CRD 적용 (namespace={namespace})", "ts": now - timedelta(minutes=4)},
            {"source": "chaos", "reason": "Started",
             "message": "delay 200ms 주입 시작", "ts": now - timedelta(minutes=3, seconds=50)},
            {"source": "k8s", "reason": "Unhealthy",
             "message": "readiness probe 실패: frontend-7d9", "ts": now - timedelta(minutes=3)},
            {"source": "k8s", "reason": "BackOff",
             "message": "cartservice-5fc 재시작 백오프", "ts": now - timedelta(minutes=2, seconds=30)},
            {"source": "k8s", "reason": "Started",
             "message": "frontend-7d9 컨테이너 시작", "ts": now - timedelta(minutes=1)},
        ]
