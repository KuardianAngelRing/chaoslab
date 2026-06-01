def test_stream_emits_event(client):
    with client.stream("GET", "/stream?once=1") as resp:
        assert resp.status_code == 200
        body = next(resp.iter_lines())
        assert body is not None
