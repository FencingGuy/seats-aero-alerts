from seatsalerts.points import coverage, parse_balances

TM = {"aeroplan": ["amex", "chase", "capitalone", "bilt"], "lufthansa": []}


def test_parse_balances_ok():
    assert parse_balances("bilt=100000, chase=200000") == {"bilt": 100000, "chase": 200000}


def test_parse_balances_garbage_is_empty():
    assert parse_balances(None) == {}
    assert parse_balances("") == {}
    assert parse_balances("nonsense") == {}


def test_coverage_never_prints_numbers():
    out = coverage("aeroplan", 285000, {"bilt": 100000, "chase": 200000}, TM)
    assert "200000" not in out and "100000" not in out
    assert "Chase" in out


def test_coverage_short():
    out = coverage("aeroplan", 300000, {"bilt": 100000}, TM)
    assert "short" in out and "200k" in out


def test_coverage_empty_when_no_balances():
    assert coverage("aeroplan", 1, {}, TM) == ""


def test_coverage_no_partner():
    assert "no transfer partner" in coverage("lufthansa", 1, {"amex": 5}, TM)
