def test_healthz(client):
    resp = client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_dashboard_full_page(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "ChaosLab" in resp.text            # base 셸 포함
    assert 'id="main-content"' in resp.text


def test_dashboard_partial_when_hx(client):
    resp = client.get("/", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "<!DOCTYPE html>" not in resp.text  # 셸 없음 (부분만)


def test_apps_page_lists_seeded(client):
    resp = client.get("/apps")
    assert resp.status_code == 200
    assert "online-boutique" in resp.text     # seed된 앱 이름
    assert "새 앱" in resp.text


def test_experiments_page(client):
    resp = client.get("/experiments")
    assert resp.status_code == 200
    assert "NetworkChaos" in resp.text         # seed된 실험
    assert "카오스 테스트" in resp.text


def test_experiment_detail(client):
    resp = client.get("/experiments/1")
    assert resp.status_code == 200
    assert "개요" in resp.text and "메트릭" in resp.text and "AI 루프" in resp.text


def test_experiment_detail_404(client):
    resp = client.get("/experiments/99999")
    assert resp.status_code == 404


def test_infra_page(client):
    resp = client.get("/infra")
    assert resp.status_code == 200
    assert "Prometheus" in resp.text and "ng-spot-1" in resp.text


def test_settings_page(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "설정" in resp.text and ("목표 R" in resp.text or "GitHub" in resp.text)


def test_recent_activity_assembles_and_limits(db_session):
    from app.db.seed import seed_data
    from app.routers.pages import _recent_activity

    seed_data(db_session)
    items = _recent_activity(db_session)
    assert len(items) <= 5
    assert all({"icon", "text", "ts"} <= set(it) for it in items)
    joined = " ".join(it["text"] for it in items)
    assert "online-boutique" in joined


def test_dashboard_merged_experiment_card(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # 합친 카드의 실데이터(seed)
    assert "online-boutique" in resp.text and "NetworkChaos" in resp.text
    assert "관찰" in resp.text and "가설" in resp.text and "권고" in resp.text
    assert "timeout 1s→3s" in resp.text  # seed recommender_output
    # 제거 대상
    assert "자동 적용" not in resp.text       # Phase 3 버튼 삭제
    assert "주입 중" not in resp.text          # 상태 배지 삭제
    assert "Iteration 4 / 10" not in resp.text  # iteration 카운트 줄 삭제
    # 정직성 라벨
    assert "Phase 3" in resp.text  # AI 진단 배지


def test_dashboard_hero_and_kpi_honest(client):
    resp = client.get("/")
    assert resp.status_code == 200
    # 제거되어야 할 가짜들
    assert "Phase 4" not in resp.text
    assert "👋" not in resp.text
    assert "$5.00 한도" not in resp.text
    assert "+1 어제 대비" not in resp.text
    # 새 라벨
    assert "진행중인 실험" in resp.text
    assert "총 소요된 LLM 비용" in resp.text
    assert "최근 R 지수" in resp.text
    # 실 비용(seed 3 iter × 0.012 = 0.036) → $0.04 표기
    assert "$0.04" in resp.text
    # '새 실험 시작' 버튼 제거
    assert "새 실험 시작" not in resp.text


def test_elapsed_min_handles_naive_datetime():
    from datetime import datetime, timezone, timedelta
    from app.routers.pages import _elapsed_min

    assert _elapsed_min(None) is None
    past = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=12)
    assert _elapsed_min(past) >= 11


def test_dashboard_system_status_real(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "Supabase" not in resp.text          # 스택에 없는 항목 제거
    assert "sidecars" not in resp.text           # node_count 오표기 제거
    assert "Chaos Mesh" in resp.text             # components() 실항목
    # 최근 활동이 실데이터(seed 앱명)
    assert "online-boutique 신규 등록" in resp.text or "online-boutique 새 SHA" in resp.text


def test_sidebar_no_eks_status_box(client):
    resp = client.get("/")          # 풀페이지(사이드바 포함)
    assert resp.status_code == 200
    assert "EKS 정상" not in resp.text  # 박스를 유일하게 식별하는 라벨 ("5/5"는 Slice4 실 노드수와 충돌 가능해 제외)
