"""
Recency-weighted baseline: P_final = w1*week1 + w2*week2 + w3*week3 + w4*week4.
"""
from __future__ import annotations

import pandas as pd
from typing import List


def compute_baseline_probabilities(
    weekly_df: pd.DataFrame,
    recency_weights: List[float],
) -> pd.DataFrame:
    """
    Apply recency weights to weekly probabilities. Weights order: [week1, week2, week3, week4].
    Returns DataFrame with columns: word, model_probability (baseline).
    """
    if len(recency_weights) != 4:
        recency_weights = (recency_weights + [0.25] * 4)[:4]
    w1, w2, w3, w4 = recency_weights[:4]
    need = ["word", "week1", "week2", "week3", "week4"]
    if not all(c in weekly_df.columns for c in need):
        return pd.DataFrame(columns=["word", "model_probability"])
    out = weekly_df[["word"]].copy()
    out["model_probability"] = (
        w1 * weekly_df["week1"]
        + w2 * weekly_df["week2"]
        + w3 * weekly_df["week3"]
        + w4 * weekly_df["week4"]
    ).round(4)
    return out
