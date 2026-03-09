"""
Narrative signal: count tracked word mentions in news from the last N days, apply multiplier, cap P at 0.95.
Used to adjust current-week prediction using recent news (default: last 3 days).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional

import pandas as pd

from scripts.tokenizer import tokenize


def _get_multiplier(mention_count: int, news_multipliers: dict) -> float:
    """Map mention count to multiplier. Keys '0','1','3','5' -> 5 means 5+."""
    if mention_count >= 5:
        return float(news_multipliers.get("5", 1.8))
    if mention_count >= 3:
        return float(news_multipliers.get("3", 1.4))
    if mention_count >= 1:
        return float(news_multipliers.get("1", 1.1))
    return float(news_multipliers.get("0", 0.9))


def apply_narrative_adjustment(
    baseline_df: pd.DataFrame,
    processed_news_path: str,
    tracked_words: List[str],
    news_multipliers: dict,
    stopwords: Optional[List[str]] = None,
    reference_time: Optional[datetime] = None,
    news_days: int = 3,
    cap: float = 0.95,
) -> pd.DataFrame:
    """
    For each word: count mentions in news from the last `news_days` days, get multiplier,
    P_adjusted = min(cap, P_baseline * multiplier). This adjusts the current-week prediction using recent news.
    baseline_df must have columns: word, model_probability. Returns same frame with model_probability updated.
    """
    stopwords = stopwords or []
    ref = reference_time or datetime.utcnow()
    if ref.tzinfo:
        ref = ref.replace(tzinfo=None)
    ref_date = ref.date() if hasattr(ref, "date") else ref
    cutoff_date = ref_date - timedelta(days=news_days)
    path = Path(processed_news_path)
    if not path.exists():
        return baseline_df.copy()
    with open(path, encoding="utf-8") as f:
        news = json.load(f)
    # Filter to last N days by date (news items with date >= cutoff_date)
    recent = []
    for item in news:
        try:
            d = item.get("date", "")
            if len(d) < 10:
                continue
            item_date = datetime.strptime(d[:10], "%Y-%m-%d").date()
            if item_date >= cutoff_date:
                recent.append(item.get("text", ""))
        except Exception:
            continue
    combined_text = " ".join(recent)
    tokens = tokenize(combined_text, stopwords)
    token_counts = {}
    for t in tokens:
        token_counts[t] = token_counts.get(t, 0) + 1
    tracked_lower = [w.lower() for w in tracked_words]
    multipliers = [_get_multiplier(token_counts.get(w, 0), news_multipliers) for w in tracked_lower]
    out = baseline_df.copy()
    if "model_probability" not in out.columns:
        return out
    for i, word in enumerate(tracked_lower):
        mask = out["word"] == word
        if mask.any() and i < len(multipliers):
            p = out.loc[mask, "model_probability"].iloc[0] * multipliers[i]
            out.loc[mask, "model_probability"] = min(cap, round(p, 4))
    return out
