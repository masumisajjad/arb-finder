"""Tests for the arbitrage engine edge calculations."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from arb_engine import ArbEngine, ArbOpportunity, KALSHI_FEE_PCT


class TestArbOpportunity:
    def _make_opp(self, yes_ask, fair_prob, best_prob=None, num_books=4):
        best_prob = best_prob or fair_prob
        # edge_pct = (fair_in_cents - yes_ask) / yes_ask
        edge_pct = (fair_prob * 100 - yes_ask) / yes_ask

        sbook_no = (1.0 - best_prob) * 100
        arb_total_fees = yes_ask * (1 + KALSHI_FEE_PCT) + sbook_no
        is_pure_arb = arb_total_fees < 97
        arb_profit = (100 - arb_total_fees) / arb_total_fees if is_pure_arb else 0.0

        return ArbOpportunity(
            ticker="KXNBAGAME-26FEB28TEST-TST",
            sport="NBA",
            team="TST",
            opponent="OPP",
            game_time="2026-02-28T20:00:00Z",
            kalshi_yes_price=yes_ask - 2,
            kalshi_no_price=100 - yes_ask,
            kalshi_yes_ask=yes_ask,
            kalshi_no_ask=100 - yes_ask,
            fair_prob=fair_prob,
            best_book_prob=best_prob,
            num_books=num_books,
            edge_pct=edge_pct,
            is_pure_arb=is_pure_arb,
            arb_profit_pct=arb_profit,
            direction="YES",
            confidence="HIGH" if edge_pct > 0.12 else "MEDIUM",
        )

    def test_high_edge_gets_5_stars(self):
        opp = self._make_opp(yes_ask=30, fair_prob=0.70)
        assert opp.star_rating == "⭐⭐⭐⭐⭐"

    def test_medium_edge_gets_3_stars(self):
        opp = self._make_opp(yes_ask=45, fair_prob=0.50)  # ~11% edge
        stars = opp.star_rating
        assert "⭐⭐⭐" in stars

    def test_fair_priced_is_1_star(self):
        opp = self._make_opp(yes_ask=50, fair_prob=0.50)  # 0% edge
        assert "⭐" in opp.star_rating

    def test_kelly_is_nonzero_with_edge(self):
        opp = self._make_opp(yes_ask=30, fair_prob=0.70)  # big edge
        assert opp.kelly_fraction > 0

    def test_kelly_caps_at_0_15(self):
        opp = self._make_opp(yes_ask=10, fair_prob=0.90)  # huge edge
        assert opp.kelly_fraction <= 0.15

    def test_suggested_bet_rounds_to_5(self):
        opp = self._make_opp(yes_ask=30, fair_prob=0.70)
        bet = opp.suggested_bet(bankroll=190)
        assert bet % 5 == 0

    def test_suggested_bet_caps_at_50(self):
        opp = self._make_opp(yes_ask=10, fair_prob=0.90)
        assert opp.suggested_bet(bankroll=1000) <= 50

    def test_pure_arb_detected(self):
        # YES at 30¢, sportsbook says 75% probability → sbook_no = 25¢, total = ~55¢ < 97
        opp = self._make_opp(yes_ask=30, fair_prob=0.75, best_prob=0.75)
        assert opp.is_pure_arb is True
        assert opp.arb_profit_pct > 0

    def test_no_arb_at_fair_price(self):
        # YES at 50¢, sportsbook says 50% → sbook_no = 50¢, total = 100.5¢ ≥ 97
        opp = self._make_opp(yes_ask=50, fair_prob=0.50, best_prob=0.50)
        assert opp.is_pure_arb is False
        assert opp.arb_profit_pct == 0.0

    def test_no_arb_when_no_fee_marginal(self):
        # YES at 95¢, sportsbook says 97% → sbook_no = 3¢, total ≈ 98.95 ≥ 97
        opp = self._make_opp(yes_ask=95, fair_prob=0.97, best_prob=0.97)
        assert opp.is_pure_arb is False


class TestEdgeCalculations:
    """Test edge math directly."""

    def test_big_underpricing(self):
        # Kalshi 35¢, fair value 65¢ → edge = (65-35)/35 = 85.7%
        yes_ask = 35
        fair_prob = 0.65
        edge = (fair_prob * 100 - yes_ask) / yes_ask
        assert abs(edge - 0.857) < 0.01

    def test_overpriced(self):
        # Kalshi 70¢, fair value 60¢ → edge negative = (60-70)/70 = -14.3%
        yes_ask = 70
        fair_prob = 0.60
        edge = (fair_prob * 100 - yes_ask) / yes_ask
        assert edge < 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
