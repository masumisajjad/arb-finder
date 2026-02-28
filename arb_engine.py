"""
Arbitrage Engine — compares Kalshi YES contract prices vs sportsbook implied probabilities.

Arb Logic:
  Kalshi YES contract at price P (in cents) settles at $1.00 if outcome occurs.
  Expected value per dollar: (fair_prob - P/100) / (P/100)
  Kalshi fee: ~1% round-trip (0.5% each side — updated from earlier 7% estimate per LESSONS.md)

  True arb requires:
    kalshi_price + sportsbook_no_price < 100  (absolute guaranteed profit)

  Strong value requires:
    kalshi_price < fair_prob * 100 - FEE_BUFFER

We look for BOTH:
  1. Pure arbitrage (guaranteed profit regardless of outcome)
  2. Strong value plays (Kalshi significantly underprices vs sportsbook consensus)
"""
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from datetime import datetime, timezone
import math


KALSHI_FEE_PCT = 0.01          # 1% round-trip
MIN_EDGE_PCT = 0.05             # 5% minimum edge after fees to flag as value
MIN_ARB_EDGE_PCT = 0.02         # 2% edge for a pure arb (both sides positive)
MIN_BOOKS = 1                   # Minimum sportsbook sources to trust the price


@dataclass
class ArbOpportunity:
    ticker: str
    sport: str
    team: str
    opponent: str
    game_time: str

    # Kalshi side
    kalshi_yes_price: float     # in cents (0-100)
    kalshi_no_price: float      # in cents
    kalshi_yes_ask: float       # best ask (what you pay to buy YES)
    kalshi_no_ask: float        # best ask (what you pay to buy NO)

    # Sportsbook side
    fair_prob: float            # vig-removed fair probability (0-1)
    best_book_prob: float       # best moneyline price available (lowest prob = best odds)
    num_books: int

    # Derived
    edge_pct: float             # (fair_prob - kalshi_yes_ask/100) / (kalshi_yes_ask/100)
    is_pure_arb: bool           # kalshi_yes + sportsbook_no < 100
    arb_profit_pct: float       # guaranteed profit % if pure arb
    direction: str              # 'YES' or 'NO' (which side is underpriced)
    confidence: str             # 'HIGH' / 'MEDIUM' / 'LOW'
    reasoning: List[str] = field(default_factory=list)

    @property
    def star_rating(self) -> str:
        if self.edge_pct >= 0.20 or self.is_pure_arb:
            return "⭐⭐⭐⭐⭐"
        elif self.edge_pct >= 0.12:
            return "⭐⭐⭐⭐"
        elif self.edge_pct >= 0.08:
            return "⭐⭐⭐"
        elif self.edge_pct >= 0.05:
            return "⭐⭐"
        else:
            return "⭐"

    @property
    def kelly_fraction(self) -> float:
        """Kelly criterion fraction of bankroll to bet."""
        p = self.fair_prob
        b = (100 / self.kalshi_yes_ask) - 1  # net odds per dollar
        if b <= 0:
            return 0.0
        k = (b * p - (1 - p)) / b
        # Quarter Kelly for safety
        return max(0.0, min(k * 0.25, 0.15))  # cap at 15% of bankroll

    def suggested_bet(self, bankroll: float = 190.0) -> float:
        """Suggested bet size based on Kelly, capped at $50."""
        raw = bankroll * self.kelly_fraction
        return min(round(raw / 5) * 5, 50.0)  # round to nearest $5, cap $50


class ArbEngine:
    def __init__(self, kalshi_client, odds_client, verbose: bool = True):
        self.kalshi = kalshi_client
        self.odds = odds_client
        self.verbose = verbose

    def log(self, msg: str):
        if self.verbose:
            ts = datetime.now().strftime("%H:%M:%S")
            print(f"[{ts}] {msg}")

    def scan(self, sports: List[str] = None) -> List[ArbOpportunity]:
        """Main scan: find arb/value plays across all configured sports."""
        if sports is None:
            sports = ["NBA"]

        opportunities = []

        for sport in sports:
            self.log(f"Scanning {sport} markets on Kalshi...")
            opps = self._scan_sport(sport)
            self.log(f"  Found {len(opps)} opportunities in {sport}")
            opportunities.extend(opps)

        # Sort: pure arbs first, then by edge descending
        opportunities.sort(key=lambda o: (-int(o.is_pure_arb), -o.edge_pct))
        return opportunities

    def _scan_sport(self, sport: str) -> List[ArbOpportunity]:
        from matcher import parse_kalshi_ticker, find_odds_team

        # Step 1: Get sportsbook prices
        self.log(f"  Fetching {sport} sportsbook prices...")
        odds_prices = self.odds.get_best_prices(sport)
        self.log(f"  Got prices for {len(odds_prices)} teams")
        if not odds_prices:
            self.log(f"  No sportsbook data for {sport}")
            return []

        # Step 2: Get Kalshi markets — try multiple series names
        series_map = {
            "NBA": ["KXNBAGAME"],   # Game winners (most comparable to moneyline)
            "NFL": ["KXNFLGAME"],
            "MLB": ["KXMLBGAME"],
            "NHL": ["KXNHLGAME"],
        }
        all_markets = []
        for series in series_map.get(sport, [f"KX{sport}GAME"]):
            self.log(f"  Fetching Kalshi markets (series={series})...")
            markets = self.kalshi.get_all_open_markets(series_ticker=series)
            self.log(f"  Found {len(markets)} markets in {series}")
            all_markets.extend(markets)

        markets = all_markets
        self.log(f"  Total Kalshi markets: {len(markets)}")

        opportunities = []
        matched = 0
        unmatched = []

        for market in markets:
            ticker = market.get("ticker", "")
            parsed = parse_kalshi_ticker(ticker)
            if not parsed:
                continue

            # Only process game winner markets for clean arb comparison
            if parsed.get("market_type") not in ("game_winner", None):
                continue

            # Skip championship futures
            if parsed.get("market_type") == "championship_future":
                continue

            # Skip markets too far in the future (only today + 2 days)
            mdate = parsed.get("date")
            if mdate:
                days_out = (mdate.date() - datetime.now().date()).days
                if days_out > 2 or days_out < 0:
                    continue

            # Get the "yes" side team (this YES contract = team wins)
            team1 = parsed.get("team1")
            if not team1:
                continue

            # Try to match to an odds team
            odds_key = find_odds_team(team1, odds_prices, sport)
            if not odds_key:
                unmatched.append(ticker)
                continue

            odds_data = odds_prices[odds_key]

            # CRITICAL: Validate the opponent matches too
            # Don't compare NOP vs LAC Kalshi price with NOP vs UTA odds data
            team2 = parsed.get("team2", "")
            if team2:
                odds_opponent = find_odds_team(team2, odds_prices, sport)
                expected_opp = odds_data.get("opponent", "")
                if odds_opponent and odds_opponent != expected_opp:
                    # Different game — skip to avoid false arb signals
                    unmatched.append(f"{ticker}(opp_mismatch:{team2}≠{expected_opp})")
                    continue
                if not odds_opponent:
                    # Can't verify opponent — skip
                    unmatched.append(f"{ticker}(opp_unknown:{team2})")
                    continue

            matched += 1

            # Get Kalshi prices
            yes_price = float(market.get("yes_bid", 0) or 0)   # what YES sellers bid
            no_price = float(market.get("no_bid", 0) or 0)
            yes_ask = float(market.get("yes_ask", 0) or 0)     # what you pay to buy YES
            no_ask = float(market.get("no_ask", 0) or 0)

            # If no orderbook data in market object, try fetching orderbook
            if yes_ask == 0:
                ob = self.kalshi.get_orderbook(ticker)
                if ob:
                    asks = ob.get("yes", [])
                    bids_no = ob.get("no", [])
                    if asks:
                        yes_ask = float(asks[0][0]) if asks[0] else 0
                    if bids_no:
                        no_ask = float(bids_no[0][0]) if bids_no[0] else 0

            # Fallback: use yes_bid as proxy
            if yes_ask == 0:
                yes_ask = yes_price if yes_price > 0 else float(market.get("last_price", 50) or 50)

            if yes_ask == 0:
                continue

            fair_prob = odds_data["fair_prob"]
            best_prob = odds_data["best_price"]
            num_books = odds_data["num_books"]

            # Edge: how much Kalshi underprices vs fair value
            fair_in_cents = fair_prob * 100
            edge_cents = fair_in_cents - yes_ask
            edge_pct = edge_cents / yes_ask if yes_ask > 0 else 0

            # Pure arb: Kalshi YES price + (1 - sportsbook YES price) < 100
            # Meaning: if you buy Kalshi YES at P_yes cents AND also bet the NO side
            # on sportsbooks (which costs ~(1-prob)*100 cents equivalent),
            # the total outlay < $1.00, guaranteeing profit regardless of outcome.
            #
            # Conservative: require total < 97¢ (3¢ buffer for Kalshi fee + execution)
            sportsbook_no_implied = (1.0 - best_prob) * 100  # sportsbook's "cost" for NO side
            arb_total = yes_ask + sportsbook_no_implied
            # Account for Kalshi ~1% round-trip fee on the YES side
            arb_total_with_fees = yes_ask * (1 + KALSHI_FEE_PCT) + sportsbook_no_implied
            is_pure_arb = arb_total_with_fees < 97  # <97 = genuine profit after fees
            arb_profit_pct = (100 - arb_total_with_fees) / arb_total_with_fees if is_pure_arb else 0.0

            if edge_pct < MIN_EDGE_PCT and not is_pure_arb:
                continue

            if num_books < MIN_BOOKS:
                continue

            # Direction
            direction = "YES"
            if no_ask > 0:
                no_fair = (1 - fair_prob) * 100
                no_edge = (no_fair - no_ask) / no_ask
                if no_edge > edge_pct:
                    direction = "NO"
                    edge_pct = no_edge

            # Confidence
            if is_pure_arb:
                confidence = "HIGH"
            elif edge_pct >= 0.12 and num_books >= 3:
                confidence = "HIGH"
            elif edge_pct >= 0.07:
                confidence = "MEDIUM"
            else:
                confidence = "LOW"

            reasoning = [
                f"Kalshi YES ask: {yes_ask:.0f}¢",
                f"Fair probability: {fair_prob*100:.1f}¢ ({num_books} books)",
                f"Edge: {edge_pct*100:.1f}% ({edge_cents:.1f}¢)",
            ]
            if is_pure_arb:
                reasoning.insert(0, f"🚨 PURE ARB: guaranteed {arb_profit_pct*100:.1f}% profit")

            opp = ArbOpportunity(
                ticker=ticker,
                sport=sport,
                team=team1,
                opponent=parsed.get("team2", ""),
                game_time=odds_data.get("commence_time", ""),
                kalshi_yes_price=yes_price,
                kalshi_no_price=no_price,
                kalshi_yes_ask=yes_ask,
                kalshi_no_ask=no_ask,
                fair_prob=fair_prob,
                best_book_prob=best_prob,
                num_books=num_books,
                edge_pct=edge_pct,
                is_pure_arb=is_pure_arb,
                arb_profit_pct=arb_profit_pct,
                direction=direction,
                confidence=confidence,
                reasoning=reasoning,
            )
            opportunities.append(opp)

        self.log(f"  Matched {matched}/{len(markets)} markets | {len(unmatched)} unmatched")
        if unmatched and self.verbose:
            self.log(f"  Unmatched sample: {unmatched[:5]}")

        return opportunities
