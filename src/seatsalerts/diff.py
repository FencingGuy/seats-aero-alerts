"""Turns this poll's verdicts plus remembered state into what deserves a message."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .rules import Verdict
from .state import SeenFind, State

REAPPEAR_AFTER = timedelta(hours=6)
POSSIBLE_REPEAT_AFTER = timedelta(hours=24)
FORGET_AFTER = timedelta(days=14)


@dataclass
class Change:
    availability_id: str
    verdict: Verdict
    seen: SeenFind
    note: str = ""


@dataclass
class Changes:
    new: list[Change] = field(default_factory=list)
    gone: list[Change] = field(default_factory=list)
    back: list[Change] = field(default_factory=list)
    changed: list[Change] = field(default_factory=list)
    possible_repeat: list[Change] = field(default_factory=list)

    def any(self) -> bool:
        return bool(self.new or self.gone or self.back or self.changed or self.possible_repeat)

    def all_pinged(self) -> list[Change]:
        return self.new + self.gone + self.back + self.changed + self.possible_repeat


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _parse(s: str) -> datetime:
    return datetime.fromisoformat(s)


def compute(verdicts: dict[str, Verdict], state: State, now: datetime,
            baseline: bool = False, meta: dict[str, dict] | None = None,
            price_drop_alert: int = 5000) -> Changes:
    """Mutates state. `meta` optionally carries route/date/program per availability id."""
    changes = Changes()
    now_s = _iso(now)
    meta = meta or {}

    for aid, verdict in verdicts.items():
        prior = state.seen.get(aid)
        m = meta.get(aid, {})
        if prior is None or (prior.gone_sent and prior.gone_at
                             and now - _parse(prior.gone_at) >= REAPPEAR_AFTER):
            seen = SeenFind(aid, verdict.kind, verdict.cabin, verdict.seats, verdict.miles,
                            first_seen=now_s, last_seen=now_s, last_pinged=now_s,
                            origin=m.get("origin", ""), destination=m.get("destination", ""),
                            date=m.get("date", ""), program=m.get("program", ""))
            state.seen[aid] = seen
            if not baseline:
                changes.new.append(Change(aid, verdict, seen))
            continue

        was_real = prior.kind != "possible"
        came_back = prior.gone_sent
        prior.last_seen = now_s
        prior.gone_sent = False
        prior.gone_at = None

        if baseline:
            pass
        elif came_back:
            prior.last_pinged = now_s
            changes.back.append(Change(aid, verdict, prior))
        elif was_real and verdict.kind == "possible":
            prior.last_pinged = now_s
            changes.possible_repeat.append(Change(aid, verdict, prior, "seat count is now hidden"))
        elif verdict.kind == "possible":
            if now - _parse(prior.last_pinged) >= POSSIBLE_REPEAT_AFTER:
                prior.last_pinged = now_s
                changes.possible_repeat.append(Change(aid, verdict, prior))
        elif not was_real:
            prior.last_pinged = now_s
            changes.changed.append(Change(aid, verdict, prior, "seat count now confirmed"))
        elif verdict.cabin != prior.cabin or prior.miles - verdict.miles >= price_drop_alert:
            prior.last_pinged = now_s
            changes.changed.append(Change(aid, verdict, prior,
                                          f"was {prior.miles:,} per person"))

        prior.kind = verdict.kind
        prior.cabin = verdict.cabin
        prior.seats = verdict.seats
        prior.miles = verdict.miles

    for aid, prior in list(state.seen.items()):
        if aid in verdicts:
            continue
        if not prior.gone_sent:
            prior.gone_sent = True
            prior.gone_at = now_s
            if not baseline:
                changes.gone.append(Change(aid, Verdict(prior.kind, prior.cabin, prior.seats,
                                                        prior.miles), prior))
        elif prior.gone_at and now - _parse(prior.gone_at) >= FORGET_AFTER:
            del state.seen[aid]

    return changes
