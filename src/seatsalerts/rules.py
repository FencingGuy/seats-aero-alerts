"""The party rule: decides whether one availability record is worth a ping."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .config import Config

CABIN_CODES = {"business": "J", "premium": "W", "economy": "Y"}
PREMIUM_CABINS = ("business", "premium")


@dataclass
class Verdict:
    kind: Literal["full_premium", "split", "possible", "economy"]
    cabin: str
    seats: int | None
    miles: int
    reasons: list[str] = field(default_factory=list)
    taxes_usd: float | None = None
    taxes_native: str = ""
    direct: bool = False
    updated_at: str = ""


def taxes_usd(record: dict, code: str, cfg: Config) -> tuple[float | None, str]:
    """Surcharges per person in USD, plus a native-currency string. The API returns cents."""
    raw = record.get(f"{code}TotalTaxes")
    if raw in (None, "", 0, "0"):
        return None, ""
    try:
        cents = int(float(str(raw).replace(",", "")))
    except ValueError:
        return None, ""
    currency = str(record.get("TaxesCurrency") or "USD").upper()
    native = cents / 100.0
    usd = round(native * cfg.fx_to_usd.get(currency, 1.0), 2)
    return usd, f"{native:,.0f} {currency}"


def _miles(record: dict, code: str) -> int | None:
    raw = record.get(f"{code}MileageCost")
    try:
        value = int(str(raw).strip() or 0)
    except ValueError:
        return None
    return value if value > 0 else None


def _cabin(record: dict, cabin: str) -> tuple[bool, int | None, int | None]:
    """Returns (available, seats or None when unknown, miles or None)."""
    code = CABIN_CODES[cabin]
    available = bool(record.get(f"{code}Available"))
    if not available:
        return False, None, None
    seats = int(record.get(f"{code}RemainingSeats") or 0)
    return True, (seats if seats > 0 else None), _miles(record, code)


def evaluate(record: dict, cfg: Config) -> Verdict | None:
    """Apply the party rule and the price ceilings to one cached record."""
    economy_ok, economy_seats, economy_miles = _cabin(record, "economy")
    economy_under = economy_miles is not None and economy_miles <= cfg.ceilings["economy"]
    possible: Verdict | None = None

    for cabin in PREMIUM_CABINS:
        available, seats, miles = _cabin(record, cabin)
        if not available or miles is None or miles > cfg.ceilings[cabin]:
            continue
        code = CABIN_CODES[cabin]
        tax_usd, tax_native = taxes_usd(record, code, cfg)
        if tax_usd is not None and tax_usd > cfg.max_taxes_usd:
            continue
        extra = dict(taxes_usd=tax_usd, taxes_native=tax_native,
                     direct=bool(record.get(f"{code}Direct")),
                     updated_at=str(record.get("UpdatedAt") or ""))
        if seats is None:
            # Program hides seat counts (United, American, sometimes Aeroplan).
            possible = possible or Verdict("possible", cabin, None, miles,
                                           ["seat count unknown"], **extra)
            continue
        if seats >= cfg.party_size:
            return Verdict("full_premium", cabin, seats, miles, **extra)
        need_premium = cfg.split_rule.get("premium", 1)
        need_economy = cfg.split_rule.get("economy", cfg.party_size - need_premium)
        if (seats >= need_premium and economy_ok and economy_seats is not None
                and economy_seats >= need_economy and economy_under):
            return Verdict("split", cabin, seats, miles,
                           [f"{need_premium} {cabin} + {need_economy} economy"], **extra)
    if possible:
        return possible
    if (cfg.alert_economy and economy_ok and economy_seats is not None
            and economy_seats >= cfg.party_size and economy_under):
        tax_usd, tax_native = taxes_usd(record, "Y", cfg)
        if tax_usd is None or tax_usd <= cfg.max_taxes_usd:
            return Verdict("economy", "economy", economy_seats, economy_miles,
                           taxes_usd=tax_usd, taxes_native=tax_native,
                           direct=bool(record.get("YDirect")),
                           updated_at=str(record.get("UpdatedAt") or ""))
    return None
