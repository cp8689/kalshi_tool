"""
Data contracts and extension points for the pipeline.
Use these types when adding real-time transcription, alternate market feeds, or new models.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, TypedDict


class TranscriptRecord(TypedDict, total=False):
    """Single processed transcript. Written to processed_transcripts.json."""
    date: str
    source: str
    path: str
    tokens: List[str]
    raw_text_preview: str
    speaker_id: Optional[str]  # For multi-speaker extension
    word_count: Optional[int]  # For speech length extension
    duration_seconds: Optional[float]


class NewsRecord(TypedDict, total=False):
    """Single news item. Written to processed_news.json."""
    date: str
    source: str
    text: str


class MarketRow(TypedDict, total=False):
    """Single Kalshi-style market row after parsing."""
    word: str
    contract_name: str
    market_probability: float


class EdgeRow(TypedDict, total=False):
    """Single edge output row."""
    word: str
    market_probability: float
    model_probability: float
    edge: float
    flagged: bool
