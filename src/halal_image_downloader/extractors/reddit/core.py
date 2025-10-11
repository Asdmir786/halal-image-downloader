#!/usr/bin/env python3
"""
Core mixin for Reddit extractor: session, headers, URL utilities, JSON fetching,
rate limiting, and download implementation/validation.
"""
from __future__ import annotations

import re
import json
import time
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, unquote

import requests

from ..base_extractor import (
    BaseExtractor, logger,
    ExtractorError, TemporaryError, PermanentError,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError
)


class RedditCoreMixin:
    """Provides core utilities and network operations for Reddit."""

    def __init__(self, max_retries: int = 3, use_old_reddit: bool = True):
        # Initialize base extractor with strict mode
        super().__init__(strict_mode=True)

        # Reddit-specific settings
        self.use_old_reddit = use_old_reddit
        self.session = requests.Session()

        # Updated headers based on latest anti-bot research
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

        # Rate limiting (respecting 60 requests/min for anonymous)
        self.request_delay = 1.1  # Slightly over 1 second to stay under 60/min

    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Check if the URL is a valid Reddit URL."""
        reddit_patterns = [
            r'https?://(?:www\.)?reddit\.com/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9]+/?.*',  # Post URLs
            r'https?://(?:www\.)?reddit\.com/r/[A-Za-z0-9_]+/?.*',  # Subreddit URLs
            r'https?://(?:old\.)?reddit\.com/r/[A-Za-z0-9_]+/comments/[A-Za-z0-9]+/?.*',  # Old Reddit post
            r'https?://(?:old\.)?reddit\.com/r/[A-Za-z0-9_]+/?.*',  # Old Reddit subreddit
        ]
        return any(re.match(pattern, url) for pattern in reddit_patterns)

    def extract_subreddit_name(self, url: str) -> Optional[str]:
        """Extract subreddit name from Reddit URL."""
        match = re.search(r'/r/([A-Za-z0-9_]+)', url)
        return match.group(1) if match else None

    def extract_post_id(self, url: str) -> Optional[str]:
        """Extract post ID from Reddit URL."""
        match = re.search(r'/comments/([A-Za-z0-9]+)', url)
        return match.group(1) if match else None

    def convert_to_json_url(self, url: str) -> str:
        """Convert Reddit URL to JSON API format using latest 2025 method."""
        # Remove trailing slash and fragments
        url = url.rstrip('/').split('#')[0].split('?')[0]

        # Convert to old.reddit if enabled (recommended for better JSON structure)
        if self.use_old_reddit and 'old.reddit' not in url:
            if 'www.reddit.com' in url:
                url = url.replace('www.reddit.com', 'old.reddit.com')
            elif 'reddit.com' in url:
                url = url.replace('reddit.com', 'old.reddit.com')

        # Add .json suffix for direct API access
        return f"{url}.json"

    def _fetch_json_impl(self, url: str) -> Dict[str, Any]:
        """Implementation of JSON fetching (without retry logic)."""
        # Respect rate limiting
        time.sleep(self.request_delay)

        # Use fresh user agent for each request
        headers = self.get_fresh_headers(self.session.headers)

        try:
            resp = self.session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()

            # Check for Cloudflare challenges or rate limiting
            if 'cloudflare' in resp.text.lower() or resp.status_code == 429:
                raise RateLimitError("Reddit rate limit or Cloudflare protection detected")

            return resp.json()
        except requests.exceptions.JSONDecodeError as e:
            raise InvalidUrlError(f"Invalid JSON response from Reddit: {e}")
        except requests.exceptions.RequestException as e:
            # Let the classify_error method handle the specific error type
            raise

    def _fetch_json(self, url: str) -> Dict[str, Any]:
        """Fetch JSON with strict error handling."""
        return self.execute_with_error_handling_sync(self._fetch_json_impl, url)

    def download_image(self, image_url: str, output_path: str) -> bool:
        """Download a single image from Reddit with strict error handling."""
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

            # Use fresh user agent + Reddit-specific headers
            headers = self.get_fresh_headers(self.session.headers)
            headers.update({
                'Referer': 'https://www.reddit.com/',
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
        valid_types = ['image/jpeg', 'image/jpg', 'image/png', 'image/gif', 'image/webp', 'image/bmp']
        if any(img_type in content_type for img_type in valid_types):
            return True

        # If content-type is missing or wrong, check first few bytes for image magic numbers
        try:
            # Peek at first chunk without consuming the stream
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
            elif first_chunk.startswith(b'BM'):  # BMP
                return True

            # Check for HTML content (common when blocked)
            html_indicators = [b'<!DOCTYPE', b'<html', b'<HTML', b'<head', b'<HEAD']
            if any(indicator in first_chunk[:100] for indicator in html_indicators):
                logger.warning("Received HTML content instead of image - likely blocked or requires authentication")
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
            if b'<!DOCTYPE' in header or b'<html' in header or b'<HTML' in header:
                logger.error("Downloaded file contains HTML instead of image data")
                return False

            # Check magic bytes again
            if header.startswith(b'\xff\xd8\xff'):  # JPEG
                return True
            elif header.startswith(b'\x89PNG\r\n\x1a\n'):  # PNG
                return True
            elif header.startswith(b'GIF87a') or header.startswith(b'GIF89a'):  # GIF
                return True
            elif header.startswith(b'RIFF') and b'WEBP' in header[:12]:  # WebP
                return True
            elif header.startswith(b'BM'):  # BMP
                return True

            return False

        except Exception as e:
            logger.error(f"Error validating downloaded image: {e}")
            return False
