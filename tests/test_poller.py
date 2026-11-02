import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from seatsalerts.config import load
from seatsalerts.poller import Poller
from seatsalerts.seats_client import AuthError, CallCounter, RetryableError
from seatsalerts.state import State

FIX = Path(__file__).parent / "fixtures"
CFG = load("config.yaml")
T0 = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)  # 12:00 Pacific


def records():
    return json.loads((FIX / "search_page1.json").read_text())["data"]


class FakeSeats:
    def __init__(self, pages=None, errors=None):
        self.pages = pages
        self.errors = list(errors or [])
        self.counter = CallCounter()
        self.trip_calls = []

    def search(self, cfg):
        self.counter.record(day="2026-11-01")
        if self.errors:
            raise self.errors.pop(0)
        return self.pages() if callable(self.pages) else (self.pages or [])

    def trips(self, aid):
        self.counter.record(day="2026-11-01")
        self.trip_calls.append(aid)
        return json.loads((FIX / "trips.json").read_text())


class FakeTg:
    def __init__(self):
        self.sent = []

    def send(self, text):
        self.sent.append(text)


def make(seats, state=None, balances="chase=200000", dry_run=False):
    tg = FakeTg()
    st = state or State()
    st.calls = seats.counter
    st.last_daily_health = "2026-11-01"
    st.last_run_at = (T0 - timedelta(minutes=3)).isoformat()
    st.baselined = True
    p = Poller(CFG, st, seats, tg, balances_env=balances, dry_run=dry_run)
    return p, tg, st


def test_once_sends_only_new_passing_finds():
    p, tg, _ = make(FakeSeats(records))
    p.run_once(now=T0)
    assert len(tg.sent) == 1 and "SGN to LAX" in tg.sent[0]
    p.run_once(now=T0 + timedelta(minutes=3))
    assert len(tg.sent) == 1


def test_once_fetches_trips_only_for_new_finds():
    seats = FakeSeats(records)
    p, _, _ = make(seats)
    p.run_once(now=T0)
    p.run_once(now=T0 + timedelta(minutes=3))
    assert seats.trip_calls == ["avail-aeroplan-sgn-lax-0107"]


def test_three_consecutive_failures_send_one_health_message():
    seats = FakeSeats([], errors=[RetryableError("x")] * 4)
    p, tg, _ = make(seats)
    for i in range(4):
        p.run_once(now=T0 + timedelta(minutes=3 * i))
    assert len(tg.sent) == 1 and "trouble" in tg.sent[0].lower()


def test_auth_error_sends_health_and_stops():
    seats = FakeSeats([], errors=[AuthError("bad key")])
    p, tg, _ = make(seats)
    p.run_once(now=T0)
    assert p.stopped and len(tg.sent) == 1 and "api key" in tg.sent[0].lower()


def test_backoff_at_900_calls():
    seats = FakeSeats([])
    p, _, st = make(seats)
    assert p.interval(day="2026-11-01") == CFG.poll_seconds
    for _ in range(900):
        st.calls.record(day="2026-11-01")
    assert p.interval(day="2026-11-01") == CFG.backoff_seconds


def test_daily_health_once_per_pacific_day():
    p, tg, st = make(FakeSeats([]))
    st.last_daily_health = "2026-10-31"
    p.run_once(now=T0)
    p.run_once(now=T0 + timedelta(minutes=3))
    assert len(tg.sent) == 1 and "alive" in tg.sent[0].lower()
    assert st.last_daily_health == "2026-11-01"


def test_gap_over_90_minutes_sends_warning():
    p, tg, st = make(FakeSeats([]))
    st.last_run_at = (T0 - timedelta(minutes=120)).isoformat()
    p.run_once(now=T0)
    assert any("gap" in m.lower() for m in tg.sent)


def test_missing_balances_omits_coverage_and_warns_once():
    p, tg, st = make(FakeSeats(records), balances=None)
    p.run_once(now=T0)
    assert any("balances" in m.lower() for m in tg.sent)
    find_msgs = [m for m in tg.sent if "SGN to LAX" in m]
    assert find_msgs and "covered" not in find_msgs[0]
    before = len(tg.sent)
    p.run_once(now=T0 + timedelta(minutes=3))
    assert len(tg.sent) == before


def test_dry_run_sends_nothing():
    p, tg, _ = make(FakeSeats(records), dry_run=True)
    p.run_once(now=T0)
    assert tg.sent == []


def test_first_poll_is_baseline_summary_not_new():
    p, tg, st = make(FakeSeats(records))
    st.baselined = False
    p.run_once(now=T0)
    assert any("Already open" in m for m in tg.sent)
    assert all("New:" not in m for m in tg.sent)
    assert "avail-aeroplan-sgn-lax-0107" in st.seen
    p.run_once(now=T0 + timedelta(minutes=3))
    assert sum("SGN to LAX" in m for m in tg.sent) == 1
