"""
Reddit extractor for halal-image-downloader

This module handles extraction of images from Reddit posts and subreddits using 
the latest 2025 methods including JSON suffix API and hidden endpoints.
"""

import re
import json
from typing import List, Dict, Any, Optional, Union
from urllib.parse import urlparse, unquote
import requests
from datetime import datetime

from .base_extractor import (
    BaseExtractor, logger,
    ExtractorError, TemporaryError, PermanentError,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError
)


class RedditExtractor(BaseExtractor):
    """Extractor for Reddit content using latest 2025 methods."""
    
    def __init__(self, max_retries: int = 3, use_old_reddit: bool = True):
        # Initialize base extractor
        super().__init__(max_retries=max_retries)
        
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
        import time
        
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
        """Fetch JSON with retry logic."""
        return self.retry_with_backoff_sync(self._fetch_json_impl, url)
    
    def extract_images_from_post_data(self, post_data: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Extract image URLs and metadata from Reddit post JSON data."""
        images = []
        
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
        images = []
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
                        # Sometimes Reddit URLs have extra encoding
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
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        
        # Build filename
        if index:
            filename = f"reddit_{safe_title}_{post_id}_{index}_{timestamp}{ext}"
        else:
            filename = f"reddit_{safe_title}_{post_id}_{timestamp}{ext}"
        
        return filename
    
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
    
    def extract(self, url: str) -> List[Dict[str, Any]]:
        """Main extraction method - implements BaseExtractor abstract method."""
        return self.extract_images(url)
    
    def download_image(self, image_url: str, output_path: str) -> bool:
        """Download a single image from Reddit with retry logic."""
        try:
            return self.retry_with_backoff_sync(self._download_image_impl, image_url, output_path)
        except Exception as e:
            logger.error(f"Failed to download image after all retries: {e}")
            return False
    
    def _download_image_impl(self, image_url: str, output_path: str) -> bool:
        """Implementation of image downloading (without retry logic)."""
        import time
        
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
    
    def close(self):
        """Close the session."""
        self.session.close()
