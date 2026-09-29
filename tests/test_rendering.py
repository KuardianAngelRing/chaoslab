from app.rendering import resolve_layout


def test_resolve_layout_full_when_no_hx():
    assert resolve_layout({}) == "base.html"


def test_resolve_layout_partial_when_hx():
    assert resolve_layout({"hx-request": "true"}) == "_partial.html"


def test_resolve_layout_case_insensitive():
    assert resolve_layout({"HX-Request": "true"}) == "_partial.html"


def test_kst_filter_converts_naive_utc_to_korea_time():
    """DB의 naive UTC datetime은 화면에서 KST(+9)로 보여야 한다 — 실험 카드·빌드/배포 이력·차트 라벨 공용 필터."""
    from datetime import datetime, timezone
    from app.rendering import templates, to_kst

    naive_utc = datetime(2026, 9, 29, 3, 1, 41)
    assert to_kst(naive_utc) == "09/29 12:01"
    assert to_kst(naive_utc, "%H:%M:%S") == "12:01:41"
    assert to_kst(datetime(2026, 9, 29, 3, 1, 41, tzinfo=timezone.utc)) == "09/29 12:01"
    assert to_kst(None) == "-"
    assert templates.env.filters["kst"] is to_kst
