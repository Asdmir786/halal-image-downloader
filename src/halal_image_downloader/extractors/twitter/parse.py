#!/usr/bin/env python3
"""
Parsing/detection mixin for Twitter/X.com extractor.
Contains classification, HTML parsing for images, and helper utilities.
"""
from __future__ import annotations

import re
import time
from typing import List, Dict, Any, Optional

from bs4 import BeautifulSoup

from ..base_extractor import (
    logger,
    InvalidUrlError,
)


class TwitterParseMixin:
    """Provides parsing and detection for Twitter/X.com HTML."""

    def classify_tweet_content(self, html_content: str, tweet_id: str = "unknown") -> Dict[str, Any]:
        """Classify X.com tweet content type based on HTML analysis."""
        # Enhanced content detection - check for multiple possible indicators
        tweet_indicators = [
            'data-testid="tweet"',
            'data-testid="tweetText"',
            'data-testid="tweetPhoto"',
            'data-testid="cellInnerDiv"',
            'role="article"',
            'pbs.twimg.com/media/',
            '/status/' + str(tweet_id) if tweet_id != "unknown" else None
        ]

        # Filter out None values
        tweet_indicators = [indicator for indicator in tweet_indicators if indicator]

        # Check how many indicators we found
        found_indicators = [indicator for indicator in tweet_indicators if indicator in html_content]

        logger.info(f"Tweet content detection: found {len(found_indicators)}/{len(tweet_indicators)} indicators")
        logger.info(f"Found indicators: {found_indicators}")

        # If we found some indicators, continue processing
        if len(found_indicators) >= 2:
            logger.info("Sufficient tweet content indicators found, proceeding with classification")
        elif 'pbs.twimg.com/media/' in html_content:
            logger.info("Found Twitter media URLs, proceeding despite missing other indicators")
        else:
            # Debug: Save HTML for inspection
            try:
                debug_path = f"debug_failed_twitter_{tweet_id}_{int(time.time())}.html"
                with open(debug_path, 'w', encoding='utf-8') as f:
                    f.write(html_content[:50000])  # First 50k chars to avoid huge files
                logger.warning(f"Saved failed HTML sample to {debug_path}")
            except Exception as e:
                logger.warning(f"Failed to save debug HTML: {e}")

            # Check for specific error patterns
            if 'login' in html_content.lower() or 'sign up' in html_content.lower():
                raise InvalidUrlError("❌ X.com is requiring login to view this tweet.")
            elif 'not found' in html_content.lower() or 'page not found' in html_content.lower():
                raise InvalidUrlError("❌ Tweet not found - it may have been deleted or made private.")
            elif len(html_content) < 10000:
                raise InvalidUrlError("❌ Received minimal content from X.com - possible blocking or rate limiting.")
            else:
                logger.warning("Proceeding with classification despite missing tweet indicators - content may be incomplete")
                # Don't throw error, let the extraction attempt continue

        # Search for key indicators (based on HTML pattern analysis)
        has_video_player = 'data-testid="videoPlayer"' in html_content
        # Be more specific about video URLs - avoid DNS prefetch false positives
        has_video_urls = ('src="https://video.twimg.com' in html_content or 
                         'blob:https://video.twimg.com' in html_content)
        has_video_tag = '<video' in html_content and 'preload=' in html_content
        has_blob_video = 'blob:https://x.com/' in html_content  # New pattern from 2025 HTML
        has_video_component = 'data-testid="videoComponent"' in html_content  # Another video indicator
        has_video_poster = 'amplify_video_thumb' in html_content  # Video poster/thumbnail

        # Critical: Check for video thumbnail URLs - these indicate video posts, NOT image posts
        has_video_thumbnails = ('ext_tw_video_thumb' in html_content or 
                               'video_thumb' in html_content)

        has_photos = 'data-testid="tweetPhoto"' in html_content
        has_carousel = 'carousel' in html_content.lower()

        # Count tweetPhoto instances for carousel detection
        photo_count = html_content.count('data-testid="tweetPhoto"')

        # Count different media URLs for better classification
        image_urls = len(re.findall(r'pbs\.twimg\.com/media/[^"\']*', html_content))
        # More specific video URL matching - avoid DNS prefetch links
        video_urls = len(re.findall(r'src=["\']https://video\.twimg\.com/[^"\']*', html_content))
        blob_videos = len(re.findall(r'blob:https://x\.com/[^"\']*', html_content))  # Count blob video sources
        # Count video thumbnail URLs
        video_thumb_urls = len(re.findall(r'ext_tw_video_thumb', html_content))

        logger.info(f"Content analysis: photos={photo_count}, images={image_urls}, videos={video_urls}, blob_videos={blob_videos}, video_thumbs={video_thumb_urls}")

        # Debug: Log what indicators were found
        logger.info(f"HTML indicators: video_player={has_video_player}, video_urls={has_video_urls}, video_tag={has_video_tag}, blob_video={has_blob_video}, video_component={has_video_component}, video_poster={has_video_poster}, video_thumbnails={has_video_thumbnails}, photos={has_photos}, carousel={has_carousel}")

        # Classification logic based on HTML patterns
        # Enhanced video detection for 2025 X.com patterns
        # CRITICAL: Video thumbnail detection - these are NOT real images, they're video previews
        if (has_video_player or has_video_urls or has_video_tag or has_blob_video or 
            has_video_component or has_video_poster or has_video_thumbnails or 
            video_urls > 0 or blob_videos > 0 or video_thumb_urls > 0):

            # Even if we have "photos", if we detect video thumbnails, it's a video post
            if has_video_thumbnails or video_thumb_urls > 0:
                return {
                    'type': 'video_only',
                    'has_video': True,
                    'has_images': False,
                    'video_count': max(video_urls, blob_videos, video_thumb_urls, 1),
                    'image_count': 0,
                    'description': f'Video post with thumbnail (video thumbnails are not downloadable images)'
                }
            elif has_photos or image_urls > 0:
                return {
                    'type': 'mixed_media',
                    'has_video': True,
                    'has_images': True,
                    'video_count': max(video_urls, blob_videos, 1),  # At least 1 if video detected
                    'image_count': max(photo_count, image_urls),
                    'description': f'Video with {max(photo_count, image_urls)} thumbnail/preview image(s)'
                }
            else:
                return {
                    'type': 'video_only',
                    'has_video': True,
                    'has_images': False,
                    'video_count': max(video_urls, blob_videos, 1),  # At least 1 if video detected
                    'image_count': 0,
                    'description': 'Video-only post'
                }

        elif has_photos or image_urls > 0:
            if photo_count > 1 or has_carousel or image_urls > 1:
                return {
                    'type': 'image_carousel',
                    'has_video': False,
                    'has_images': True,
                    'video_count': 0,
                    'image_count': max(photo_count, image_urls),
                    'description': f'Multi-image carousel ({max(photo_count, image_urls)} images)'
                }
            else:
                return {
                    'type': 'single_image',
                    'has_video': False,
                    'has_images': True,
                    'video_count': 0,
                    'image_count': 1,
                    'description': 'Single image post'
                }
        else:
            return {
                'type': 'text_only',
                'has_video': False,
                'has_images': False,
                'video_count': 0,
                'image_count': 0,
                'description': 'Text-only post'
            }

    def handle_mixed_media_prompt(self, classification: Dict[str, Any]) -> bool:
        """Handle interactive prompt for mixed media content (similar to Reddit)."""
        print(f"\n⚠️  Mixed media tweet detected!")
        print(f"📝 Content: {classification['description']}")
        print(f"🖼️  Images: {classification['image_count']}")
        print(f"🎥 Videos: {classification['video_count']}")
        print(f"")
        print(f"This tweet contains both images and videos.")
        print(f"halal-image-downloader only downloads images.")
        print(f"")

        while True:
            choice = input("Choose an option:\n[C]ontinue (download images only)\n[Q]uit program\nYour choice (C/Q): ").strip().upper()

            if choice in ['C', 'CONTINUE']:
                print(f"✅ Continuing - will download {classification['image_count']} image(s) and skip {classification['video_count']} video(s)")
                logger.info(f"User chose to continue with mixed media: {classification['image_count']} images, {classification['video_count']} videos skipped")
                return True
            elif choice in ['Q', 'QUIT']:
                print(f"❌ Exiting program as requested.")
                import sys
                sys.exit(0)
            else:
                print(f"Invalid choice. Please enter 'C' for Continue or 'Q' for Quit.")

    def extract_image_urls_from_html(self, html_content: str) -> List[Dict[str, Any]]:
        """Extract image URLs and metadata from Twitter HTML."""
        images: List[Dict[str, Any]] = []
        seen_urls = set()

        # Parse HTML
        soup = BeautifulSoup(html_content, 'html.parser')

        # Method 1: Find tweetPhoto containers
        photo_containers = soup.find_all('div', {'data-testid': 'tweetPhoto'})
        logger.info(f"Found {len(photo_containers)} tweetPhoto containers")

        for i, container in enumerate(photo_containers, 1):
            # Look for background-image style
            style_divs = container.find_all('div', style=lambda x: x and 'background-image' in x)
            for style_div in style_divs:
                style = style_div.get('style', '')
                # Extract URL from style="background-image: url('...');" or url("...")
                # Handle both single and double quotes, and HTML entities
                url_match = re.search(r"url\(['\"]?(https://pbs\.twimg\.com/media/[^'\")\s]+)", style)
                if url_match:
                    url = url_match.group(1)
                    # Clean up HTML entities
                    url = url.replace('&amp;', '&').replace('&quot;', '"')
                    # Remove any trailing quote or parenthesis that might have been captured
                    url = re.sub(r'["\')]+$', '', url)

                    if url not in seen_urls:
                        seen_urls.add(url)
                        # Convert to high quality version
                        high_quality_url = self.get_high_quality_url(url)
                        images.append({
                            'url': high_quality_url,
                            'filename': self._generate_filename(high_quality_url, f"twitter_image_{len(images)+1}"),
                            'source': 'tweetPhoto_background',
                            'index': len(images) + 1
                        })
                        logger.info(f"Extracted background image {len(images)}: {high_quality_url}")

            # Look for img tags within the container
            img_tags = container.find_all('img')
            for img_tag in img_tags:
                alt_text = img_tag.get('alt', '')
                # Skip if it looks like a profile picture or icon
                if any(skip_word in alt_text.lower() for skip_word in ['profile', 'avatar', 'icon']):
                    continue

                src = img_tag.get('src', '')
                if src and ('twimg.com' in src or src.startswith('http')):
                    # Handle relative URLs or convert to full pbs.twimg.com URL
                    if not src.startswith('http'):
                        # This might be a local saved file, try to construct the URL
                        # Look for a pattern that might indicate the original URL
                        continue

                    if src not in seen_urls:
                        seen_urls.add(src)
                        images.append({
                            'url': src,
                            'filename': self._generate_filename(src, f"twitter_image_{len(images)+1}"),
                            'source': 'img_tag',
                            'alt_text': alt_text,
                            'index': len(images) + 1
                        })
                        logger.info(f"Extracted img tag {len(images)}: {src}")

        # Method 2: Regex fallback for any missed pbs.twimg.com URLs
        # Look for any pbs.twimg.com URLs in the HTML that we might have missed
        # Updated pattern to handle more URL variations and HTML entities
        regex_patterns = [
            r'https://pbs\.twimg\.com/media/[A-Za-z0-9_-]+(?:\?[^"\')\s]*)?',  # Standard pattern
            r'src=["\']?(https://pbs\.twimg\.com/media/[^"\')\s]+)',  # src attribute
            r'url\(["\']?(https://pbs\.twimg\.com/media/[^"\')\s]+)\)',  # CSS url() function
        ]

        for pattern in regex_patterns:
            matches = re.findall(pattern, html_content)
            for match in matches:
                # Handle both direct matches and group matches
                url = match if isinstance(match, str) else match[0] if match else ""
                if not url:
                    continue

                # Clean up the URL
                url = url.replace('&amp;', '&').replace('&quot;', '"')
                url = re.sub(r'["\')]+$', '', url)  # Remove trailing quotes/parentheses

                if url and url not in seen_urls and 'pbs.twimg.com/media/' in url:
                    seen_urls.add(url)
                    high_quality_url = self.get_high_quality_url(url)
                    images.append({
                        'url': high_quality_url,
                        'filename': self._generate_filename(high_quality_url, f"twitter_image_{len(images)+1}"),
                        'source': 'regex_fallback',
                        'index': len(images) + 1
                    })
                    logger.info(f"Extracted via regex {len(images)}: {high_quality_url}")

        logger.info(f"Total images extracted: {len(images)}")
        return images

    def get_high_quality_url(self, url: str) -> str:
        """Convert Twitter image URL to highest quality version."""
        # Twitter URL format: https://pbs.twimg.com/media/ID?format=jpg&name=SIZE
        # Available sizes: thumb, small, medium, large, orig
        # Respect preferred_quality if provided by CLI
        pref = getattr(self, 'preferred_quality', 'best') or 'best'
        size = 'large'
        if str(pref).lower() in ('original', 'orig'):
            size = 'orig'
        elif str(pref).lower() == 'worst':
            size = 'small'
        # Replace size parameter accordingly
        url = re.sub(r'name=\w+', f'name={size}', url)

        # If no name parameter, add it
        if 'name=' not in url:
            if '?' in url:
                url += f'&name={size}'
            else:
                url += f'?name={size}'

        # Ensure format is specified
        if 'format=' not in url:
            if '?' in url:
                url += '&format=jpg'
            else:
                url += '?format=jpg'

        return url

    def _generate_filename(self, url: str, fallback_name: str) -> str:
        """Generate a safe filename for the image."""
        # Extract media ID from Twitter URL
        match = re.search(r'/media/([A-Za-z0-9_-]+)', url)
        if match:
            media_id = match.group(1)
            # Add timestamp for uniqueness
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return f"twitter_{media_id}_{timestamp}.jpg"
        else:
            # Fallback to safe name
            safe_name = self.sanitize_filename(fallback_name)
            from datetime import datetime
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return f"{safe_name}_{timestamp}.jpg"
