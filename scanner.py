"""
HALAL SCAN AI PRO ULTIMATE
scanner.py — Live scanner engine.

Fetches current candles for all halal USDT pairs, runs the trained model,
ranks coins by probability, and saves live_signals.csv.

Can be run standalone:
    python scanner.py

Or imported by app.py for API use.
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

logger = logging.getLogger(__name__)


# ─── Model Loading ────────────────────────────────────────────────────────────

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


# ─── Verdict Mapping ─────────────────────────────────────────────────────────

def get_verdict(prob: float) -> str:
    """Map probability to human verdict using VERDICT_RULES from config."""
    for verdict, threshold in VERDICT_RULES.items():
        if prob >= threshold:
            return verdict
    return "AVOID"


def get_signal_strength(prob: float) -> int:
    """Return signal strength 1–4 bars for UI display."""
    if prob >= 0.85:   return 4
    if prob >= 0.70:   return 3
    if prob >= 0.50:   return 2
    return 1


# ─── Single Symbol Analysis ──────────────────────────────────────────────────

def analyze_symbol(symbol: str) -> Optional[Dict]:
    """
    Full analysis pipeline for one symbol.
    Used by My Coin Analyzer feature.

    Returns dict with probability, indicators, verdict, or None on failure.
    """
    # Normalise symbol
    sym = symbol.upper().strip()
    if "/" not in sym:
        sym = f"{sym}/USDT"

    # Fetch OHLCV
    df = collect_one(sym)
    if df is None or df.empty:
        logger.warning(f"[{sym}] Could not fetch data.")
        return None

    # Feature engineering (no target needed)
    feat_df = engineer_features(df, add_target=False)
    if feat_df.empty:
        logger.warning(f"[{sym}] Feature engineering failed.")
        return None

    latest = feat_df[FEATURE_NAMES].iloc[-1]

    # Predict
    model, features = _get_model()
    X = latest.values.reshape(1, -1)
    prob = float(model.predict_proba(X)[0, 1])

    # Latest OHLCV info
    price = float(df["close"].iloc[-1])

    return {
        "symbol":          sym.replace("/USDT", ""),
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
    }


# ─── Full Market Scan ────────────────────────────────────────────────────────

def run_scan(
    min_prob: float = PROB_THRESHOLD,
    top_n: int = SCAN_TOP_N,
    save_csv: bool = True,
) -> List[Dict]:
    """
    Scan all halal USDT pairs. Returns ranked list of signals above min_prob.

    Args:
        min_prob: Minimum probability threshold (0-1).
        top_n:    Maximum number of results to return.
        save_csv: Save results to live_signals.csv.

    Returns:
        List of result dicts, sorted by probability descending.
    """
    logger.info(f"Starting full market scan (min_prob={min_prob:.0%}, top_n={top_n})…")
    model, features = _get_model()
    scan_start = time.time()

    # Collect all data
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

            results.append({
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
            })

        except Exception as e:
            logger.debug(f"[{symbol}] Error during scan: {e}")
            continue

    # Sort by probability
    results.sort(key=lambda r: r["prob_raw"], reverse=True)
    results = results[:top_n]

    elapsed = time.time() - scan_start
    logger.info(
        f"Scan complete: {len(results)} signals above {min_prob:.0%} | "
        f"{elapsed:.1f}s elapsed"
    )

    if save_csv and results:
        _save_signals(results)
        _append_history(results)

    return results


def _save_signals(results: List[Dict]) -> None:
    """Save latest scan results to live_signals.csv."""
    df = pd.DataFrame(results)
    df.to_csv(SIGNALS_PATH, index=False)
    logger.info(f"Signals saved → {SIGNALS_PATH}")


def _append_history(results: List[Dict]) -> None:
    """Append results to signal_history.csv for historical display."""
    HISTORY_PATH.parent.mkdir(exist_ok=True)
    df = pd.DataFrame(results)

    if HISTORY_PATH.exists():
        existing = pd.read_csv(HISTORY_PATH)
        combined = pd.concat([existing, df], ignore_index=True)
        # Keep last 10,000 rows
        combined = combined.tail(10_000)
        combined.to_csv(HISTORY_PATH, index=False)
    else:
        df.to_csv(HISTORY_PATH, index=False)


def load_last_signals() -> List[Dict]:
    """Load most recent scan results from CSV for dashboard display."""
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
    """Load signal history for the history dashboard tab."""
    if not HISTORY_PATH.exists():
        return []
    try:
        df = pd.read_csv(HISTORY_PATH)
        df.sort_values("scanned_at", ascending=False, inplace=True)
        return df.head(limit).to_dict(orient="records")
    except Exception as e:
        logger.error(f"Could not load history: {e}")
        return []


# ─── Standalone Run ───────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S",
    )
    results = run_scan(min_prob=0.60, top_n=20, save_csv=True)
    print(f"\n{'─'*70}")
    print(f"{'Symbol':<12} {'Prob%':>7} {'Verdict':<12} {'RSI':>6} {'ADX':>6} {'VolRat':>8} {'Price':>12}")
    print(f"{'─'*70}")
    for r in results:
        print(
            f"{r['symbol']:<12} {r['probability']:>6.1f}% "
            f"{r['verdict']:<12} {r['rsi']:>6.1f} {r['adx']:>6.1f} "
            f"{r['volume_ratio']:>8.2f} {r['price']:>12.6f}"
        )
    print(f"{'─'*70}")
