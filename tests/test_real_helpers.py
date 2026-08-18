"""RealGitOps/RealBuilder/RealLocalK8s 순수 헬퍼 — IO 없이 검증 (boto3/k8s 불필요)."""
from app.services.interfaces import BuildRequest
from app.services.real.builder import build_workflow_manifest
from app.services.real.local_k8s import parse_cpu, parse_mem, usage_pct
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


def test_render_chaos_manifest_network_delay():
    from app.services.real.chaos import render_chaos_manifest

    m = render_chaos_manifest("NetworkChaos", "sut", "demo",
                              {"action": "delay", "latency_ms": 200, "duration_s": 300})
    assert m["kind"] == "NetworkChaos"
    assert m["metadata"]["generateName"] == "exp-demo-"
    assert m["metadata"]["namespace"] == "sut"
    assert m["spec"]["selector"] == {"namespaces": ["sut"], "labelSelectors": {"app": "demo"}}
    assert m["spec"]["mode"] == "all"
    assert m["spec"]["action"] == "delay"
    assert m["spec"]["delay"] == {"latency": "200ms"}
    assert m["spec"]["duration"] == "300s"


def test_render_chaos_manifest_pod_kill_has_no_duration():
    from app.services.real.chaos import render_chaos_manifest

    m = render_chaos_manifest("PodChaos", "sut", "demo", {"action": "pod-kill"})
    assert m["kind"] == "PodChaos"
    assert m["spec"]["action"] == "pod-kill"
    assert "duration" not in m["spec"]


def test_render_chaos_manifest_stress_cpu():
    from app.services.real.chaos import render_chaos_manifest

    m = render_chaos_manifest("StressChaos", "sut", "demo",
                              {"action": "cpu", "cpu_load": 80, "duration_s": 60})
    assert m["kind"] == "StressChaos"
    assert m["spec"]["stressors"] == {"cpu": {"workers": 1, "load": 80}}
    assert m["spec"]["duration"] == "60s"


def test_parse_cpu_units():
    assert parse_cpu("250m") == 0.25
    assert parse_cpu("2") == 2.0
    assert parse_cpu("1500000000n") == 1.5
    assert parse_cpu("500000u") == 0.5


def test_parse_mem_units():
    assert parse_mem("1024Ki") == 2**20
    assert parse_mem("512Mi") == 512 * 2**20
    assert parse_mem("8Gi") == 8 * 2**30
    assert parse_mem("1000000") == 1000000.0


def test_usage_pct_clamps_and_guards():
    assert usage_pct(1.0, 4.0) == 25
    assert usage_pct(5.0, 4.0) == 100   # 100 초과 클램프
    assert usage_pct(1.0, 0) == 0       # allocatable 없으면 0


def test_build_ssh_command_full():
    from types import SimpleNamespace

    from app.services.real.tunnel import build_ssh_command

    s = SimpleNamespace(local_ssh_host="capstone.example.dev", local_ssh_port=1111,
                        local_ssh_user="master", local_ssh_key_path="~/.ssh/id_rsa",
                        local_tunnel_port=6443, local_tunnel_target="localhost:6443")
    cmd = build_ssh_command(s)
    assert cmd[:2] == ["ssh", "-N"]
    assert "-L" in cmd and "6443:localhost:6443" in cmd
    assert "-p" in cmd and "1111" in cmd
    assert "-i" in cmd  # 키 경로 지정 시 -i 포함 (expanduser 적용)
    assert cmd[-1] == "master@capstone.example.dev"
    assert "BatchMode=yes" in cmd  # 프롬프트 블록 방지


def test_build_ssh_command_defaults_omit_key_and_user():
    from types import SimpleNamespace

    from app.services.real.tunnel import build_ssh_command

    s = SimpleNamespace(local_ssh_host="h", local_ssh_port=22, local_ssh_user="",
                        local_ssh_key_path="", local_tunnel_port=6443,
                        local_tunnel_target="localhost:6443")
    cmd = build_ssh_command(s)
    assert "-i" not in cmd
    assert cmd[-1] == "h"


def test_render_chaos_manifest_namespace_wide_selector():
    from app.services.real.chaos import render_chaos_manifest

    m = render_chaos_manifest("PodChaos", "chaoslab-msa-1", "msa",
                              {"action": "pod-kill"}, label_selector=False)
    assert m["spec"]["selector"] == {"namespaces": ["chaoslab-msa-1"]}  # ns 전체 (ADR-0009)
