#!/usr/bin/env python3
"""
Parsing mixin for Reddit extractor.
Contains image extraction from JSON responses and helper utilities.
"""
from __future__ import annotations

import re
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse

from ..base_extractor import logger


class RedditParseMixin:
    """Provides parsing helpers for Reddit JSON responses."""

    def extract_images_from_post_data(self, post_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract image URLs and metadata from Reddit post JSON data."""
        images: List[Dict[str, Any]] = []

        try:
            # Handle both single post and listing formats
            if isinstance(post_data, list) and len(post_data) > 0:
                # Post comment format: [post_data, comments_data]
                post_data = post_data[0]['data']['children'][0]['data']
            elif 'data' in post_data and 'children' in post_data['data']:
                # Subreddit listing format
                posts = post_data['data']['children']
                for post in posts:
                    if post['kind'] == 't3':  # t3 = link/post
                        images.extend(self._extract_images_from_single_post(post['data']))
                return images

            # Single post format
            images.extend(self._extract_images_from_single_post(post_data))

        except (KeyError, TypeError, IndexError) as e:
            logger.warning(f"Error parsing Reddit post data: {e}")

        return images

    def _extract_images_from_single_post(self, post: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract images from a single Reddit post."""
        images: List[Dict[str, Any]] = []
        seen_urls = set()  # Track URLs to avoid duplicates

        try:
            post_title = post.get('title', 'Unknown')
            post_id = post.get('id', 'unknown')
            subreddit = post.get('subreddit', 'unknown')
            author = post.get('author', 'unknown')

            # Comprehensive media type detection
            url = post.get('url', '')
            is_video = post.get('is_video', False)
            is_gallery = post.get('is_gallery', False)

            # Skip video posts
            if is_video or 'v.redd.it' in url:
                logger.info(f"Skipping video post: {post_title}")
                return images

            # Skip audio posts
            if any(audio_host in url for audio_host in ['soundcloud.com', 'spotify.com', 'audio', '.mp3', '.wav', '.m4a']):
                logger.info(f"Skipping audio post: {post_title}")
                return images

            # Skip video hosting sites
            video_hosts = ['youtube.com', 'youtu.be', 'vimeo.com', 'tiktok.com', 'twitch.tv', 'streamable.com']
            if any(video_host in url for video_host in video_hosts):
                logger.info(f"Skipping video hosting site post: {post_title}")
                return images

            # For gallery posts, check if they contain any video/audio content
            if is_gallery:
                media_metadata = post.get('media_metadata', {})
                if media_metadata:
                    has_video_audio = False
                    total_items = len(media_metadata)
                    image_count = 0
                    video_count = 0

                    for media_id, media in media_metadata.items():
                        media_type = media.get('e', 'unknown')
                        if media_type == 'RedditVideo' or media_type == 'AnimatedImage':
                            has_video_audio = True
                            video_count += 1
                        elif media_type == 'Image':
                            image_count += 1

                    if has_video_audio and image_count > 0:
                        # Mixed media gallery - ask user what to do
                        print(f"\n⚠️  Mixed media gallery detected!")
                        print(f"📝 Post: {post_title}")
                        print(f"🖼️  Images: {image_count}")
                        print(f"🎥 Videos/Animations: {video_count}")
                        print(f"")
                        print(f"This gallery contains both images and videos.")
                        print(f"halal-image-downloader only downloads images.")
                        print(f"")

                        while True:
                            choice = input("Choose an option:\n[C]ontinue (download images only)\n[Q]uit program\nYour choice (C/Q): ").strip().upper()

                            if choice in ['C', 'CONTINUE']:
                                print(f"✅ Continuing - will download {image_count} image(s) and skip {video_count} video(s)")
                                logger.info(f"User chose to continue with mixed gallery: {image_count} images, {video_count} videos skipped")
                                break
                            elif choice in ['Q', 'QUIT']:
                                print(f"❌ Exiting program as requested.")
                                import sys
                                sys.exit(0)
                            else:
                                print(f"Invalid choice. Please enter 'C' for Continue or 'Q' for Quit.")

                    elif has_video_audio and image_count == 0:
                        logger.info(f"Skipping video-only gallery: {post_title}")
                        return images
                    elif image_count == 0:
                        logger.info(f"Skipping gallery with no images: {post_title}")
                        return images
                    else:
                        logger.info(f"Pure image gallery with {image_count} image(s): {post_title}")

            # Debug: Check post structure
            has_preview = bool(post.get('preview', {}).get('images'))
            logger.info(f"Post analysis - Gallery: {is_gallery}, Has Preview: {has_preview}, Direct URL: {url}")

            # Method 1: Direct image URL
            url = post.get('url', '')
            if self._is_direct_image_url(url) and url not in seen_urls:
                seen_urls.add(url)
                logger.info(f"Method 1 (Direct): Found image URL: {url}")
                images.append({
                    'url': url,
                    'filename': self._generate_filename(url, post_title, post_id),
                    'title': post_title,
                    'post_id': post_id,
                    'subreddit': subreddit,
                    'author': author,
                    'source': 'direct_url'
                })

            # Method 2: Preview images (multiple resolutions) - Only if no direct image found
            if not images:  # Only use preview if we didn't find a direct image
                preview = post.get('preview', {})
                if 'images' in preview and len(preview['images']) > 0:
                    # Get the first (and usually only) image from preview
                    img = preview['images'][0]

                    # Try to get highest resolution available
                    best_img = None
                    best_resolution = 0

                    # Check source resolution (highest quality)
                    candidate = img.get('source', {})
                    if 'url' in candidate:
                        width = candidate.get('width', 0)
                        height = candidate.get('height', 0)
                        resolution = width * height

                        if resolution > best_resolution:
                            best_resolution = resolution
                            best_img = candidate

                    if best_img and 'url' in best_img:
                        # Decode HTML entities and clean URL
                        img_url = best_img['url'].replace('&amp;', '&')
                        import urllib.parse
                        img_url = urllib.parse.unquote(img_url)

                        # Only add if we haven't seen this URL before
                        if img_url not in seen_urls:
                            seen_urls.add(img_url)
                            logger.info(f"Method 2 (Preview): Found image URL: {img_url} ({best_img.get('width', 'unknown')}x{best_img.get('height', 'unknown')})")
                            images.append({
                                'url': img_url,
                                'filename': self._generate_filename(img_url, post_title, post_id, len(images)+1),
                                'title': post_title,
                                'post_id': post_id,
                                'subreddit': subreddit,
                                'author': author,
                                'resolution': f"{best_img.get('width', 'unknown')}x{best_img.get('height', 'unknown')}",
                                'source': 'preview'
                            })

            # Method 3: Gallery posts (Reddit native)
            if post.get('is_gallery', False):
                gallery_data = post.get('gallery_data', {})
                media_metadata = post.get('media_metadata', {})

                for item in gallery_data.get('items', []):
                    media_id = item.get('media_id')
                    if media_id and media_id in media_metadata:
                        media = media_metadata[media_id]
                        media_type = media.get('e', 'unknown')

                        if media_type == 'Image':  # Only process images
                            # Get highest resolution
                            if 's' in media and 'u' in media['s']:
                                img_url = media['s']['u'].replace('&amp;', '&')
                                # Only add if we haven't seen this URL before
                                if img_url not in seen_urls:
                                    seen_urls.add(img_url)
                                    logger.info(f"Method 3 (Gallery): Found image URL: {img_url}")
                                    images.append({
                                        'url': img_url,
                                        'filename': self._generate_filename(img_url, post_title, post_id, len(images)+1),
                                        'title': post_title,
                                        'post_id': post_id,
                                        'subreddit': subreddit,
                                        'author': author,
                                        'gallery_item': True,
                                        'source': 'gallery'
                                    })
                        elif media_type in ['RedditVideo', 'AnimatedImage']:
                            # Skip video/animation items (user already chose to continue)
                            logger.info(f"Method 3 (Gallery): Skipping {media_type} item as requested")
                        else:
                            logger.warning(f"Method 3 (Gallery): Unknown media type '{media_type}' - skipping")

        except (KeyError, TypeError) as e:
            logger.warning(f"Error extracting images from post: {e}")

        return images

    def _is_direct_image_url(self, url: str) -> bool:
        """Check if URL is a direct image link."""
        if not url:
            return False

        # Common image file extensions
        image_extensions = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg'}

        # Check file extension
        parsed = urlparse(url.lower())
        path = parsed.path

        # Handle imgur and other image hosts
        if 'imgur.com' in parsed.netloc or 'i.redd.it' in parsed.netloc:
            return True

        return any(path.endswith(ext) for ext in image_extensions)

    def _generate_filename(self, url: str, title: str, post_id: str, index: Optional[int] = None) -> str:
        """Generate a safe filename for the image."""
        # Clean up title for filename
        safe_title = self.sanitize_filename(title)[:50]  # Limit title length

        # Get file extension from URL
        parsed = urlparse(url)
        path = parsed.path
        ext = '.jpg'  # Default extension

        if '.' in path:
            ext = '.' + path.split('.')[-1].lower()
            if ext not in {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}:
                ext = '.jpg'

        # Generate timestamp
        from datetime import datetime
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Build filename
        if index:
            filename = f"reddit_{safe_title}_{post_id}_{index}_{timestamp}{ext}"
        else:
            filename = f"reddit_{safe_title}_{post_id}_{timestamp}{ext}"

        return filename
