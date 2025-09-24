"""
Twitter/X.com extractor for halal-image-downloader

This module handles extraction of images from Twitter/X.com posts using Playwright for HTML fetching
and BeautifulSoup for parsing. Uses Playwright to handle JavaScript-heavy X.com pages and get fully
rendered HTML, then processes it with our improved parsing logic.

Based on analysis of X.com HTML structure from 2025, supports single images,
carousels, and mixed media with interactive user prompts.
"""

import re
import sys
import time
import asyncio
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse, unquote
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from .base_extractor import (
    BaseExtractor, logger,
    ExtractorError, TemporaryError, PermanentError,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError
)


class TwitterExtractor(BaseExtractor):
    """Extractor for Twitter/X.com content."""
    
    def __init__(self, max_retries: int = 3):
        # Initialize base extractor
        super().__init__(max_retries=max_retries)
        
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
    
    async def _fetch_html_with_playwright_impl(self, url: str) -> str:
        """Implementation of HTML fetching using Playwright (without retry logic)."""
        # Respect rate limiting
        time.sleep(self.request_delay)
        
        async with async_playwright() as p:
            browser = None
            try:
                # Launch browser with anti-detection settings for X.com
                browser = await p.chromium.launch(
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
    
    def _fetch_html(self, url: str) -> tuple[str, str]:
        """Fetch HTML with retry logic using Playwright. Returns (html_content, final_url)."""
        async def fetch_with_retry():
            return await self.retry_with_backoff_async(self._fetch_html_with_playwright_impl, url)
        
        return asyncio.run(fetch_with_retry())
    
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
        
        # Debug: Save HTML to file for inspection (only in verbose mode)
        if logger.level <= 20:  # INFO level or below
            try:
                debug_path = f"debug_twitter_{tweet_id}_{int(time.time())}.html"
                with open(debug_path, 'w', encoding='utf-8') as f:
                    f.write(html_content)
                logger.info(f"Debug: Saved HTML to {debug_path}")
            except Exception as e:
                logger.warning(f"Failed to save debug HTML: {e}")
        
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
                sys.exit(0)
            else:
                print(f"Invalid choice. Please enter 'C' for Continue or 'Q' for Quit.")
    
    def extract_image_urls_from_html(self, html_content: str) -> List[Dict[str, Any]]:
        """Extract image URLs and metadata from Twitter HTML."""
        images = []
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
        
        # Replace size parameter with 'large' (best balance of quality and availability)
        url = re.sub(r'name=\w+', 'name=large', url)
        
        # If no name parameter, add it
        if 'name=' not in url:
            if '?' in url:
                url += '&name=large'
            else:
                url += '?name=large'
        
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
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return f"twitter_{media_id}_{timestamp}.jpg"
        else:
            # Fallback to safe name
            safe_name = self.sanitize_filename(fallback_name)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            return f"{safe_name}_{timestamp}.jpg"
    
    def extract_images(self, url: str) -> List[Dict[str, Any]]:
        """Extract image URLs and metadata from Twitter post."""
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
                raise InvalidUrlError(f"❌ This tweet contains only videos. halal-image-downloader is for images only.\n💡 Details: {description}")
            
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
    
    def extract(self, url: str) -> List[Dict[str, Any]]:
        """Main extraction method - implements BaseExtractor abstract method."""
        return self.extract_images(url)
    
    def download_image(self, image_url: str, output_path: str) -> bool:
        """Download a single image from Twitter with retry logic."""
        try:
            return self.retry_with_backoff_sync(self._download_image_impl, image_url, output_path)
        except Exception as e:
            logger.error(f"Failed to download image after all retries: {e}")
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
    
    def close(self):
        """Close the session."""
        self.session.close()
