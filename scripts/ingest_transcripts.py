"""
Ingest transcript text files: parse date from filename, tokenize, store metadata.
Supports: (1) manual transcript files in data/transcripts/ (2) optional YouTube caption path.
Output: data/transcripts/processed_transcripts.json
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Optional

from scripts.tokenizer import tokenize

DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _get_stopwords(config_stopwords: list) -> list[str]:
    try:
        import nltk
        try:
            nltk.data.find("corpora/stopwords")
        except LookupError:
            nltk.download("stopwords", quiet=True)
        from nltk.corpus import stopwords as nltk_stop
        base = list(nltk_stop.words("english"))
    except Exception:
        base = []
    return list(set(base) | set(c.lower() for c in (config_stopwords or [])))


def _parse_date_from_filename(filename: str) -> Optional[str]:
    m = DATE_PATTERN.search(filename)
    return m.group(1) if m else None


def _ingest_file(filepath: str, tokenizer_fn: Callable[..., Any]) -> Optional[dict]:
    path = Path(filepath)
    if not path.is_file():
        return None
    date = _parse_date_from_filename(path.name)
    if not date:
        return None
    try:
        raw = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    tokens = tokenizer_fn(raw)
    source = path.stem.replace(date, "").lstrip("_-")
    return {
        "date": date,
        "source": source or path.name,
        "path": str(path),
        "tokens": tokens,
        "raw_text_preview": raw[:500] if raw else "",
    }


def ingest_transcripts(
    transcripts_dir: str,
    output_path: str,
    tokenizer_fn: Optional[Callable[..., Any]] = None,
    config: Optional[dict] = None,
) -> list:
    """
    Ingest all transcript files in transcripts_dir; save structured JSON to output_path.
    tokenizer_fn(text) -> list[str]. If None, uses tokenize(text, stopwords) with config stopwords.
    """
    config = config or {}
    stopwords = _get_stopwords(config.get("stopwords", []))
    if tokenizer_fn is None:
        def _fn(text):
            return tokenize(text, stopwords)
        tokenizer_fn = _fn

    records = []
    root = Path(transcripts_dir)
    if not root.is_dir():
        os.makedirs(root, exist_ok=True)
        return records
    for f in root.iterdir():
        if f.suffix.lower() not in (".txt", ".json"):
            continue
        if f.name.startswith(".") or f.name == "processed_transcripts.json":
            continue
        if f.suffix.lower() == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                date = data.get("date") or _parse_date_from_filename(f.name)
                text = data.get("text") or data.get("body") or ""
                if not date:
                    continue
                tokens = tokenizer_fn(text)
                records.append({
                    "date": date,
                    "source": data.get("source", f.stem),
                    "path": str(f),
                    "tokens": tokens,
                    "raw_text_preview": text[:500],
                })
            except Exception:
                continue
            continue
        rec = _ingest_file(str(f), tokenizer_fn)
        if rec:
            records.append(rec)
    records.sort(key=lambda r: r["date"], reverse=True)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(records, fp, indent=2)
    return records
