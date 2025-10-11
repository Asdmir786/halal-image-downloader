#!/usr/bin/env python3
"""
Core mixin for Pinterest extractor: session, headers, URL utilities, HTML fetching,
ID extraction, basic pin info, and image download implementation.
"""
from __future__ import annotations

import re
import json
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from ..base_extractor import (
    BaseExtractor, logger,
    ExtractorError, TemporaryError, PermanentError,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError
)


class PinterestCoreMixin:
    """Provides core utilities and network operations for Pinterest."""

    def __init__(self, max_retries: int = 3):
        # Initialize base extractor with strict mode
        super().__init__(strict_mode=True)

        # Pinterest-specific settings
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Check if the URL is a valid Pinterest URL."""
        pinterest_patterns = [
            r'https?://(?:www\.)?pinterest\.com/pin/[0-9]+/?',
            r'https?://(?:www\.)?pinterest\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?',
            r'https?://(?:www\.)?pinterest\.com/[A-Za-z0-9_.-]+/?',
        ]
        return any(re.match(pattern, url) for pattern in pinterest_patterns)

    def extract_pin_id(self, url: str) -> Optional[str]:
        """Extract pin ID from Pinterest URL."""
        match = re.search(r'/pin/([0-9]+)', url)
        return match.group(1) if match else None

    # --------------------
    # Fetch and parse utils
    # --------------------

    def _fetch_html_impl(self, url: str) -> str:
        """Implementation of HTML fetching (without retry logic)."""
        # Use fresh user agent for each request
        headers = self.get_fresh_headers(self.session.headers)
        try:
            resp = self.session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as e:
            # Let the classify_error method handle the specific error type
            raise

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML with strict error handling."""
        return self.execute_with_error_handling_sync(self._fetch_html_impl, url)

    def get_pin_info(self, url: str) -> Dict[str, Any]:
        """Extract basic information about the Pinterest pin with error handling."""
        if not self.is_valid_url(url):
            raise InvalidUrlError(f"Invalid Pinterest URL format: {url}")

        pin_id = self.extract_pin_id(url)
        if not pin_id:
            # Handle board/profile URLs
            pin_id = self._generate_id_from_url(url)

        try:
            # Fetch page to populate metadata (best-effort)
            html = self._fetch_html(url)
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.title.string.strip() if soup.title and soup.title.string else f'Pinterest Pin {pin_id}'
            desc_meta = soup.find('meta', attrs={'name': 'description'})
            description = desc_meta.get('content') if desc_meta else None

            return {
                'id': pin_id,
                'url': url,
                'title': title,
                'uploader': 'unknown',
                'upload_date': None,
                'description': description,
                'images': [],
                'thumbnail': None,
                'board_name': None,
                'save_count': None,
                'comment_count': None,
                'html': html,
            }
        except Exception as e:
            logger.error(f"Error fetching pin info for {url}: {e}")
            # Re-raise to be handled by retry mechanism
            raise

    def _generate_id_from_url(self, url: str) -> str:
        """Generate an ID from Pinterest URL for non-pin URLs."""
        parsed = urlparse(url)
        path_parts = [part for part in parsed.path.split('/') if part]
        return '_'.join(path_parts) if path_parts else 'pinterest_content'

    def download_image(self, image_url: str, output_path: str) -> bool:
        """Download a single image from Pinterest with strict error handling."""
        try:
            return self.execute_with_error_handling_sync(self._download_image_impl, image_url, output_path)
        except Exception as e:
            logger.error(f"Failed to download image: {e}")
            return False

    def _download_image_impl(self, image_url: str, output_path: str) -> bool:
        """Implementation of image downloading (without retry logic)."""
        try:
            # Use fresh user agent for each request
            headers = self.get_fresh_headers(self.session.headers)

            response = self.session.get(image_url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()

            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)

            return True
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
            # Re-raise to be handled by retry mechanism
            raise
