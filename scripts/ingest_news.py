"""
Ingest news from data/news/: JSON/HTML/TXT with date and body. Save processed_news.json.
Local files only in v1 (no live scraping).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from datetime import datetime
from typing import Optional

DATE_PATTERN = re.compile(r"(\d{4}-\d{2}-\d{2})")


def _parse_date(s: str) -> Optional[str]:
    if not s:
        return None
    m = DATE_PATTERN.search(s)
    if m:
        return m.group(1)
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d")
    except Exception:
        return None


def ingest_news(news_dir: str, output_path: str) -> list[dict]:
    """
    Read all news files from news_dir; write list of {date, source, text} to output_path.
    """
    records = []
    root = Path(news_dir)
    if not root.is_dir():
        os.makedirs(root, exist_ok=True)
        Path(output_path).parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump([], f, indent=2)
        return records
    for f in root.iterdir():
        if f.name.startswith("."):
            continue
        date = None
        text = ""
        source = f.stem
        if f.suffix.lower() == ".json":
            try:
                data = json.loads(f.read_text(encoding="utf-8"))
                date = data.get("date") or _parse_date(f.name)
                text = data.get("text") or data.get("body") or data.get("content") or ""
                source = data.get("source", source)
            except Exception:
                continue
        elif f.suffix.lower() in (".txt", ".html", ".htm"):
            try:
                raw = f.read_text(encoding="utf-8", errors="replace")
                date = _parse_date(f.name)
                if f.suffix.lower() in (".html", ".htm"):
                    try:
                        from bs4 import BeautifulSoup
                        text = BeautifulSoup(raw, "html.parser").get_text(separator=" ")
                    except Exception:
                        text = raw
                else:
                    text = raw
            except Exception:
                continue
        if date and text:
            records.append({"date": date, "source": source, "text": text})
    records.sort(key=lambda r: r["date"], reverse=True)
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fp:
        json.dump(records, fp, indent=2)
    return records
