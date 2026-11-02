from seatsalerts.config import load


def test_loads_repo_config():
    c = load("config.yaml")
    assert c.party_size == 3
    assert "TYO" in c.origins
    assert c.ceilings["business"] == 110000
    assert c.split_rule == {"premium": 1, "economy": 2}
