"""Builds the Telegram text for a set of changes. HTML parse mode, no em dashes."""
from __future__ import annotations

import html
from urllib.parse import urlencode

from .config import Config
from .diff import Change, Changes
from .points import coverage

MAX_LEN = 4000
PROGRAM_NAMES = {
    "aeroplan": "Aeroplan", "united": "United", "virginatlantic": "Virgin Atlantic",
    "flyingblue": "Flying Blue", "singapore": "KrisFlyer", "qatar": "Qatar", "etihad": "Etihad",
    "emirates": "Emirates", "turkish": "Turkish", "alaska": "Alaska", "american": "American",
    "delta": "Delta", "qantas": "Qantas", "finnair": "Finnair", "eurobonus": "EuroBonus",
    "velocity": "Velocity", "lufthansa": "Miles and More", "asiamiles": "Asia Miles",
    "british": "British Airways", "jal": "JAL", "eva": "EVA", "lifemiles": "LifeMiles",
}
CABIN_NAMES = {"business": "Business", "premium": "Premium Economy", "economy": "Economy"}
COVERAGE_PREFIXES = ("covered by", "short by", "no transfer partner", "no balance", "transfer partners unknown")


def esc(value) -> str:
    return html.escape(str(value), quote=False)


def search_link(cfg: Config, origin: str, destination: str, date: str, cabin: str) -> str:
    q = {"origins": origin, "destinations": destination, "date": date,
         "applicable_cabin": cabin, "min_seats": cfg.party_size, "stops": cfg.max_stops,
         "min_cabin_pct": cfg.min_cabin_pct}
    return "https://seats.aero/search?" + urlencode(q)


def _program(code: str) -> str:
    return esc(PROGRAM_NAMES.get(code, code))


def _fmt_trips(trips: dict | None, limit: int = 3) -> list[str]:
    if not trips:
        return []
    lines = []
    for t in (trips.get("data") or [])[:limit]:
        hours = int(t.get("TotalDuration") or 0) // 60
        dep = str(t.get("DepartsAt", ""))[:16].replace("T", " ")
        taxes = t.get("TotalTaxes")
        tax_s = (f", taxes {esc(t.get('TaxesCurrencySymbol', ''))}{taxes / 100:,.0f} "
                 f"{esc(t.get('TaxesCurrency', ''))}") if taxes else ""
        mixed = f", {int(t['MixedCabinPct'])}% in a lower cabin" if t.get("MixedCabinPct") else ""
        lines.append(f"  {esc(t.get('FlightNumbers', ''))} dep {esc(dep)}, "
                     f"{esc(t.get('Stops', '?'))} stop(s), {hours}h{tax_s}{mixed}")
    return lines


def _find_block(ch: Change, cfg: Config, trips: dict | None, balances: dict[str, int],
                label: str) -> str:
    s, v = ch.seen, ch.verdict
    per = v.miles
    total = per * cfg.party_size
    if v.kind == "possible":
        seats = "seat count unknown, check before you trust it"
    elif v.kind == "split":
        seats = f"{v.seats} {CABIN_NAMES.get(v.cabin, v.cabin)} + economy for the rest"
    else:
        seats = f"{v.seats} seats"
    body = [f"<b>{esc(label)}: {esc(s.origin)} to {esc(s.destination)}, {esc(s.date)}</b>"]
    if ch.note:
        body.append(esc(ch.note))
    body.append(f"{CABIN_NAMES.get(v.cabin, v.cabin)} on {_program(s.program)}: {seats}")
    body.append(f"{per:,} miles per person, {total:,} for {cfg.party_size}")
    cov = coverage(s.program, total, balances, cfg.transfer_map)
    if cov:
        body.append(esc(cov))
    body.extend(_fmt_trips(trips))
    link = html.escape(search_link(cfg, s.origin, s.destination, s.date, v.cabin), quote=True)
    body.append(f'<a href="{link}">Open on seats.aero</a>')
    return "\n".join(body)


def format_changes(changes: Changes, trips_by_id: dict[str, dict], cfg: Config,
                   balances: dict[str, int], baseline: bool = False) -> list[str]:
    blocks: list[str] = []
    if baseline and changes.new:
        blocks.append(f"<b>Already open when the watcher started: {len(changes.new)} find(s).</b> "
                      "From now on you only hear about changes.")
    for ch in changes.new:
        label = "Possible" if ch.verdict.kind == "possible" else ("Open" if baseline else "New")
        blocks.append(_find_block(ch, cfg, trips_by_id.get(ch.availability_id), balances, label))
    for ch in changes.back:
        blocks.append(_find_block(ch, cfg, trips_by_id.get(ch.availability_id), balances, "Back"))
    for ch in changes.changed:
        blocks.append(_find_block(ch, cfg, trips_by_id.get(ch.availability_id), balances, "Update"))
    for ch in changes.possible_repeat:
        blocks.append(_find_block(ch, cfg, trips_by_id.get(ch.availability_id), balances,
                                  "Still possible"))
    for ch in changes.gone:
        s = ch.seen
        blocks.append(f"Gone: {esc(s.origin)} to {esc(s.destination)}, {esc(s.date)}, "
                      f"{CABIN_NAMES.get(s.cabin, s.cabin)} on {_program(s.program)} "
                      f"no longer fits the party rule or the price ceiling.")

    messages: list[str] = []
    current = ""
    for b in blocks:
        b = b[:MAX_LEN]
        candidate = b if not current else current + "\n\n" + b
        if len(candidate) > MAX_LEN and current:
            messages.append(current)
            current = b
        else:
            current = candidate
    if current:
        messages.append(current)
    return [m.replace("—", ",") for m in messages]


def scrub_for_log(text: str) -> str:
    """Drop the affordability line so public Actions logs cannot reveal balances."""
    return "\n".join(line for line in text.splitlines()
                     if not line.strip().lower().startswith(COVERAGE_PREFIXES))
