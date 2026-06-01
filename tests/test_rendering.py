from app.rendering import resolve_layout


def test_resolve_layout_full_when_no_hx():
    assert resolve_layout({}) == "base.html"


def test_resolve_layout_partial_when_hx():
    assert resolve_layout({"hx-request": "true"}) == "_partial.html"


def test_resolve_layout_case_insensitive():
    assert resolve_layout({"HX-Request": "true"}) == "_partial.html"
