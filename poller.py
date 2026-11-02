"""Entry point. Run `python poller.py --once --dry-run` to test locally."""
import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))

from seatsalerts.config import load  # noqa: E402
from seatsalerts.poller import Poller  # noqa: E402
from seatsalerts.seats_client import SeatsClient  # noqa: E402
from seatsalerts.state import load as load_state  # noqa: E402
from seatsalerts.telegram import TelegramClient  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--once", action="store_true", help="poll one time and exit")
    mode.add_argument("--loop", action="store_true", help="poll repeatedly for --minutes")
    ap.add_argument("--minutes", type=int, default=58)
    ap.add_argument("--dry-run", action="store_true", help="log instead of sending to Telegram")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--state", default=os.path.join("state", "state.json"))
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    api_key = os.environ.get("SEATS_AERO_API_KEY")
    if not api_key:
        print("SEATS_AERO_API_KEY is not set", file=sys.stderr)
        return 2
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not args.dry_run and not (token and chat):
        print("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID are required unless --dry-run", file=sys.stderr)
        return 2

    cfg = load(args.config)
    state = load_state(args.state)
    seats = SeatsClient(api_key, state.calls)
    tg = TelegramClient(token or "", chat or "")
    poller = Poller(cfg, state, seats, tg, balances_env=os.environ.get("POINTS_BALANCES"),
                    dry_run=args.dry_run, state_path=args.state)
    if args.once:
        poller.run_once()
    else:
        poller.run_loop(args.minutes)
    return 0


if __name__ == "__main__":
    sys.exit(main())
