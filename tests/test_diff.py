from datetime import datetime, timedelta, timezone

from seatsalerts.diff import compute
from seatsalerts.rules import Verdict
from seatsalerts.state import State, load, save

T0 = datetime(2026, 11, 1, 12, 0, tzinfo=timezone.utc)


def v(kind="full_premium", seats=4, miles=95000, cabin="business"):
    return Verdict(kind, cabin, seats, miles)


def test_new_find_is_new():
    s = State()
    ch = compute({"a": v()}, s, T0)
    assert [x.availability_id for x in ch.new] == ["a"] and ch.gone == []


def test_same_find_next_poll_is_silent():
    s = State()
    compute({"a": v()}, s, T0)
    ch = compute({"a": v()}, s, T0 + timedelta(minutes=3))
    assert ch.new == [] and ch.gone == [] and ch.possible_repeat == []


def test_drop_below_rule_sends_gone_once():
    s = State()
    compute({"a": v()}, s, T0)
    ch = compute({}, s, T0 + timedelta(minutes=3))
    assert [x.availability_id for x in ch.gone] == ["a"]
    ch2 = compute({}, s, T0 + timedelta(minutes=6))
    assert ch2.gone == []


def test_seat_increase_is_silent():
    s = State()
    compute({"a": v(seats=3)}, s, T0)
    ch = compute({"a": v(seats=6)}, s, T0 + timedelta(minutes=3))
    assert ch.new == [] and ch.gone == []


def test_reappear_after_six_hours_is_new():
    s = State()
    compute({"a": v()}, s, T0)
    compute({}, s, T0 + timedelta(minutes=3))
    ch = compute({"a": v()}, s, T0 + timedelta(hours=6, minutes=4))
    assert [x.availability_id for x in ch.new] == ["a"]


def test_reappear_within_six_hours_is_silent():
    s = State()
    compute({"a": v()}, s, T0)
    compute({}, s, T0 + timedelta(minutes=3))
    ch = compute({"a": v()}, s, T0 + timedelta(hours=2))
    assert ch.new == [] and ch.gone == []


def test_real_count_to_unknown_is_not_gone_and_possible_once_per_day():
    s = State()
    compute({"a": v(seats=4)}, s, T0)
    ch = compute({"a": v(kind="possible", seats=None)}, s, T0 + timedelta(minutes=3))
    assert ch.gone == [] and ch.new == []
    assert [x.availability_id for x in ch.possible_repeat] == ["a"]
    ch2 = compute({"a": v(kind="possible", seats=None)}, s, T0 + timedelta(hours=3))
    assert ch2.possible_repeat == []
    ch3 = compute({"a": v(kind="possible", seats=None)}, s, T0 + timedelta(hours=25))
    assert [x.availability_id for x in ch3.possible_repeat] == ["a"]


def test_possible_find_first_time_is_new_then_daily():
    s = State()
    ch = compute({"p": v(kind="possible", seats=None)}, s, T0)
    assert [x.availability_id for x in ch.new] == ["p"]
    ch2 = compute({"p": v(kind="possible", seats=None)}, s, T0 + timedelta(hours=1))
    assert ch2.new == [] and ch2.possible_repeat == []


def test_baseline_mode_reports_nothing():
    s = State()
    ch = compute({"a": v(), "b": v()}, s, T0, baseline=True)
    assert ch.new == [] and ch.gone == []
    assert set(s.seen) == {"a", "b"}


def test_state_round_trips(tmp_path):
    s = State()
    compute({"a": v()}, s, T0)
    s.calls.record(day="2026-11-01")
    p = tmp_path / "state.json"
    save(s, str(p))
    s2 = load(str(p))
    assert "a" in s2.seen and s2.calls.today_count(day="2026-11-01") == 1
    assert load(str(tmp_path / "missing.json")).seen == {}
