"""
HALAL SCAN AI PRO ULTIMATE
feature_engineer.py — Technical indicator calculation + normalisation.

Critical design rules (hard lessons from notebook v1–v3):
  1. ALL rolling/shift operations use shift(1) — never look at the current bar's future.
  2. Per-symbol rolling z-score normalisation (not cross-sectional ranking).
     Cross-sectional ranking destroys signal magnitude needed for threshold filtering.
  3. NaN rows are dropped AFTER feature calculation (never before).
  4. Returns raw feature DataFrame + normalised feature DataFrame for training.
"""

import logging
from typing import Optional

import numpy as np
import pandas as pd
import ta

from config import (
    RSI_PERIOD, EMA_SHORT, EMA_MID, EMA_LONG,
    MACD_FAST, MACD_SLOW, MACD_SIGNAL,
    ADX_PERIOD, ATR_PERIOD, VOL_RATIO_WIN,
    ROLL_Z_WIN, ROLL_Z_CLIP,
    TARGET_HORIZON, TARGET_RETURN,
)

logger = logging.getLogger(__name__)

# Feature names used for training (must stay stable across train/inference)
FEATURE_NAMES = [
    "rsi", "ema20", "ema50", "ema200",
    "macd", "macd_signal", "macd_hist",
    "adx", "atr_pct",
    "volume_ratio",
    "return_24h", "return_72h", "return_168h",
    "ema20_50_cross", "ema50_200_cross",
    "rsi_z", "adx_z", "volume_ratio_z",
    "macd_z", "return_24h_z", "return_72h_z",
]


# ─── Raw Indicator Calculation ────────────────────────────────────────────────

def _calc_raw_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Calculate all raw technical indicators on a single symbol's OHLCV DataFrame.
    No normalisation, no shifting. Returns df with extra columns.
    """
    close = df["close"]
    high  = df["high"]
    low   = df["low"]
    vol   = df["volume"]

    out = df.copy()

    # ── Momentum ────────────────────────────────────────────────────────────
    rsi_ind = ta.momentum.RSIIndicator(close=close, window=RSI_PERIOD)
    out["rsi"] = rsi_ind.rsi()

    # ── Trend — EMAs ────────────────────────────────────────────────────────
    out["ema20"]  = ta.trend.EMAIndicator(close=close, window=EMA_SHORT).ema_indicator()
    out["ema50"]  = ta.trend.EMAIndicator(close=close, window=EMA_MID).ema_indicator()
    out["ema200"] = ta.trend.EMAIndicator(close=close, window=EMA_LONG).ema_indicator()

    # ── MACD ────────────────────────────────────────────────────────────────
    macd_ind = ta.trend.MACD(
        close=close,
        window_fast=MACD_FAST,
        window_slow=MACD_SLOW,
        window_sign=MACD_SIGNAL,
    )
    out["macd"]        = macd_ind.macd()
    out["macd_signal"] = macd_ind.macd_signal()
    out["macd_hist"]   = macd_ind.macd_diff()

    # ── ADX ─────────────────────────────────────────────────────────────────
    adx_ind = ta.trend.ADXIndicator(high=high, low=low, close=close, window=ADX_PERIOD)
    out["adx"] = adx_ind.adx()

    # ── ATR (as % of close to normalise across price levels) ────────────────
    atr_ind = ta.volatility.AverageTrueRange(high=high, low=low, close=close, window=ATR_PERIOD)
    out["atr_pct"] = atr_ind.average_true_range() / close

    # ── Volume Ratio ────────────────────────────────────────────────────────
    vol_ma = vol.rolling(window=VOL_RATIO_WIN, min_periods=VOL_RATIO_WIN // 2).mean()
    out["volume_ratio"] = vol / vol_ma.replace(0, np.nan)

    # ── Price Returns ────────────────────────────────────────────────────────
    out["return_24h"]  = close.pct_change(24)
    out["return_72h"]  = close.pct_change(72)
    out["return_168h"] = close.pct_change(168)

    # ── EMA Cross Signals (boolean → int) ───────────────────────────────────
    out["ema20_50_cross"]  = (out["ema20"]  > out["ema50"] ).astype(int)
    out["ema50_200_cross"] = (out["ema50"]  > out["ema200"]).astype(int)

    return out


def _rolling_zscore(series: pd.Series, window: int, clip: float) -> pd.Series:
    """
    Per-symbol rolling z-score normalisation.
    Uses shift(1) so the normalisation doesn't peek at the current bar.
    Clips at ±clip sigma to prevent outlier dominance.
    """
    mean = series.shift(1).rolling(window=window, min_periods=window // 2).mean()
    std  = series.shift(1).rolling(window=window, min_periods=window // 2).std()
    z    = (series - mean) / std.replace(0, np.nan)
    return z.clip(-clip, clip)


def _add_normalised_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add rolling z-score versions of key continuous indicators.
    These give the model relative context (is RSI unusually high RIGHT NOW?).
    """
    out = df.copy()
    for col, alias in [
        ("rsi",          "rsi_z"),
        ("adx",          "adx_z"),
        ("volume_ratio", "volume_ratio_z"),
        ("macd",         "macd_z"),
        ("return_24h",   "return_24h_z"),
        ("return_72h",   "return_72h_z"),
    ]:
        out[alias] = _rolling_zscore(out[col], ROLL_Z_WIN, ROLL_Z_CLIP)
    return out


# ─── Target Construction ──────────────────────────────────────────────────────

def _build_target(df: pd.DataFrame) -> pd.DataFrame:
    """
    Target = 1 if close[t + TARGET_HORIZON] >= close[t] * (1 + TARGET_RETURN).
    Uses shift(-TARGET_HORIZON) — looks forward, so last TARGET_HORIZON rows
    will have NaN targets and must be dropped before training.
    """
    df = df.copy()
    future_close = df["close"].shift(-TARGET_HORIZON)
    threshold    = df["close"] * (1 + TARGET_RETURN)
    df["target"] = (future_close >= threshold).astype(float)
    # Rows where we cannot know the future get NaN
    df.loc[df.index[-TARGET_HORIZON:], "target"] = np.nan
    return df


# ─── Public API ───────────────────────────────────────────────────────────────

def engineer_features(
    df: pd.DataFrame,
    add_target: bool = True,
) -> pd.DataFrame:
    """
    Full pipeline for ONE symbol:
      raw OHLCV → indicators → z-scores → (optional) target → drop NaN rows

    Args:
        df:         OHLCV DataFrame (index = DatetimeIndex, cols = open/high/low/close/volume)
        add_target: Whether to add the 72h forward target column.

    Returns:
        DataFrame with all FEATURE_NAMES columns (+ 'target' if add_target=True).
        NaN rows are dropped.
    """
    if len(df) < max(EMA_LONG, ROLL_Z_WIN, TARGET_HORIZON) + 10:
        logger.debug("Too few rows for feature engineering.")
        return pd.DataFrame()

    df = _calc_raw_features(df)
    df = _add_normalised_features(df)

    if add_target:
        df = _build_target(df)
        df.dropna(subset=FEATURE_NAMES + ["target"], inplace=True)
    else:
        df.dropna(subset=FEATURE_NAMES, inplace=True)

    if len(df) < 50:
        return pd.DataFrame()

    return df


def engineer_all(
    data: dict,
    add_target: bool = True,
    verbose: bool = True,
) -> pd.DataFrame:
    """
    Run engineer_features across all symbols in the data dict.
    Adds a 'symbol' column and concatenates into one master DataFrame.

    Args:
        data:       dict[symbol → OHLCV DataFrame]
        add_target: Whether to include target column.
        verbose:    Log progress.

    Returns:
        Concatenated DataFrame across all symbols, sorted by (symbol, timestamp).
    """
    frames = []
    skipped = 0

    for symbol, df in data.items():
        feat_df = engineer_features(df, add_target=add_target)
        if feat_df.empty:
            skipped += 1
            continue
        feat_df["symbol"] = symbol
        frames.append(feat_df)

    if not frames:
        logger.error("No symbols produced valid features — check data.")
        return pd.DataFrame()

    master = pd.concat(frames, axis=0).sort_index()
    master.reset_index(inplace=True)           # moves timestamp to column
    master.rename(columns={"index": "timestamp", "timestamp": "timestamp"}, inplace=True)

    if verbose:
        label_rate = master["target"].mean() if "target" in master.columns else float("nan")
        logger.info(
            f"Feature matrix: {len(master):,} rows × {len(master.columns)} cols | "
            f"{len(frames)} symbols | {skipped} skipped | "
            f"target rate: {label_rate:.3f}"
        )

    return master


def get_latest_features(df: pd.DataFrame) -> Optional[pd.Series]:
    """
    For the LIVE scanner: engineer features on a single symbol's OHLCV,
    return only the LAST ROW as a Series.
    No target needed.
    """
    feat_df = engineer_features(df, add_target=False)
    if feat_df.empty:
        return None
    return feat_df[FEATURE_NAMES].iloc[-1]
