"""
HALAL SCAN AI PRO ULTIMATE
data_collector.py — Fetches Binance spot OHLCV data via CCXT.

Key design decisions (learned from notebook v1–v3):
  - Only spot USDT pairs (no futures, no perpetuals)
  - Halal filter applied before any fetching
  - Per-symbol retry with exponential backoff
  - Returns dict[symbol → DataFrame] for downstream processing
"""

import time
import logging
from typing import Dict, List, Optional

import ccxt
import pandas as pd

from config import (
    EXCHANGE_ID, TIMEFRAME, CANDLES, QUOTE_CURRENCY,
    FETCH_DELAY_S, MAX_RETRIES
)
from halal_filter import filter_halal

logger = logging.getLogger(__name__)

OHLCV_COLS = ["timestamp", "open", "high", "low", "close", "volume"]


def _build_exchange() -> ccxt.Exchange:
    exchange = getattr(ccxt, EXCHANGE_ID)({"enableRateLimit": True})
    exchange.load_markets()
    return exchange


def _get_spot_usdt_symbols(exchange: ccxt.Exchange) -> List[str]:
    """
    Return all active Binance spot USDT pairs.
    Excludes: futures, inactive markets, non-USDT quotes.
    """
    symbols = []
    for symbol, market in exchange.markets.items():
        if (
            market.get("spot", False)
            and market.get("active", False)
            and market.get("quote") == QUOTE_CURRENCY
            and "/" in symbol
            and ":" not in symbol          # ':' indicates perpetual/futures
        ):
            symbols.append(symbol)
    logger.info(f"Raw spot USDT pairs found: {len(symbols)}")
    return symbols


def _fetch_ohlcv_with_retry(
    exchange: ccxt.Exchange,
    symbol: str,
    timeframe: str,
    limit: int,
    retries: int = MAX_RETRIES,
) -> Optional[pd.DataFrame]:
    """
    Fetch OHLCV for one symbol. Returns DataFrame or None on failure.
    Uses exponential backoff on errors.
    """
    for attempt in range(1, retries + 1):
        try:
            raw = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
            if not raw or len(raw) < 100:          # skip sparse data
                return None

            df = pd.DataFrame(raw, columns=OHLCV_COLS)
            df["timestamp"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)
            df.set_index("timestamp", inplace=True)
            df = df.astype(float)
            df.sort_index(inplace=True)
            df.dropna(inplace=True)
            return df

        except (ccxt.NetworkError, ccxt.RequestTimeout) as e:
            wait = 2 ** attempt
            logger.warning(f"[{symbol}] Network error (attempt {attempt}/{retries}): {e}. Retrying in {wait}s…")
            time.sleep(wait)
        except ccxt.BadSymbol:
            logger.debug(f"[{symbol}] Bad symbol — skipping.")
            return None
        except Exception as e:
            logger.error(f"[{symbol}] Unexpected error: {e}")
            return None

    logger.error(f"[{symbol}] All {retries} retries exhausted.")
    return None


def collect_all(
    symbols_override: Optional[List[str]] = None,
    limit: int = CANDLES,
    apply_halal: bool = True,
    verbose: bool = True,
) -> Dict[str, pd.DataFrame]:
    """
    Main entry point. Fetches OHLCV for all (halal-filtered) USDT spot pairs.

    Args:
        symbols_override: If provided, fetch only these symbols (must include '/USDT').
        limit:            Number of candles per symbol.
        apply_halal:      Whether to apply halal filter.
        verbose:          Print progress.

    Returns:
        dict mapping symbol → OHLCV DataFrame.
    """
    logger.info("Connecting to Binance…")
    exchange = _build_exchange()

    if symbols_override:
        symbols = symbols_override
        logger.info(f"Using {len(symbols)} override symbols.")
    else:
        symbols = _get_spot_usdt_symbols(exchange)

    if apply_halal:
        symbols = filter_halal(symbols)

    total = len(symbols)
    logger.info(f"Fetching {total} symbols × {limit} candles ({TIMEFRAME})…")

    data: Dict[str, pd.DataFrame] = {}
    failed = 0

    for i, symbol in enumerate(symbols, 1):
        df = _fetch_ohlcv_with_retry(exchange, symbol, TIMEFRAME, limit)
        if df is not None:
            data[symbol] = df
        else:
            failed += 1

        if verbose and i % 50 == 0:
            logger.info(f"  Progress: {i}/{total} ({failed} failed so far)")

        time.sleep(FETCH_DELAY_S)

    logger.info(
        f"Collection complete: {len(data)}/{total} symbols fetched, {failed} failed."
    )
    return data


def collect_one(symbol: str) -> Optional[pd.DataFrame]:
    """
    Fetch a single symbol. Used by the live scanner and coin analyzer.
    Auto-appends '/USDT' if missing.
    """
    if "/" not in symbol:
        symbol = f"{symbol.upper()}/USDT"
    symbol = symbol.upper()

    exchange = _build_exchange()
    return _fetch_ohlcv_with_retry(exchange, symbol, TIMEFRAME, CANDLES)
