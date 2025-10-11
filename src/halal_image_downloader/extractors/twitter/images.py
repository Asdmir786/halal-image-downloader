#!/usr/bin/env python3
"""
Images mixin for Twitter/X.com extractor: high-level extraction orchestration.
"""
from __future__ import annotations

from typing import List, Dict, Any

from ..base_extractor import (
    logger,
    PermanentError,
    InvalidUrlError,
)


class TwitterImagesMixin:
    """Provides high-level operations for Twitter/X.com: extract_images()."""

    def extract_images(self, url: str) -> List[Dict[str, Any]]:
        """Extract image URLs and metadata from Twitter/X.com post."""
        if not self.is_valid_url(url):
            raise InvalidUrlError(f"Invalid Twitter/X.com URL format: {url}")

        # Normalize URL for better access
        normalized_url = self.normalize_twitter_url(url)

        tweet_id = self.extract_tweet_id(normalized_url)
        username = self.extract_username(normalized_url) or "i"  # Default to "i" for embedded tweets

        logger.info(f"Extracting images from Twitter post: @{username}/status/{tweet_id}")

        try:
            # Fetch HTML content and get final URL after any redirects
            html_content, final_url = self._fetch_html(normalized_url)

            # If we got redirected, extract username from the final URL and update our working URL
            if final_url != normalized_url:
                final_username = self.extract_username(final_url)
                if final_username and final_username != "i":
                    username = final_username
                    logger.info(f"Updated username from redirect: @{username}")

                # For /i/status/ URLs that don't contain full content,
                # try fetching the redirected URL directly
                if '/i/status/' in normalized_url and final_url != normalized_url:
                    logger.info(f"Embedded URL detected, refetching content from final URL: {final_url}")
                    html_content, _ = self._fetch_html(final_url)

            # Classify content type
            classification = self.classify_tweet_content(html_content, tweet_id)
            logger.info(f"Content classification: {classification}")

            # Handle based on content type
            content_type = classification['type']

            if content_type == 'video_only':
                description = classification.get('description', 'Video-only post')
                raise InvalidUrlError(
                    f"❌ This tweet contains only videos. halal-image-downloader is for images only.\n💡 Details: {description}"
                )

            elif content_type == 'mixed_media':
                # Interactive prompt for user choice
                continue_download = self.handle_mixed_media_prompt(classification)
                if not continue_download:
                    return []

            elif content_type == 'text_only':
                raise InvalidUrlError("❌ No images found in this tweet.")

            # Extract images (for single_image, image_carousel, or mixed_media with user consent)
            images = self.extract_image_urls_from_html(html_content)

            if not images:
                logger.warning("No images found despite content classification indicating images present")
                logger.warning(f"Classification was: {classification}")
                logger.warning(f"HTML sample: {html_content[:500]}...")
                raise InvalidUrlError("❌ No downloadable images found in this tweet.")

            logger.info(f"Successfully extracted {len(images)} image(s)")
            return images

        except PermanentError as e:
            logger.error(f"Permanent error extracting from {url}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error extracting images from {url}: {e}")
            return []
