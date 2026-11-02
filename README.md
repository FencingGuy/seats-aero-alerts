# seats.aero award alerts

A small watcher that checks seats.aero every 3 minutes, around the clock, and sends a Telegram message only when award seats appear that fit the whole party at a sensible price. It runs for free on GitHub Actions and needs no computer left on at home.

## What it sends

- **New:** a find that fits the party rule (all seats in business or premium economy, or one premium seat plus two economy seats on the same flight) at or under the price ceiling. Includes the date, route, program, miles per person and for the party, the first few flight options, which card program covers it, and a link to seats.aero.
- **Possible:** same, but the program does not publish seat counts (United and American hide them). Check before you trust it. Repeats at most once a day.
- **Back:** a find that went away has reappeared.
- **Update:** the price changed, or a "possible" find now shows a real seat count.
- **Gone:** a find you were told about no longer fits. Sent once per disappearance.
- **Alive:** one line each morning with yesterday's API call count, so silence means something broke rather than "nothing found."
- **Trouble:** a warning if seats.aero stops answering, the API key is rejected, or GitHub skipped an hour.

Everything else is silent by design.

## One-time setup (about 15 minutes)

### 1. Create the Telegram bot

1. In Telegram, open a chat with **@BotFather** and send `/newbot`. Give it a name and a username ending in `bot`. BotFather replies with a token that looks like `123456789:AAH...`. That is `TELEGRAM_BOT_TOKEN`.
2. Open a chat with your new bot and send it any message (it cannot message you first).
3. To find your chat ID, open a chat with **@userinfobot** and send `/start`. It replies with your numeric ID. That is `TELEGRAM_CHAT_ID`.

### 2. Get your seats.aero API key

Go to seats.aero, Settings, then the API tab, and copy your key. That is `SEATS_AERO_API_KEY`.

### 3. Put the secrets in GitHub

In the repo on github.com: **Settings** > **Secrets and variables** > **Actions** > **New repository secret**. Add four:

| Name | Value |
|---|---|
| `SEATS_AERO_API_KEY` | your seats.aero key |
| `TELEGRAM_BOT_TOKEN` | the BotFather token |
| `TELEGRAM_CHAT_ID` | your numeric Telegram ID |
| `POINTS_BALANCES` | your balances, like `bilt=100000,chase=200000,amex=150000,capitalone=80000,virgin=50000` |

Secrets are encrypted and never appear in the code or the logs. Update `POINTS_BALANCES` whenever your balances change; it only affects the "covered by" line. No commas inside the numbers. Known names: `amex`, `chase`, `capitalone`, `bilt`, `virgin`, `citi`.

### 4. Run it once by hand

**Actions** tab > **Poll seats.aero** > **Run workflow**. Tick "dry run" the first time if you like; otherwise leave the defaults. Within a minute or two you should get an "Alive" message on Telegram. After that it runs itself every hour, polling every 3 minutes inside each run.

The very first poll sends one "Already open" summary of anything that qualifies right now, then only reports changes from the second poll on.

### 5. Keep GitHub from switching it off (important)

GitHub automatically disables scheduled workflows in a repo that has had no commits for 60 days. Set up on Nov 1, that lands right around Dec 31, days before the watch window. **Around Dec 15, make any small commit** (edit a word in this README and commit it from GitHub Desktop, or edit it on github.com). If GitHub emails you that the workflow was disabled, open the Actions tab and click Enable.

## Changing the trip

Edit `config.yaml` and commit. The important lines:

```yaml
origins: [DAD, SGN, HAN, BKK, SIN, HKG, TPE, ICN, TYO]
destinations: [SFO, SJC, OAK, LAX, SEA]
start_date: "2027-01-04"
end_date: "2027-01-11"
party_size: 3
ceilings:
  business: 110000      # miles per person; above this, silence
  premium: 75000
  economy: 45000
```

Airport codes can be single airports or seats.aero metro codes like `TYO` (all Tokyo airports) or `NYC`. For a new trip, change the origins, destinations, and dates. For a different party, change `party_size` and `split_rule`.

## Pausing and stopping

Actions tab > Poll seats.aero > the "..." menu > **Disable workflow**. Enable it again the same way. To stop for good, delete the repo or the workflow file.

## Limits worth knowing

- seats.aero Pro allows 1,000 API calls a day. At 3-minute polling this uses about 480 plus a handful per new find. The watcher slows itself to 6-minute polling if it ever reaches 900.
- seats.aero data is cached, not live. A find can be gone by the time you look. Book fast.
- GitHub's scheduler sometimes starts an hourly run a few minutes late. The watcher warns you if a gap exceeds 90 minutes.

## Running on your own computer (optional)

```
pip install -r requirements.txt
set SEATS_AERO_API_KEY=...          (PowerShell: $env:SEATS_AERO_API_KEY="...")
python poller.py --once --dry-run
```

`--dry-run` prints what it would send instead of sending it. `python -m pytest` runs the tests.
