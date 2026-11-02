"""Tests for the behaviors adopted from Sam's alerter."""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

from seatsalerts.config import load
from seatsalerts.diff import Change, Changes, compute
from seatsalerts.messages import cache_age, format_changes
from seatsalerts.points import coverage
from seatsalerts.rules import Verdict, evaluate
from seatsalerts.state import SeenFind, State
from test_rules import cfg as base_cfg, rec

CFG = load("config.yaml")
T0 = datetime(2026, 11, 1, 20, 0, tzinfo=timezone.utc)
NOW = T0.isoformat()


def test_surcharge_cap_blocks_expensive_taxes():
    c = base_cfg()
    c.max_taxes_usd = 400
    r = rec(J=3, Jm="95000")
    r["JTotalTaxes"] = 140400  # $1,404.00 in cents
    r["TaxesCurrency"] = "USD"
    assert evaluate(r, c) is None
    r["JTotalTaxes"] = 14490
    r["TaxesCurrency"] = "CAD"
    c.fx_to_usd = {"USD": 1.0, "CAD": 0.73}
    v = evaluate(r, c)
    assert v is not None and v.taxes_usd == 105.78 and v.taxes_native == "145 CAD"


def test_direct_and_updated_at_carried():
    r = rec(J=3, Jm="95000")
    r["JDirect"] = True
    r["UpdatedAt"] = "2026-11-01T19:30:00Z"
    v = evaluate(r, base_cfg())
    assert v.direct and v.updated_at == "2026-11-01T19:30:00Z"


def test_cache_age_text():
    assert cache_age("2026-11-01T19:30:00Z", T0) == "seen by seats.aero 30 min ago"
    assert cache_age("2026-10-31T19:00:00Z", T0) == "seen by seats.aero 25h ago"
    assert cache_age("", T0) == "cache age unknown"


def test_price_drop_threshold():
    s = State()
    compute({"a": Verdict("full_premium", "business", 4, 95000)}, s, T0)
    ch = compute({"a": Verdict("full_premium", "business", 4, 93000)}, s, T0 + timedelta(minutes=6),
                 price_drop_alert=5000)
    assert ch.changed == []
    ch = compute({"a": Verdict("full_premium", "business", 4, 88000)}, s, T0 + timedelta(minutes=12),
                 price_drop_alert=5000)
    assert [x.availability_id for x in ch.changed] == ["a"]


def test_onhand_airline_miles_count_for_their_program():
    out = coverage("virginatlantic", 150000, {"virgin": 160000}, CFG.transfer_map,
                   CFG.onhand_airline, CFG.alliances)
    assert out.startswith("covered by Virgin")
    assert "160000" not in out


def test_alliance_partner_hint():
    out = coverage("flyingblue", 300000, {"virgin": 160000, "chase": 100000}, CFG.transfer_map,
                   CFG.onhand_airline, CFG.alliances)
    assert "skyteam partner award" in out and "Virgin" in out


def change(program, miles=95000, direct=False, kind="full_premium"):
    seen = SeenFind(program, kind, "business", 4, miles, NOW, NOW, NOW,
                    origin="SGN", destination="SFO", date="2027-01-07", program=program)
    return Change(program, Verdict(kind, "business", 4, miles, direct=direct,
                                   updated_at="2026-11-01T19:30:00Z", taxes_native="145 CAD"), seen)


def test_message_has_booking_link_badge_cache_age_taxes_nonstop():
    text = "\n".join(format_changes(Changes(new=[change("aeroplan", direct=True)]), {}, CFG, {}))
    assert "Book on Aeroplan" in text and "aircanada.com" in text
    assert "(favored)" in text and "nonstop" in text
    assert "seen by seats.aero" in text and "145 CAD" in text


def test_priority_sort_puts_united_last():
    msgs = format_changes(Changes(new=[change("united", miles=80000), change("aeroplan", miles=95000)]),
                          {}, CFG, {})
    text = "\n".join(msgs)
    assert text.index("Aeroplan") < text.index("United")
    assert "dynamic pricing" in text


def test_economy_tier_when_enabled():
    c = base_cfg()
    c.alert_economy = True
    v = evaluate(rec(Y=4, Ym="38000"), c)
    assert v is not None and v.kind == "economy" and v.seats == 4
    c.alert_economy = False
    assert evaluate(rec(Y=4, Ym="38000"), c) is None


def test_economy_never_outranks_premium():
    c = base_cfg()
    c.alert_economy = True
    v = evaluate(rec(J=3, Jm="95000", Y=5, Ym="30000"), c)
    assert v.kind == "full_premium"


def test_economy_to_premium_upgrade_pings():
    s = State()
    compute({"a": Verdict("economy", "economy", 4, 38000)}, s, T0)
    ch = compute({"a": Verdict("full_premium", "business", 3, 95000)}, s, T0 + timedelta(hours=1))
    assert [x.availability_id for x in ch.changed] == ["a"]
