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
    parser.add_argument("--run-pipeline", action="store_true", help="Run full pipeline")
    parser.add_argument("--dashboard", action="store_true", help="Launch Streamlit dashboard")
    parser.add_argument("--config", default=None, help="Path to config.json")
    args = parser.parse_args()

    if args.dashboard:
        import subprocess
        dashboard_script = os.path.join(PROJECT_ROOT, "scripts", "dashboard.py")
        return subprocess.call([sys.executable, "-m", "streamlit", "run", dashboard_script, "--server.headless", "true"], cwd=PROJECT_ROOT)

    # Default: run pipeline
    config = load_config(args.config)
    # Pipeline will be wired in when scheduler/edge_detector are ready
    from scripts.scheduler import run_pipeline
    run_pipeline(args.config or os.path.join(PROJECT_ROOT, "config.json"), PROJECT_ROOT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
