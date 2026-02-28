# arb-finder 🎯

Scans Kalshi prediction markets vs DraftKings/FanDuel/BetMGM for pricing gaps and genuine arbitrage opportunities.

## What It Does

- Pulls all open Kalshi NBA/NFL game winner markets
- Fetches moneyline odds from 4+ sportsbooks via The Odds API
- Removes vig to calculate fair probability
- Compares Kalshi YES price vs fair value
- Flags: pure arb (guaranteed profit both sides) and value plays (Kalshi underpriced)
- Kelly criterion bet sizing
- Optional Telegram alerts

## Setup

```bash
cd arb-finder
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# Fill in: KALSHI_API_KEY, KALSHI_PRIVATE_KEY, ODDS_API_KEY, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
```

Keys:
- **Kalshi**: Settings → API at kalshi.com (RSA key pair)
- **The Odds API**: theOddsAPI.com (free tier: 500 req/month)

## Usage

```bash
# Single scan — print to console
python main.py

# Scan and send Telegram alert
python main.py --telegram

# Specific sports
python main.py --sport NBA NFL

# Continuous scan every 5 min
python main.py --watch --telegram

# Lower edge threshold (default: 5%)
python main.py --min-edge 0.02

# Verbose debug output
python main.py --verbose
```

## How Arb Works

**Pure Arbitrage** (guaranteed profit):
- Buy Kalshi YES at P¢
- Bet the NO side on a sportsbook
- Total cost < $1.00 → profit regardless of outcome

**Value Play** (one-sided edge):
- Kalshi asks 35¢ for an outcome sportsbooks price at 65% fair value
- +85% edge — you're getting heavily underpriced probability

## Architecture

```
main.py              — CLI entry point + scan orchestration
kalshi_client.py     — Kalshi API (RSA-PSS auth, market/orderbook fetch)
odds_client.py       — The Odds API wrapper (5-min cache)
matcher.py           — Ticker parser + team abbreviation matching
arb_engine.py        — Edge calculation, Kelly sizing, opportunity model
notifier.py          — Telegram formatter + sender
tests/               — 27 unit tests (pytest)
```

## Important Notes

- **Markets available**: Kalshi `KXNBAGAME` (game winner), `KXNBASPREAD` (spread)
- **Opponent validation**: Only compares markets where BOTH teams match same game
- **No cross-game mixing**: NOP vs UTA odds ≠ NOP vs LAC Kalshi market
- **Conservative arb threshold**: 97¢ total (3¢ buffer for Kalshi ~1% fee + execution)
- Kalshi Multiverse (KXMV) parlay markets are excluded — too complex to compare

## Ports & Integration

Standalone tool — no port. Run manually or via cron.

To wire into Mission Control or send to Telegram on a schedule, use the `--telegram --watch` flags or add a cron job.

## Tests

```bash
source venv/bin/activate
python -m pytest tests/ -v   # 27 tests, < 1s
```
