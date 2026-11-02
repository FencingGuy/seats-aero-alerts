from seatsalerts.config import Config
from seatsalerts.rules import evaluate


def cfg():
    return Config(
        origins=["DAD"], destinations=["SFO"],
        start_date="2027-01-04", end_date="2027-01-11",
        cabins=["business", "premium", "economy"],
        party_size=3, split_rule={"premium": 1, "economy": 2},
        ceilings={"business": 110000, "premium": 75000, "economy": 45000},
        poll_seconds=180, backoff_seconds=360, backoff_at_calls=900,
        daily_budget=700, transfer_map={},
    )


def rec(J=None, W=None, Y=None, Jm="0", Wm="0", Ym="0"):
    r = {"ID": "abc", "Source": "aeroplan", "Date": "2027-01-07",
         "Route": {"OriginAirport": "DAD", "DestinationAirport": "SFO"}}
    for code, seats, miles in (("J", J, Jm), ("W", W, Wm), ("Y", Y, Ym)):
        r[f"{code}Available"] = seats is not None
        r[f"{code}RemainingSeats"] = seats or 0
        r[f"{code}MileageCost"] = miles
    return r


def test_three_business_passes():
    v = evaluate(rec(J=3, Jm="95000"), cfg())
    assert v.kind == "full_premium" and v.cabin == "business" and v.seats == 3


def test_two_business_one_economy_fails():
    assert evaluate(rec(J=2, Jm="95000", Y=1, Ym="30000"), cfg()) is None


def test_two_business_no_economy_fails():
    assert evaluate(rec(J=2, Jm="95000"), cfg()) is None


def test_one_business_two_economy_passes():
    v = evaluate(rec(J=1, Jm="95000", Y=2, Ym="30000"), cfg())
    assert v.kind == "split" and v.cabin == "business"


def test_one_business_one_economy_fails():
    assert evaluate(rec(J=1, Jm="95000", Y=1, Ym="30000"), cfg()) is None


def test_over_ceiling_fails():
    assert evaluate(rec(J=3, Jm="319055"), cfg()) is None


def test_unknown_count_is_possible():
    v = evaluate(rec(J=0, Jm="90000"), cfg())
    assert v.kind == "possible" and v.seats is None


def test_unknown_does_not_satisfy_split():
    v = evaluate(rec(J=0, Jm="90000", Y=0, Ym="30000"), cfg())
    assert v.kind == "possible"


def test_premium_economy_three_passes():
    v = evaluate(rec(W=3, Wm="70000"), cfg())
    assert v.kind == "full_premium" and v.cabin == "premium"


def test_split_economy_over_ceiling_fails():
    assert evaluate(rec(J=1, Jm="95000", Y=2, Ym="90000"), cfg()) is None
