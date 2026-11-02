"""Tests added from the final review. Each one failed before its fix."""
import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from seatsalerts.config import load
from seatsalerts.diff import Change, Changes, compute
from seatsalerts.messages import format_changes
from seatsalerts.points import parse_balances
from seatsalerts.poller import Poller
from seatsalerts.rules import Verdict
from seatsalerts.seats_client import AuthError, CallCounter, RetryableError, SeatsClient
from seatsalerts.state import SeenFind, State

FIX = Path(__file__).parent / "fixtures"
CFG = load("config.yaml")
T0 = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
NOW = T0.isoformat()


def v(kind="full_premium", seats=4, miles=95000, cabin="business"):
    return Verdict(kind, cabin, seats, miles)


def change(aid="a", kind="full_premium", seats=4, miles=95000):
    seen = SeenFind(aid, kind, "business", seats, miles, NOW, NOW, NOW,
                    origin="SGN", destination="LAX", date="2027-01-07", program="lufthansa")
    return Change(aid, Verdict(kind, "business", seats, miles), seen)


# C2: no bare ampersands in HTML mode
def test_no_bare_ampersand_in_messages():
    text = "\n".join(format_changes(Changes(new=[change()]), {}, CFG, {}))
    assert "&" in text  # the link has query params
    assert not re.search(r"&(?!amp;|lt;|gt;|quot;)", text)


# C3: exception text is escaped in health messages
class Seats:
    def __init__(self, errors=None, pages=None):
        self.errors = list(errors or [])
        self.pages = pages
        self.counter = CallCounter()
        self.trip_calls = []

    def search(self, cfg):
        self.counter.record(day="2026-11-01")
        if self.errors:
            raise self.errors.pop(0)
        return self.pages() if callable(self.pages) else (self.pages or [])

    def trips(self, aid):
        self.trip_calls.append(aid)
        return json.loads((FIX / "trips.json").read_text())


class Tg:
    def __init__(self, fail_times=0):
        self.sent, self.fail_times = [], fail_times

    def send(self, text):
        if self.fail_times:
            self.fail_times -= 1
            raise RuntimeError("boom")
        self.sent.append(text)


def records():
    return json.loads((FIX / "search_page1.json").read_text())["data"]


def make(seats, tg=None, balances="chase=200000", baselined=True):
    st = State()
    st.calls = seats.counter
    st.last_daily_health = "2026-11-01"
    st.last_run_at = (T0 - timedelta(minutes=3)).isoformat()
    st.baselined = baselined
    tg = tg or Tg()
    return Poller(CFG, st, seats, tg, balances_env=balances, sleep=lambda s: None), tg, st


def test_exception_text_is_escaped():
    p, tg, _ = make(Seats(errors=[RetryableError("<urllib3 object at 0x1>")] * 3))
    for i in range(3):
        p.run_once(now=T0 + timedelta(minutes=3 * i))
    assert "&lt;urllib3" in tg.sent[0] and "<urllib3" not in tg.sent[0]


# I1: a failed first poll must not consume the baseline
def test_failed_first_poll_keeps_baseline():
    seats = Seats(errors=[RetryableError("x")], pages=records)
    p, tg, st = make(seats, baselined=False)
    p.run_once(now=T0)
    p.run_once(now=T0 + timedelta(minutes=3))
    assert st.baselined and all("New" not in m for m in tg.sent)


# I5: baseline sends one summary of what is already open
def test_baseline_sends_summary():
    p, tg, st = make(Seats(pages=records), baselined=False)
    p.run_once(now=T0)
    assert any("Already open" in m and "SGN to LAX" in m for m in tg.sent)


# I2: reappearance after a gone notice sends "Back"
def test_back_notice_after_gone():
    s = State()
    compute({"a": v()}, s, T0)
    compute({}, s, T0 + timedelta(minutes=3))
    ch = compute({"a": v()}, s, T0 + timedelta(minutes=6))
    assert [x.availability_id for x in ch.back] == ["a"]


def test_back_message_text():
    text = "\n".join(format_changes(Changes(back=[change()]), {}, CFG, {}))
    assert "Back" in text


# I7: price change and possible-to-real upgrade ping
def test_price_change_pings():
    s = State()
    compute({"a": v(miles=95000)}, s, T0)
    ch = compute({"a": v(miles=80000)}, s, T0 + timedelta(minutes=3))
    assert [x.availability_id for x in ch.changed] == ["a"]


def test_possible_to_real_pings():
    s = State()
    compute({"a": v(kind="possible", seats=None)}, s, T0)
    ch = compute({"a": v(seats=4)}, s, T0 + timedelta(minutes=3))
    assert [x.availability_id for x in ch.changed] == ["a"]


# I3: Telegram send retries, and an unsent find is not marked pinged
def test_send_retries_then_succeeds():
    p, tg, _ = make(Seats(pages=records), tg=Tg(fail_times=2))
    p.run_once(now=T0)
    assert len(tg.sent) == 1


def test_unsent_find_is_forgotten_so_it_can_retry_next_poll():
    seats = Seats(pages=records)
    p, tg, st = make(seats, tg=Tg(fail_times=10))
    p.run_once(now=T0)
    assert "avail-aeroplan-sgn-lax-0107" not in st.seen
    tg.fail_times = 0
    p.run_once(now=T0 + timedelta(minutes=3))
    assert any("SGN to LAX" in m for m in tg.sent)


# I4: pagination cap, skip param, hard budget stop
class Resp:
    def __init__(self, payload):
        self.status_code, self._p, self.text = 200, payload, ""

    def json(self):
        return self._p


def test_pagination_is_capped(monkeypatch):
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        calls.append(dict(params))
        return Resp({"data": [{"ID": str(len(calls))}], "hasMore": True, "cursor": "c"})

    monkeypatch.setattr("seatsalerts.seats_client.requests.get", fake_get)
    out = SeatsClient("k", CallCounter()).search(CFG)
    assert len(calls) == 5 and len(out) == 5
    assert calls[1]["skip"] == 1


def test_poll_skipped_at_daily_budget():
    seats = Seats(pages=records)
    p, tg, st = make(seats)
    for _ in range(CFG.daily_budget):
        st.calls.record(day="2026-11-01")
    before = st.calls.today_count(day="2026-11-01")
    p.run_once(now=T0)
    assert st.calls.today_count(day="2026-11-01") == before


# I6: malformed balances warn
def test_parse_balances_reports_problems():
    balances, problems = parse_balances("bilt=194,000, capital one=5, chase=200000", report=True)
    assert balances == {"chase": 200000, "capitalone": 5}
    assert any("comma" in p for p in problems)


# I8: dry-run logs must not include the coverage line
def test_dry_run_log_strips_coverage(caplog):
    p, tg, _ = make(Seats(pages=records))
    p.dry_run = True
    with caplog.at_level("INFO"):
        p.run_once(now=T0)
    assert "covered by" not in caplog.text and "short by" not in caplog.text


# Minor: auth error message only once; empty response guard
def test_auth_error_message_once_across_runs():
    s1 = Seats(errors=[AuthError("bad")])
    p, tg, st = make(s1)
    p.run_once(now=T0)
    p2 = Poller(CFG, st, Seats(errors=[AuthError("bad")]), tg, balances_env="chase=200000",
                sleep=lambda s: None)
    p2.run_once(now=T0 + timedelta(hours=1))
    assert len(tg.sent) == 1


def test_empty_response_with_known_finds_does_not_send_gone():
    seats = Seats(pages=records)
    p, tg, st = make(seats)
    p.run_once(now=T0)
    seats.pages = []
    p.run_once(now=T0 + timedelta(minutes=3))
    assert not any("Gone" in m for m in tg.sent)


def test_failed_health_send_is_retried_next_poll():
    p, tg, st = make(Seats(pages=[]), tg=Tg(fail_times=3))
    st.last_daily_health = "2026-10-31"
    p.run_once(now=T0)
    assert st.last_daily_health == "2026-10-31"
    tg.fail_times = 0
    p.run_once(now=T0 + timedelta(minutes=6))
    assert any("Alive" in m for m in tg.sent) and st.last_daily_health == "2026-11-01"
