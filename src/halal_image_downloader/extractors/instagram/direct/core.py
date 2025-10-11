#!/usr/bin/env python3
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ...base_extractor import (
    logger,
    ExtractorError, TemporaryError, PermanentError,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError,
)


@dataclass
class DirectPostMetadata:
    author: Optional[str] = None
    verified: bool = False
    published_on: Optional[str] = None  # ISO8601
    likes: Optional[int] = None
    caption: Optional[str] = None
    image_url: Optional[str] = None
    image_alt: Optional[str] = None


class DirectCoreMixin:
    def __init__(
        self,
        output_dir: str = ".",
        headless: bool = True,
        debug_wait_seconds: float = 0.0,
        browser: str = "chromium",
        max_retries: int = 3,
        interactive_pauses: bool = True,
        output_template: Optional[str] = None,
        skip_download: bool = False,
        ig_accept_cookies: bool = False,
        use_chrome_channel: bool = False,
        quiet: bool = False,
    ) -> None:
        super().__init__(strict_mode=True)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.headless = headless
        self.debug_wait_ms = int(max(0.0, debug_wait_seconds) * 1000)
        self.browser_engine = (browser or "chromium").strip().lower()
        if self.browser_engine not in {"chromium", "firefox", "webkit"}:
            self.browser_engine = "chromium"

        self.interactive_pauses = interactive_pauses
        self.output_template = output_template
        self.skip_download = skip_download
        # Instagram-specific option toggled from CLI
        self.ig_accept_cookies = ig_accept_cookies
        # When True and browser_engine is chromium, launch via Chrome stable channel
        self.use_chrome_channel = use_chrome_channel
        # Quiet output (suppress non-essential prints unless verbose)
        self.quiet = bool(quiet)

        self.headers = {
            "User-Agent": self.ua.random,
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        # HTTP client (initialized only during download phase for pooling/HTTP2)
        self._http: Optional[httpx.Client] = None

    @staticmethod
    def is_valid_url(url: str) -> bool:
        patterns = [
            r"https?://(?:www\.)?instagram\.com/p/[A-Za-z0-9_-]+/?",
            r"https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?",
        ]
        return any(re.match(p, url) for p in patterns)

    @staticmethod
    def extract_post_id(url: str) -> Optional[str]:
        m = re.search(r"/(?:p|reel)/([A-Za-z0-9_-]+)/", url)
        return m.group(1) if m else None

    async def _wait_for_enter(self, prompt: str, timeout_seconds: Optional[float] = None) -> bool:
        """No-op pause (disabled). Always returns False; no interactive pauses used."""
        return False

    async def _save_screenshot(self, page, tag: str) -> Optional[Path]:
        """Best-effort screenshot utility. Returns path if saved, else None."""
        try:
            ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            name = f"debug_screenshot__{tag}__{ts}.png"
            out = self.output_dir / name
            await page.screenshot(path=str(out), full_page=False)
            try:
                self._print(f"Saved screenshot: {out}")
            except Exception:
                pass
            return out
        except Exception:
            return None

    def _print(self, msg: str) -> None:
        """Conditional print respecting quiet mode."""
        try:
            if not getattr(self, 'quiet', False):
                print(msg, flush=True)
        except Exception:
            pass

    def _blocking_input_wait(self) -> None:
        """Blocking input wait with Windows-specific handling."""
        try:
            if os.name == 'nt':
                try:
                    import msvcrt
                    # Consume until Enter
                    while True:
                        ch = msvcrt.getwch()
                        if ch in ('\r', '\n'):
                            break
                    return
                except Exception:
                    # Fallback to stdin
                    pass
            # Non-Windows or fallback
            input()
        except EOFError:
            return

    async def _wait_for_enter_timeout(self, prompt: str, timeout_seconds: float) -> bool:
        """Wait for Enter with a timeout. Returns True if Enter pressed, False if timed out."""
        if not self.interactive_pauses:
            return False
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.run_in_executor(None, lambda: input(prompt)), timeout=timeout_seconds)
            return True
        except Exception:
            try:
                print(f"No input within {timeout_seconds}s, auto-proceeding...", flush=True)
            except Exception:
                pass
            return False
