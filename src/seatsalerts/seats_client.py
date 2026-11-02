"""Thin client for the seats.aero Partner API (cached search and trips)."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import requests

from .config import Config

BASE_URL = "https://seats.aero/partnerapi"
PACIFIC = ZoneInfo("America/Los_Angeles")
TIMEOUT = 30
MAX_PAGES = 5  # one poll can never burn more than this many calls on search


class RetryableError(Exception):
    """Rate limit or server error: sleep and try again later."""


class AuthError(Exception):
    """Bad or revoked API key: stop and tell Adam."""


def today_key(now: datetime | None = None) -> str:
    return (now or datetime.now(PACIFIC)).astimezone(PACIFIC).strftime("%Y-%m-%d")


class CallCounter:
    """Counts API calls per Pacific-time day so the loop can respect the daily budget."""

    def __init__(self, counts: dict[str, int] | None = None):
        self.counts: dict[str, int] = dict(counts or {})

    def record(self, day: str | None = None) -> None:
        day = day or today_key()
        self.counts[day] = self.counts.get(day, 0) + 1

    def today_count(self, day: str | None = None) -> int:
        return self.counts.get(day or today_key(), 0)

    def to_dict(self) -> dict:
        recent = sorted(self.counts)[-7:]
        return {"counts": {d: self.counts[d] for d in recent}}

    @classmethod
    def from_dict(cls, data: dict | None) -> "CallCounter":
        return cls((data or {}).get("counts"))


class SeatsClient:
    def __init__(self, api_key: str, call_counter: CallCounter):
        self.api_key = api_key
        self.counter = call_counter

    def _get(self, path: str, params: dict | None = None) -> dict:
        self.counter.record()
        resp = requests.get(f"{BASE_URL}{path}",
                            headers={"Partner-Authorization": self.api_key, "Accept": "application/json"},
                            params=params, timeout=TIMEOUT)
        if resp.status_code in (401, 403):
            raise AuthError(f"seats.aero returned {resp.status_code}")
        if resp.status_code == 429 or resp.status_code >= 500:
            raise RetryableError(f"seats.aero returned {resp.status_code}")
        if resp.status_code != 200:
            raise RetryableError(f"seats.aero returned {resp.status_code}")
        return resp.json()

    def search(self, cfg: Config) -> list[dict]:
        """One cached search across all configured origins and destinations, pages merged, capped."""
        params = {
            "origin_airport": ",".join(cfg.origins),
            "destination_airport": ",".join(cfg.destinations),
            "start_date": cfg.start_date,
            "end_date": cfg.end_date,
            "cabins": ",".join(cfg.cabins),
            "min_cabin_pct": cfg.min_cabin_pct,
            "take": 1000,
        }
        records: list[dict] = []
        for _ in range(MAX_PAGES):
            page = self._get("/search", params)
            records.extend(page.get("data") or [])
            cursor = page.get("cursor")
            if not page.get("hasMore") or not cursor:
                break
            params["cursor"] = cursor
            params["skip"] = len(records)
        return records

    def trips(self, availability_id: str) -> dict:
        return self._get(f"/trips/{availability_id}", {"include_filtered": "false"})
