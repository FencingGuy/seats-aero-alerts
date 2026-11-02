"""The loop: search, judge, diff, notify, remember. Health messages kept rare."""
from __future__ import annotations

import copy
import html
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from .config import Config
from .diff import Changes, compute
from .messages import format_changes, scrub_for_log
from .points import parse_balances
from .rules import evaluate
from .seats_client import AuthError, today_key
from .state import State, save

log = logging.getLogger("seatsalerts")
FAILURES_BEFORE_WARNING = 3
GAP_WARNING = timedelta(minutes=90)
SEND_ATTEMPTS = 3


class Poller:
    def __init__(self, cfg: Config, state: State, seats, telegram, balances_env: str | None,
                 dry_run: bool = False, state_path: str | None = None,
                 sleep: Callable[[float], None] = time.sleep):
        self.cfg = cfg
        self.state = state
        self.seats = seats
        self.tg = telegram
        self.balances, self.balance_problems = parse_balances(balances_env, report=True)
        self.dry_run = dry_run
        self.state_path = state_path
        self.sleep = sleep
        self.failures = 0
        self.failure_warned = False
        self.stopped = False

    # -- helpers -----------------------------------------------------------

    def _send(self, text: str) -> bool:
        if self.dry_run:
            log.info("DRY RUN, would send:\n%s", scrub_for_log(text))
            return True
        for attempt in range(SEND_ATTEMPTS):
            try:
                self.tg.send(text)
                return True
            except Exception as exc:  # noqa: BLE001
                log.error("Telegram send failed (%s/%s): %s", attempt + 1, SEND_ATTEMPTS, exc)
                self.sleep(2 * (attempt + 1))
        return False

    def _persist(self) -> None:
        if self.state_path and not self.dry_run:
            save(self.state, self.state_path)

    def sample(self) -> int:
        """Print one raw record so the field names and tax units can be eyeballed. One API call."""
        records = self.seats.search(self.cfg)
        if not records:
            print("No records returned for the configured search.")
            return 0
        print(json.dumps(records[0], indent=2, sort_keys=True))
        print(f"\n{len(records)} records total. Check JTotalTaxes (cents) and TaxesCurrency above.")
        return 0

    def interval(self, day: str | None = None) -> int:
        if self.state.calls.today_count(day) >= self.cfg.backoff_at_calls:
            return self.cfg.backoff_seconds
        return self.cfg.poll_seconds

    def _health_checks(self, now: datetime) -> None:
        day = today_key(now)
        if self.state.last_run_at:
            gap = now - datetime.fromisoformat(self.state.last_run_at)
            if gap > GAP_WARNING:
                self._send(f"Heads up: there was a gap of {int(gap.total_seconds() // 60)} minutes "
                           f"between polls. GitHub may have delayed or skipped a run.")
        if self.state.last_daily_health != day:
            used = self.state.calls.today_count(today_key(now - timedelta(days=1)))
            if self._send(f"Alive. {used} seats.aero calls used yesterday, watching "
                          f"{self.cfg.start_date} to {self.cfg.end_date}."):
                self.state.last_daily_health = day
        if (not self.balances or self.balance_problems) and not self.state.balances_warned:
            detail = "; ".join(html.escape(p) for p in self.balance_problems) or "it is not set"
            if self._send(f"Note: POINTS_BALANCES could not be fully read ({detail}). "
                          f"Use the form bilt=100000,chase=200000 with no commas inside numbers. "
                          f"Messages will skip or misjudge the 'covered by' line until fixed."):
                self.state.balances_warned = True

    def _notify(self, changes: Changes, baseline: bool) -> None:
        trips = {}
        for ch in changes.new + changes.back + changes.changed:
            try:
                trips[ch.availability_id] = self.seats.trips(ch.availability_id)
            except Exception as exc:  # noqa: BLE001
                log.warning("trips fetch failed for %s: %s", ch.availability_id, exc)
        for text in format_changes(changes, trips, self.cfg, self.balances, baseline=baseline):
            if not self._send(text):
                # Forget the finds in this batch so the next poll announces them again.
                for ch in changes.all_pinged():
                    self.state.seen.pop(ch.availability_id, None)
                log.error("Telegram unreachable; finds will be re-announced next poll")
                return

    # -- one poll ----------------------------------------------------------

    def run_once(self, now: datetime | None = None) -> None:
        if self.stopped:
            return
        now = now or datetime.now(timezone.utc)
        day = today_key(now)
        self._health_checks(now)

        if self.state.calls.today_count(day) >= self.cfg.daily_budget:
            log.warning("daily budget reached (%s), skipping this poll", self.cfg.daily_budget)
            self.state.last_run_at = now.isoformat()
            self._persist()
            return

        try:
            records = self.seats.search(self.cfg)
        except AuthError as exc:
            if not self.state.auth_warned:
                self._send(f"Stopping: seats.aero rejected the API key ({html.escape(str(exc))}). "
                           f"Regenerate it at seats.aero/settings and update the GitHub secret.")
                self.state.auth_warned = True
            self.stopped = True
            self._persist()
            return
        except Exception as exc:  # noqa: BLE001
            self.failures += 1
            log.warning("search failed (%s/%s): %s", self.failures, FAILURES_BEFORE_WARNING, exc)
            if self.failures >= FAILURES_BEFORE_WARNING and not self.failure_warned:
                self._send(f"Trouble reaching seats.aero: {self.failures} polls in a row failed "
                           f"({html.escape(str(exc))[:300]}). Will keep trying.")
                self.failure_warned = True
            self.state.last_run_at = now.isoformat()
            self._persist()
            return
        self.failures = 0
        self.failure_warned = False
        self.state.auth_warned = False

        if not records and self.state.seen:
            log.warning("empty response while finds are known; treating as a hiccup")
            self.state.last_run_at = now.isoformat()
            self._persist()
            return

        verdicts, meta = {}, {}
        for r in records:
            v = evaluate(r, self.cfg)
            if v is None:
                continue
            aid = str(r.get("ID"))
            verdicts[aid] = v
            route = r.get("Route") or {}
            meta[aid] = {"origin": route.get("OriginAirport", ""),
                         "destination": route.get("DestinationAirport", ""),
                         "date": str(r.get("Date", ""))[:10],
                         "program": r.get("Source", "")}
        log.info("%d records, %d pass the party rule", len(records), len(verdicts))

        baseline = not self.state.baselined
        if self.dry_run:
            # A dry run must not change what the real run will consider new.
            self.state = copy.deepcopy(self.state)
        changes = compute(verdicts, self.state, now, meta=meta,
                          price_drop_alert=self.cfg.price_drop_alert)
        if baseline:
            self.state.baselined = True
            if changes.new:
                self._notify(Changes(new=changes.new), baseline=True)
        elif changes.any():
            self._notify(changes, baseline=False)

        self.state.last_run_at = now.isoformat()
        self._persist()

    # -- the hour-long loop -------------------------------------------------

    def run_loop(self, minutes: int) -> None:
        deadline = time.monotonic() + minutes * 60
        while not self.stopped:
            self.run_once()
            wait = self.interval()
            if time.monotonic() + wait > deadline:
                break
            self.sleep(wait)
