"""
Market matcher — maps Kalshi tickers to Odds API teams.

Kalshi NBA ticker format examples:
  KXNBA-25FEB27-DEN-NYK   → DEN vs NYK on Feb 27
  KXNBAS-25FEB27-DAL       → DAL game-level series market

We normalize team abbreviations to full names and fuzzy-match.
"""
import re
from datetime import datetime
from typing import Dict, Optional, Tuple


# Kalshi abbreviation → common name (used in Odds API)
KALSHI_ABBREV_TO_NAME = {
    # NBA
    "ATL": "Atlanta Hawks",
    "BOS": "Boston Celtics",
    "BKN": "Brooklyn Nets",
    "CHA": "Charlotte Hornets",
    "CHI": "Chicago Bulls",
    "CLE": "Cleveland Cavaliers",
    "DAL": "Dallas Mavericks",
    "DEN": "Denver Nuggets",
    "DET": "Detroit Pistons",
    "GSW": "Golden State Warriors",
    "HOU": "Houston Rockets",
    "IND": "Indiana Pacers",
    "LAC": "LA Clippers",
    "LAL": "Los Angeles Lakers",
    "MEM": "Memphis Grizzlies",
    "MIA": "Miami Heat",
    "MIL": "Milwaukee Bucks",
    "MIN": "Minnesota Timberwolves",
    "NOP": "New Orleans Pelicans",
    "NYK": "New York Knicks",
    "OKC": "Oklahoma City Thunder",
    "ORL": "Orlando Magic",
    "PHI": "Philadelphia 76ers",
    "PHX": "Phoenix Suns",
    "POR": "Portland Trail Blazers",
    "SAC": "Sacramento Kings",
    "SAS": "San Antonio Spurs",
    "TOR": "Toronto Raptors",
    "UTA": "Utah Jazz",
    "WAS": "Washington Wizards",
    # NFL
    "ARI": "Arizona Cardinals",
    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",
    "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",
    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",
    "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",
    "DEN": "Denver Broncos",
    "DET": "Detroit Lions",
    "GB": "Green Bay Packers",
    "HOU": "Houston Texans",
    "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars",
    "KC": "Kansas City Chiefs",
    "LAR": "Los Angeles Rams",
    "LV": "Las Vegas Raiders",
    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",
    "NE": "New England Patriots",
    "NO": "New Orleans Saints",
    "NYG": "New York Giants",
    "NYJ": "New York Jets",
    "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",
    "SEA": "Seattle Seahawks",
    "SF": "San Francisco 49ers",
    "TB": "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",
    "WAS": "Washington Commanders",
}

# Reverse: partial name → abbreviation used in Odds API team names
ODDS_TEAM_KEYWORDS = {
    "Hawks": "ATL", "Celtics": "BOS", "Nets": "BKN", "Hornets": "CHA",
    "Bulls": "CHI", "Cavaliers": "CLE", "Mavericks": "DAL", "Nuggets": "DEN",
    "Pistons": "DET", "Warriors": "GSW", "Rockets": "HOU", "Pacers": "IND",
    "Clippers": "LAC", "Lakers": "LAL", "Grizzlies": "MEM", "Heat": "MIA",
    "Bucks": "MIL", "Timberwolves": "MIN", "Pelicans": "NOP", "Knicks": "NYK",
    "Thunder": "OKC", "Magic": "ORL", "76ers": "PHI", "Suns": "PHX",
    "Trail Blazers": "POR", "Kings": "SAC", "Spurs": "SAS", "Raptors": "TOR",
    "Jazz": "UTA", "Wizards": "WAS",
}


def _split_team_pair(pair_str: str) -> tuple:
    """
    Split a concatenated team pair like 'SACLAL', 'PHIBOS', 'OKCDAL' into (team1, team2).
    Uses known 3-letter abbreviations to split correctly.
    """
    # All known 3-letter NBA abbreviations
    known = set(KALSHI_ABBREV_TO_NAME.keys())

    # Also add 2-letter NFL abbreviations
    nfl_2_letter = {"GB", "KC", "LV", "NO", "SF", "TB", "LA", "NE"}

    # Try 3+3 first
    if len(pair_str) >= 6:
        t1 = pair_str[:3]
        t2 = pair_str[3:]
        if t1 in known:
            return t1, t2

    # Try 3+2
    if len(pair_str) == 5:
        t1 = pair_str[:3]
        t2 = pair_str[3:]
        return t1, t2

    # Try 2+3
    if len(pair_str) == 5:
        t1 = pair_str[:2]
        t2 = pair_str[2:]
        if t1 in nfl_2_letter:
            return t1, t2

    # Default: split at midpoint
    mid = len(pair_str) // 2
    return pair_str[:mid], pair_str[mid:]


def parse_kalshi_ticker(ticker: str) -> Optional[Dict]:
    """
    Parse a Kalshi ticker and extract sport, date, and teams.

    Supported formats:
      KXNBAGAME-26MAR01SACLAL-SAC     → NBA game winner (SAC vs LAL, pick SAC)
      KXNBASPREAD-26FEB28PORCHA-CHA6  → NBA spread (CHA wins by 6.5+)
      KXNBA-26-OKC                    → NBA championship futures
      KXNFLGAME-26SEP01KCDAL-KC       → NFL game winner
      KXNFLSPREAD-26SEP01KCDAL-KC7    → NFL spread
    """
    ticker = ticker.upper().strip()

    # KXNBAGAME: KXNBAGAME-YYMONDDTEAM1TEAM2-WINNER
    m = re.match(r"KXNBAGAME-(\d{2}[A-Z]{3}\d{2})([A-Z]+)-([A-Z]+)$", ticker)
    if m:
        date_str, team_pair, winner = m.group(1), m.group(2), m.group(3)
        team1, team2 = _split_team_pair(team_pair)
        try:
            date = datetime.strptime(date_str, "%y%b%d")
        except ValueError:
            date = None
        return {
            "sport": "NBA",
            "market_type": "game_winner",
            "date": date,
            "team1": winner,          # the team this YES resolves to
            "team2": team2 if winner == team1 else team1,
            "ticker": ticker,
        }

    # KXNBASPREAD: KXNBASPREAD-YYMONDDTEAM1TEAM2-TEAMPTS
    m = re.match(r"KXNBASPREAD-(\d{2}[A-Z]{3}\d{2})([A-Z]+)-([A-Z]+)(\d+)$", ticker)
    if m:
        date_str, team_pair, team, pts = m.group(1), m.group(2), m.group(3), m.group(4)
        team1, team2 = _split_team_pair(team_pair)
        try:
            date = datetime.strptime(date_str, "%y%b%d")
        except ValueError:
            date = None
        return {
            "sport": "NBA",
            "market_type": "spread",
            "date": date,
            "team1": team,            # team that needs to win by X+
            "team2": team2 if team == team1 else team1,
            "spread": float(pts) + 0.5,  # add 0.5 for "over X.5"
            "ticker": ticker,
        }

    # KXNFLGAME: KXNFLGAME-YYMONDDTEAM1TEAM2-WINNER
    m = re.match(r"KXNFLGAME-(\d{2}[A-Z]{3}\d{2})([A-Z]+)-([A-Z]+)$", ticker)
    if m:
        date_str, team_pair, winner = m.group(1), m.group(2), m.group(3)
        team1, team2 = _split_team_pair(team_pair)
        try:
            date = datetime.strptime(date_str, "%y%b%d")
        except ValueError:
            date = None
        return {
            "sport": "NFL",
            "market_type": "game_winner",
            "date": date,
            "team1": winner,
            "team2": team2 if winner == team1 else team1,
            "ticker": ticker,
        }

    # Legacy KXNBA-YY-TEAM format (championship futures — skip for arb)
    m = re.match(r"KXNBA-(\d{2})-([A-Z]+)$", ticker)
    if m:
        return {
            "sport": "NBA",
            "market_type": "championship_future",
            "date": None,
            "team1": m.group(2),
            "team2": None,
            "ticker": ticker,
        }

    return None


def normalize_team(abbrev: str) -> str:
    """Convert Kalshi abbreviation to full team name."""
    return KALSHI_ABBREV_TO_NAME.get(abbrev.upper(), abbrev)


def find_odds_team(
    team_abbrev: str, odds_prices: Dict[str, Dict], sport: str = "NBA"
) -> Optional[str]:
    """
    Find the matching team name in odds_prices dict.
    Uses exact keyword matching to avoid false positives.
    Returns the key (full team name) if found, else None.
    """
    abbrev = team_abbrev.upper().strip()

    # Get the full team name for this abbreviation
    full_name = KALSHI_ABBREV_TO_NAME.get(abbrev, "").lower()
    if not full_name:
        return None

    # Try exact full name match first
    for team_key in odds_prices:
        if odds_prices[team_key].get("sport") != sport:
            continue
        if team_key.lower() == full_name:
            return team_key

    # Extract team nickname from full name (last word or two)
    # e.g. "Boston Celtics" → "celtics", "LA Clippers" → "clippers"
    full_words = full_name.split()
    nickname = full_words[-1]  # last word is usually the team name

    # For teams with 2-word nicknames
    two_word_nicknames = {
        "trail blazers": "Portland Trail Blazers",
        "76ers": "Philadelphia 76ers",
    }

    for team_key in odds_prices:
        if odds_prices[team_key].get("sport") != sport:
            continue
        key_lower = team_key.lower()
        # Exact nickname match at word boundary
        key_words = key_lower.split()
        if nickname in key_words:
            return team_key

    # Special cases
    special_map = {
        "BKN": "Brooklyn Nets",
        "GSW": "Golden State Warriors",
        "LAC": "LA Clippers",
        "LAL": "Los Angeles Lakers",
        "NOP": "New Orleans Pelicans",
        "OKC": "Oklahoma City Thunder",
        "SAS": "San Antonio Spurs",
    }
    if abbrev in special_map:
        target = special_map[abbrev].lower()
        for team_key in odds_prices:
            if team_key.lower() == target:
                return team_key

    return None
