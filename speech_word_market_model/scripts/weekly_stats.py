"""
Group transcripts into 4 rolling weeks. For each week compute P(word | week) = speeches_containing_word / total_speeches.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Optional, Union

import pandas as pd


def _week_bounds_dates(reference_date: datetime, week_index: int) -> tuple:
    """week_index 0 = most recent week (week1), 3 = oldest (week4). Returns (start_date, end_date) for date-only comparison."""
    ref_d = reference_date.date() if hasattr(reference_date, "date") else reference_date
    end_d = ref_d - timedelta(days=week_index * 7)
    start_d = end_d - timedelta(days=7)
    return start_d, end_d


def compute_weekly_probabilities(
    transcripts_path: str,
    tracked_words: List[str],
    reference_date: Optional[Union[datetime, str]] = None,
) -> pd.DataFrame:
    """
    Bucket transcripts into last 4 weeks (week1 = most recent). For each word and week,
    P(word | week) = speeches_containing_word / total_speeches. Returns DataFrame with
    columns: word, week1, week2, week3, week4.
    """
    ref = reference_date
    if ref is None:
        ref = datetime.utcnow()
    elif isinstance(ref, str):
        ref = datetime.fromisoformat(ref.replace("Z", "+00:00"))
    if ref.tzinfo:
        ref = ref.replace(tzinfo=None)

    path = Path(transcripts_path)
    if not path.exists():
        return pd.DataFrame(columns=["word", "week1", "week2", "week3", "week4"])
    with open(path, encoding="utf-8") as f:
        records = json.load(f)
    if not records:
        return pd.DataFrame(columns=["word", "week1", "week2", "week3", "week4"])

    tracked_lower = [w.lower() for w in tracked_words]
    week_ranges = [_week_bounds_dates(ref, i) for i in range(4)]

    # Assign each record to a week (by date only, so midnight transcript dates bucket correctly)
    def record_week(rec):
        try:
            dt = datetime.fromisoformat(rec["date"].replace("Z", "+00:00"))
            d = dt.date() if hasattr(dt, "date") else dt
        except Exception:
            return -1
        for i, (start_d, end_d) in enumerate(week_ranges):
            if start_d <= d < end_d:
                return i
        return -1

    # Per week: total speeches and speeches containing each word
    total_per_week = [0] * 4
    word_count_per_week = [{w: 0 for w in tracked_lower} for _ in range(4)]
    for rec in records:
        w = record_week(rec)
        if w < 0:
            continue
        total_per_week[w] += 1
        tokens_set = set(t.lower() for t in rec.get("tokens", []))
        for word in tracked_lower:
            if word in tokens_set:
                word_count_per_week[w][word] += 1

    rows = []
    for word in tracked_lower:
        week_probs = []
        for i in range(4):
            total = total_per_week[i]
            count = word_count_per_week[i][word]
            p = count / total if total else 0.0
            week_probs.append(round(p, 4))
        rows.append({"word": word, "week1": week_probs[0], "week2": week_probs[1], "week3": week_probs[2], "week4": week_probs[3]})
    return pd.DataFrame(rows)
