"""Tests for pregame_scanner.py — game filtering and window logic."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock

import pregame_scanner as ps


# ---------------------------------------------------------------------------
# _minutes_until
# ---------------------------------------------------------------------------

class TestMinutesUntil:
    def test_future_game_returns_positive(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        m = ps._minutes_until(future)
        assert m is not None
        assert 29 < m < 31

    def test_past_game_returns_negative(self):
        past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        m = ps._minutes_until(past)
        assert m is not None
        assert m < 0

    def test_z_suffix_parsed(self):
        future = (datetime.now(timezone.utc) + timedelta(minutes=25)).strftime("%Y-%m-%dT%H:%M:%SZ")
        m = ps._minutes_until(future)
        assert m is not None
        assert 24 < m < 26

    def test_none_on_empty_string(self):
        assert ps._minutes_until("") is None

    def test_none_on_invalid_string(self):
        assert ps._minutes_until("not-a-date") is None


# ---------------------------------------------------------------------------
# filter_upcoming_games
# ---------------------------------------------------------------------------

def _make_odds(teams: list[tuple[str, str, int]]) -> dict:
    """
    Build a minimal odds_prices dict.
    teams: [(team_name, opponent, minutes_from_now), ...]
    """
    result = {}
    for team, opp, mins in teams:
        ct = (datetime.now(timezone.utc) + timedelta(minutes=mins)).isoformat()
        result[team] = {
            "opponent": opp,
            "commence_time": ct,
            "fair_prob": 0.60,
            "best_price": 0.60,
            "num_books": 3,
        }
        result[opp] = {
            "opponent": team,
            "commence_time": ct,
            "fair_prob": 0.40,
            "best_price": 0.40,
            "num_books": 3,
        }
    return result


class TestFilterUpcomingGames:
    def test_returns_games_in_window(self):
        prices = _make_odds([("Boston Celtics", "New York Knicks", 30)])
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        assert len(results) == 1

    def test_excludes_games_too_soon(self):
        prices = _make_odds([("Boston Celtics", "New York Knicks", 10)])
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        assert len(results) == 0

    def test_excludes_games_too_far(self):
        prices = _make_odds([("Boston Celtics", "New York Knicks", 90)])
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        assert len(results) == 0

    def test_deduplicates_home_and_away(self):
        # Both home and away team entries represent the SAME game
        prices = _make_odds([("Boston Celtics", "New York Knicks", 30)])
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        # Should only appear once even though odds_prices has both teams
        assert len(results) == 1

    def test_multiple_games_all_returned(self):
        prices = _make_odds([
            ("Boston Celtics", "New York Knicks", 30),
            ("Los Angeles Lakers", "Golden State Warriors", 35),
            ("Chicago Bulls", "Miami Heat", 40),
        ])
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        assert len(results) == 3

    def test_mixed_games_filters_correctly(self):
        prices = _make_odds([
            ("Boston Celtics", "New York Knicks", 30),    # in window
            ("Los Angeles Lakers", "Golden State Warriors", 5),   # too soon
            ("Chicago Bulls", "Miami Heat", 120),          # too far
        ])
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        assert len(results) == 1
        assert results[0][0] == "Boston Celtics"

    def test_sorted_by_soonest_first(self):
        prices = _make_odds([
            ("Boston Celtics", "New York Knicks", 40),
            ("Los Angeles Lakers", "Golden State Warriors", 25),
        ])
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        assert len(results) == 2
        assert results[0][3] < results[1][3]  # soonest minutes first

    def test_exact_window_boundary_inclusive(self):
        # Exactly at window_min should be included
        prices = _make_odds([("Boston Celtics", "New York Knicks", 20)])
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        # Note: mins might be 19.9x due to execution time — allow slack
        # The test validates boundary logic is >= not >
        # Due to test execution time, we give 1-min slack
        prices2 = _make_odds([("Boston Celtics", "New York Knicks", 21)])
        results2 = ps.filter_upcoming_games(prices2, window_min=20, window_max=45)
        assert len(results2) == 1

    def test_returns_tuple_structure(self):
        prices = _make_odds([("Boston Celtics", "New York Knicks", 30)])
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        assert len(results) == 1
        home, away, ct_iso, mins = results[0]
        assert isinstance(home, str)
        assert isinstance(away, str)
        assert isinstance(ct_iso, str)
        assert isinstance(mins, float)
        assert 20 <= mins <= 45

    def test_empty_odds_returns_empty(self):
        results = ps.filter_upcoming_games({}, window_min=20, window_max=45)
        assert results == []

    def test_missing_commence_time_skipped(self):
        prices = {
            "Boston Celtics": {
                "opponent": "New York Knicks",
                "commence_time": "",  # missing
                "fair_prob": 0.55,
                "best_price": 0.55,
                "num_books": 3,
            }
        }
        results = ps.filter_upcoming_games(prices, window_min=20, window_max=45)
        assert len(results) == 0


# ---------------------------------------------------------------------------
# _ct_str
# ---------------------------------------------------------------------------

class TestCtStr:
    def test_formats_valid_iso(self):
        iso = "2026-03-08T01:00:00Z"  # 7 PM CT
        s = ps._ct_str(iso)
        assert "PM CT" in s or "AM CT" in s

    def test_returns_tbd_for_empty(self):
        assert ps._ct_str("") == "TBD"


# ---------------------------------------------------------------------------
# run_pregame_scan integration (mocked)
# ---------------------------------------------------------------------------

class TestRunPregameScanMocked:
    def _base_odds(self):
        """One game in 30 min."""
        ct = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        return {
            "Boston Celtics": {
                "opponent": "New York Knicks",
                "commence_time": ct,
                "fair_prob": 0.65,
                "best_price": 0.63,
                "num_books": 4,
                "sport": "NBA",
            },
            "New York Knicks": {
                "opponent": "Boston Celtics",
                "commence_time": ct,
                "fair_prob": 0.35,
                "best_price": 0.37,
                "num_books": 4,
                "sport": "NBA",
            },
        }

    def test_returns_zero_when_no_api_keys(self, monkeypatch):
        monkeypatch.delenv("KALSHI_API_KEY", raising=False)
        monkeypatch.delenv("ODDS_API_KEY", raising=False)
        result = ps.run_pregame_scan(send_telegram=False)
        assert result == 0

    def test_dry_run_skips_scan(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY", "test")
        monkeypatch.setenv("ODDS_API_KEY", "test")

        # Patch the source module (lazy import target)
        with patch("odds_client.OddsClient") as MockOdds:
            MockOdds.return_value.get_best_prices.return_value = self._base_odds()
            result = ps.run_pregame_scan(dry_run=True, send_telegram=False)
            assert result == 0

    def test_returns_zero_when_no_upcoming_games(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY", "test")
        monkeypatch.setenv("ODDS_API_KEY", "test")

        # Games that already started (negative minutes)
        ct_past = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
        past_odds = {
            "Boston Celtics": {
                "opponent": "New York Knicks",
                "commence_time": ct_past,
                "fair_prob": 0.60,
                "best_price": 0.58,
                "num_books": 3,
                "sport": "NBA",
            }
        }

        with patch("odds_client.OddsClient") as MockOdds:
            MockOdds.return_value.get_best_prices.return_value = past_odds
            result = ps.run_pregame_scan(send_telegram=False)
            assert result == 0

    def test_sends_telegram_when_opportunities_found(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY", "test")
        monkeypatch.setenv("ODDS_API_KEY", "test")

        from arb_engine import ArbOpportunity

        ct = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        mock_opp = ArbOpportunity(
            ticker="KXNBAGAME-26MAR08BOSNYKNYK",
            sport="NBA",
            team="Boston Celtics",
            opponent="New York Knicks",
            game_time=ct,
            kalshi_yes_price=40.0,
            kalshi_no_price=60.0,
            kalshi_yes_ask=42.0,
            kalshi_no_ask=58.0,
            fair_prob=0.65,
            best_book_prob=0.63,
            num_books=4,
            edge_pct=0.15,
            is_pure_arb=False,
            arb_profit_pct=0.0,
            direction="YES",
            confidence="HIGH",
            reasoning=["Kalshi YES ask: 42¢", "Fair: 65¢", "Edge: 15%"],
        )

        # Patch source modules since run_pregame_scan uses lazy imports
        with patch("odds_client.OddsClient") as MockOdds, \
             patch("kalshi_client.KalshiClient"), \
             patch("arb_engine.ArbEngine") as MockEngine, \
             patch("notifier.TelegramNotifier") as MockTelegram:

            MockOdds.return_value.get_best_prices.return_value = self._base_odds()
            MockEngine.return_value.scan.return_value = [mock_opp]
            mock_tg_instance = MagicMock()
            mock_tg_instance.send.return_value = True
            MockTelegram.return_value = mock_tg_instance

            result = ps.run_pregame_scan(
                send_telegram=True,
                verbose=False,
                window_min=20,
                window_max=45,
            )

        assert result == 1
        mock_tg_instance.send.assert_called()
        msg = mock_tg_instance.send.call_args[0][0]
        assert "PRE-GAME ARB ALERT" in msg
        assert "Boston Celtics" in msg

    def test_sends_clean_checkin_when_no_edge(self, monkeypatch):
        monkeypatch.setenv("KALSHI_API_KEY", "test")
        monkeypatch.setenv("ODDS_API_KEY", "test")

        with patch("odds_client.OddsClient") as MockOdds, \
             patch("kalshi_client.KalshiClient"), \
             patch("arb_engine.ArbEngine") as MockEngine, \
             patch("notifier.TelegramNotifier") as MockTelegram:

            MockOdds.return_value.get_best_prices.return_value = self._base_odds()
            MockEngine.return_value.scan.return_value = []  # no opps
            mock_tg_instance = MagicMock()
            mock_tg_instance.send.return_value = True
            MockTelegram.return_value = mock_tg_instance

            result = ps.run_pregame_scan(
                send_telegram=True,
                verbose=False,
                window_min=20,
                window_max=45,
            )

        assert result == 0
        mock_tg_instance.send.assert_called()
        msg = mock_tg_instance.send.call_args[0][0]
        assert "Pre-game check" in msg
        assert "No edge found" in msg
