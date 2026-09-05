"""개선 명세 화이트리스트 — 순수 검증 (설계 2026-09-05 §3)."""
from app.services.improvement_specs import (
    change_rows,
    flatten_patch,
    manifest_workloads,
    preview_rows,
    project,
    validate_improvement,
)

MANIFEST = """apiVersion: apps/v1
kind: Deployment
metadata:
  name: nginx
spec:
  replicas: 2
  selector:
    matchLabels:
      app: nginx
  template:
    metadata:
      labels:
        app: nginx
    spec:
      containers:
        - name: nginx
          image: nginx:1.27
          ports:
            - containerPort: 80
          env:
            - name: TIMEOUT
              value: "3"
          readinessProbe:
            httpGet:
              path: /
              port: 80
            periodSeconds: 10
---
apiVersion: v1
kind: Service
metadata:
  name: nginx
spec:
  selector:
    app: nginx
  ports:
    - port: 80
"""


def _patch(container: dict) -> dict:
    return {"spec": {"template": {"spec": {"containers": [{"name": "nginx", **container}]}}}}


def test_manifest_patch_probe_prestop_resources_replicas_are_normalized():
    raw = {
        "type": "manifest_patch", "deployment": "nginx", "container": "nginx",
        "patch": {"spec": {"replicas": 3, "template": {"spec": {"containers": [{
            "name": "nginx",
            "readinessProbe": {"periodSeconds": 2, "failureThreshold": 2, "tcpSocket": {"port": 80}},
            "lifecycle": {"preStop": {"sleep": {"seconds": 5}}},
            "resources": {"limits": {"cpu": "500m", "memory": "256Mi"}},
        }]}}}},
    }
    normalized, errors = validate_improvement(raw)
    assert errors == []
    assert normalized["type"] == "manifest_patch" and normalized["key"] == "" and normalized["value"] == ""
    assert normalized["patch"]["spec"]["replicas"] == 3
    [c] = normalized["patch"]["spec"]["template"]["spec"]["containers"]
    assert c["readinessProbe"] == {"periodSeconds": 2, "failureThreshold": 2, "tcpSocket": {"port": 80}}
    assert c["lifecycle"] == {"preStop": {"sleep": {"seconds": 5}}}
    assert c["resources"] == {"limits": {"cpu": "500m", "memory": "256Mi"}}


def test_manifest_patch_rejects_paths_outside_whitelist():
    cases = {
        "env": _patch({"env": [{"name": "A", "value": "1"}]}),
        "image": _patch({"image": "nginx:evil"}),
        "strategy": {"spec": {"strategy": {"type": "Recreate"}}},
        "replicas_range": {"spec": {"replicas": 0}},
        "quantity": _patch({"resources": {"limits": {"cpu": "half"}}}),
        "two_handlers": _patch({"readinessProbe": {"httpGet": {"path": "/", "port": 80}, "tcpSocket": {"port": 80}}}),
        "probe_range": _patch({"livenessProbe": {"periodSeconds": 0}}),
        "prestop_both": _patch({"lifecycle": {"preStop": {"sleep": {"seconds": 5}, "exec": {"command": ["true"]}}}}),
        "postStart": _patch({"lifecycle": {"postStart": {"exec": {"command": ["true"]}}}}),
        "volumes": {"spec": {"template": {"spec": {"volumes": []}}}},
        "no_name": {"spec": {"template": {"spec": {"containers": [{"readinessProbe": {"periodSeconds": 1}}]}}}},
        "empty": {"spec": {}},
    }
    for label, patch in cases.items():
        _, errors = validate_improvement({"type": "manifest_patch", "deployment": "nginx", "patch": patch})
        assert errors, label
    _, errors = validate_improvement({"type": "manifest_patch", "deployment": "nginx",
                                      "patch": _patch({"env": [{"name": "A", "value": "1"}]})})
    assert any("deployment_env" in e for e in errors)


def test_deployment_env_validation():
    normalized, errors = validate_improvement({"type": "deployment_env", "deployment": "nginx",
                                               "container": "nginx", "key": "TIMEOUT", "value": 5})
    assert errors == [] and normalized["value"] == "5" and normalized["patch"] == {}
    for bad in ({"key": "timeout", "value": "1"}, {"key": "TIMEOUT", "value": None},
                {"key": "TIMEOUT", "value": "x" * 201}):
        _, errors = validate_improvement({"type": "deployment_env", "deployment": "nginx",
                                          "container": "nginx", **bad})
        assert errors, bad
    _, errors = validate_improvement({"type": "deployment_env", "deployment": "nginx", "key": "A", "value": "1"})
    assert any("container" in e for e in errors)
    assert validate_improvement({"type": "istio_patch"})[1]
    assert validate_improvement("nope")[1]


def test_flatten_project_and_rows_match_by_container_name():
    patch = _patch({"readinessProbe": {"periodSeconds": 2, "httpGet": {"path": "/healthz", "port": 80}},
                    "lifecycle": {"preStop": {"sleep": {"seconds": 5}}}})
    assert flatten_patch(patch) == [
        "spec.template.spec.containers[nginx].readinessProbe.periodSeconds",
        "spec.template.spec.containers[nginx].readinessProbe.httpGet",
        "spec.template.spec.containers[nginx].lifecycle.preStop.sleep",
    ]
    doc = manifest_workloads(MANIFEST)["nginx"]
    before = project(doc, patch)
    [c] = before["spec"]["template"]["spec"]["containers"]
    assert c == {"name": "nginx",
                 "readinessProbe": {"periodSeconds": 10, "httpGet": {"path": "/", "port": 80}},
                 "lifecycle": {"preStop": {"sleep": None}}}   # 없던 경로는 None = 롤백 시 삭제
    rows = change_rows({"type": "manifest_patch", "patch": patch, "before": before, "after": patch})
    assert [(r["before"], r["after"]) for r in rows] == [
        (10, 2), ({"path": "/", "port": 80}, {"path": "/healthz", "port": 80}), (None, {"seconds": 5}),
    ]
    # 구형 env 기록(type 없음)도 env 행으로
    assert change_rows({"deployment": "a", "key": "K", "before": "1", "after": "2"}) == [
        {"path": "env.K", "before": "1", "after": "2"}]


def test_preview_rows_read_current_values_from_manifest():
    rows = preview_rows({"type": "deployment_env", "deployment": "nginx", "container": "nginx",
                         "key": "TIMEOUT", "value": "5"}, MANIFEST)
    assert rows == [{"path": "env.TIMEOUT", "before": "3", "after": "5"}]
    rows = preview_rows({"type": "manifest_patch", "deployment": "nginx",
                         "patch": {"spec": {"replicas": 3}}}, MANIFEST)
    assert rows == [{"path": "spec.replicas", "before": 2, "after": 3}]
    assert preview_rows({"type": "manifest_patch", "deployment": "ghost",
                         "patch": {"spec": {"replicas": 3}}}, MANIFEST)[0]["before"] is None


def test_change_rows_only_changed_drops_identical_paths_but_keeps_noop_record():
    change = {"type": "manifest_patch",
              "patch": _patch({"readinessProbe": {"periodSeconds": 2, "timeoutSeconds": 1}}),
              "before": _patch({"readinessProbe": {"periodSeconds": 3, "timeoutSeconds": 1}}),
              "after": _patch({"readinessProbe": {"periodSeconds": 2, "timeoutSeconds": 1}})}
    assert [r["path"].rsplit(".", 1)[1] for r in change_rows(change, only_changed=True)] == ["periodSeconds"]
    assert len(change_rows(change)) == 2
    noop = {**change, "before": change["after"]}
    assert len(change_rows(noop, only_changed=True)) == 2      # 전부 같으면 원래 행 유지
