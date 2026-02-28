"""
Kalshi API client — lightweight wrapper for arb-finder.
Handles RSA-PSS auth and market/orderbook fetching.
"""
import os
import time
import base64
import hashlib
import requests
from datetime import datetime, timezone
from typing import Dict, List, Optional


try:
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    CRYPTO_OK = True
except ImportError:
    CRYPTO_OK = False


class KalshiClient:
    BASE_URL = "https://api.elections.kalshi.com"

    def __init__(self):
        self.api_key = os.getenv("KALSHI_API_KEY")
        pk_str = os.getenv("KALSHI_PRIVATE_KEY", "")
        self.private_key = None

        if CRYPTO_OK and pk_str:
            # Strip surrounding quotes if present
            pk_str = pk_str.strip().strip('"').strip("'")
            # Ensure proper PEM format
            if "-----BEGIN" not in pk_str:
                pk_str = f"-----BEGIN RSA PRIVATE KEY-----\n{pk_str}\n-----END RSA PRIVATE KEY-----"
            try:
                self.private_key = serialization.load_pem_private_key(pk_str.encode(), password=None)
            except Exception as e:
                print(f"[kalshi] Warning: failed to load private key: {e}")

    def _sign(self, method: str, path: str) -> Dict[str, str]:
        """Build RSA-PSS auth headers."""
        if not self.api_key or not self.private_key:
            return {}

        ts = str(int(datetime.now(timezone.utc).timestamp() * 1000))
        msg = ts + method.upper() + path
        sig = self.private_key.sign(
            msg.encode("utf-8"),
            padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=padding.PSS.DIGEST_LENGTH),
            hashes.SHA256(),
        )
        return {
            "KALSHI-ACCESS-KEY": self.api_key,
            "KALSHI-ACCESS-TIMESTAMP": ts,
            "KALSHI-ACCESS-SIGNATURE": base64.b64encode(sig).decode(),
            "Content-Type": "application/json",
        }

    def get(self, path: str, params: Dict = None, timeout: int = 10) -> Optional[Dict]:
        headers = self._sign("GET", path)
        if not headers:
            return None
        url = self.BASE_URL + path
        try:
            r = requests.get(url, headers=headers, params=params or {}, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            print(f"[kalshi] GET {path} error: {e}")
            return None

    def get_markets(
        self,
        series_ticker: str = None,
        status: str = "open",
        limit: int = 200,
        cursor: str = None,
    ) -> List[Dict]:
        """Fetch list of open markets, optionally filtered by series."""
        params = {"status": status, "limit": limit}
        if series_ticker:
            params["series_ticker"] = series_ticker
        if cursor:
            params["cursor"] = cursor

        data = self.get("/trade-api/v2/markets", params=params)
        if not data:
            return []
        return data.get("markets", [])

    def get_market(self, ticker: str) -> Optional[Dict]:
        """Fetch a single market by ticker."""
        data = self.get(f"/trade-api/v2/markets/{ticker}")
        return data.get("market") if data else None

    def get_orderbook(self, ticker: str, depth: int = 5) -> Optional[Dict]:
        """Fetch top-of-book for a market."""
        data = self.get(f"/trade-api/v2/markets/{ticker}/orderbook", {"depth": depth})
        return data.get("orderbook") if data else None

    def get_all_open_markets(self, series_ticker: str = None, max_pages: int = 10) -> List[Dict]:
        """Paginate through all open markets."""
        all_markets = []
        cursor = None
        for _ in range(max_pages):
            params = {"status": "open", "limit": 200}
            if series_ticker:
                params["series_ticker"] = series_ticker
            if cursor:
                params["cursor"] = cursor

            data = self.get("/trade-api/v2/markets", params=params)
            if not data:
                break

            markets = data.get("markets", [])
            all_markets.extend(markets)

            cursor = data.get("cursor")
            if not cursor or not markets:
                break

        return all_markets
