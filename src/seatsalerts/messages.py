"""Builds the Telegram text for a set of changes. HTML parse mode, no em dashes."""
from __future__ import annotations

import html
from datetime import datetime, timezone
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


def program_rank(code: str, cfg: Config) -> int:
    if code in cfg.priority_programs:
        return 0
    if code in cfg.deprioritize_programs:
        return 2
    return 1


def badge(code: str, cfg: Config) -> str:
    if code in cfg.priority_programs:
        return "favored"
    if code in cfg.deprioritize_programs:
        return "dynamic pricing, usually poor value"
    return ""


def cache_age(updated_at: str, now: datetime | None = None) -> str:
    """How old the seats.aero crawl is. Stale data is the usual reason a find is gone."""
    if not updated_at:
        return "cache age unknown"
    try:
        ts = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
    except ValueError:
        return "cache age unknown"
    now = now or datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    mins = max(0, int((now - ts).total_seconds() // 60))
    if mins < 60:
        return f"seen by seats.aero {mins} min ago"
    if mins < 48 * 60:
        return f"seen by seats.aero {mins // 60}h ago"
    return f"seen by seats.aero {mins // 1440}d ago"


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
    direct = ", nonstop" if v.direct else ""
    body = [f"<b>{esc(label)}: {esc(s.origin)} to {esc(s.destination)}, {esc(s.date)}{direct}</b>"]
    if ch.note:
        body.append(esc(ch.note))
    b = badge(s.program, cfg)
    body.append(f"{CABIN_NAMES.get(v.cabin, v.cabin)} on {_program(s.program)}"
                f"{' (' + b + ')' if b else ''}: {seats}")
    tax = f", taxes about {esc(v.taxes_native)} each" if v.taxes_native else ""
    body.append(f"{per:,} miles per person, {total:,} for {cfg.party_size}{tax}")
    cov = coverage(s.program, total, balances, cfg.transfer_map, cfg.onhand_airline, cfg.alliances)
    if cov:
        body.append(esc(cov))
    body.extend(_fmt_trips(trips))
    body.append(esc(cache_age(v.updated_at)))
    link = html.escape(search_link(cfg, s.origin, s.destination, s.date, v.cabin), quote=True)
    links = [f'<a href="{link}">Open on seats.aero</a>']
    site = cfg.booking_sites.get(s.program)
    if site:
        links.append(f'<a href="{html.escape(site, quote=True)}">Book on {_program(s.program)}</a>')
    body.append(" | ".join(links))
    return "\n".join(body)


def _economy_digest(items: list[Change], cfg: Config, balances: dict[str, int]) -> str:
    """Best N economy finds as one compact block, cheapest first, nonstop as a tiebreaker."""
    items = sorted(items, key=lambda ch: (ch.verdict.miles, not ch.verdict.direct, ch.seen.date))
    top = items[:cfg.economy_digest_size]
    lines = [f"<b>Economy: {len(items)} date(s) with {cfg.party_size} seats. Best {len(top)}:</b>"]
    for ch in top:
        s, v = ch.seen, ch.verdict
        link = html.escape(search_link(cfg, s.origin, s.destination, s.date, "economy"), quote=True)
        nonstop = ", nonstop" if v.direct else ""
        tax = f", {esc(v.taxes_native)} fees" if v.taxes_native else ""
        lines.append(f'<a href="{link}">{esc(s.date)} {esc(s.origin)} to {esc(s.destination)}</a> '
                     f'{v.miles:,} on {_program(s.program)}{nonstop}{tax}')
    if len(items) > len(top):
        lines.append(f"and {len(items) - len(top)} more above {top[-1].verdict.miles:,} miles")
    return "
".join(lines)


def format_changes(changes: Changes, trips_by_id: dict[str, dict], cfg: Config,
                   balances: dict[str, int], baseline: bool = False) -> list[str]:
    blocks: list[str] = []
    economy_new = [ch for ch in changes.new if ch.verdict.kind == "economy"]
    premium_new = [ch for ch in changes.new if ch.verdict.kind != "economy"]
    if baseline and changes.new:
        blocks.append(f"<b>Already open when the watcher started: {len(changes.new)} find(s).</b> "
                      "From now on you only hear about changes.")
    def order(ch: Change):
        kind_rank = {"full_premium": 0, "split": 1, "possible": 2}.get(ch.verdict.kind, 3)
        return (kind_rank, ch.seen.date, program_rank(ch.seen.program, cfg), ch.verdict.miles)

    for ch in sorted(premium_new, key=order):
        label = ("Possible" if ch.verdict.kind == "possible"
                 else "Economy" if ch.verdict.kind == "economy"
                 else "Open" if baseline else "New")
        blocks.append(_find_block(ch, cfg, trips_by_id.get(ch.availability_id), balances, label))
    for ch in changes.back:
        blocks.append(_find_block(ch, cfg, trips_by_id.get(ch.availability_id), balances, "Back"))
    for ch in changes.changed:
        blocks.append(_find_block(ch, cfg, trips_by_id.get(ch.availability_id), balances, "Update"))
    for ch in changes.possible_repeat:
        blocks.append(_find_block(ch, cfg, trips_by_id.get(ch.availability_id), balances,
                                  "Still possible"))
    if economy_new:
        blocks.append(_economy_digest(economy_new, cfg, balances))
    for ch in changes.gone:
        if ch.seen.kind == "economy":
            continue
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
