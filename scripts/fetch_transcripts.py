#!/usr/bin/env python3
"""
Fetch transcripts for Kalshi-relevant events (State of the Union, major speeches).
Reads sources from data/transcript_sources.json; writes YYYY-MM-DD_source.txt into data/transcripts/.
Supports: YouTube (via yt-dlp) and transcript URLs (requests + BeautifulSoup).
Run: python scripts/fetch_transcripts.py [--config path/to/transcript_sources.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

# Project root = parent of scripts/
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SOURCES_PATH = PROJECT_ROOT / "data" / "transcript_sources.json"
TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "transcripts"
NEWS_DIR = PROJECT_ROOT / "data" / "news"
MARKETS_DIR = PROJECT_ROOT / "data" / "markets"

# Kalshi uses "next major speech" / State of the Union – these are the event types we fetch for
EVENT_TYPES = ("sotu", "state of the union", "major speech", "address")


def _load_sources(config_path: Path) -> list[dict]:
    if not config_path.is_file():
        return []
    with open(config_path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, list):
        return data
    return data.get("sources", data.get("transcript_sources", []))


def _load_config_raw(config_path: Path) -> dict:
    if not config_path.is_file():
        return {}
    with open(config_path, encoding="utf-8") as f:
        return json.load(f)


def _slug(s: str) -> str:
    return re.sub(r"[^\w\-]", "_", s.lower()).strip("_") or "speech"


def fetch_youtube_captions(url: str, date: str, source: str) -> str | None:
    """Use yt-dlp to download auto or manual captions. Returns transcript text or None."""
    try:
        # yt-dlp writes subs next to the output path; use a stub so we can find *.vtt
        out_stub = TRANSCRIPTS_DIR / f"{date}_{_slug(source)}"
        subprocess.run(
            [
                "yt-dlp",
                "--skip-download",
                "--write-auto-sub",
                "--write-sub",
                "--sub-langs", "en",
                "--sub-format", "vtt",
                "--output", str(out_stub) + ".%(ext)s",
                "--no-warnings",
                url,
            ],
            capture_output=True,
            text=True,
            timeout=120,
            cwd=str(PROJECT_ROOT),
        )
        # Find any .vtt written (e.g. ...en.vtt or ...vtt)
        for f in TRANSCRIPTS_DIR.glob(f"{date}_{_slug(source)}*.vtt"):
            text = _vtt_to_plain_text(f.read_text(encoding="utf-8", errors="replace"))
            try:
                f.unlink()  # remove vtt after extracting text; we write .txt below
            except Exception:
                pass
            return text
        return None
    except FileNotFoundError:
        return None
    except Exception:
        return None


def _vtt_to_plain_text(vtt: str) -> str:
    """Strip VTT timestamps and metadata to plain text."""
    lines = []
    for line in vtt.splitlines():
        line = line.strip()
        if not line or line.startswith("WEBVTT") or line.startswith("Kind:") or " --> " in line:
            continue
        if re.match(r"^\d+$", line):
            continue
        lines.append(line)
    return " ".join(lines).replace("  ", " ")


def _get_session():
    """Shared requests session with browser-like User-Agent for whitehouse.gov."""
    try:
        import requests
    except ImportError:
        return None
    s = requests.Session()
    s.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-US,en;q=0.9",
    })
    return s


def fetch_transcript_url(url: str) -> str | None:
    """Fetch a transcript page and extract main text (requests + BeautifulSoup)."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return None
    session = _get_session()
    if not session:
        return None
    try:
        r = session.get(url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        body = soup.find("article") or soup.find("main") or soup.find(attrs={"role": "main"}) or soup.body
        if not body:
            return None
        text = body.get_text(separator="\n", strip=True)
        return re.sub(r"\n{3,}", "\n\n", text).strip() if text else None
    except Exception:
        return None


def _parse_date_text(date_str: str) -> str | None:
    """Parse 'March 5, 2026' or '2026-03-05' -> YYYY-MM-DD."""
    date_str = (date_str or "").strip()
    if re.match(r"\d{4}-\d{2}-\d{2}", date_str):
        return date_str[:10]
    try:
        from datetime import datetime
        dt = datetime.strptime(date_str, "%B %d, %Y")  # March 5, 2026
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        pass
    try:
        from datetime import datetime
        dt = datetime.strptime(date_str, "%b %d, %Y")  # Mar 5, 2026
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return None


def fetch_whitehouse_briefings(
    listing_url: str,
    transcripts_dir: Path,
    max_items: int = 25,
    dry_run: bool = False,
) -> list[dict]:
    """
    Scrape White House Briefings & Statements listing; fetch each article and save as transcript.
    listing_url e.g. https://www.whitehouse.gov/briefings-statements/
    """
    try:
        import requests
        from bs4 import BeautifulSoup
        from urllib.parse import urljoin
    except ImportError:
        return []
    session = _get_session()
    if not session:
        return []
    results = []
    try:
        r = session.get(listing_url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        base = listing_url.rstrip("/").rsplit("/", 1)[0] + "/"
        # Collect (href, date_iso, title) from listing – link + date in same block
        entries = []
        date_pattern = re.compile(
            r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}"
        )
        iso_pattern = re.compile(r"\d{4}-\d{2}-\d{2}")
        for a in soup.find_all("a", href=True):
            href = a.get("href", "")
            if "/briefings-statements/" not in href or href.count("/") < 4:
                continue
            full_url = urljoin(listing_url, href)
            if "whitehouse.gov" not in full_url:
                continue
            title = (a.get_text(strip=True) or "").strip()
            if len(title) < 10:
                continue
            date_iso = None
            parent = a.parent
            for _ in range(6):
                if not parent:
                    break
                text = parent.get_text(separator=" ", strip=True)
                m = date_pattern.search(text) or iso_pattern.search(text)
                if m:
                    date_iso = _parse_date_text(m.group(0)) or (m.group(0)[:10] if m.group(0) else None)
                    break
                parent = getattr(parent, "parent", None)
            if not date_iso:
                continue
            entries.append((full_url, date_iso, title))
        seen = set()
        uniq = []
        for url, d, t in entries:
            key = (d, t[:60])
            if key in seen:
                continue
            seen.add(key)
            uniq.append((url, d, t))
        for url, date_iso, title in uniq[:max_items]:
            slug = _slug(title[:80])
            out_file = transcripts_dir / f"{date_iso}_{slug}.txt"
            if dry_run:
                results.append({"date": date_iso, "source": slug, "path": str(out_file), "method": "whitehouse", "success": None})
                continue
            text = fetch_transcript_url(url)
            if text and len(text) > 100:
                out_file.write_text(text, encoding="utf-8")
                results.append({"date": date_iso, "source": slug, "path": str(out_file), "method": "whitehouse", "success": True})
            else:
                results.append({"date": date_iso, "source": slug, "path": None, "method": "whitehouse", "success": False})
    except Exception as e:
        results.append({"date": None, "source": "whitehouse_briefings", "path": None, "method": "whitehouse", "success": False, "error": str(e)})
    return results


def _clear_transcript_data(transcripts_dir: Path) -> None:
    """Remove all existing .txt transcript files and processed_transcripts.json before a fresh fetch."""
    if not transcripts_dir.is_dir():
        return
    for f in transcripts_dir.iterdir():
        if f.name.startswith("."):
            continue
        if f.suffix.lower() == ".txt" or f.name == "processed_transcripts.json":
            try:
                f.unlink()
            except OSError:
                pass


def _clear_news_data(news_dir: Path) -> None:
    """Remove all existing news .json and processed_news.json; keep sample_*.json and example*.json."""
    if not news_dir.is_dir():
        return
    for f in news_dir.iterdir():
        if f.name.startswith("."):
            continue
        if f.name == "processed_news.json":
            try:
                f.unlink()
            except OSError:
                pass
            continue
        if f.suffix.lower() != ".json":
            continue
        if f.name.startswith("sample_") or f.name.lower().startswith("example"):
            continue
        try:
            f.unlink()
        except OSError:
            pass


def _clear_markets_data(markets_dir: Path) -> None:
    """Remove all existing market .json and .csv; keep kalshi_sample.json and *example*."""
    if not markets_dir.is_dir():
        return
    for f in markets_dir.iterdir():
        if f.name.startswith("."):
            continue
        if f.suffix.lower() not in (".json", ".csv"):
            continue
        if f.name == "kalshi_sample.json" or "example" in f.name.lower():
            continue
        try:
            f.unlink()
        except OSError:
            pass


def fetch_transcripts(
    config_path: Path | None = None,
    transcripts_dir: Path | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """
    Load transcript_sources.json; for each source with youtube_url or transcript_url,
    fetch transcript and save as YYYY-MM-DD_source.txt in data/transcripts/.
    Before fetching, deletes existing transcript, news, and market data (keeps sample/example files).
    Returns list of {date, source, path, method, success}.
    """
    config_path = config_path or DEFAULT_SOURCES_PATH
    transcripts_dir = transcripts_dir or TRANSCRIPTS_DIR
    transcripts_dir.mkdir(parents=True, exist_ok=True)
    if not dry_run:
        _clear_transcript_data(transcripts_dir)
        _clear_news_data(NEWS_DIR)
        _clear_markets_data(MARKETS_DIR)
    sources = _load_sources(config_path)
    config_raw = _load_config_raw(config_path)
    results = []
    for entry in sources:
        date = entry.get("date")
        source = entry.get("source", "speech")
        if not date or not re.match(r"\d{4}-\d{2}-\d{2}", date):
            results.append({"date": date, "source": source, "path": None, "method": "skip", "success": False})
            continue
        slug = _slug(source)
        out_file = transcripts_dir / f"{date}_{slug}.txt"
        text = None
        method = None
        if entry.get("youtube_url"):
            method = "youtube"
            if not dry_run:
                text = fetch_youtube_captions(entry["youtube_url"], date, source)
        if text is None and entry.get("transcript_url"):
            method = "url"
            if not dry_run:
                text = fetch_transcript_url(entry["transcript_url"])
        if dry_run:
            results.append({"date": date, "source": source, "path": str(out_file), "method": method or "none", "success": None})
            continue
        if text:
            out_file.write_text(text, encoding="utf-8")
            results.append({"date": date, "source": source, "path": str(out_file), "method": method, "success": True})
        else:
            results.append({"date": date, "source": source, "path": None, "method": method or "none", "success": False})
    # White House Briefings & Statements (scrape listing then fetch each article)
    wh = config_raw.get("whitehouse_briefings") or config_raw.get("whitehouse_briefings_url")
    if wh:
        url = wh if isinstance(wh, str) else wh.get("url")
        max_items = 25
        if isinstance(wh, dict):
            max_items = int(wh.get("max_items", max_items))
        if url:
            wh_results = fetch_whitehouse_briefings(url, transcripts_dir, max_items=max_items, dry_run=dry_run)
            results.extend(wh_results)
    return results


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch Kalshi-relevant transcripts (SOTU, major speeches) from YouTube or transcript URLs."
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_SOURCES_PATH,
        help="Path to transcript_sources.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Only list what would be fetched, do not write files.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=TRANSCRIPTS_DIR,
        help="Directory to write transcript .txt files (default: data/transcripts)",
    )
    args = parser.parse_args()
    results = fetch_transcripts(config_path=args.config, transcripts_dir=args.output_dir, dry_run=args.dry_run)
    for r in results:
        status = "ok" if r["success"] is True else ("skip" if r["success"] is None else "fail")
        print(f"  {r['date']} {r['source']} ({r['method']}) -> {status}" + (f"  {r['path']}" if r.get("path") else ""))
    if not results:
        print("No sources in config. Edit data/transcript_sources.json and add youtube_url or transcript_url entries.")
    failed = sum(1 for r in results if r["success"] is False)
    return 1 if failed and not args.dry_run else 0


if __name__ == "__main__":
    sys.exit(main())
