"""
The Odds API wrapper — fetches sportsbook prices for arb comparison.
Supports NBA, NFL, NCAAB, MLB, NHL.
"""
import os
import time
import requests
from typing import Dict, List, Optional, Tuple


# sport keys for The Odds API
SPORT_KEYS = {
    "NBA": "basketball_nba",
    "NFL": "americanfootball_nfl",
    "NCAAB": "basketball_ncaab",
    "MLB": "baseball_mlb",
    "NHL": "icehockey_nhl",
    "SOCCER_EPL": "soccer_epl",
}

# Bookmakers to check (prioritize for best prices)
PRIORITY_BOOKS = ["fanduel", "draftkings", "betmgm", "williamhill_us", "pointsbet_us"]


class OddsClient:
    BASE_URL = "https://api.the-odds-api.com/v4"

    def __init__(self):
        self.api_key = os.getenv("ODDS_API_KEY")
        self._cache: Dict[str, Tuple[float, any]] = {}  # key → (timestamp, data)
        self._cache_ttl = 300  # 5 min

    def _get(self, path: str, params: Dict = None) -> Optional[any]:
        if not self.api_key:
            print("[odds] ODDS_API_KEY not set")
            return None

        # Cache check
        cache_key = path + str(sorted((params or {}).items()))
        if cache_key in self._cache:
            ts, data = self._cache[cache_key]
            if time.time() - ts < self._cache_ttl:
                return data

        full_params = {"apiKey": self.api_key, **(params or {})}
        url = self.BASE_URL + path
        try:
            r = requests.get(url, params=full_params, timeout=10)
            remaining = r.headers.get("x-requests-remaining", "?")
            used = r.headers.get("x-requests-used", "?")
            print(f"[odds] {path} — quota: {used} used, {remaining} remaining")
            r.raise_for_status()
            data = r.json()
            self._cache[cache_key] = (time.time(), data)
            return data
        except Exception as e:
            print(f"[odds] GET {path} error: {e}")
            return None

    def get_odds(self, sport: str = "NBA", regions: str = "us", markets: str = "h2h") -> List[Dict]:
        """Get moneyline odds for all games in a sport."""
        sport_key = SPORT_KEYS.get(sport, sport)
        data = self._get(f"/sports/{sport_key}/odds", {
            "regions": regions,
            "markets": markets,
            "oddsFormat": "decimal",
        })
        return data or []

    def get_best_prices(self, sport: str = "NBA") -> Dict[str, Dict]:
        """
        Returns a map of: team_name → {best_yes_prob, best_no_prob, best_yes_book, best_no_book}
        where yes_prob = probability of winning the moneyline bet.
        """
        games = self.get_odds(sport)
        results = {}

        for game in games:
            home = game.get("home_team", "")
            away = game.get("away_team", "")
            commence = game.get("commence_time", "")
            bookmakers = game.get("bookmakers", [])

            # Collect all prices across bookmakers
            home_probs = []
            away_probs = []

            for book in bookmakers:
                if book.get("key") not in PRIORITY_BOOKS:
                    continue
                for market in book.get("markets", []):
                    if market.get("key") != "h2h":
                        continue
                    for outcome in market.get("outcomes", []):
                        dec = outcome.get("price", 1.0)
                        prob = 1.0 / dec if dec > 1 else 0.0
                        if outcome.get("name") == home:
                            home_probs.append(prob)
                        elif outcome.get("name") == away:
                            away_probs.append(prob)

            if not home_probs or not away_probs:
                continue

            # Best price = lowest probability = most generous odds for bettor
            best_home_prob = min(home_probs)  # best odds for home team bettor
            best_away_prob = min(away_probs)  # best odds for away team bettor

            # Vig-free fair value using consensus
            avg_home = sum(home_probs) / len(home_probs)
            avg_away = sum(away_probs) / len(away_probs)
            total = avg_home + avg_away
            fair_home = avg_home / total if total > 0 else 0.5
            fair_away = avg_away / total if total > 0 else 0.5

            results[home] = {
                "opponent": away,
                "commence_time": commence,
                "sport": sport,
                "best_price": best_home_prob,   # best moneyline prob available
                "fair_prob": fair_home,          # vig-removed fair value
                "num_books": len(home_probs),
                "raw_probs": home_probs,
            }
            results[away] = {
                "opponent": home,
                "commence_time": commence,
                "sport": sport,
                "best_price": best_away_prob,
                "fair_prob": fair_away,
                "num_books": len(away_probs),
                "raw_probs": away_probs,
            }

        return results
