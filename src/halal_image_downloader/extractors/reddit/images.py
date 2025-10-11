#!/usr/bin/env python3
"""
Images mixin for Reddit extractor: high-level extraction and JSON metadata.
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional

from ..base_extractor import (
    logger,
    PermanentError,
    InvalidUrlError,
)


class RedditImagesMixin:
    """Provides high-level operations for Reddit: extract() and extract_json_metadata()."""

    def extract_images(self, url: str) -> List[Dict[str, Any]]:
        """Extract image URLs and metadata from Reddit post or subreddit."""
        if not self.is_valid_url(url):
            raise InvalidUrlError(f"Invalid Reddit URL format: {url}")

        logger.info(f"Extracting images from Reddit: {url}")

        try:
            # Convert to JSON API URL
            json_url = self.convert_to_json_url(url)
            logger.info(f"Using JSON API: {json_url}")

            # Fetch JSON data
            json_data = self._fetch_json(json_url)

            # Extract images from the JSON response
            images = self.extract_images_from_post_data(json_data)

            if not images:
                logger.info("No images found in Reddit post/subreddit")
                return []

            logger.info(f"Found {len(images)} image(s)")
            return images

        except PermanentError as e:
            logger.error(f"Permanent error extracting from {url}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error extracting images from {url}: {e}")
            return []

    def extract_json_metadata(self, url: str) -> Dict[str, Any]:
        """Extract comprehensive JSON metadata from Reddit post or subreddit."""
        from datetime import datetime

        if not self.is_valid_url(url):
            raise InvalidUrlError(f"Invalid Reddit URL format: {url}")

        # Determine content type first (outside try block)
        post_id = self.extract_post_id(url)
        subreddit_name = self.extract_subreddit_name(url)
        is_post = post_id is not None

        try:
            # Get JSON data from Reddit API
            json_url = self.convert_to_json_url(url)
            json_data = self._fetch_json(json_url)

            # Extract images using existing method
            images = self.extract_images_from_post_data(json_data)

            # Build comprehensive metadata
            metadata = {
                "platform": "reddit",
                "url": url,
                "json_url": json_url,
                "type": "post" if is_post else "subreddit",
                "subreddit": subreddit_name,
                "extraction_method": "reddit_json_api",
                "extraction_timestamp": datetime.now().isoformat(),
                "counts": {
                    "total_images": len(images),
                    "posts_analyzed": 0
                },
                "images": images
            }

            # Add post-specific metadata if it's a single post
            if is_post and json_data:
                try:
                    # Handle Reddit API response format
                    if isinstance(json_data, list) and len(json_data) > 0:
                        post_data = json_data[0]['data']['children'][0]['data']
                    elif 'data' in json_data and 'children' in json_data['data']:
                        post_data = json_data['data']['children'][0]['data']
                    else:
                        post_data = json_data

                    metadata.update({
                        "post_id": post_data.get('id'),
                        "title": post_data.get('title'),
                        "author": post_data.get('author'),
                        "score": post_data.get('score'),
                        "upvote_ratio": post_data.get('upvote_ratio'),
                        "num_comments": post_data.get('num_comments'),
                        "created_utc": post_data.get('created_utc'),
                        "permalink": post_data.get('permalink'),
                        "is_video": post_data.get('is_video', False),
                        "is_gallery": post_data.get('is_gallery', False),
                        "domain": post_data.get('domain'),
                        "post_hint": post_data.get('post_hint')
                    })
                except (KeyError, IndexError, TypeError) as e:
                    logger.warning(f"Could not extract post metadata: {e}")

            # Add subreddit listing metadata
            elif not is_post and json_data and 'data' in json_data:
                try:
                    listing_data = json_data['data']
                    posts = listing_data.get('children', [])
                    metadata['counts']['posts_analyzed'] = len(posts)
                    metadata.update({
                        "listing_after": listing_data.get('after'),
                        "listing_before": listing_data.get('before'),
                        "subreddit_type": "public"  # Could be enhanced
                    })
                except (KeyError, TypeError) as e:
                    logger.warning(f"Could not extract subreddit metadata: {e}")

            return metadata

        except Exception as e:
            logger.error(f"Error extracting JSON metadata from {url}: {e}")
            # Return error metadata
            return {
                "platform": "reddit",
                "url": url,
                "type": "post" if is_post else "subreddit", 
                "subreddit": subreddit_name,
                "extraction_method": "reddit_json_api",
                "extraction_timestamp": datetime.now().isoformat(),
                "error": str(e),
                "images": []
            }
