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
    assert "카오스 테스트" in resp.text
    assert "UI 디자인 시안" in resp.text
    assert "새 실험 시작" in resp.text
    assert "후보 선택" in resp.text and "최종 검증" in resp.text
    assert 'hx-post="/experiments"' not in resp.text
    assert "data-running-exp" not in resp.text
    for run_id, stage in ((1, "plan"), (2, "execute"), (3, "result")):
        assert f'/experiments/{run_id}?view={stage}' in resp.text


def test_experiment_detail(client):
    resp = client.get("/experiments/1")
    assert resp.status_code == 200
    # 준비 탭 제거 — 4단계 스테퍼 (게이트는 후보 선택 탭 배너로 흡수)
    for stage in ("후보 선택", "순차 실행·개선", "최종 회귀 검증", "결과"):
        assert stage in resp.text
    assert 'data-workflow-stage="prepare"' not in resp.text
    assert "data-workflow-candidate" in resp.text
    # SAMPLE DATA 배너·실행 컨텍스트 사이드 패널 제거 (디자인 피드백)
    assert "SAMPLE DATA" not in resp.text
    assert "실행 컨텍스트" not in resp.text
    assert "hx-post" not in resp.text


def test_experiment_demo_rows_open_their_own_fixed_state(client):
    for run_id, code, stage in ((1, "CL-042", "plan"), (2, "CL-041", "execute"), (3, "CL-040", "result")):
        resp = client.get(f"/experiments/{run_id}?view={stage}")
        assert resp.status_code == 200
        assert code in resp.text
        assert f'data-initial-stage="{stage}"' in resp.text


def test_experiment_future_stage_query_is_clamped(client):
    resp = client.get("/experiments/1?view=result")
    assert resp.status_code == 200
    assert 'data-initial-stage="plan"' in resp.text
    resp = client.get("/experiments/2?view=verify")
    assert resp.status_code == 200
    assert 'data-initial-stage="execute"' in resp.text


def test_prepare_view_removed_and_gates_absorbed_into_plan(client):
    # 구 준비 탭 URL은 존재하지 않는 view → 기본 view로 클램프
    resp = client.get("/experiments/1?view=prepare")
    assert resp.status_code == 200
    assert 'data-initial-stage="plan"' in resp.text
    # 게이트 3종은 후보 선택 탭 상단 접이식 배너로
    resp = client.get("/experiments/1?view=plan")
    assert "data-precheck-banner" in resp.text
    assert "사전 점검 3/3 통과" in resp.text
    for gate in ("대상 유효성", "판정 가능한 관측", "장애 정리 보장"):
        assert gate in resp.text
    assert "후보 생성이 차단됩니다" in resp.text   # 실패 시 차단 계약 명시


def test_candidate_prompt_adds_a_selectable_ui_only_sample(client):
    resp = client.get("/experiments/1?view=plan")
    assert resp.status_code == 200
    assert "원하는 후보가 없나요?" in resp.text
    assert "data-candidate-prompt" in resp.text
    assert "data-candidate-generate" in resp.text
    assert 'data-workflow-max-selected="3"' in resp.text
    assert 'data-candidate-id="custom"' in resp.text
    assert 'data-execution-queue-item="custom"' in resp.text
    assert 'data-candidate-execution="custom"' in resp.text
    assert "checkoutservice · memory-stress" in resp.text
    assert "입력 내용과 무관하게" in resp.text
    assert "hx-post" not in resp.text


def test_execute_stage_can_open_final_verification_preview(client):
    resp = client.get("/experiments/2?view=execute")
    assert resp.status_code == 200
    assert 'data-workflow-go="verify"' in resp.text
    assert "data-workflow-preview-unlock" in resp.text
    assert "최종 회귀 검증 시안 보기" in resp.text
    assert 'data-workflow-go="result" data-workflow-preview-unlock' in resp.text
    assert "결과 화면 시안 보기" in resp.text


def test_experiment_detail_404(client):
    resp = client.get("/experiments/99999")
    assert resp.status_code == 404


def test_infra_page(client):
    resp = client.get("/infra")
    assert resp.status_code == 200
    assert "Prometheus" in resp.text and "ng-spot-1" in resp.text


def test_local_infra_page(client):
    resp = client.get("/infra/local")
    assert resp.status_code == 200
    assert "로컬 인프라" in resp.text
    assert "chaospilot-k3s" in resp.text
    assert "masternode" in resp.text and "worker2" in resp.text
    assert "Raspberry Pi 4B" in resp.text
    assert "Chaos Mesh" in resp.text and "chaospilot-observability" in resp.text
    assert "SSH 터널" in resp.text
    assert "모의 데이터" in resp.text            # 목업 정직 표기


def test_local_infra_partial_when_hx(client):
    resp = client.get("/infra/local", headers={"HX-Request": "true"})
    assert resp.status_code == 200
    assert "<!DOCTYPE html>" not in resp.text


def test_apps_new_dialog_env_branch(client):
    resp = client.get("/apps")
    assert resp.status_code == 200
    # 4-step 위저드: 환경 → 소스 → 설정 → 마무리 (ADR-0003)
    assert 'data-wiz-steps="4"' in resp.text
    assert "어느 클러스터" in resp.text
    assert "manifest YAML을 그대로 배포해요" in resp.text
    assert "부하 검증 경로" in resp.text          # ADR-0005 필드 (k3s 분기)
    assert "등록하고 배포할게요" in resp.text      # ADR-0004 정직 CTA


def test_register_k3s_app_stub(client):
    resp = client.post("/apps/k3s", data={"name": "demo-msa", "health_path": "/orders"})
    assert resp.status_code == 200
    assert "demo-msa" in resp.text               # 앱 목록에 즉시 등장
    # 새 실험 위저드에서 k3s 환경 배지로 표시 (seed order-msa + 신규 = 2개 이상)
    exp = client.get("/experiments")
    assert "demo-msa" in exp.text
    assert exp.text.count("k3s · 온프레미스") >= 2


def test_experiments_new_dialog_wizard(client):
    resp = client.get("/experiments")
    assert resp.status_code == 200
    # 2-step 위저드: 대상 앱 → 검증 목표 (설계는 항상 AI 후보 선택형, ADR-0006)
    assert 'data-wiz-steps="2"' in resp.text
    assert "대상 앱" in resp.text and "검증 목표" in resp.text
    assert "후보 생성 요청할게요" in resp.text
    # 제출은 워크플로우 시안의 후보 선택 단계로 바로 진입 (준비 탭 제거)
    assert 'hx-get="/experiments/1?view=plan"' in resp.text
    # 환경 배지 — order-msa만 k3s, 나머지는 EKS
    assert "k3s · 온프레미스" in resp.text and "EKS · 클라우드" in resp.text
    # 직접 설계 폼 제거 (ADR-0006)
    assert 'name="latency_ms"' not in resp.text and "직접 설계" not in resp.text


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
