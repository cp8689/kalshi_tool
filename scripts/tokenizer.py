"""
Tokenize text: lowercase, strip punctuation, split on whitespace, remove stopwords.
Pure function, no file I/O.
"""
from __future__ import annotations

import re
import string
from typing import List


def tokenize(text: str, stopwords: List[str]) -> List[str]:
    """
    Process text into cleaned token list.
    - Lowercase
    - Remove punctuation
    - Split on whitespace
    - Remove stopwords (case-insensitive)
    """
    if not text or not isinstance(text, str):
        return []
    stop_set = {s.lower() for s in stopwords}
    text = text.lower().strip()
    # Replace ASCII + common Unicode punctuation (e.g. em-dash) with space
    text = re.sub(r"[\s\u2014\u2013\-]+", " ", text)
    text = re.sub(f"[{re.escape(string.punctuation)}]+", " ", text)
    tokens = text.split()
    return [t for t in tokens if t and t not in stop_set]
