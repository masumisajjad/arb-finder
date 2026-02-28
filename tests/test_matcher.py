"""Tests for the Kalshi ticker parser and team matcher."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from matcher import parse_kalshi_ticker, find_odds_team, normalize_team


class TestTickerParser:
    def test_nba_game_winner(self):
        result = parse_kalshi_ticker("KXNBAGAME-26MAR01SACLAL-SAC")
        assert result is not None
        assert result["sport"] == "NBA"
        assert result["market_type"] == "game_winner"
        assert result["team1"] == "SAC"
        assert result["date"].day == 1
        assert result["date"].month == 3

    def test_nba_game_winner_lal(self):
        result = parse_kalshi_ticker("KXNBAGAME-26MAR01SACLAL-LAL")
        assert result is not None
        assert result["team1"] == "LAL"

    def test_nba_game_winner_okc(self):
        result = parse_kalshi_ticker("KXNBAGAME-26FEB27DENOKC-OKC")
        assert result is not None
        assert result["team1"] == "OKC"

    def test_nba_spread(self):
        result = parse_kalshi_ticker("KXNBASPREAD-26FEB28PORCHA-CHA6")
        assert result is not None
        assert result["sport"] == "NBA"
        assert result["market_type"] == "spread"
        assert result["team1"] == "CHA"
        assert result["spread"] == 6.5

    def test_nba_championship_future(self):
        result = parse_kalshi_ticker("KXNBA-26-OKC")
        assert result is not None
        assert result["market_type"] == "championship_future"
        assert result["team1"] == "OKC"

    def test_unknown_ticker_returns_none(self):
        result = parse_kalshi_ticker("KXELONMARS-99")
        assert result is None

    def test_case_insensitive(self):
        result = parse_kalshi_ticker("kxnbagame-26mar01saclal-sac")
        assert result is not None
        assert result["team1"] == "SAC"


class TestTeamNormalization:
    def test_known_abbreviations(self):
        assert "Boston Celtics" in normalize_team("BOS")
        # DAL is dual-use (Cowboys NFL / Mavericks NBA) — normalize returns first match
        assert "Dallas" in normalize_team("DAL")
        assert "Oklahoma City Thunder" in normalize_team("OKC")

    def test_unknown_abbreviation_passthrough(self):
        result = normalize_team("XYZ")
        assert result == "XYZ"


class TestFindOddsTeam:
    def _sample_odds(self):
        return {
            "Charlotte Hornets": {"sport": "NBA", "fair_prob": 0.735, "opponent": "Portland Trail Blazers"},
            "Portland Trail Blazers": {"sport": "NBA", "fair_prob": 0.265, "opponent": "Charlotte Hornets"},
            "Golden State Warriors": {"sport": "NBA", "fair_prob": 0.397, "opponent": "Los Angeles Lakers"},
            "Los Angeles Lakers": {"sport": "NBA", "fair_prob": 0.603, "opponent": "Golden State Warriors"},
        }

    def test_finds_charlotte(self):
        odds = self._sample_odds()
        result = find_odds_team("CHA", odds, "NBA")
        assert result == "Charlotte Hornets"

    def test_finds_portland(self):
        odds = self._sample_odds()
        result = find_odds_team("POR", odds, "NBA")
        assert result == "Portland Trail Blazers"

    def test_finds_gsw(self):
        odds = self._sample_odds()
        result = find_odds_team("GSW", odds, "NBA")
        assert result == "Golden State Warriors"

    def test_finds_lal(self):
        odds = self._sample_odds()
        result = find_odds_team("LAL", odds, "NBA")
        assert result == "Los Angeles Lakers"

    def test_no_match_returns_none(self):
        odds = self._sample_odds()
        result = find_odds_team("BKN", odds, "NBA")
        assert result is None

    def test_sport_filter_works(self):
        odds = self._sample_odds()
        # Asking for NBA team in NFL context should return None
        result = find_odds_team("CHA", odds, "NFL")
        assert result is None


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
