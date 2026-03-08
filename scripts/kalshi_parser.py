"""
Parse Kalshi market data (JSON or CSV). Extract word from contract name, normalize market probability.
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import List, Optional, Union

import pandas as pd


def _normalize_prob(val) -> float:
    if val is None:
        return 0.0
    try:
        p = float(val)
        return max(0.0, min(1.0, p))
    except (TypeError, ValueError):
        return 0.0


def _extract_word_from_title(title: str, tracked_words: List[str]) -> Optional[str]:
    """Match quoted word or tracked word in contract title. Prefer quoted phrase."""
    if not title:
        return None
    title_lower = title.lower()
    # Quoted word e.g. Will Trump say 'border'?
    quoted = re.findall(r"['\"]([a-z]+)['\"]", title_lower)
    for w in quoted:
        if w in [t.lower() for t in tracked_words]:
            return w
    for w in tracked_words:
        if w.lower() in title_lower:
            return w.lower()
    return None


def _prob_from_row(row: dict) -> float:
    for key in ("market_probability", "last_price", "yes_bid", "probability", "price"):
        if key in row and row[key] is not None:
            return _normalize_prob(row[key])
    return 0.0


def parse_kalshi_markets(
    markets_path_or_paths: Union[str, List[str]],
    tracked_words: List[str],
) -> pd.DataFrame:
    """
    Load Kalshi JSON or CSV; extract word from contract_name (or title); return DataFrame
    with columns: word, contract_name, market_probability.
    """
    if isinstance(markets_path_or_paths, str):
        paths = [Path(markets_path_or_paths)]
    else:
        paths = [Path(p) for p in markets_path_or_paths]
    rows = []
    for path in paths:
        if not path.exists():
            continue
        if path.suffix.lower() == ".json":
            try:
                raw = path.read_text(encoding="utf-8")
                data = json.loads(raw)
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict) and "markets" in data:
                    items = data["markets"]
                elif isinstance(data, dict):
                    items = [data]
                else:
                    items = []
                for item in items:
                    if isinstance(item, dict):
                        name = item.get("contract_name") or item.get("title") or item.get("name") or ""
                    else:
                        continue
                    word = _extract_word_from_title(name, tracked_words)
                    if word is None:
                        continue
                    prob = _prob_from_row(item)
                    rows.append({"word": word, "contract_name": name, "market_probability": prob})
            except Exception:
                continue
        elif path.suffix.lower() == ".csv":
            try:
                with open(path, newline="", encoding="utf-8") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        name = row.get("contract_name") or row.get("title") or row.get("name") or ""
                        word = _extract_word_from_title(name, tracked_words)
                        if word is None:
                            continue
                        prob = _normalize_prob(row.get("market_probability") or row.get("last_price") or row.get("yes_bid") or 0)
                        rows.append({"word": word, "contract_name": name, "market_probability": prob})
            except Exception:
                continue
    if not rows:
        return pd.DataFrame(columns=["word", "contract_name", "market_probability"])
    return pd.DataFrame(rows)
