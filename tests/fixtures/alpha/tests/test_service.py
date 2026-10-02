from unittest import mock

import pytest

from app.service import fetch_orders, load_settings


def test_load_settings_requires_token(monkeypatch):
    monkeypatch.delenv("ORDERS_API_TOKEN", raising=False)
    with pytest.raises(KeyError):
        load_settings()


def test_fetch_orders_drops_negative_totals():
    settings = {"api_url": "https://api.test", "token": "t", "cache_dir": "/tmp"}
    response = mock.Mock(status_code=200)
    response.json.return_value = {"orders": [{"id": "1", "total": -1}, {"id": "2", "total": 3, "currency": "GBP"}]}
    with mock.patch("app.service.requests.get", return_value=response), mock.patch("app.service._write_cache"):
        orders = fetch_orders(settings, None, 0, False, [])
    assert [o["id"] for o in orders] == ["2"]
    assert orders[0]["currency"] == "EUR"
