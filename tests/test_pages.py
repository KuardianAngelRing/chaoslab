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


def test_experiment_detail_running(client):
    # seed 1번: boutique NetworkChaos running — 실행 진행 중 + 이후 단계 대기 (ADR-0008)
    resp = client.get("/experiments/1")
    assert resp.status_code == 200
    for stage in ("실행", "판정", "개선", "보고"):  # 스테퍼 4단계
        assert stage in resp.text
    assert "진행 중" in resp.text and "대기" in resp.text
    assert "ADR-0005" in resp.text  # NetworkChaos엔 /healthz 얕은 측정 경고 상시 표기
    assert "AI 루프" not in resp.text  # 구 5탭 잔재 제거


def test_experiment_detail_completed_story(client):
    # seed 2번: order-msa PodChaos completed — smoke 완주 스토리 (실패→개선→통과)
    resp = client.get("/experiments/2")
    assert resp.status_code == 200
    # 판정: 12종 체크 전체 노출 + 실패 근거
    assert "11/12" in resp.text
    assert "ready_pods_maintained_during_fault" in resp.text
    assert "LLM 판정 아님" in resp.text
    # 개선: iteration 카드 (패치·안전 검증·재실험)
    assert "PodDisruptionBudget" in resp.text
    assert "안전 검증" in resp.text and "재실험 PASSED" in resp.text
    # 보고: 원시 지표 비교 + R 수식 미확정 정직 표기
    assert "원시 지표" in resp.text and "수식 미확정" in resp.text


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
    # 환경 배지 — order-msa만 k3s, 나머지는 EKS
    assert "k3s · 온프레미스" in resp.text and "EKS · 클라우드" in resp.text
    # 직접 설계 폼 제거 (ADR-0006)
    assert 'name="latency_ms"' not in resp.text and "직접 설계" not in resp.text


def test_experiment_candidates_page(client):
    resp = client.get("/experiments/candidates", params={"app_id": 1, "objective": "주문 흐름 검증"})
    assert resp.status_code == 200
    assert "실험 후보" in resp.text and "직접 입력" in resp.text
    # 근거형 카드 (ADR-0007): 유형 배지 + 가설 + 예상 영향
    assert "PodChaos" in resp.text and "파드 강제종료" in resp.text
    assert "예상 영향" in resp.text
    assert "주문 흐름 검증" in resp.text            # 검증 목표 에코
    assert resp.text.count('<input type="radio" name="candidate"') == 4  # 후보 3 + 직접 입력


def test_plan_review_page(client):
    resp = client.get("/experiments/plan-review",
                      params={"app_id": 1, "candidate": "1", "objective": "주문 흐름 검증"})
    assert resp.status_code == 200
    assert "실험 계획 검토" in resp.text
    # 레이아웃 시안 3종 세그먼트 (팀 결정 전)
    assert "seg-control" in resp.text
    assert "요약 + YAML" in resp.text and "체크리스트" in resp.text and "타임라인" in resp.text
    # 공유 stub 데이터: 사람말 요약 + 조건 + YAML + 검증 배지
    assert "이렇게 진행돼요" in resp.text
    assert "labelSelectors" in resp.text            # Chaos Mesh CR 전문
    assert "보정 1회" in resp.text
    # 시안 C 체크리스트 / 시안 E 타임라인 요소
    assert "대상이 맞나요?" in resp.text
    assert "계획이 완성됐어요" in resp.text
    assert "실험 실행할게요" in resp.text


def test_plan_review_candidate_types(client):
    # 후보 2 = NetworkChaos → 스펙과 ADR-0005 경고 문구
    resp = client.get("/experiments/plan-review", params={"app_id": 1, "candidate": "2"})
    assert "NetworkChaos" in resp.text and "delay" in resp.text
    assert "ADR-0005" in resp.text
    # 직접 입력 → 서술 에코
    resp = client.get("/experiments/plan-review",
                      params={"app_id": 1, "candidate": "custom", "custom_text": "트래픽 절반 유실"})
    assert "직접 입력 실험" in resp.text and "트래픽 절반 유실" in resp.text


def test_plan_review_unknown_app_404(client):
    assert client.get("/experiments/plan-review", params={"app_id": 9999}).status_code == 404


def test_candidates_approve_navigates_to_plan_review(client):
    resp = client.get("/experiments/candidates", params={"app_id": 1})
    assert "/experiments/plan-review" in resp.text   # 승인 버튼이 검토 화면으로 이동


def test_experiment_candidates_unknown_app_404(client):
    assert client.get("/experiments/candidates", params={"app_id": 9999}).status_code == 404


def test_sidebar_no_eks_status_box(client):
    resp = client.get("/")          # 풀페이지(사이드바 포함)
    assert resp.status_code == 200
    assert "EKS 정상" not in resp.text  # 박스를 유일하게 식별하는 라벨 ("5/5"는 Slice4 실 노드수와 충돌 가능해 제외)
