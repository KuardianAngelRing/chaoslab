"""RealGitOps/RealBuilder 순수 헬퍼 — IO 없이 검증 (boto3/k8s 불필요)."""
from app.services.interfaces import BuildRequest
from app.services.real.builder import build_workflow_manifest
from app.services.real.gitops import (
    derive_app_name,
    render_application_yaml,
    render_values_yaml,
    set_image_in_values,
    split_env,
)


def test_derive_app_name():
    assert derive_app_name("https://github.com/foo/spring-boot-demo") == "spring-boot-demo"
    assert derive_app_name("https://github.com/foo/My_App.git") == "my-app"
    assert derive_app_name("https://github.com/foo/bar/") == "bar"


def test_render_values_yaml_roundtrip():
    text = render_values_yaml("demo", "reg/demo:abc12345", 8080, "/healthz")
    assert "name: demo" in text
    assert "image: reg/demo:abc12345" in text
    assert "port: 8080" in text
    assert "healthPath: /healthz" in text


def test_set_image_in_values_replaces_only_image_line():
    before = render_values_yaml("demo", "reg/demo:placeholder", 8080, "/healthz")
    after = set_image_in_values(before, "reg/demo:newsha99")
    assert "image: reg/demo:newsha99" in after
    assert "placeholder" not in after
    assert "port: 8080" in after  # 다른 줄 보존


def test_render_application_yaml_multisource():
    y = render_application_yaml("demo", "https://github.com/org/Iac-aws", "sut")
    assert "name: demo" in y
    assert "$values/gitops/apps/demo/values.yaml" in y
    assert "namespace: sut" in y


def test_split_env_separates_secret():
    rows = [{"key": "DB_HOST", "value": "mysql", "is_secret": False},
            {"key": "JWT", "value": "x", "is_secret": True},
            {"key": "", "value": "skip", "is_secret": False}]  # 빈 키 무시
    plain, secret = split_env(rows)
    assert plain == {"DB_HOST": "mysql"}
    assert secret == {"JWT": "x"}


def test_render_values_yaml_with_env_and_secret():
    text = render_values_yaml("demo", "reg/demo:abc12345", 8080, "/healthz",
                              env={"DB_HOST": "mysql:3306"}, secret_name="demo-env")
    assert 'DB_HOST: "mysql:3306"' in text
    assert "secretName: demo-env" in text
    assert "env:" in text


def test_render_values_yaml_no_env_omits_blocks():
    text = render_values_yaml("demo", "reg/demo:abc12345", 8080, "/healthz")
    assert "env:" not in text
    assert "secretName" not in text


def test_set_image_in_values_preserves_env():
    before = render_values_yaml("demo", "reg/demo:placeholder", 8080, "/healthz",
                                env={"DB_HOST": "mysql"}, secret_name="demo-env")
    after = set_image_in_values(before, "reg/demo:newsha99")
    assert "image: reg/demo:newsha99" in after
    assert 'DB_HOST: "mysql"' in after
    assert "secretName: demo-env" in after


def test_build_workflow_manifest():
    req = BuildRequest(app_name="demo", repo_url="https://x/demo", framework="fastapi",
                       git_sha="abc123def", image="reg/demo:abc123de")
    m = build_workflow_manifest(req, "build-and-push", "argo")
    assert m["kind"] == "Workflow"
    assert m["spec"]["workflowTemplateRef"]["name"] == "build-and-push"
    params = {p["name"]: p["value"] for p in m["spec"]["arguments"]["parameters"]}
    assert params["image"] == "reg/demo:abc123de"
    assert params["framework"] == "fastapi"
    assert params["dockerfile"] == "Dockerfile"
