#!/usr/bin/env python3
"""
Speech Word Market Model — CLI entrypoint.
Run full pipeline or launch dashboard.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Optional

# Project root = directory containing main.py (so "scripts" is importable)
PROJECT_ROOT = os.path.dirname(os.path.abspath(__file__))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def load_config(config_path: Optional[str] = None) -> dict:
    path = config_path or os.path.join(PROJECT_ROOT, "config.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    parser = argparse.ArgumentParser(description="Speech Word Market Model")
    parser.add_argument("--fetch-all", action="store_true", help="Fetch transcripts and news (10 articles), then exit")
    parser.add_argument("--run-pipeline", action="store_true", help="Run full pipeline")
    parser.add_argument("--dashboard", action="store_true", help="Launch Streamlit dashboard")
    parser.add_argument("--config", default=None, help="Path to config.json")
    args = parser.parse_args()

    if args.dashboard:
        import subprocess
        dashboard_script = os.path.join(PROJECT_ROOT, "scripts", "dashboard.py")
        return subprocess.call([sys.executable, "-m", "streamlit", "run", dashboard_script, "--server.headless", "true"], cwd=PROJECT_ROOT)

    if args.fetch_all:
        from pathlib import Path
        from scripts.fetch_transcripts import fetch_transcripts, DEFAULT_SOURCES_PATH
        sources_path = Path(args.config) if args.config else DEFAULT_SOURCES_PATH
        results = fetch_transcripts(config_path=sources_path, dry_run=False)
        for r in results:
            status = "ok" if r["success"] is True else ("skip" if r["success"] is None else "fail")
            print(f"  {r['date']} {r['source']} ({r['method']}) -> {status}" + (f"  {r['path']}" if r.get("path") else ""))
        failed = sum(1 for r in results if r["success"] is False and r.get("method") in ("youtube", "url", "whitehouse"))
        return 1 if failed else 0

    # Default: run pipeline
    from scripts.scheduler import run_pipeline
    run_pipeline(args.config or os.path.join(PROJECT_ROOT, "config.json"), PROJECT_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
