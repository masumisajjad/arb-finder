#!/usr/bin/env python3
"""
🎯 Sports Arbitrage Finder
Scans Kalshi prediction markets vs DraftKings/FanDuel for pricing gaps.

Usage:
    python main.py                    # Run scan once, print to console
    python main.py --telegram         # Send results to Telegram
    python main.py --sport NBA NFL    # Scan specific sports (default: NBA)
    python main.py --watch            # Continuous scan every 5 min
    python main.py --min-edge 0.03    # Override minimum edge threshold
    python main.py --verbose          # Extra debug logging
"""
import argparse
import os
import sys
import time
from datetime import datetime

from dotenv import load_dotenv

# Load env from local .env first, then fall back to kalshi bot's .env
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), ".env"))
# Also load from kalshi bot env for API keys
KALSHI_ENV = os.path.expanduser("~/projects/kalshi-deficit-receiver/.env")
if os.path.exists(KALSHI_ENV):
    load_dotenv(dotenv_path=KALSHI_ENV, override=False)  # don't override if already set

PRIZEPICKS_ENV = os.path.expanduser("~/Developer/prizepicks-nba-picker/.env")
if os.path.exists(PRIZEPICKS_ENV):
    load_dotenv(dotenv_path=PRIZEPICKS_ENV, override=False)


def main():
    parser = argparse.ArgumentParser(description="Sports Arbitrage Finder")
    parser.add_argument("--telegram", action="store_true", help="Send results to Telegram")
    parser.add_argument("--sport", nargs="+", default=["NBA"], help="Sports to scan (NBA NFL MLB NHL)")
    parser.add_argument("--watch", action="store_true", help="Continuous scan loop")
    parser.add_argument("--interval", type=int, default=300, help="Watch interval in seconds (default: 300)")
    parser.add_argument("--min-edge", type=float, default=None, help="Minimum edge % threshold")
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    parser.add_argument("--dry-run", action="store_true", help="Show config, don't actually scan")
    args = parser.parse_args()

    # Apply overrides
    if args.min_edge is not None:
        import arb_engine
        arb_engine.MIN_EDGE_PCT = args.min_edge
        print(f"[config] Min edge override: {args.min_edge*100:.1f}%")

    # Validate environment
    kalshi_key = os.getenv("KALSHI_API_KEY")
    odds_key = os.getenv("ODDS_API_KEY")
    print(f"[config] KALSHI_API_KEY: {'✅ set' if kalshi_key else '❌ MISSING'}")
    print(f"[config] ODDS_API_KEY:   {'✅ set' if odds_key else '❌ MISSING'}")
    print(f"[config] Sports: {args.sport}")

    if args.dry_run:
        print("[config] Dry run — exiting")
        return

    if not kalshi_key or not odds_key:
        print("ERROR: Missing API keys. Set KALSHI_API_KEY and ODDS_API_KEY in .env")
        sys.exit(1)

    from kalshi_client import KalshiClient
    from odds_client import OddsClient
    from arb_engine import ArbEngine
    from notifier import TelegramNotifier, format_summary

    kalshi = KalshiClient()
    odds = OddsClient()
    engine = ArbEngine(kalshi, odds, verbose=args.verbose or not args.watch)
    telegram = TelegramNotifier() if args.telegram else None

    def run_scan():
        scan_time = datetime.now().strftime("%b %d %I:%M %p CT")
        print(f"\n{'='*50}")
        print(f"🔍 Scanning {args.sport} @ {scan_time}")
        print('='*50)

        try:
            opportunities = engine.scan(args.sport)
        except Exception as e:
            print(f"[ERROR] Scan failed: {e}")
            import traceback
            traceback.print_exc()
            return

        # Console output
        if not opportunities:
            print("No opportunities above threshold.")
        else:
            for i, opp in enumerate(opportunities, 1):
                from notifier import format_opportunity
                print(format_opportunity(opp, i))
                print("-" * 40)

        # Telegram
        if telegram:
            msg = format_summary(opportunities, scan_time)
            if opportunities or not args.watch:  # Always send if one-shot
                sent = telegram.send(msg)
                print(f"[telegram] {'sent ✅' if sent else 'failed ❌'}")

        return opportunities

    if args.watch:
        print(f"👀 Watch mode — scanning every {args.interval}s")
        while True:
            run_scan()
            print(f"⏳ Next scan in {args.interval}s...")
            time.sleep(args.interval)
    else:
        run_scan()


if __name__ == "__main__":
    main()
