"""Point balances live in a secret. This module says whether a find is affordable without printing figures."""
from __future__ import annotations

PRETTY = {"amex": "Amex", "chase": "Chase", "capitalone": "Capital One", "bilt": "Bilt",
          "virgin": "Virgin", "citi": "Citi"}


def parse_balances(env_value: str | None, report: bool = False):
    """Parse 'bilt=100000,chase=200000'. With report=True returns (balances, problems)."""
    out: dict[str, int] = {}
    problems: list[str] = []
    if env_value:
        for part in env_value.split(","):
            part = part.strip()
            if not part:
                continue
            if "=" not in part:
                if part.isdigit() and out:
                    # "bilt=194,000" split on the comma; drop the half-parsed entry.
                    bad = list(out)[-1]
                    out.pop(bad)
                    problems.append(f"'{bad}' has a comma inside the number")
                else:
                    problems.append(f"'{part}' is not name=number")
                continue
            k, v = part.split("=", 1)
            key = k.strip().lower().replace(" ", "")
            try:
                value = int(v.strip().lower().replace("k", "000"))
            except ValueError:
                problems.append(f"'{part}' has a bad number")
                continue
            if key not in PRETTY:
                problems.append(f"'{key}' is not a known program")
                continue
            out[key] = value
    return (out, problems) if report else out


def _k(n: int) -> str:
    return f"{round(n / 1000)}k"


def _alliance_of(program: str, alliances: dict[str, list[str]]) -> str | None:
    for name, members in alliances.items():
        if program in members:
            return name
    return None


def coverage(program: str, miles_total: int, balances: dict[str, int],
             transfer_map: dict[str, list[str]], onhand_airline: dict[str, str] | None = None,
             alliances: dict[str, list[str]] | None = None) -> str:
    """Plain-English affordability line. Never includes balance figures.

    Card points transfer in; airline miles held directly count for their own program;
    same-alliance airline miles get a partner-award hint."""
    if not balances:
        return ""
    onhand_airline = onhand_airline or {}
    alliances = alliances or {}
    partners = transfer_map.get(program)
    if partners is None:
        return "transfer partners unknown for this program"
    held = [(p, balances[p]) for p in partners if p in balances]
    for key, prog in onhand_airline.items():
        if prog == program and key in balances and key not in dict(held):
            held.append((key, balances[key]))
    hint = ""
    alliance = _alliance_of(program, alliances)
    if alliance:
        same = [PRETTY.get(k, k) for k, prog in onhand_airline.items()
                if k in balances and prog != program and prog in alliances.get(alliance, [])]
        if same:
            hint = f"; your {' or '.join(same)} miles may book this as a {alliance} partner award"
    if not partners and not held:
        return "no transfer partner among your cards" + hint
    if not held:
        return "no balance in a partner program" + hint
    best = max(held, key=lambda x: x[1])
    covering = [PRETTY.get(p, p) for p, b in held if b >= miles_total]
    if covering:
        return "covered by " + " or ".join(covering) + hint
    return f"short by {_k(miles_total - best[1])} via {PRETTY.get(best[0], best[0])}" + hint
