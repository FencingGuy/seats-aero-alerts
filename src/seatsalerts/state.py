"""Persistent memory of what has already been reported."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field

from .seats_client import CallCounter


@dataclass
class SeenFind:
    availability_id: str
    kind: str
    cabin: str
    seats: int | None
    miles: int
    first_seen: str
    last_seen: str
    last_pinged: str
    gone_sent: bool = False
    gone_at: str | None = None
    origin: str = ""
    destination: str = ""
    date: str = ""
    program: str = ""


@dataclass
class State:
    seen: dict[str, SeenFind] = field(default_factory=dict)
    calls: CallCounter = field(default_factory=CallCounter)
    last_run_at: str | None = None
    last_daily_health: str | None = None
    balances_warned: bool = False
    baselined: bool = False
    auth_warned: bool = False


def load(path: str) -> State:
    if not os.path.exists(path):
        return State()
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    return State(
        seen={k: SeenFind(**v) for k, v in raw.get("seen", {}).items()},
        calls=CallCounter.from_dict(raw.get("calls")),
        last_run_at=raw.get("last_run_at"),
        last_daily_health=raw.get("last_daily_health"),
        balances_warned=bool(raw.get("balances_warned", False)),
        baselined=bool(raw.get("baselined", False)),
        auth_warned=bool(raw.get("auth_warned", False)),
    )


def save(state: State, path: str) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload = {
        "seen": {k: asdict(v) for k, v in state.seen.items()},
        "calls": state.calls.to_dict(),
        "last_run_at": state.last_run_at,
        "last_daily_health": state.last_daily_health,
        "balances_warned": state.balances_warned,
        "baselined": state.baselined,
        "auth_warned": state.auth_warned,
    }
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=1)
    os.replace(tmp, path)
