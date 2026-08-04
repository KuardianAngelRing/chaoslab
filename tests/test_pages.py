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


def test_experiment_detail_event_feed(client):
    resp = client.get("/experiments/1")
    assert resp.status_code == 200
    assert "이벤트 피드" in resp.text
    assert "주입 시작" in resp.text            # StubK8s chaos 이벤트
    assert "Unhealthy" in resp.text            # StubK8s k8s 이벤트
    assert "실험 시작" in resp.text            # 플랫폼 이벤트 (DB)


def test_experiment_detail_safety_card(client):
    resp = client.get("/experiments/1")
    assert "안전장치" in resp.text
    assert "허용 범위" in resp.text
    assert "10~10000" in resp.text             # chaos_specs latency_ms 범위
    assert "자동 중단 조건" in resp.text
    assert "예정" in resp.text                 # 자동 중단은 표시만 (신규 개념)


def test_experiment_detail_r_breakdown(client):
    resp = client.get("/experiments/1")
    assert "가용성" in resp.text and "복구속도" in resp.text
    assert "0.98" in resp.text                 # availability (seed 기준 r_components)
    assert "0.68" in resp.text                 # recovery_speed
    assert "$1.23" not in resp.text            # 하드코딩 LLM 비용 제거
    assert "$0.04" in resp.text                # seed 실비용 3×0.012 반올림


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
    # 상태 배지 (seed 실험은 running)
    assert "진행중" in resp.text
    # 주입 파라미터 줄은 미노출
    assert "주입 설정" not in resp.text
    # R 지수 추이 차트 제목 + 회차 라벨 (data-labels는 tojson이 \u 이스케이프)
    assert "R 지수 추이" in resp.text
    assert "기준선" in resp.text  # 지표 타일의 기준선 표기
    assert "\\uac1c\\uc120 1\\ud68c\\ucc28" in resp.text  # 차트 라벨 "개선 1회차"
    # AI 진단은 iteration이 있으면 진행중이어도 표시 (seed는 3회차 보유)
    assert "AI Agent 진단" in resp.text
    assert "관찰" in resp.text and "가설" in resp.text and "권고" in resp.text
    assert "timeout 1s→3s" in resp.text  # seed recommender_output
    # 제거 대상
    assert "자동 적용" not in resp.text       # Phase 3 버튼 삭제
    assert "분 경과" not in resp.text          # 경과 배지 → 상태 배지로 대체
    assert "Iteration 4 / 10" not in resp.text  # iteration 카운트 줄 삭제


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
