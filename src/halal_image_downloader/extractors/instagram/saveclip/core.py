#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx

from ...base_extractor import (
    logger,
)


class SaveClipCoreMixin:
    def __init__(self, output_dir: str = ".", headless: bool = True, debug_wait_seconds: float = 0.0, browser: str = "chromium", max_retries: int = 3, quiet: bool = False):
        # Initialize base extractor with strict mode
        super().__init__(strict_mode=True)

        # Instagram-specific settings
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.headless = headless
        self.debug_wait_ms = int(max(0.0, debug_wait_seconds) * 1000)
        self.browser_engine = (browser or "chromium").strip().lower()
        if self.browser_engine not in {"chromium", "firefox", "webkit"}:
            self.browser_engine = "chromium"
        # Quiet output (suppress non-essential prints unless verbose)
        self.quiet = bool(quiet)

        self.headers = {
            'User-Agent': self.ua.random,
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }

        # Connection pooling: persistent HTTP client for faster downloads
        self._http_client = httpx.Client(
            timeout=30,
            limits=httpx.Limits(max_connections=10, max_keepalive_connections=5)
        )

    def __del__(self):
        """Cleanup: close HTTP client when extractor is destroyed."""
        try:
            if hasattr(self, '_http_client') and self._http_client:
                self._http_client.close()
        except Exception:
            pass

    def _print(self, msg: str) -> None:
        """Conditional print respecting quiet mode."""
        try:
            if not getattr(self, 'quiet', False):
                print(msg, flush=True)
        except Exception:
            pass

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Check if the URL is a valid Instagram URL."""
        import re
        instagram_patterns = [
            r'https?://(?:www\.)?instagram\.com/p/[A-Za-z0-9_-]+/?',
            r'https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?',
        ]
        return any(re.match(pattern, url) for pattern in instagram_patterns)

    def extract_post_id(self, url: str) -> Optional[str]:
        """Extract post ID from Instagram URL."""
        import re
        # Match patterns like /p/POST_ID/ or /reel/POST_ID/
        match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)/', url)
        return match.group(1) if match else None

    async def _download_images_concurrent(self, image_downloads: List[tuple[str, str]]):
        """Download multiple images concurrently for maximum speed."""
        from concurrent.futures import ThreadPoolExecutor

        async def download_single_async(download_url: str, filename: str, index: int):
            """Download single image in thread pool."""
            loop = asyncio.get_event_loop()
            try:
                # Run sync download in thread pool to avoid blocking
                filepath = await loop.run_in_executor(
                    None,
                    lambda: self.download_image(download_url, filename)
                )
                if filepath:
                    self._print(f"✅ Downloaded image {index}/{len(image_downloads)}: {Path(filepath).name}")
                    return filepath
                else:
                    self._print(f"❌ Failed to download image {index}/{len(image_downloads)}")
                    return None
            except Exception as e:
                logger.error(f"Failed to download image {index}: {e}")
                self._print(f"✗ Failed to download image {index}: {e}")
                return None

        # Create concurrent download tasks
        tasks = [
            download_single_async(download_url, filename, i + 1)
            for i, (download_url, filename) in enumerate(image_downloads)
        ]

        # Execute all downloads concurrently
        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Filter successful downloads
        downloaded_files = [
            result for result in results
            if result is not None and not isinstance(result, Exception)
        ]

        return downloaded_files

    def download_image(self, image_url: str, filename: str) -> Optional[str]:
        """Download a single image from URL to filename. Returns filepath on success."""
        try:
            response = self._http_client.get(image_url, headers=self.headers, timeout=30)
            response.raise_for_status()

            # Ensure output directory exists
            filepath = Path(self.output_dir) / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)

            # Write image data
            with open(filepath, 'wb') as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)

            return str(filepath)

        except Exception as e:
            logger.error(f"Failed to download {image_url}: {e}")
            return None
