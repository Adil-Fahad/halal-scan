"""
HALAL SCAN AI PRO ULTIMATE
order_flow.py — Real-time order flow analysis from Binance API.

Fetches:
  - Taker buy/sell ratio (last 1h)
  - Order book imbalance (top 20 levels)
  - Large trade detection (whale activity)
  - Volume delta (net buying pressure)

All data fetched live — no model retraining needed.
Used for display confirmation alongside AI probability score.
"""

import logging
import time
from typing import Dict, Optional

import ccxt

logger = logging.getLogger(__name__)

# Whale threshold — trades above this USDT value count as whale
WHALE_THRESHOLD_USDT = 50_000
ORDER_BOOK_DEPTH     = 20
RECENT_TRADES_LIMIT  = 500


def _build_exchange() -> ccxt.binance:
    exchange = ccxt.binance({"enableRateLimit": True})
    return exchange


def get_order_flow(symbol: str) -> Optional[Dict]:
    """
    Fetch full order flow analysis for one symbol.

    Args:
        symbol: e.g. 'BTC/USDT' or 'BTCUSDT'

    Returns:
        dict with order flow metrics, or None on failure.
    """
    # Normalise symbol
    sym = symbol.upper().strip()
    if "/" not in sym:
        sym = f"{sym}/USDT"

    try:
        exchange = _build_exchange()

        # ── 1. Order Book ────────────────────────────────────────────────────
        ob = exchange.fetch_order_book(sym, limit=ORDER_BOOK_DEPTH)
        bids = ob.get("bids", [])   # [[price, size], ...]
        asks = ob.get("asks", [])

        bid_vol = sum(b[0] * b[1] for b in bids) if bids else 0
        ask_vol = sum(a[0] * a[1] for a in asks) if asks else 0
        total_ob = bid_vol + ask_vol

        ob_imbalance = 0.0
        if total_ob > 0:
            ob_imbalance = (bid_vol - ask_vol) / total_ob  # -1 to +1

        best_bid = bids[0][0] if bids else 0
        best_ask = asks[0][0] if asks else 0
        spread_pct = ((best_ask - best_bid) / best_bid * 100) if best_bid > 0 else 0

        # ── 2. Recent Trades (Taker Analysis) ───────────────────────────────
        trades = exchange.fetch_trades(sym, limit=RECENT_TRADES_LIMIT)

        buy_vol  = 0.0
        sell_vol = 0.0
        whale_buys  = 0
        whale_sells = 0
        large_trade_vol = 0.0

        for t in trades:
            price  = t.get("price", 0)
            amount = t.get("amount", 0)
            side   = t.get("side", "")
            usdt_val = price * amount

            if side == "buy":
                buy_vol += usdt_val
                if usdt_val >= WHALE_THRESHOLD_USDT:
                    whale_buys += 1
                    large_trade_vol += usdt_val
            else:
                sell_vol += usdt_val
                if usdt_val >= WHALE_THRESHOLD_USDT:
                    whale_sells += 1
                    large_trade_vol += usdt_val

        total_vol = buy_vol + sell_vol
        taker_buy_ratio = (buy_vol / total_vol * 100) if total_vol > 0 else 50.0
        volume_delta = buy_vol - sell_vol
        volume_delta_pct = (volume_delta / total_vol * 100) if total_vol > 0 else 0.0

        # ── 3. Composite Order Flow Score (0-100) ────────────────────────────
        # Weighted combination:
        # - Taker buy ratio    40%
        # - OB imbalance       35%
        # - Whale net buys     25%
        tbr_score = taker_buy_ratio  # already 0-100
        ob_score  = (ob_imbalance + 1) / 2 * 100  # convert -1/+1 → 0-100

        whale_net = whale_buys - whale_sells
        whale_score = min(max((whale_net + 5) / 10 * 100, 0), 100)  # normalise

        flow_score = (tbr_score * 0.40) + (ob_score * 0.35) + (whale_score * 0.25)

        # ── 4. Flow Signal ───────────────────────────────────────────────────
        if flow_score >= 65:
            flow_signal = "BUYING PRESSURE"
        elif flow_score <= 35:
            flow_signal = "SELLING PRESSURE"
        else:
            flow_signal = "NEUTRAL"

        return {
            "symbol":            sym.replace("/USDT", ""),
            # Order book
            "ob_imbalance":      round(ob_imbalance, 4),
            "ob_imbalance_pct":  round(ob_imbalance * 100, 1),
            "bid_volume_usdt":   round(bid_vol, 0),
            "ask_volume_usdt":   round(ask_vol, 0),
            "spread_pct":        round(spread_pct, 4),
            # Taker flow
            "taker_buy_ratio":   round(taker_buy_ratio, 1),
            "taker_sell_ratio":  round(100 - taker_buy_ratio, 1),
            "buy_volume_usdt":   round(buy_vol, 0),
            "sell_volume_usdt":  round(sell_vol, 0),
            "volume_delta_pct":  round(volume_delta_pct, 1),
            # Whale activity
            "whale_buys":        whale_buys,
            "whale_sells":       whale_sells,
            "whale_net":         whale_buys - whale_sells,
            "large_trade_vol":   round(large_trade_vol, 0),
            # Composite
            "flow_score":        round(flow_score, 1),
            "flow_signal":       flow_signal,
        }

    except ccxt.BadSymbol:
        logger.warning(f"[{sym}] Bad symbol for order flow.")
        return None
    except Exception as e:
        logger.error(f"[{sym}] Order flow error: {e}")
        return None
