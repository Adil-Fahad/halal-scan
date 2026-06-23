"""
HALAL SCAN AI PRO ULTIMATE
halal_filter.py — Dynamic halal filtering. Loads blacklist.json at runtime.
"""

import json
import logging
from pathlib import Path
from typing import List

from config import BLACKLIST_PATH

logger = logging.getLogger(__name__)


class HalalFilter:
    """
    Loads halal_blacklist.json and screens Binance symbols.
    Filtering logic:
      1. Symbol base (e.g. 'SHIB' from 'SHIB/USDT') must not be in blacklist symbols set.
      2. Base must not contain any blacklisted substrings.
    Call .is_halal(symbol) or .filter(symbols) from anywhere.
    """

    def __init__(self, path: Path = BLACKLIST_PATH):
        self._path = path
        self._blacklist_symbols: set[str] = set()
        self._blacklist_substrings: list[str] = []
        self._load()

    def _load(self) -> None:
        try:
            with open(self._path, "r", encoding="utf-8") as f:
                data = json.load(f)

            # Direct symbol hits (uppercased)
            self._blacklist_symbols = {s.upper() for s in data.get("symbols", [])}

            # Substring matches (uppercased)
            self._blacklist_substrings = [s.upper() for s in data.get("substrings", [])]

            logger.info(
                f"HalalFilter loaded: {len(self._blacklist_symbols)} symbols, "
                f"{len(self._blacklist_substrings)} substrings"
            )
        except FileNotFoundError:
            logger.warning(f"Blacklist not found at {self._path} — no filtering applied.")
        except json.JSONDecodeError as e:
            logger.error(f"Blacklist JSON parse error: {e}")

    def reload(self) -> None:
        """Hot-reload the blacklist from disk."""
        self._load()

    @staticmethod
    def _base(symbol: str) -> str:
        """Extract base currency from 'BTC/USDT' → 'BTC'."""
        return symbol.split("/")[0].upper()

    def is_halal(self, symbol: str) -> bool:
        """Return True if the symbol passes all halal checks."""
        base = self._base(symbol)

        # 1. Direct blacklist hit
        if base in self._blacklist_symbols:
            return False

        # 2. Substring match (e.g. 'ETHUP', 'BTCDOWN', 'STETH')
        for sub in self._blacklist_substrings:
            if sub in base:
                return False

        return True

    def filter(self, symbols: List[str]) -> List[str]:
        """
        Return only halal symbols from the input list.
        Logs how many were filtered out.
        """
        halal = [s for s in symbols if self.is_halal(s)]
        removed = len(symbols) - len(halal)
        logger.info(f"HalalFilter: {len(symbols)} → {len(halal)} symbols ({removed} removed)")
        return halal


# ── Singleton for import convenience ─────────────────────────────────────────
_filter_instance: HalalFilter | None = None


def get_halal_filter() -> HalalFilter:
    global _filter_instance
    if _filter_instance is None:
        _filter_instance = HalalFilter()
    return _filter_instance


def is_halal(symbol: str) -> bool:
    return get_halal_filter().is_halal(symbol)


def filter_halal(symbols: List[str]) -> List[str]:
    return get_halal_filter().filter(symbols)
