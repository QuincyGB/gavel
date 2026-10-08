#!/usr/bin/env python3
"""Record the Gavel demo trial on the live site with Playwright video capture.

Flow: landing -> load demo case -> file -> deliberation transcript -> verdict.
Saves: gavel-trial-raw.webm (screen recording)
"""
import os
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

from playwright.sync_api import sync_playwright

URL = "http://127.0.0.1:8123/"
OUT_DIR = Path(__file__).parent
RAW = OUT_DIR / "gavel-trial-raw.webm"


def _proxy():
    # Local server: bypass any proxy for localhost.
    return {"server": "http://127.0.0.1:1", "bypass": "127.0.0.1,localhost"}


def main():
    with sync_playwright() as p:
        launch_kw = {"args": ["--autoplay-policy=no-user-gesture-required"]}
        proxy = _proxy()
        if proxy:
            launch_kw["proxy"] = proxy
        browser = p.chromium.launch(**launch_kw)
        ctx = browser.new_context(
            viewport={"width": 1280, "height": 720},
            record_video_dir=str(OUT_DIR),
            record_video_size={"width": 1280, "height": 720},
        )
        page = ctx.new_page()
        page.goto(URL, wait_until="networkidle")
        page.wait_for_timeout(2500)  # landing / filing view

        # Load the demo case, then file it.
        page.click("#demo-btn")
        page.wait_for_timeout(1200)
        page.click("#submit-btn")

        # Wait for the verdict banner to render (deliberation streams via SSE).
        # Scripted provider is fast server-side; the typewriter paces the UI.
        # 13 events, ~1330 words at ~28wps ≈ 50s + markers/verdict.
        page.wait_for_selector("#verdict-banner:not(.hidden)", timeout=300_000)
        page.wait_for_timeout(6000)  # let verdict + hash settle on screen

        # Hold on the verdict, then close.
        page.wait_for_timeout(4000)
        ctx.close()
        browser.close()

    # Playwright names the file arbitrarily; find and rename it.
    vids = sorted(OUT_DIR.glob("*.webm"))
    if not vids:
        print("no video captured", file=sys.stderr)
        sys.exit(1)
    latest = max(vids, key=lambda f: f.stat().st_mtime)
    latest.rename(RAW)
    print("saved", RAW, f"{RAW.stat().st_size/1e6:.1f} MB")


if __name__ == "__main__":
    main()
