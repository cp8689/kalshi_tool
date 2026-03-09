#!/usr/bin/env python3
"""
Parse news files: fetch full article body from each item's URL and update the news JSON for analysis.
Run after fetch_transcripts so data/news/*.json have url; then run before or as part of the pipeline.
Reads config.json for parse_news settings (fetch_article_body, max_articles_to_parse).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

# Project root = parent of scripts/
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.fetch_transcripts import fetch_transcript_url

NEWS_DIR = PROJECT_ROOT / "data" / "news"
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config.json"


def _load_config(config_path: Path) -> dict:
    if not config_path.is_file():
        return {}
    try:
        with open(config_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def parse_news(
    news_dir: Path | None = None,
    config_path: Path | None = None,
    fetch_article_body: bool | None = None,
    max_articles: int | None = None,
    skip_existing: bool = True,
) -> tuple[int, int]:
    """
    For each news JSON in news_dir that has 'url' (and optionally not yet body_parsed),
    fetch the article page and replace 'text' with the extracted body for analysis.
    Returns (updated_count, error_count).
    """
    news_dir = news_dir or NEWS_DIR
    config_path = config_path or DEFAULT_CONFIG_PATH
    config = _load_config(config_path)
    parse_config = config.get("parse_news", config.get("news_parsing", {}))
    if isinstance(parse_config, bool):
        fetch_article_body = fetch_article_body if fetch_article_body is not None else parse_config
        max_articles = max_articles if max_articles is not None else 100
    else:
        fetch_article_body = fetch_article_body if fetch_article_body is not None else parse_config.get("fetch_article_body", False)
        max_articles = max_articles if max_articles is not None else int(parse_config.get("max_articles_to_parse", 50))

    if not fetch_article_body:
        return 0, 0

    if not news_dir.is_dir():
        return 0, 0

    updated = 0
    errors = 0
    candidates = []
    for f in news_dir.iterdir():
        if f.suffix.lower() != ".json" or f.name.startswith(".") or f.name.startswith("sample_") or f.name == "processed_news.json":
            continue
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        url = data.get("url") or data.get("link")
        if not url or not isinstance(url, str) or not url.startswith("http"):
            continue
        if skip_existing and data.get("body_parsed"):
            continue
        candidates.append((f, data))

    for f, data in candidates[:max_articles]:
        url = data.get("url") or data.get("link")
        try:
            body = fetch_transcript_url(url)
            if body and len(body.strip()) > 100:
                data["text"] = body.strip()
                data["body_parsed"] = True
                f.write_text(json.dumps(data, indent=2), encoding="utf-8")
                updated += 1
            else:
                errors += 1
        except Exception:
            errors += 1
        time.sleep(0.3)

    return updated, errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse news: fetch article bodies from URLs and update news JSON for analysis.")
    parser.add_argument("--news-dir", type=Path, default=NEWS_DIR, help="Directory containing news JSON files")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG_PATH, help="Path to config.json")
    parser.add_argument("--fetch-bodies", action="store_true", help="Enable fetching full article body from URL (or set parse_news.fetch_article_body in config)")
    parser.add_argument("--max", type=int, default=50, help="Max number of articles to fetch (default 50)")
    parser.add_argument("--no-skip-existing", action="store_true", help="Re-fetch even if body_parsed is already true")
    args = parser.parse_args()

    fetch = args.fetch_bodies or _load_config(args.config).get("parse_news", {}).get("fetch_article_body", False)
    if not fetch:
        print("Parse-news skipped (fetch_article_body off). Use --fetch-bodies or set config.parse_news.fetch_article_body.", file=sys.stderr)
        return 0

    updated, errors = parse_news(
        news_dir=args.news_dir,
        config_path=args.config,
        fetch_article_body=True,
        max_articles=args.max,
        skip_existing=not args.no_skip_existing,
    )
    print(f"  [parse_news] updated={updated} errors={errors}")
    return 1 if errors and not updated else 0


if __name__ == "__main__":
    sys.exit(main())
