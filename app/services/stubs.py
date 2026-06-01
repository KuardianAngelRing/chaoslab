"""Slice 1 스텁 — mock 데이터 반환. 외부 시스템 호출 없음. 이후 RealXxx로 교체."""


class StubBuilder:
    def trigger_build(self, app_id: int, git_sha: str) -> str:
        return f"build-{app_id}-{git_sha[:8]}"

    def build_status(self, workflow_name: str) -> str:
        return "succeeded"


class StubGitOps:
    def bootstrap_app(self, name: str, repo_url: str, framework: str) -> None:
        return None

    def update_image_tag(self, name: str, image_tag: str) -> None:
        return None


class StubChaos:
    def inject(self, namespace: str, chaos_type: str, params: dict) -> str:
        return f"{chaos_type.lower()}-{namespace}-stub"

    def delete(self, crd_name: str) -> None:
        return None


class StubPrometheus:
    def red_metrics(self, namespace: str) -> dict:
        return {"rate": 42.0, "error": 1.8, "duration": 380.0}


class StubLoki:
    def tail(self, namespace: str, limit: int = 100) -> list[str]:
        return [f"[{namespace}] mock log line {i}" for i in range(limit)]


class StubK8s:
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
