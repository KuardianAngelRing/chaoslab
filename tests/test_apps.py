"""앱 등록/빌드 라우트 — stub 모드(기본). 외부 시스템 호출 없이 동작."""


def test_register_app_creates_and_lists(client):
    resp = client.post(
        "/apps",
        data={"repo_url": "https://github.com/foo/payment-svc",
              "framework": "fastapi", "health_path": "/healthz", "port": "8080"},
    )
    assert resp.status_code == 200
    assert "payment-svc" in resp.text  # 파생된 앱 이름이 목록에 노출


def test_build_app_returns_ok(client):
    # seed된 app id=1 (online-boutique)에 수동 빌드 트리거
    resp = client.post("/apps/1/build")
    assert resp.status_code == 200


def test_build_unknown_app_404(client):
    resp = client.post("/apps/99999/build")
    assert resp.status_code == 404
