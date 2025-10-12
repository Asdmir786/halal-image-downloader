#!/usr/bin/env python3
"""
Core mixin for Twitter/X.com extractor: session, headers, URL utilities,
Playwright HTML fetching, and image download/validation helpers.
"""
from __future__ import annotations

import re
import time
import asyncio
from typing import List, Dict, Any, Optional, Tuple

import requests
from playwright.async_api import async_playwright

from ...utils.browser import launch_browser_smart
from ..base_extractor import (
    BaseExtractor, logger,
    ExtractorError, TemporaryError, PermanentError,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError
)


class TwitterCoreMixin:
    """Provides core utilities and network operations for Twitter/X.com."""

    def __init__(self, max_retries: int = 3):
        # Initialize base extractor with strict mode
        super().__init__(strict_mode=True)

        # Twitter-specific settings
        self.session = requests.Session()

        # Updated headers based on X.com requirements
        self.session.headers.update({
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Cache-Control': 'max-age=0'
        })

        # Rate limiting (be respectful to Twitter)
        self.request_delay = 2.0  # 2 seconds between requests

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Check if the URL is a valid Twitter/X.com URL."""
        twitter_patterns = [
            r'https?://(?:www\.)?(?:twitter\.com|x\.com)/[^/]+/status/\d+/?.*',
            r'https?://(?:mobile\.)?(?:twitter\.com|x\.com)/[^/]+/status/\d+/?.*',
            r'https?://(?:www\.)?(?:twitter\.com|x\.com)/i/status/\d+/?.*',  # Embedded tweets
        ]
        return any(re.match(pattern, url) for pattern in twitter_patterns)

    def extract_tweet_id(self, url: str) -> Optional[str]:
        """Extract tweet ID from Twitter/X.com URL."""
        match = re.search(r'/status/(\d+)', url)
        return match.group(1) if match else None

    def extract_username(self, url: str) -> Optional[str]:
        """Extract username from Twitter/X.com URL."""
        match = re.search(r'(?:twitter\.com|x\.com)/([^/]+)/status/', url)
        return match.group(1) if match else None

    def normalize_twitter_url(self, url: str) -> str:
        """Convert embedded tweet URLs to regular tweet URLs for better access."""
        # Convert /i/status/ URLs to regular format - we'll need to fetch the actual username
        if '/i/status/' in url:
            logger.info("Detected embedded tweet URL format (/i/status/)")
            logger.info("Note: Embedded tweet URLs may have limited content access")
            # Keep the URL as-is but log the limitation
        return url

    async def _fetch_html_with_playwright_impl(self, url: str) -> Tuple[str, str]:
        """Implementation of HTML fetching using Playwright (without retry logic)."""
        # Respect rate limiting
        time.sleep(self.request_delay)

        async with async_playwright() as p:
            browser = None
            try:
                # Launch browser with anti-detection settings for X.com
                browser = await launch_browser_smart(
                    p,
                    browser_type="chromium",
                    headless=True,
                    args=[
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                        '--disable-accelerated-2d-canvas',
                        '--no-first-run',
                        '--no-zygote',
                        '--disable-gpu',
                        '--disable-web-security',
                        '--disable-features=VizDisplayCompositor'
                    ]
                )

                # Use more realistic browser context
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                    locale='en-US',
                    timezone_id='America/New_York',
                    extra_http_headers={
                        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                        'DNT': '1',
                        'Upgrade-Insecure-Requests': '1',
                        'Sec-Fetch-Dest': 'document',
                        'Sec-Fetch-Mode': 'navigate',
                        'Sec-Fetch-Site': 'none',
                        'Sec-Fetch-User': '?1'
                    }
                )

                page = await context.new_page()

                # Navigate to the URL and follow redirects
                logger.info(f"Loading X.com page: {url}")
                response = await page.goto(url, wait_until='networkidle', timeout=30000)

                # Check if we got redirected (especially for /i/status/ URLs)
                final_url = page.url
                if final_url != url:
                    logger.info(f"Redirected from {url} to {final_url}")

                # Check for error responses
                if response and response.status >= 400:
                    if response.status == 429:
                        raise RateLimitError("Twitter/X.com rate limit detected")
                    elif response.status == 404:
                        raise InvalidUrlError("Tweet not found or has been deleted")
                    elif response.status >= 500:
                        raise ServiceUnavailableError(f"Twitter/X.com server error: {response.status}")

                # Wait for various content indicators to load
                selectors_to_try = [
                    '[data-testid="tweet"]',
                    '[data-testid="tweetPhoto"]',
                    '[data-testid="cellInnerDiv"]',
                    '[role="article"]',
                    'img[src*="pbs.twimg.com"]'
                ]

                content_loaded = False
                for selector in selectors_to_try:
                    try:
                        await page.wait_for_selector(selector, timeout=5000)
                        logger.info(f"Content loaded successfully (found: {selector})")
                        content_loaded = True
                        break
                    except:
                        continue

                if not content_loaded:
                    logger.warning("No expected content selectors found, but continuing with full page content")
                    # Wait a bit longer for any remaining content to load
                    await page.wait_for_timeout(3000)

                # Check if we're redirected to login page
                current_url = page.url
                if 'login' in current_url.lower() or 'auth' in current_url.lower():
                    raise InvalidUrlError("Tweet requires authentication or is private")

                # Get the full page HTML
                html_content = await page.content()

                # Basic validation that we got actual content
                if len(html_content) < 1000:
                    raise InvalidUrlError("Received minimal content - page may be blocked or unavailable")

                logger.info(f"Successfully fetched {len(html_content)} characters of HTML content")
                return html_content, final_url

            except Exception as e:
                if isinstance(e, (RateLimitError, InvalidUrlError, ServiceUnavailableError)):
                    raise
                else:
                    # Wrap other errors as network errors
                    raise NetworkError(f"Failed to fetch X.com page: {str(e)}")
            finally:
                if browser:
                    await browser.close()

    def _fetch_html(self, url: str) -> Tuple[str, str]:
        """Fetch HTML with retry logic using Playwright. Returns (html_content, final_url)."""
        async def fetch_with_retry():
            return await self.execute_with_error_handling(self._fetch_html_with_playwright_impl, url)

        return asyncio.run(fetch_with_retry())

    def download_image(self, image_url: str, output_path: str) -> bool:
        """Download a single image from Twitter with strict error handling."""
        try:
            return self.execute_with_error_handling_sync(self._download_image_impl, image_url, output_path)
        except Exception as e:
            logger.error(f"Failed to download image: {e}")
            return False

    def _download_image_impl(self, image_url: str, output_path: str) -> bool:
        """Implementation of image downloading (without retry logic)."""
        try:
            # Respect rate limiting
            time.sleep(self.request_delay)

            # Use fresh user agent + Twitter-specific headers
            headers = self.get_fresh_headers(self.session.headers)
            headers.update({
                'Referer': 'https://x.com/',
                'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
                'Sec-Fetch-Dest': 'image',
                'Sec-Fetch-Mode': 'no-cors',
                'Sec-Fetch-Site': 'cross-site'
            })

            response = self.session.get(image_url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()

            # Validate content is actually an image
            content_type = response.headers.get('content-type', '').lower()
            if not self._is_valid_image_content(content_type, response):
                logger.error(f"Invalid content type '{content_type}' for image URL: {image_url}")
                return False

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            # Final validation: check if file is actually an image
            if not self._validate_downloaded_image(output_path):
                logger.error(f"Downloaded file is not a valid image: {output_path}")
                # Remove the invalid file
                try:
                    import os
                    os.remove(output_path)
                except:
                    pass
                return False

            return True
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
            # Re-raise to be handled by retry mechanism
            raise

    def _is_valid_image_content(self, content_type: str, response) -> bool:
        """Check if the response contains valid image content."""
        # Check content-type header
        valid_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp']
        if any(img_type in content_type for img_type in valid_types):
            return True

        # If content-type is missing or wrong, check first few bytes
        try:
            first_chunk = next(response.iter_content(chunk_size=512), b'')
            if not first_chunk:
                return False

            # Check magic bytes for common image formats
            if first_chunk.startswith(b'\xff\xd8\xff'):  # JPEG
                return True
            elif first_chunk.startswith(b'\x89PNG\r\n\x1a\n'):  # PNG
                return True
            elif first_chunk.startswith(b'GIF87a') or first_chunk.startswith(b'GIF89a'):  # GIF
                return True
            elif first_chunk.startswith(b'RIFF') and b'WEBP' in first_chunk[:12]:  # WebP
                return True

            # Check for HTML content (blocked)
            html_indicators = [b'<!DOCTYPE', b'<html', b'<HTML']
            if any(indicator in first_chunk[:100] for indicator in html_indicators):
                logger.warning("Received HTML content instead of image - likely blocked")
                return False

        except Exception as e:
            logger.warning(f"Could not validate content: {e}")

        return False

    def _validate_downloaded_image(self, file_path: str) -> bool:
        """Validate that the downloaded file is actually an image."""
        try:
            with open(file_path, 'rb') as f:
                header = f.read(512)

            # Check for HTML content in downloaded file
            if b'<!DOCTYPE' in header or b'<html' in header:
                logger.error("Downloaded file contains HTML instead of image data")
                return False

            # Check magic bytes
            if header.startswith(b'\xff\xd8\xff'):  # JPEG
                return True
            elif header.startswith(b'\x89PNG\r\n\x1a\n'):  # PNG
                return True
            elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):  # GIF
                return True
            elif header.startswith(b'RIFF') and b'WEBP' in header[:12]:  # WebP
                return True

            return False

        except Exception as e:
            logger.error(f"Error validating downloaded image: {e}")
            return False
