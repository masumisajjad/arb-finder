"""
Notifier — formats and sends arb opportunities to Telegram.
Formats for WhatsApp (no markdown tables, no headers).
"""
import os
import requests
from datetime import datetime
from typing import List

from arb_engine import ArbOpportunity


def _parse_game_time(iso_str: str) -> str:
    """Convert ISO timestamp to human-readable."""
    if not iso_str:
        return "TBD"
    try:
        from datetime import timezone
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        # Convert to CT
        import pytz
        ct = pytz.timezone("America/Chicago")
        dt_ct = dt.astimezone(ct)
        return dt_ct.strftime("%-I:%M %p CT")
    except Exception:
        return iso_str[:16]


def format_opportunity(opp: ArbOpportunity, idx: int) -> str:
    """Format a single arb opportunity as a clean text block."""
    game_time = _parse_game_time(opp.game_time)
    team_display = opp.team
    opp_display = opp.opponent if opp.opponent else "?"

    lines = [
        f"{opp.star_rating} #{idx} {team_display} vs {opp_display} ({opp.sport})",
        f"⏰ {game_time}",
        f"📋 Ticker: {opp.ticker}",
        "",
        f"💰 Kalshi YES ask: {opp.kalshi_yes_ask:.0f}¢",
        f"📊 Fair value: {opp.fair_prob*100:.1f}¢ ({opp.num_books} books)",
        f"🎯 Edge: +{opp.edge_pct*100:.1f}% ({opp.direction})",
        f"🔥 Confidence: {opp.confidence}",
        "",
    ]

    if opp.is_pure_arb:
        lines.insert(0, "🚨 PURE ARB — guaranteed profit!")
        lines.append(f"📈 Arb profit: {opp.arb_profit_pct*100:.2f}%")
        lines.append("")

    bet = opp.suggested_bet()
    if bet > 0:
        lines.append(f"💵 Suggested bet: ${bet:.0f} (Kelly ¼)")

    lines.append(f"💡 {' | '.join(opp.reasoning)}")
    return "\n".join(lines)


def format_summary(opportunities: List[ArbOpportunity], scan_time: str) -> str:
    """Format full scan summary for Telegram."""
    if not opportunities:
        return f"🔍 Arb scan complete ({scan_time})\n\nNo opportunities found above threshold."

    pure_arbs = [o for o in opportunities if o.is_pure_arb]
    value_plays = [o for o in opportunities if not o.is_pure_arb]

    header_lines = [
        f"🎯 ARB SCAN — {scan_time}",
        f"Found {len(opportunities)} opportunities ({len(pure_arbs)} pure arb, {len(value_plays)} value)",
        "",
    ]

    if pure_arbs:
        header_lines.append("🚨 PURE ARBITRAGE (guaranteed profit):")
        header_lines.append("")
        for i, opp in enumerate(pure_arbs, 1):
            header_lines.append(format_opportunity(opp, i))
            header_lines.append("—" * 30)

    if value_plays:
        header_lines.append("💡 VALUE PLAYS (Kalshi underpriced vs sportsbooks):")
        header_lines.append("")
        start_idx = len(pure_arbs) + 1
        for i, opp in enumerate(value_plays[:5], start_idx):  # Top 5 value plays
            header_lines.append(format_opportunity(opp, i))
            header_lines.append("—" * 30)

    header_lines.append("")
    header_lines.append("⚠️ Always verify before trading. Edge disappears fast.")

    return "\n".join(header_lines)


class TelegramNotifier:
    def __init__(self):
        self.token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

    def send(self, text: str) -> bool:
        if not self.token or not self.chat_id:
            print("[telegram] No token/chat_id — skipping send")
            return False

        # Split if too long (Telegram max ~4096 chars)
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            try:
                r = requests.post(
                    f"https://api.telegram.org/bot{self.token}/sendMessage",
                    json={"chat_id": self.chat_id, "text": chunk, "parse_mode": ""},
                    timeout=10,
                )
                r.raise_for_status()
            except Exception as e:
                print(f"[telegram] send error: {e}")
                return False
        return True
