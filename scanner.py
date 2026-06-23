"""
HALAL SCAN AI PRO ULTIMATE
scanner.py — Live scanner engine with Order Flow integration.
"""

import logging
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional

import joblib
import pandas as pd

from config import (
    MODEL_PATH, FEATURES_PATH, SIGNALS_PATH, HISTORY_PATH,
    SCAN_TOP_N, PROB_THRESHOLD, VERDICT_RULES,
)
from data_collector import collect_all, collect_one
from feature_engineer import engineer_features, FEATURE_NAMES
from order_flow import get_order_flow

logger = logging.getLogger(__name__)

_model    = None
_features = None


def load_model():
    global _model, _features
    if not MODEL_PATH.exists():
        raise FileNotFoundError(
            f"Model not found at {MODEL_PATH}. Run train_model.py first."
        )
    _model    = joblib.load(MODEL_PATH)
    _features = joblib.load(FEATURES_PATH)
    logger.info(f"Model loaded from {MODEL_PATH}")
    return _model, _features


def _get_model():
    if _model is None:
        load_model()
    return _model, _features


def get_verdict(prob: float) -> str:
    for verdict, threshold in VERDICT_RULES.items():
        if prob >= threshold:
            return verdict
    return "AVOID"


def get_signal_strength(prob: float) -> int:
    if prob >= 0.85: return 4
    if prob >= 0.70: return 3
    if prob >= 0.50: return 2
    return 1


def get_combined_verdict(prob: float, flow_score: float) -> str:
    """
    Combined verdict using both AI probability and order flow score.
    Order flow acts as confirmation filter.
    """
    verdict = get_verdict(prob)

    # Upgrade: BUY + strong flow = STRONG BUY
    if verdict == "BUY" and flow_score >= 65:
        return "STRONG BUY"

    # Downgrade: high prob but selling pressure = WATCH
    if verdict in ["STRONG BUY", "BUY"] and flow_score <= 35:
        return "WATCH"

    return verdict


def analyze_symbol(symbol: str, include_order_flow: bool = True) -> Optional[Dict]:
    """
    Full analysis pipeline for one symbol including order flow.
    """
    sym = symbol.upper().strip()
    if "/" not in sym:
        sym = f"{sym}/USDT"

    df = collect_one(sym)
    if df is None or df.empty:
        logger.warning(f"[{sym}] Could not fetch data.")
        return None

    feat_df = engineer_features(df, add_target=False)
    if feat_df.empty:
        logger.warning(f"[{sym}] Feature engineering failed.")
        return None

    latest = feat_df[FEATURE_NAMES].iloc[-1]

    model, features = _get_model()
    X    = latest.values.reshape(1, -1)
    prob = float(model.predict_proba(X)[0, 1])

    price = float(df["close"].iloc[-1])
    base  = sym.replace("/USDT", "")

    result = {
        "symbol":          base,
        "full_symbol":     sym,
        "probability":     round(prob * 100, 2),
        "prob_raw":        round(prob, 4),
        "verdict":         get_verdict(prob),
        "signal_strength": get_signal_strength(prob),
        "price":           price,
        "rsi":             round(float(latest["rsi"]), 2),
        "adx":             round(float(latest["adx"]), 2),
        "volume_ratio":    round(float(latest["volume_ratio"]), 3),
        "ema20":           round(float(latest["ema20"]), 6),
        "ema50":           round(float(latest["ema50"]), 6),
        "macd":            round(float(latest["macd"]), 8),
        "macd_signal":     round(float(latest["macd_signal"]), 8),
        "return_24h":      round(float(latest["return_24h"]) * 100, 2),
        "return_72h":      round(float(latest["return_72h"]) * 100, 2),
        "scanned_at":      datetime.now(timezone.utc).isoformat(),
        # Order flow defaults
        "flow_score":      None,
        "flow_signal":     None,
        "taker_buy_ratio": None,
        "ob_imbalance_pct": None,
        "whale_buys":      None,
        "whale_sells":     None,
        "whale_net":       None,
        "volume_delta_pct": None,
        "combined_verdict": get_verdict(prob),
    }

    # Fetch order flow
    if include_order_flow:
        try:
            of = get_order_flow(sym)
            if of:
                result.update({
                    "flow_score":       of["flow_score"],
                    "flow_signal":      of["flow_signal"],
                    "taker_buy_ratio":  of["taker_buy_ratio"],
                    "ob_imbalance_pct": of["ob_imbalance_pct"],
                    "whale_buys":       of["whale_buys"],
                    "whale_sells":      of["whale_sells"],
                    "whale_net":        of["whale_net"],
                    "volume_delta_pct": of["volume_delta_pct"],
                    "combined_verdict": get_combined_verdict(prob, of["flow_score"]),
                })
        except Exception as e:
            logger.warning(f"[{sym}] Order flow fetch failed: {e}")

    return result


def run_scan(
    min_prob: float = PROB_THRESHOLD,
    top_n: int = SCAN_TOP_N,
    save_csv: bool = True,
) -> List[Dict]:
    """
    Scan all halal USDT pairs with AI + order flow scoring.
    """
    logger.info(f"Starting full market scan (min_prob={min_prob:.0%}, top_n={top_n})…")
    model, features = _get_model()
    scan_start = time.time()

    data = collect_all(apply_halal=True, verbose=True)
    results = []

    for symbol, df in data.items():
        try:
            feat_df = engineer_features(df, add_target=False)
            if feat_df.empty:
                continue

            latest = feat_df[FEATURE_NAMES].iloc[-1]
            X      = latest.values.reshape(1, -1)
            prob   = float(model.predict_proba(X)[0, 1])

            if prob < min_prob:
                continue

            price = float(df["close"].iloc[-1])
            base  = symbol.replace("/USDT", "")

            entry = {
                "symbol":       base,
                "probability":  round(prob * 100, 2),
                "prob_raw":     round(prob, 4),
                "verdict":      get_verdict(prob),
                "price":        price,
                "rsi":          round(float(latest["rsi"]), 2),
                "adx":          round(float(latest["adx"]), 2),
                "volume_ratio": round(float(latest["volume_ratio"]), 3),
                "return_24h":   round(float(latest["return_24h"]) * 100, 2),
                "return_72h":   round(float(latest["return_72h"]) * 100, 2),
                "scanned_at":   datetime.now(timezone.utc).isoformat(),
                "flow_score":   None,
                "flow_signal":  None,
                "taker_buy_ratio": None,
                "whale_net":    None,
                "combined_verdict": get_verdict(prob),
            }

            # Fetch order flow for top signals only (saves time)
            try:
                of = get_order_flow(symbol)
                if of:
                    entry.update({
                        "flow_score":       of["flow_score"],
                        "flow_signal":      of["flow_signal"],
                        "taker_buy_ratio":  of["taker_buy_ratio"],
                        "whale_net":        of["whale_net"],
                        "combined_verdict": get_combined_verdict(prob, of["flow_score"]),
                    })
            except Exception:
                pass

            results.append(entry)

        except Exception as e:
            logger.debug(f"[{symbol}] Error during scan: {e}")
            continue

    results.sort(key=lambda r: r["prob_raw"], reverse=True)
    results = results[:top_n]

    elapsed = time.time() - scan_start
    logger.info(f"Scan complete: {len(results)} signals | {elapsed:.1f}s elapsed")

    if save_csv and results:
        _save_signals(results)
        _append_history(results)

    return results


def _save_signals(results: List[Dict]) -> None:
    df = pd.DataFrame(results)
    df.to_csv(SIGNALS_PATH, index=False)
    logger.info(f"Signals saved → {SIGNALS_PATH}")


def _append_history(results: List[Dict]) -> None:
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    df = pd.DataFrame(results)
    if HISTORY_PATH.exists():
        existing = pd.read_csv(HISTORY_PATH)
        combined = pd.concat([existing, df], ignore_index=True)
        combined = combined.tail(10_000)
        combined.to_csv(HISTORY_PATH, index=False)
    else:
        df.to_csv(HISTORY_PATH, index=False)


def load_last_signals() -> List[Dict]:
    if not SIGNALS_PATH.exists():
        return []
    try:
        df = pd.read_csv(SIGNALS_PATH)
        df.sort_values("probability", ascending=False, inplace=True)
        return df.to_dict(orient="records")
    except Exception as e:
        logger.error(f"Could not load signals: {e}")
        return []


def load_history(limit: int = 200) -> List[Dict]:
    if not HISTORY_PATH.exists():
        return []
    try:
        df = pd.read_csv(HISTORY_PATH)
        df.sort_values("scanned_at", ascending=False, inplace=True)
        return df.head(limit).to_dict(orient="records")
    except Exception as e:
        logger.error(f"Could not load history: {e}")
        return []
