#!/usr/bin/env python3
"""
Fetch transcripts and news for Kalshi-relevant events (State of the Union, major speeches).
Reads data/transcript_sources.json and data/news_sources.json; writes transcripts to data/transcripts/
and news JSON to data/news/ (past week from 5+ RSS/Atom feeds).
Supports: YouTube (yt-dlp), transcript URLs (requests + BeautifulSoup), White House briefings, RSS/Atom news.
Run: python scripts/fetch_transcripts.py [--config path/to/transcript_sources.json] [--dry-run]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

# Project root = parent of scripts/
SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DEFAULT_SOURCES_PATH = PROJECT_ROOT / "data" / "transcript_sources.json"
DEFAULT_WHITELIST_PATH = PROJECT_ROOT / "data" / "source_whitelist.json"
NEWS_SOURCES_PATH = PROJECT_ROOT / "data" / "news_sources.json"
TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "transcripts"
NEWS_DIR = PROJECT_ROOT / "data" / "news"
MARKETS_DIR = PROJECT_ROOT / "data" / "markets"

# Kalshi uses "next major speech" / State of the Union – these are the event types we fetch for
EVENT_TYPES = ("sotu", "state of the union", "major speech", "address")


def _load_resolution_grade_domains(whitelist_path: Path | None = None) -> set[str]:
    """Load Tier A (resolution-grade) domains from source_whitelist.json. Used to allow only Kalshi-safe sources."""
    path = whitelist_path or DEFAULT_WHITELIST_PATH
    if not path.is_file():
        return set()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except Exception:
        return set()
    tier = data.get("tier_a_resolution_grade") or {}
    domains = set()
    for key in ("official", "approved_media"):
        for d in tier.get(key) or []:
            domains.add((d or "").lower().strip())
    return domains


def _is_resolution_grade_url(url: str, allowed_domains: set[str]) -> bool:
    """True if url's host is in the Tier A whitelist (resolution-grade)."""
    if not url or not allowed_domains:
        return False
    try:
        parsed = urlparse(url)
        host = (parsed.netloc or "").lower().strip()
        if not host:
            return False
        # Strip port if present
        if ":" in host:
            host = host.split(":")[0]
        return any(host == d or host.endswith("." + d) for d in allowed_domains)
    except Exception:
        return False


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
    """Shared requests session with browser-like User-Agent. Bypasses proxy to avoid ProxyError/403."""
    try:
        import requests
    except ImportError:
        return None
    s = requests.Session()
    s.trust_env = False  # do not use HTTP_PROXY/HTTPS_PROXY (avoids tunnel 403 / ProxyError)
    s.proxies = {"http": None, "https": None}
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


def _parse_briefings_page(soup, page_url: str):
    """Extract (url, date_iso, title) entries from a single White House briefings listing page."""
    from urllib.parse import urljoin
    date_pattern = re.compile(
        r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}"
    )
    iso_pattern = re.compile(r"\d{4}-\d{2}-\d{2}")
    entries = []
    for a in soup.find_all("a", href=True):
        href = a.get("href", "")
        if "/briefings-statements/" not in href or href.count("/") < 4:
            continue
        full_url = urljoin(page_url, href)
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
    return entries


def fetch_whitehouse_briefings(
    listing_url: str,
    transcripts_dir: Path,
    max_items: int = 25,
    max_pages: int = 5,
    dry_run: bool = False,
    allowed_domains: set[str] | None = None,
) -> list[dict]:
    """
    Scrape White House Briefings & Statements listing; fetch each article and save as transcript.
    Pagination uses path-based URLs: .../briefings-statements/page/2/, page/3/, etc.
    listing_url e.g. https://www.whitehouse.gov/briefings-statements/
    """
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    session = _get_session()
    if not session:
        return []
    results = []
    base = listing_url.rstrip("/")
    # Only include entries from the last 4 weeks
    cutoff_date = (datetime.now(timezone.utc).date() - timedelta(days=28)).isoformat()
    all_entries = []
    for page_num in range(1, max_pages + 1):
        if page_num == 1:
            page_url = base + "/"
        else:
            page_url = f"{base}/page/{page_num}/"
        try:
            r = session.get(page_url, timeout=30)
            r.raise_for_status()
            soup = BeautifulSoup(r.text, "html.parser")
            entries = _parse_briefings_page(soup, page_url)
            # Keep only entries within the 4-week window
            within_window = [(url, d, t) for url, d, t in entries if d >= cutoff_date]
            all_entries.extend(within_window)
            # Stop fetching pages once we see only entries older than 4 weeks
            if entries and not within_window:
                break
        except Exception as e:
            if page_num == 1:
                results.append({"date": None, "source": "whitehouse_briefings", "path": None, "method": "whitehouse", "success": False, "error": str(e)})
                return results
            # Log and continue so one bad page doesn't kill the run
            print(f"  [whitehouse] page {page_num} failed: {e}", file=sys.stderr)
            continue
    # Dedupe by (date, title); keep only resolution-grade URLs if whitelist is set
    seen = set()
    uniq = []
    for url, d, t in all_entries:
        if allowed_domains and not _is_resolution_grade_url(url, allowed_domains):
            continue
        key = (d, t[:60])
        if key in seen:
            continue
        seen.add(key)
        uniq.append((url, d, t))
    try:
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


def _parse_rss_item(item_el, _ns: dict) -> tuple[str | None, str | None, str, str | None]:
    """Extract (date_iso, title, text, link) from an RSS <item>. Returns (None, None, '', None) if invalid."""
    def text(el):
        if el is None:
            return ""
        return (el.text or "").strip()
    date_iso = None
    for tag in ("pubDate", "date", "dc:date"):
        date_el = item_el.find(tag) or item_el.find("{http://purl.org/dc/elements/1.1/}date")
        if date_el is not None and (date_el.text or "").strip():
            dt = _parse_feed_date((date_el.text or "").strip())
            if dt:
                date_iso = dt.strftime("%Y-%m-%d")
                break
    link_el = item_el.find("link")
    link = None
    if link_el is not None and (link_el.text or "").strip():
        link = (link_el.text or "").strip()
    if not link and link_el is not None and link_el.get("href"):
        link = link_el.get("href", "").strip()
    title_el = item_el.find("title")
    title = text(title_el)
    desc_el = item_el.find("description")
    desc = text(desc_el)
    if not title and not desc:
        return (None, None, "", link)
    body = re.sub(r"<[^>]+>", " ", (desc or "")).strip() or ""
    text_str = (title + " " + body).strip()
    return (date_iso, title or "item", text_str, link)


def _parse_atom_entry(entry_el, ns_atom: str) -> tuple[str | None, str | None, str, str | None]:
    """Extract (date_iso, title, text, link) from an Atom <entry>. ns_atom e.g. http://www.w3.org/2005/Atom."""
    def find(el, local: str):
        if ns_atom:
            e = el.find(f"{{{ns_atom}}}{local}") if el is not None else None
            return e or (el.find(local) if el is not None else None)
        return el.find(local) if el is not None else None
    date_iso = None
    for local in ("updated", "published"):
        date_el = find(entry_el, local)
        if date_el is not None and (date_el.text or "").strip():
            dt = _parse_feed_date((date_el.text or "").strip())
            if dt:
                date_iso = dt.strftime("%Y-%m-%d")
                break
    link = None
    link_el = find(entry_el, "link")
    if link_el is not None and link_el.get("href"):
        link = (link_el.get("href") or "").strip()
    title_el = find(entry_el, "title")
    title = (title_el.text or "").strip() if title_el is not None else ""
    summary_el = find(entry_el, "summary")
    content_el = find(entry_el, "content")
    desc = (summary_el.text or "").strip() if summary_el is not None else ""
    if not desc and content_el is not None and content_el.text:
        desc = (content_el.text or "").strip()
    desc = re.sub(r"<[^>]+>", " ", desc).strip()
    text_str = (title + " " + desc).strip()
    return (date_iso, title or "entry", text_str, link)


def _parse_feed_date(s: str) -> datetime | None:
    """Parse RSS/Atom date string to datetime (timezone-naive for comparison)."""
    if not s or not s.strip():
        return None
    s = s.strip()
    # Remove trailing Z or +00:00 for simpler parsing
    for fmt in (
        "%a, %d %b %Y %H:%M:%S %z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            dt = datetime.strptime(s[:26], fmt) if len(s) > 26 else datetime.strptime(s, fmt)
            if hasattr(dt, "tzinfo") and dt.tzinfo:
                dt = dt.replace(tzinfo=None) + dt.utcoffset() if dt.utcoffset() else dt.replace(tzinfo=None)
            return dt
        except ValueError:
            continue
    try:
        from dateutil import parser as dateutil_parser
        dt = dateutil_parser.parse(s)
        if dt.tzinfo:
            dt = dt.replace(tzinfo=None) + (dt.utcoffset() or timedelta(0))
        return dt
    except Exception:
        return None


def _parse_feed_xml(xml_text: str) -> list[tuple[str | None, str | None, str, str | None]]:
    """Parse RSS or Atom XML; return list of (date_iso, title, text, link)."""
    items = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return items
    ns = {}
    if "}" in root.tag:
        ns["atom"] = root.tag[1:root.tag.index("}")]
    # Atom
    ATOM_NS = "http://www.w3.org/2005/Atom"
    if "feed" in (root.tag or "").lower() or (root.tag or "").endswith("}feed"):
        entries = root.findall(f".//{{{ATOM_NS}}}entry") or root.findall(".//entry")
        for entry in entries:
            date_iso, title, text_str, link = _parse_atom_entry(entry, ATOM_NS)
            if date_iso and text_str:
                items.append((date_iso, title, text_str, link))
        return items
    # RSS
    channel = root.find("channel") or root.find("{http://purl.org/rss/1.0/}channel")
    if channel is None:
        return items
    for item in channel.findall("item") or channel.findall("{http://purl.org/rss/1.0/}item"):
        date_iso, title, text_str, link = _parse_rss_item(item, ns)
        if date_iso and text_str:
            items.append((date_iso, title, text_str, link))
    return items


def _rss_bridge_url(base: str, bridge: str, format: str = "Atom", **params) -> str:
    """Build RSS-Bridge display URL: ?action=display&bridge=X&format=Y&param=value..."""
    base = base.rstrip("/")
    q = {"action": "display", "bridge": bridge, "format": format}
    q.update({k: v for k, v in params.items() if v is not None and v != ""})
    return f"{base}/?{urlencode(q)}"


def fetch_news(
    news_sources_path: Path | None = None,
    news_dir: Path | None = None,
    past_days: int = 7,
    max_news_items: int | None = None,
    dry_run: bool = False,
) -> list[dict]:
    """
    Fetch news from RSS/Atom feeds listed in news_sources.json. Keep items from the past `past_days`.
    Stops after saving `max_news_items` total (from config or argument). Feeds can be direct `url` or via RSS-Bridge.
    Writes JSON files to news_dir: YYYY-MM-DD_source_slug.json with {date, source, text, url?}.
    """
    news_sources_path = news_sources_path or NEWS_SOURCES_PATH
    news_dir = news_dir or NEWS_DIR
    news_dir.mkdir(parents=True, exist_ok=True)
    if not news_sources_path.is_file():
        return []
    try:
        with open(news_sources_path, encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return []
    feeds = config.get("feeds", [])
    if not feeds:
        return []
    past_days = int(config.get("past_days", past_days))
    if max_news_items is None:
        max_news_items = int(config.get("max_news_items", 10))
    cutoff = (datetime.now(timezone.utc).date() - timedelta(days=past_days)).isoformat()
    rss_bridge_base = (config.get("rss_bridge_base_url") or "").strip()
    session = _get_session()
    if not session:
        return []
    results = []
    saved_total = 0
    for feed_def in feeds:
        if saved_total >= max_news_items:
            break
        name = (feed_def.get("name") or feed_def.get("label") or "feed").strip().lower()
        name = re.sub(r"[^\w\-]", "_", name).strip("_") or "feed"
        # Resolve URL: direct "url" or build from "rss_bridge"
        url = feed_def.get("url")
        if not url and feed_def.get("rss_bridge") and rss_bridge_base:
            rb = feed_def["rss_bridge"]
            if isinstance(rb, dict) and rb.get("bridge"):
                bridge_name = rb.get("bridge")
                fmt = rb.get("format", "Atom")
                params = {k: v for k, v in rb.items() if k not in ("bridge", "format")}
                url = _rss_bridge_url(rss_bridge_base, bridge_name, fmt, **params)
        if not url:
            continue
        try:
            r = session.get(url, timeout=15)
            r.raise_for_status()
            text = (r.text or "").strip()
            if text.lower().startswith("<!") or "<html" in text[:200].lower():
                raise ValueError("Feed URL returned HTML instead of XML (site may block bots or show a consent page)")
            items = _parse_feed_xml(r.text)
        except Exception as e:
            err_msg = str(e)
            print(f"  [news] {name} failed: {err_msg}", file=sys.stderr)
            results.append({"date": None, "source": name, "path": None, "method": "news", "success": False, "error": err_msg})
            continue
        count = 0
        for date_iso, title, text_str, link in items:
            if saved_total >= max_news_items:
                break
            if date_iso < cutoff:
                continue
            if not text_str or len(text_str) < 20:
                continue
            slug = _slug((title or "item")[:60])
            out_name = f"{date_iso}_{name}_{slug}.json"
            out_file = news_dir / out_name
            if len(out_name) > 200:
                out_file = news_dir / f"{date_iso}_{name}_{hash(text_str) % 100000}.json"
            if dry_run:
                results.append({"date": date_iso, "source": name, "path": str(out_file), "method": "news", "success": None})
                count += 1
                saved_total += 1
                continue
            payload = {"date": date_iso, "source": name, "text": text_str}
            if link:
                payload["url"] = link
            try:
                out_file.write_text(json.dumps(payload, indent=2), encoding="utf-8")
                results.append({"date": date_iso, "source": name, "path": str(out_file), "method": "news", "success": True})
                count += 1
                saved_total += 1
            except Exception as e:
                results.append({"date": date_iso, "source": name, "path": None, "method": "news", "success": False, "error": str(e)})
        if count and not dry_run:
            print(f"  [news] {name}: {count} items", file=sys.stderr)
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
    whitelist_path = (PROJECT_ROOT / config_raw["source_whitelist"]) if isinstance(config_raw.get("source_whitelist"), str) else DEFAULT_WHITELIST_PATH
    allowed_domains = _load_resolution_grade_domains(whitelist_path)
    if not allowed_domains and whitelist_path != DEFAULT_WHITELIST_PATH:
        allowed_domains = _load_resolution_grade_domains(DEFAULT_WHITELIST_PATH)
    results = []
    for entry in sources:
        date = entry.get("date")
        source = entry.get("source", "speech")
        if not date or not re.match(r"\d{4}-\d{2}-\d{2}", date):
            results.append({"date": date, "source": source, "path": None, "method": "skip", "success": False})
            continue
        url_to_check = entry.get("youtube_url") or entry.get("transcript_url")
        if url_to_check and allowed_domains and not _is_resolution_grade_url(url_to_check, allowed_domains):
            results.append({"date": date, "source": source, "path": None, "method": "skip", "success": False, "reason": "url_not_on_tier_a_whitelist"})
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
        max_pages = 5
        if isinstance(wh, dict):
            max_items = int(wh.get("max_items", max_items))
            max_pages = int(wh.get("max_pages", max_pages))
        if url:
            wh_results = fetch_whitehouse_briefings(
                url, transcripts_dir, max_items=max_items, max_pages=max_pages, dry_run=dry_run, allowed_domains=allowed_domains
            )
            results.extend(wh_results)
    # Fetch news from RSS/Atom feeds (past week, 5+ sources)
    news_sources_path = PROJECT_ROOT / config_raw.get("news_sources", "data/news_sources.json")
    if isinstance(config_raw.get("news_sources"), str):
        news_sources_path = PROJECT_ROOT / config_raw["news_sources"]
    news_results = fetch_news(
        news_sources_path=news_sources_path if news_sources_path.is_file() else NEWS_SOURCES_PATH,
        news_dir=NEWS_DIR,
        dry_run=dry_run,
    )
    results.extend(news_results)
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
        line = f"  {r['date']} {r['source']} ({r['method']}) -> {status}" + (f"  {r['path']}" if r.get("path") else "")
        if r.get("success") is False and r.get("error"):
            line += f"  [{r['error'][:120]}]"
        print(line)
    if not results:
        print("No sources in config. Edit data/transcript_sources.json and add youtube_url or transcript_url entries. News: data/news_sources.json")
    # Exit 1 only when transcript/speech fetches failed; news feed failures (proxy/403) do not fail the run
    failed = sum(1 for r in results if r["success"] is False and r.get("method") in ("youtube", "url", "whitehouse"))
    return 1 if failed and not args.dry_run else 0


if __name__ == "__main__":
    sys.exit(main())
