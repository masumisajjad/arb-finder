"""
Pre-game Arb Scanner — runs ~30 min before tip-off.

Designed to be called as a standalone script (via OpenClaw cron):
    python pregame_scanner.py
    python pregame_scanner.py --window-min 20 --window-max 60
    python pregame_scanner.py --dry-run     # show upcoming games, no scan

Logic:
    1. Fetch today's NBA games from The Odds API
    2. Filter to games with tip-off in [window_min, window_max] minutes from now
    3. If games found, run full arb scan
    4. Send Telegram summary if opportunities found (or send a "no edge" note on pure arb check)
    5. Exit with code 0 (always — cron should not halt on no-games days)
"""
from __future__ import annotations

import argparse
import os
import sys
from datetime import datetime, timezone, timedelta
from typing import List, Tuple

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Env loading (same chain as main.py)
# ---------------------------------------------------------------------------
_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(dotenv_path=os.path.join(_DIR, ".env"))

_KALSHI_ENV = os.path.expanduser("~/projects/kalshi-deficit-receiver/.env")
if os.path.exists(_KALSHI_ENV):
    load_dotenv(dotenv_path=_KALSHI_ENV, override=False)

_PRIZEPICKS_ENV = os.path.expanduser("~/Developer/prizepicks-nba-picker/.env")
if os.path.exists(_PRIZEPICKS_ENV):
    load_dotenv(dotenv_path=_PRIZEPICKS_ENV, override=False)


# ---------------------------------------------------------------------------
# Time helpers
# ---------------------------------------------------------------------------

def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _minutes_until(iso_str: str) -> float | None:
    """Return minutes from now until the given ISO timestamp (UTC)."""
    if not iso_str:
        return None
    try:
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        delta = dt - _now_utc()
        return delta.total_seconds() / 60.0
    except Exception:
        return None


def _ct_str(iso_str: str) -> str:
    """Format an ISO UTC timestamp as e.g. '7:30 PM CT'."""
    if not iso_str:
        return "TBD"
    try:
        import pytz
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        ct = pytz.timezone("America/Chicago")
        return dt.astimezone(ct).strftime("%-I:%M %p CT")
    except Exception:
        return iso_str[:16]


# ---------------------------------------------------------------------------
# Game filtering
# ---------------------------------------------------------------------------

def filter_upcoming_games(
    odds_prices: dict,
    window_min: float = 20.0,
    window_max: float = 45.0,
) -> List[Tuple[str, str, str, float]]:
    """
    From odds_prices (team → {commence_time, opponent, ...}), return games
    where the tip-off is between window_min and window_max minutes from now.

    Returns: list of (home_team, away_team, commence_time_iso, minutes_until)
    Deduplicates: each game appears once (by home team only).
    """
    seen_pairs: set = set()
    upcoming = []

    for team, data in odds_prices.items():
        ct = data.get("commence_time", "")
        opp = data.get("opponent", "")
        mins = _minutes_until(ct)
        if mins is None:
            continue
        if mins < window_min or mins > window_max:
            continue

        # Deduplicate by canonical pair (sorted alphabetically)
        pair = tuple(sorted([team, opp]))
        if pair in seen_pairs:
            continue
        seen_pairs.add(pair)
        upcoming.append((team, opp, ct, mins))

    upcoming.sort(key=lambda x: x[3])  # soonest first
    return upcoming


# ---------------------------------------------------------------------------
# Main scanner logic
# ---------------------------------------------------------------------------

def run_pregame_scan(
    window_min: float = 20.0,
    window_max: float = 45.0,
    min_edge: float = 0.05,
    send_telegram: bool = True,
    verbose: bool = False,
    dry_run: bool = False,
) -> int:
    """
    Main entry point.
    Returns number of opportunities found (0 = nothing to act on).
    """
    from kalshi_client import KalshiClient
    from odds_client import OddsClient
    from arb_engine import ArbEngine
    from notifier import TelegramNotifier, format_summary, format_opportunity

    kalshi_key = os.getenv("KALSHI_API_KEY")
    odds_key = os.getenv("ODDS_API_KEY")

    if not kalshi_key or not odds_key:
        print("[pregame] ❌ Missing API keys — aborting")
        return 0

    odds = OddsClient()
    now_str = _now_utc().strftime("%b %d %I:%M %p UTC")

    print(f"[pregame] 🔍 Pre-game scan @ {now_str}")
    print(f"[pregame] Window: {window_min}–{window_max} min before tip-off")

    # Step 1: Get today's NBA prices
    odds_prices = odds.get_best_prices("NBA")
    print(f"[pregame] Odds API returned {len(odds_prices)} teams")

    if not odds_prices:
        print("[pregame] No odds data — exiting cleanly")
        return 0

    # Step 2: Filter to upcoming window
    upcoming = filter_upcoming_games(odds_prices, window_min=window_min, window_max=window_max)
    print(f"[pregame] Games in window: {len(upcoming)}")

    if not upcoming:
        print("[pregame] No games in window — nothing to scan")
        return 0

    # Print upcoming games
    for home, away, ct_iso, mins in upcoming:
        print(f"  🏀 {home} vs {away} — {_ct_str(ct_iso)} ({mins:.0f} min away)")

    if dry_run:
        print("[pregame] Dry run — skipping scan")
        return 0

    # Step 3: Run arb engine
    kalshi = KalshiClient()
    engine = ArbEngine(kalshi, odds, verbose=verbose)

    # Temporarily override min edge
    import arb_engine as _eng_mod
    original_min_edge = _eng_mod.MIN_EDGE_PCT
    _eng_mod.MIN_EDGE_PCT = min_edge

    try:
        opportunities = engine.scan(["NBA"])
    finally:
        _eng_mod.MIN_EDGE_PCT = original_min_edge

    # Step 4: Filter opportunities to only those in upcoming window
    # Match by checking if team name corresponds to an upcoming game
    upcoming_teams: set = set()
    for home, away, _, _ in upcoming:
        upcoming_teams.add(home)
        upcoming_teams.add(away)

    # Also track abbreviations the engine uses
    from matcher import KALSHI_ABBREV_TO_NAME
    abbrev_to_full = {v: k for k, v in KALSHI_ABBREV_TO_NAME.items()}  # full → abbrev

    def _is_upcoming(opp) -> bool:
        """Check if an opportunity's team is in an upcoming game."""
        team = opp.team
        # Try direct match (full name in upcoming_teams)
        if team in upcoming_teams:
            return True
        # Try abbreviation lookup
        full_name = KALSHI_ABBREV_TO_NAME.get(team, "")
        if full_name in upcoming_teams:
            return True
        return False

    filtered_opps = [o for o in opportunities if _is_upcoming(o)]
    all_opps = opportunities  # keep for reference

    scan_time = datetime.now().strftime("%b %d %I:%M %p CT")
    print(f"[pregame] Total opps from scan: {len(all_opps)}")
    print(f"[pregame] Filtered to upcoming window: {len(filtered_opps)}")

    # Step 5: Decide what to send
    telegram = TelegramNotifier() if send_telegram else None

    # Build the message
    game_list = "\n".join([
        f"  🏀 {home} vs {away} @ {_ct_str(ct_iso)} ({mins:.0f} min)"
        for home, away, ct_iso, mins in upcoming
    ])

    if filtered_opps:
        # There are actual opportunities — send full detail
        header = (
            f"🚨 PRE-GAME ARB ALERT — {scan_time}\n"
            f"Games tipping off in ~30 min:\n{game_list}\n\n"
            f"Found {len(filtered_opps)} opportunity(s):\n\n"
        )
        body = "\n".join([
            format_opportunity(o, i + 1) + "\n" + "—" * 28
            for i, o in enumerate(filtered_opps[:5])
        ])
        footer = "\n⚠️ Edge disappears fast — act now if you're betting."
        msg = header + body + footer

        print(f"[pregame] Sending {len(filtered_opps)} opportunities to Telegram")
        if telegram:
            sent = telegram.send(msg)
            print(f"[pregame] Telegram: {'✅ sent' if sent else '❌ failed'}")
    else:
        # No edge found — send a lightweight "checked, clean" message
        msg = (
            f"📊 Pre-game check — {scan_time}\n"
            f"Games soon:\n{game_list}\n\n"
            f"Scanned {len(all_opps)} total opportunities.\n"
            f"No edge found above {min_edge*100:.0f}% threshold for tonight's upcoming games.\n"
            f"Kalshi pricing looks fair."
        )
        print("[pregame] No opportunities — sending clean check-in")
        if telegram:
            sent = telegram.send(msg)
            print(f"[pregame] Telegram: {'✅ sent' if sent else '❌ failed'}")

    return len(filtered_opps)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Pre-game arb scanner — runs before tip-off")
    parser.add_argument("--window-min", type=float, default=20.0,
                        help="Min minutes before game start to scan (default: 20)")
    parser.add_argument("--window-max", type=float, default=45.0,
                        help="Max minutes before game start to scan (default: 45)")
    parser.add_argument("--min-edge", type=float, default=0.05,
                        help="Min edge %% to flag opportunity (default: 0.05 = 5%%)")
    parser.add_argument("--no-telegram", action="store_true",
                        help="Skip Telegram, print to console only")
    parser.add_argument("--verbose", action="store_true",
                        help="Verbose scan output")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show upcoming games only, skip scan")
    args = parser.parse_args()

    n = run_pregame_scan(
        window_min=args.window_min,
        window_max=args.window_max,
        min_edge=args.min_edge,
        send_telegram=not args.no_telegram,
        verbose=args.verbose,
        dry_run=args.dry_run,
    )

    sys.exit(0)  # always exit cleanly (cron shouldn't alert on "no games today")


if __name__ == "__main__":
    main()
