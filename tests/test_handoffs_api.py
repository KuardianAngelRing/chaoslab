"""핸드오프 REST API — client 픽스처(seed 포함, Stub 강제).

seed가 스냅샷을 미리 만들 수 있으므로(개수 가정 금지) 상대 검증만 한다.
"""


def test_create_then_read_flow(client):
    created = client.post("/experiments/1/handoffs")
    assert created.status_code == 201
    body = created.json()
    hid = body["id"]
    assert body["experiment_id"] == 1
    assert body["payload"]["schema_version"] == "1.0"
    assert body["payload"]["experiment"]["app_name"] == "online-boutique"

    listing = client.get("/experiments/1/handoffs")
    assert listing.status_code == 200
    assert listing.json()[0]["id"] == hid          # 최신순
    assert "payload" not in listing.json()[0]      # 목록은 메타만

    latest = client.get("/experiments/1/handoffs/latest")
    assert latest.status_code == 200
    assert latest.json()["id"] == hid

    single = client.get(f"/handoffs/{hid}")
    assert single.status_code == 200
    assert single.json()["payload"]["budget"]["llm_cost_used_usd"] == 0.036


def test_create_404_unknown_experiment(client):
    assert client.post("/experiments/999/handoffs").status_code == 404
    assert client.get("/experiments/999/handoffs").status_code == 404
    assert client.get("/experiments/999/handoffs/latest").status_code == 404


def test_put_replaces_after_validation(client):
    created = client.post("/experiments/1/handoffs").json()
    payload = created["payload"]
    payload["budget"]["iterations_remaining"] = 1

    res = client.put(f"/handoffs/{created['id']}", json=payload)
    assert res.status_code == 200
    assert res.json()["payload"]["budget"]["iterations_remaining"] == 1


def test_put_rejects_contract_violation(client):
    created = client.post("/experiments/1/handoffs").json()
    payload = created["payload"]
    payload["surprise_field"] = True  # extra=forbid

    res = client.put(f"/handoffs/{created['id']}", json=payload)
    assert res.status_code == 422


def test_put_404_unknown_handoff(client):
    payload = client.post("/experiments/1/handoffs").json()["payload"]
    assert client.put("/handoffs/999", json=payload).status_code == 404


def test_timestamps_are_utc_aware_in_all_paths(client):
    """POST(메모리 객체)와 GET(DB 재로드) 응답의 타임스탬프 표현이 동일해야 한다."""
    created = client.post("/experiments/1/handoffs").json()
    fetched = client.get(f"/handoffs/{created['id']}").json()
    assert created["created_at"] == fetched["created_at"]
    assert fetched["created_at"].endswith("+00:00")


def test_delete_then_404(client):
    hid = client.post("/experiments/1/handoffs").json()["id"]
    assert client.delete(f"/handoffs/{hid}").status_code == 204
    assert client.get(f"/handoffs/{hid}").status_code == 404
    assert client.delete(f"/handoffs/{hid}").status_code == 404


def test_latest_404_when_no_snapshot(client):
    for meta in client.get("/experiments/1/handoffs").json():
        client.delete(f"/handoffs/{meta['id']}")
    assert client.get("/experiments/1/handoffs/latest").status_code == 404
