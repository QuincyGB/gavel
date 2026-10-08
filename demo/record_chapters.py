#!/usr/bin/env python3
"""Record the Gavel demo trial in chapters, logging phase timestamps.

Chapters:
  filing      - landing -> demo case loaded -> form shown -> submit
  deliberation - transcript streams (all 13 events)
  verdict     - verdict banner hold
Saves: gavel-trial-chapters.webm + phases.json with timestamps (seconds).
"""
import json
import sys
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8123/"
OUT_DIR = Path(__file__).parent
RAW = OUT_DIR / "gavel-trial-chapters.webm"
PHASES = OUT_DIR / "phases.json"


def main():
    t0 = time.time()
    phases = {}
    with sync_playwright() as p:
        browser = p.chromium.launch(proxy={"server": "http://127.0.0.1:1",
                                           "bypass": "127.0.0.1,localhost"})
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(OUT_DIR),
            record_video_size={"width": 1280, "height": 720},
        )
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")

        # --- filing chapter: slow, deliberate ---
        page.wait_for_timeout(3000)
        page.click("#demo-btn")
        page.wait_for_timeout(4000)  # admire the filled form
        phases["submit"] = round(time.time() - t0, 2)
        page.click("#submit-btn")

        # --- deliberation chapter ---
        page.wait_for_selector("#verdict-banner:not(.hidden)", timeout=300_000)
        phases["verdict"] = round(time.time() - t0, 2)
        page.wait_for_timeout(14000)  # verdict hold
        phases["end"] = round(time.time() - t0, 2)
        ctx.close()
        browser.close()

    vids = sorted(OUT_DIR.glob("*.webm"))
    latest = max(vids, key=lambda f: f.stat().st_mtime)
    latest.rename(RAW)
    PHASES.write_text(json.dumps(phases, indent=1))
    print("saved", RAW, f"{RAW.stat().st_size/1e6:.1f} MB", phases)


if __name__ == "__main__":
    main()
