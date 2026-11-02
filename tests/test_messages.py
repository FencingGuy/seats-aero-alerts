import json
from datetime import datetime, timezone
from pathlib import Path

from seatsalerts.config import load
from seatsalerts.diff import Change, Changes
from seatsalerts.messages import format_changes, search_link
from seatsalerts.rules import Verdict
from seatsalerts.state import SeenFind

FIX = Path(__file__).parent / "fixtures"
CFG = load("config.yaml")
NOW = "2026-11-01T12:00:00+00:00"


def change(aid="avail-aeroplan-sgn-lax-0107", kind="full_premium", seats=4):
    seen = SeenFind(aid, kind, "business", seats, 95000, NOW, NOW, NOW,
                    origin="SGN", destination="LAX", date="2027-01-07", program="aeroplan")
    return Change(aid, Verdict(kind, "business", seats, 95000), seen)


def trips():
    return {"avail-aeroplan-sgn-lax-0107": json.loads((FIX / "trips.json").read_text())}


def test_message_contains_route_date_seats_program_miles_flights_link():
    msgs = format_changes(Changes(new=[change()]), trips(), CFG, {"chase": 200000})
    text = "\n".join(msgs)
    for needle in ["SGN", "LAX", "2027-01-07", "4 seats", "Aeroplan", "95,000", "285,000",
                   "SQ185", "seats.aero/search", "Chase", "12% in a lower cabin"]:
        assert needle in text, needle


def test_possible_find_is_labeled():
    msgs = format_changes(Changes(new=[change(kind="possible", seats=None)]), {}, CFG, {})
    assert "seat count unknown" in "\n".join(msgs)


def test_gone_notice():
    msgs = format_changes(Changes(gone=[change()]), {}, CFG, {})
    assert "gone" in "\n".join(msgs).lower()


def test_long_output_splits_under_4000():
    many = [change(aid=f"id-{i}") for i in range(60)]
    msgs = format_changes(Changes(new=many), {}, CFG, {})
    assert len(msgs) > 1 and all(len(m) <= 4000 for m in msgs)


def test_no_em_dash_in_output():
    msgs = format_changes(Changes(new=[change()], gone=[change(aid="x")]), trips(), CFG, {"bilt": 1})
    assert "—" not in "\n".join(msgs)


def test_search_link():
    url = search_link(CFG, "SGN", "LAX", "2027-01-07", "business")
    assert url.startswith("https://seats.aero/search?") and "origins=SGN" in url and "date=2027-01-07" in url
