from __future__ import annotations

from dataclasses import dataclass, field

import yaml


@dataclass
class Config:
    origins: list[str]
    destinations: list[str]
    start_date: str
    end_date: str
    cabins: list[str]
    party_size: int
    split_rule: dict[str, int]
    ceilings: dict[str, int]
    poll_seconds: int
    backoff_seconds: int
    backoff_at_calls: int
    daily_budget: int
    transfer_map: dict[str, list[str]] = field(default_factory=dict)
    min_cabin_pct: int = 75
    max_stops: int = 2


def load(path: str) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    return Config(
        origins=[str(x) for x in raw["origins"]],
        destinations=[str(x) for x in raw["destinations"]],
        start_date=str(raw["start_date"]),
        end_date=str(raw["end_date"]),
        cabins=list(raw["cabins"]),
        party_size=int(raw["party_size"]),
        split_rule={k: int(v) for k, v in raw["split_rule"].items()},
        ceilings={k: int(v) for k, v in raw["ceilings"].items()},
        poll_seconds=int(raw["poll_seconds"]),
        backoff_seconds=int(raw["backoff_seconds"]),
        backoff_at_calls=int(raw["backoff_at_calls"]),
        daily_budget=int(raw["daily_budget"]),
        transfer_map={k: list(v or []) for k, v in (raw.get("transfer_map") or {}).items()},
        min_cabin_pct=int(raw.get("min_cabin_pct", 75)),
        max_stops=int(raw.get("max_stops", 2)),
    )
