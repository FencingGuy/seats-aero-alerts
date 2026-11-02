import json
from pathlib import Path

import pytest

from seatsalerts.config import load
from seatsalerts.seats_client import AuthError, CallCounter, RetryableError, SeatsClient

FIX = Path(__file__).parent / "fixtures"


class FakeResponse:
    def __init__(self, status, payload):
        self.status_code = status
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self):
        return self._payload


def install(monkeypatch, responses):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append({"url": url, "headers": headers, "params": params})
        status, payload = responses.pop(0)
        return FakeResponse(status, payload)

    monkeypatch.setattr("seatsalerts.seats_client.requests.get", fake_get)
    return calls


def page(name):
    return json.loads((FIX / name).read_text())


def test_search_follows_cursor_and_counts_two_calls(monkeypatch):
    calls = install(monkeypatch, [(200, page("search_page1.json")), (200, page("search_page2.json"))])
    counter = CallCounter()
    client = SeatsClient("key", counter)
    records = client.search(load("config.yaml"))
    assert [r["ID"] for r in records] == ["avail-aeroplan-sgn-lax-0107", "avail-united-han-sfo-0111"]
    assert counter.today_count() == 2
    assert calls[1]["params"]["cursor"] == "page2cursor"


def test_search_sends_required_params(monkeypatch):
    calls = install(monkeypatch, [(200, page("search_page2.json"))])
    SeatsClient("secret-key", CallCounter()).search(load("config.yaml"))
    p = calls[0]["params"]
    assert calls[0]["url"] == "https://seats.aero/partnerapi/search"
    assert calls[0]["headers"]["Partner-Authorization"] == "secret-key"
    cfg = load("config.yaml")
    assert p["origin_airport"] == ",".join(cfg.origins)
    assert p["destination_airport"] == ",".join(cfg.destinations)
    assert p["cabins"] == ",".join(cfg.cabins)
    assert p["start_date"] == cfg.start_date and p["end_date"] == cfg.end_date
    assert p["min_cabin_pct"] == 75 and p["take"] == 1000


def test_429_raises_retryable(monkeypatch):
    install(monkeypatch, [(429, {})])
    with pytest.raises(RetryableError):
        SeatsClient("key", CallCounter()).search(load("config.yaml"))


def test_401_raises_auth_error(monkeypatch):
    install(monkeypatch, [(401, {})])
    with pytest.raises(AuthError):
        SeatsClient("key", CallCounter()).search(load("config.yaml"))


def test_trips_fetches_by_id(monkeypatch):
    calls = install(monkeypatch, [(200, page("trips.json"))])
    out = SeatsClient("key", CallCounter()).trips("avail-aeroplan-sgn-lax-0107")
    assert calls[0]["url"].endswith("/partnerapi/trips/avail-aeroplan-sgn-lax-0107")
    assert out["data"][0]["FlightNumbers"] == "SQ185, AC20, UA698"


def test_call_counter_resets_on_new_day():
    c = CallCounter()
    c.record(day="2026-11-01")
    c.record(day="2026-11-01")
    assert c.today_count(day="2026-11-01") == 2
    assert c.today_count(day="2026-11-02") == 0
    assert CallCounter.from_dict(c.to_dict()).today_count(day="2026-11-01") == 2
