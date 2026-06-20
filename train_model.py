"""
HALAL SCAN AI PRO ULTIMATE
train_model.py — Full training pipeline.

Run this once to train and save the model:
    python train_model.py

Design:
  - Temporal train/test split (NEVER random — respects time-series integrity)
  - Native XGBoost probabilities with eval_metric='aucpr'
  - NO calibration wrappers (isotonic on small slices collapses scores)
  - GO/NO-GO gate: must pass probability range + class separation before saving
  - Saves: halal_ai_production.pkl, features_production.pkl
"""

import sys
import logging
import warnings

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBClassifier
from sklearn.metrics import (
    classification_report, precision_score, recall_score,
    f1_score, roc_auc_score, average_precision_score,
)

from config import (
    TRAIN_RATIO, XGB_PARAMS,
    MIN_PROB_RANGE, MIN_CLASS_SEP,
    MODEL_PATH, FEATURES_PATH,
    DATA_DIR,
)
from data_collector import collect_all
from feature_engineer import engineer_all, FEATURE_NAMES

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def temporal_split(df: pd.DataFrame, train_ratio: float):
    """
    Split by time index position — ensures test set is ALWAYS in the future.
    Never use random splits on time series data.
    """
    df = df.sort_values("timestamp").reset_index(drop=True)
    cut = int(len(df) * train_ratio)
    train = df.iloc[:cut].copy()
    test  = df.iloc[cut:].copy()
    logger.info(
        f"Temporal split: train={len(train):,} ({train_ratio*100:.0f}%) | "
        f"test={len(test):,} ({(1-train_ratio)*100:.0f}%)"
    )
    logger.info(
        f"  Train: {train['timestamp'].min()} → {train['timestamp'].max()}"
    )
    logger.info(
        f"  Test:  {test['timestamp'].min()}  → {test['timestamp'].max()}"
    )
    return train, test


def check_go_nogo(probs: np.ndarray, labels: np.ndarray) -> bool:
    """
    GO/NO-GO gate: model must show meaningful discrimination.
    Returns True (GO) or False (NO-GO) with detailed diagnostics.
    """
    prob_range = probs.max() - probs.min()
    sep = probs[labels == 1].mean() - probs[labels == 0].mean()

    logger.info("── GO/NO-GO Gate ──────────────────────────────────")
    logger.info(f"  Probability range:   {prob_range:.4f}  (need > {MIN_PROB_RANGE})")
    logger.info(f"  Class separation:    {sep:.4f}    (need > {MIN_CLASS_SEP})")
    logger.info(f"  Prob std:            {probs.std():.4f}")
    logger.info(f"  Prob min/max:        {probs.min():.3f} / {probs.max():.3f}")
    logger.info(f"  Mean prob (y=0):     {probs[labels == 0].mean():.4f}")
    logger.info(f"  Mean prob (y=1):     {probs[labels == 1].mean():.4f}")

    gate_range = prob_range > MIN_PROB_RANGE
    gate_sep   = sep > MIN_CLASS_SEP

    if gate_range and gate_sep:
        logger.info("  ✅ GO — Model shows meaningful discrimination.")
        return True
    else:
        if not gate_range:
            logger.error(f"  ❌ NO-GO — Probability range too narrow ({prob_range:.4f})")
        if not gate_sep:
            logger.error(f"  ❌ NO-GO — Class separation insufficient ({sep:.4f})")
        return False


def evaluate(probs: np.ndarray, labels: np.ndarray, threshold: float = 0.5) -> dict:
    """Full evaluation metrics for profitability assessment."""
    preds = (probs >= threshold).astype(int)

    pos_mask = probs >= threshold
    n_trades = pos_mask.sum()

    metrics = {
        "auc_roc":       roc_auc_score(labels, probs)           if labels.sum() > 0 else 0.0,
        "auc_pr":        average_precision_score(labels, probs)  if labels.sum() > 0 else 0.0,
        "precision":     precision_score(labels, preds, zero_division=0),
        "recall":        recall_score(labels, preds, zero_division=0),
        "f1":            f1_score(labels, preds, zero_division=0),
        "n_trades":      int(n_trades),
        "base_rate":     float(labels.mean()),
        "threshold":     threshold,
    }
    return metrics


def print_feature_importance(model: XGBClassifier, features: list[str], top_n: int = 20):
    importances = model.feature_importances_
    pairs = sorted(zip(features, importances), key=lambda x: -x[1])
    logger.info(f"── Top {top_n} Feature Importances ────────────────────")
    for i, (feat, imp) in enumerate(pairs[:top_n], 1):
        bar = "█" * int(imp * 200)
        logger.info(f"  {i:2d}. {feat:<20s} {imp:.4f}  {bar}")


# ─── Main Training Pipeline ───────────────────────────────────────────────────

def main():
    logger.info("=" * 60)
    logger.info("  HALAL SCAN AI — Model Training")
    logger.info("=" * 60)

    # ── Step 1: Collect Data ─────────────────────────────────────────────────
    logger.info("\n[1/6] Collecting Binance OHLCV data…")
    data = collect_all(apply_halal=True, verbose=True)

    if len(data) < 10:
        logger.error(f"Only {len(data)} symbols collected — aborting.")
        sys.exit(1)

    # Optional: cache raw data
    DATA_DIR.mkdir(exist_ok=True)
    logger.info(f"  {len(data)} symbols collected.")

    # ── Step 2: Feature Engineering ──────────────────────────────────────────
    logger.info("\n[2/6] Engineering features…")
    master = engineer_all(data, add_target=True, verbose=True)

    if master.empty:
        logger.error("Feature engineering produced empty DataFrame — aborting.")
        sys.exit(1)

    # ── Step 3: Temporal Split ───────────────────────────────────────────────
    logger.info("\n[3/6] Temporal split…")
    train_df, test_df = temporal_split(master, TRAIN_RATIO)

    X_train = train_df[FEATURE_NAMES].values
    y_train = train_df["target"].values.astype(int)
    X_test  = test_df[FEATURE_NAMES].values
    y_test  = test_df["target"].values.astype(int)

    logger.info(f"  Train label rate: {y_train.mean():.3f}")
    logger.info(f"  Test  label rate: {y_test.mean():.3f}")

    # Handle class imbalance with scale_pos_weight
    pos = y_train.sum()
    neg = len(y_train) - pos
    scale = neg / max(pos, 1)
    logger.info(f"  scale_pos_weight: {scale:.2f}  (pos={pos}, neg={neg})")

    # ── Step 4: Train XGBoost ────────────────────────────────────────────────
    logger.info("\n[4/6] Training XGBoost…")
    params = {**XGB_PARAMS, "scale_pos_weight": scale}

    model = XGBClassifier(**params)
    model.fit(
        X_train, y_train,
        eval_set=[(X_test, y_test)],
        verbose=50,
    )

    # ── Step 5: GO/NO-GO Gate ────────────────────────────────────────────────
    logger.info("\n[5/6] GO/NO-GO Gate evaluation…")
    probs_test = model.predict_proba(X_test)[:, 1]
    go = check_go_nogo(probs_test, y_test)

    if not go:
        logger.error(
            "\n❌ Model failed GO/NO-GO gate. Do NOT proceed to live trading.\n"
            "   Potential causes:\n"
            "   • Insufficient training data\n"
            "   • Base rate too low for separation\n"
            "   • Feature engineering issue\n"
            "   Review and retrain."
        )
        sys.exit(1)

    # ── Step 6: Full Evaluation ──────────────────────────────────────────────
    logger.info("\n[6/6] Full evaluation…")
    print_feature_importance(model, FEATURE_NAMES)

    logger.info("\n── Classification Report (threshold=0.50) ──")
    preds_50 = (probs_test >= 0.50).astype(int)
    print(classification_report(y_test, preds_50, target_names=["No Move", "5%+ Move"]))

    for thresh in [0.60, 0.65, 0.70, 0.75, 0.80, 0.85]:
        m = evaluate(probs_test, y_test, threshold=thresh)
        logger.info(
            f"  thresh={thresh:.2f} | "
            f"prec={m['precision']:.3f} | "
            f"recall={m['recall']:.3f} | "
            f"n_trades={m['n_trades']:4d} | "
            f"AUC-PR={m['auc_pr']:.3f}"
        )

    # ── Save Artifacts ───────────────────────────────────────────────────────
    joblib.dump(model,        MODEL_PATH)
    joblib.dump(FEATURE_NAMES, FEATURES_PATH)
    logger.info(f"\n✅ Model saved  → {MODEL_PATH}")
    logger.info(f"✅ Features saved → {FEATURES_PATH}")
    logger.info("\nTraining complete. Run scanner.py or app.py to use the model.")


if __name__ == "__main__":
    main()
