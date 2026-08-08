from __future__ import annotations

from app.api import widget_static


async def test_widget_js_404s_when_not_baked_in(client, monkeypatch, tmp_path):
    monkeypatch.setattr(widget_static, "_WIDGET_PATH", tmp_path / "missing-widget.js")
    response = await client.get("/widget.js")
    assert response.status_code == 404


async def test_widget_js_served_with_cache_header_when_present(client, monkeypatch, tmp_path):
    fake_widget = tmp_path / "widget.js"
    fake_widget.write_text("console.log('widget');")
    monkeypatch.setattr(widget_static, "_WIDGET_PATH", fake_widget)

    response = await client.get("/widget.js")

    assert response.status_code == 200
    assert response.text == "console.log('widget');"
    assert response.headers["cache-control"] == "public, max-age=300"
