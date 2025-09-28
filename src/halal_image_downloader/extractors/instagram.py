#!/usr/bin/env python3
"""
Instagram Image Extractor using SaveClip.app
Extracts images from Instagram posts using SaveClip.app service with Playwright automation.
"""

import asyncio
import os
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote
from typing import Dict, Any, List, Optional

import httpx
from playwright.async_api import async_playwright

from .base_extractor import (
    BaseExtractor, logger,
    ExtractorError, TemporaryError, PermanentError,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError
)

class InstagramExtractor(BaseExtractor):
    def __init__(self, output_dir=".", headless: bool = True, debug_wait_seconds: float = 0.0, browser: str = "firefox", max_retries: int = 3):
        # Initialize base extractor
        super().__init__(max_retries=max_retries)
        
        # Instagram-specific settings
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        self.headless = headless
        self.debug_wait_ms = int(max(0.0, debug_wait_seconds) * 1000)
        self.browser_engine = (browser or "firefox").strip().lower()
        if self.browser_engine not in {"chromium", "firefox", "webkit"}:
            self.browser_engine = "firefox"
        
        self.headers = {
            'User-Agent': self.ua.random,
            'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
        }
    
    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Check if the URL is a valid Instagram URL."""
        instagram_patterns = [
            r'https?://(?:www\.)?instagram\.com/p/[A-Za-z0-9_-]+/?',
            r'https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?',
        ]
        return any(re.match(pattern, url) for pattern in instagram_patterns)
    
    def extract_post_id(self, url):
        """Extract post ID from Instagram URL."""
        # Match patterns like /p/POST_ID/ or /reel/POST_ID/
        match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)/', url)
        return match.group(1) if match else None
    
    
    def download_image(self, image_url, filename):
        """Download an image from URL with retry logic."""
        return self.retry_with_backoff_sync(self._download_image_impl, image_url, filename)
    
    def _download_image_impl(self, image_url, filename):
        """Implementation of image downloading (without retry logic)."""
        try:
            # Use fresh user agent for each request
            headers = self.get_fresh_headers(self.headers)
            
            with httpx.stream('GET', image_url, headers=headers, timeout=30) as response:
                response.raise_for_status()
                
                filepath = self.output_dir / filename
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
            
            return filepath
            
        except Exception as e:
            logger.error(f"Error downloading image {image_url}: {e}")
            # Re-raise to be handled by retry mechanism
            raise
    
    async def _extract_with_saveclip_impl(self, instagram_url):
        """Implementation of SaveClip extraction (without retry logic)."""
        async with async_playwright() as p:
            browser = None
            try:
                # Launch selected browser engine (default: Firefox for lightweight resource usage)
                launch_kwargs = {"headless": self.headless}
                if not self.headless:
                    # Make interactions a bit slower for visibility in debug
                    launch_kwargs["slow_mo"] = 150
                engine = getattr(p, self.browser_engine, p.firefox)
                browser = await engine.launch(**launch_kwargs)
                context = await browser.new_context(
                    user_agent=self.ua.random,
                    viewport={'width': 1024, 'height': 720},
                    locale='en-US',
                    timezone_id='UTC'
                )
                # Light stealth: remove webdriver flag to reduce bot detection
                await context.add_init_script(
                    """
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    """
                )
                page = await context.new_page()
                
                print("Navigating to SaveClip.app...")
                # Single fast load with 'domcontentloaded' to avoid long waits
                try:
                    await page.goto("https://saveclip.app/en", wait_until="domcontentloaded", timeout=8000)
                except Exception as e:
                    # Check if it's a network error
                    if any(keyword in str(e).lower() for keyword in ['net::', 'timeout', 'connection']):
                        raise NetworkError(f"Failed to connect to SaveClip.app: {e}")
                    raise ServiceUnavailableError(f"SaveClip.app is unavailable: {e}")
                
                # Handle potential cookie/consent banners and ads (best-effort)
                try:
                    # First try consent banners
                    consent_selectors = [
                        'button:has-text("Accept")',
                        'button:has-text("I Agree")',
                        'button:has-text("Allow all")',
                        '#ez-accept-all',
                        '.fc-cta-consent .fc-button:has-text("Agree")'
                    ]
                    for sel in consent_selectors:
                        if await page.is_visible(sel):
                            print("Dismissing cookie/consent banner...")
                            await page.click(sel)
                            await page.wait_for_timeout(500)
                            break
                    
                    # Then try ad dismissal buttons
                    ad_close_selectors = [
                        '#dismiss-button',
                        '#ad_position_box #dismiss-button',
                        '[aria-label="Close ad"]',
                        '.abgc',
                        '#abgc'
                    ]
                    for sel in ad_close_selectors:
                        if await page.is_visible(sel):
                            print("Dismissing advertisement overlay...")
                            await page.click(sel)
                            await page.wait_for_timeout(1000)
                            break
                except Exception:
                    pass

                # Optional: block heavy resources to speed up processing
                try:
                    async def _route_intercept(route):
                        req = route.request
                        if req.resource_type in {"image", "media", "font"}:
                            return await route.abort()
                        return await route.continue_()
                    await context.route("**/*", _route_intercept)
                except Exception:
                    pass

                # Find and fill the input field
                print("Entering Instagram URL...")
                input_selector = 'input[name="q"], input#s_input'
                await page.wait_for_selector(input_selector, timeout=10000)
                await page.fill(input_selector, instagram_url)
                
                # Click the download button with enhanced reliability
                print("Clicking download button...")
                download_btn_selectors = [
                    'button:has-text("Download")',
                    '.btn:has-text("Download")',
                    'input[type="submit"][value*="Download"]',
                    'a:has-text("Download")',
                    '#download-btn',
                    '.download-button'
                ]
                
                download_btn_clicked = False
                for btn_sel in download_btn_selectors:
                    try:
                        if await page.is_visible(btn_sel):
                            await page.click(btn_sel)
                            download_btn_selector = btn_sel  # Store for later re-clicks
                            download_btn_clicked = True
                            print(f"Successfully clicked download button: {btn_sel}")
                            break
                    except Exception as e:
                        print(f"Failed to click {btn_sel}: {e}")
                        continue
                
                if not download_btn_clicked:
                    raise Exception("Could not find or click any download button")
                
                # Wait for processing and handle modal if it appears
                print("Waiting for processing...")
                await page.wait_for_timeout(500)  # quick settle
                
                # Check for and close modal dialog
                try:
                    modal_close_selector = '#closeModalBtn, .modal .btn:has-text("Close")'
                    if await page.is_visible(modal_close_selector):
                        print("Closing modal dialog...")
                        await page.click(modal_close_selector)
                        await page.wait_for_timeout(2000)
                except:
                    pass  # Modal might not appear
                
                # If SaveClip shows the loader, wait until it disappears
                try:
                    loader_selector = '#loader-wrapper'
                    loader_visible = await page.is_visible(loader_selector)
                    # Also check computed style in case visibility API is misleading
                    loader_display = None
                    try:
                        loader_display = await page.eval_on_selector(loader_selector, 'el => getComputedStyle(el).display')
                    except Exception:
                        pass
                    if loader_visible or loader_display == 'block':
                        print("Loader detected. Waiting for processing to complete...")
                        # Wait for it to become hidden or removed
                        try:
                            await page.wait_for_selector(loader_selector, state='hidden', timeout=15000)
                        except Exception:
                            # Fallback to a short grace period if it didn't hide in time
                            await page.wait_for_timeout(2000)
                except Exception:
                    pass
                
                # Directly wait for the exact "Download Image" anchors as specified
                target_selector = (
                    'div.download-items__btn > '
                    'a[id^="photo_dl_"][href*="dl.snapcdn.app/saveinsta"][title^="Download Photo"]:has-text("Download Image")'
                )
                
                # Also check for error states
                error_selectors = [
                    '.error',
                    '.alert-danger',
                    'div:has-text("Error")',
                    'div:has-text("Failed")',
                    'div:has-text("Invalid")',
                    'div:has-text("Not found")'
                ]
                
                # Single wait for results (no polling/re-click loops)
                matched_links = []
                try:
                    await page.wait_for_selector(target_selector, state='visible', timeout=8000)
                    matched_links = await page.query_selector_all(target_selector)
                    print(f"Found {len(matched_links)} matching 'Download Image' link(s)")
                except Exception:
                    # Enhanced diagnostics for debugging
                    print("\n=== DIAGNOSTIC INFO ===")
                    try:
                        # Take screenshot for debugging if in debug mode
                        if not self.headless:
                            screenshot_path = os.path.join(self.output_dir, f"debug_screenshot_{int(time.time())}.png")
                            await page.screenshot(path=screenshot_path)
                            print(f"Debug screenshot saved: {screenshot_path}")
                        
                        # Get page title and URL for context
                        page_title = await page.title()
                        page_url = page.url
                        print(f"Page title: {page_title}")
                        print(f"Page URL: {page_url}")
                        
                        # Check if we're still on SaveClip or got redirected
                        if "saveclip" not in page_url.lower():
                            print(f"WARNING: Page redirected away from SaveClip to: {page_url}")
                        
                        # Look for any text that might indicate what happened
                        body_text = await page.evaluate("document.body.innerText")
                        if "rate limit" in body_text.lower():
                            print("DETECTED: Rate limiting may be in effect")
                        elif "blocked" in body_text.lower():
                            print("DETECTED: Request may be blocked")
                        elif "private" in body_text.lower():
                            print("DETECTED: Instagram post may be private")
                        elif "not found" in body_text.lower():
                            print("DETECTED: Instagram post may not exist")
                        
                    except Exception as diag_error:
                        print(f"Diagnostic collection failed: {diag_error}")
                    
                    print("=== END DIAGNOSTIC INFO ===\n")
                    
                    # Classify the error based on diagnostic info
                    if "rate limit" in body_text.lower():
                        raise RateLimitError("SaveClip.app rate limit detected")
                    elif "blocked" in body_text.lower():
                        raise RateLimitError("Request blocked by SaveClip.app")
                    elif "private" in body_text.lower() or "not found" in body_text.lower():
                        raise InvalidUrlError("Instagram post is private or not found")
                    else:
                        raise ServiceUnavailableError("No matching 'Download Image' links found on SaveClip page")
                
                print(f"Found {len(matched_links)} items to process...")
                
                image_downloads = []
                for i, link in enumerate(matched_links, 1):
                    try:
                        download_url = await link.get_attribute('href')
                        if not download_url:
                            print(f"Item {i}: No download URL found")
                            continue
                        
                        print(f"Item {i}: Found image download URL")
                        
                        # Try to extract filename from the URL or use default
                        try:
                            if 'filename' in download_url:
                                filename_match = re.search(r'filename["\']?:\s*["\']([^"\']+)["\']', download_url)
                                if filename_match:
                                    original_filename = unquote(filename_match.group(1))
                                else:
                                    original_filename = f"instagram_image_{i}.jpg"
                            else:
                                original_filename = f"instagram_image_{i}.jpg"
                            
                            # Sanitize filename
                            safe_filename = self.sanitize_filename(original_filename)
                            
                            # Add timestamp to avoid conflicts
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            name, ext = os.path.splitext(safe_filename)
                            final_filename = f"{name}_{timestamp}{ext}"
                            

                        except:
                            # Fallback filename
                            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                            final_filename = f"instagram_image_{i}_{timestamp}.jpg"
                        
                        image_downloads.append((download_url, final_filename))
                    except Exception as e:
                        print(f"Error processing item {i}: {e}")
                        continue
                
                # Close immediately on success (no extra debug wait)
                await browser.close()
                
                if not image_downloads:
                    raise Exception("No images found to download")
                
                # Download all images
                print(f"\nDownloading {len(image_downloads)} image(s)...")
                downloaded_files = []
                
                for i, (download_url, filename) in enumerate(image_downloads, 1):
                    print(f"Downloading image {i}/{len(image_downloads)}: {filename}")
                    try:
                        filepath = self.download_image(download_url, filename)
                        if filepath:
                            downloaded_files.append(filepath)
                            print(f"✓ Downloaded: {filepath}")
                        else:
                            print(f"✗ Failed to download image {i}")
                    except Exception as e:
                        logger.error(f"Failed to download image {i}: {e}")
                        print(f"✗ Failed to download image {i}: {e}")
                
                return downloaded_files
                
            except Exception as e:
                logger.error(f"Error during SaveClip extraction: {e}")
                if browser:
                    if not self.headless and self.debug_wait_ms > 0:
                        try:
                            # Optional wait after error (silent)
                            await page.wait_for_timeout(self.debug_wait_ms)
                        except Exception:
                            pass
                    await browser.close()
                # Re-raise the exception to be handled by retry mechanism
                raise
    
    async def extract_with_saveclip(self, instagram_url):
        """Extract images using SaveClip.app service with retry logic."""
        return await self.retry_with_backoff_async(self._extract_with_saveclip_impl, instagram_url)
    
    def extract(self, url):
        """Main extraction method with comprehensive error handling."""
        post_id = self.extract_post_id(url)
        if not post_id:
            logger.error(f"Could not extract post ID from URL: {url}")
            raise InvalidUrlError(f"Invalid Instagram URL format: {url}")
        
        logger.info(f"Extracting images from Instagram post: {post_id}")
        logger.info(f"Using SaveClip.app service with retry mechanism...")
        
        try:
            # Run the async extraction with retry logic
            result_files = asyncio.run(self.extract_with_saveclip(url))
            logger.info(f"Successfully extracted {len(result_files)} image(s)")
            return result_files
            
        except PermanentError as e:
            logger.error(f"Permanent error - not retrying: {e}")
            return []
        except (RateLimitError, ServiceUnavailableError, NetworkError) as e:
            logger.error(f"Temporary error - all retries exhausted: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error during extraction: {e}")
            return []
    
    def extract_json_metadata(self, url: str) -> Dict[str, Any]:
        """Extract JSON metadata by analyzing SaveClip.app download buttons."""
        return asyncio.run(self._extract_json_metadata_async(url))
    
    async def _extract_json_metadata_async(self, url: str) -> Dict[str, Any]:
        """Async implementation of JSON metadata extraction."""
        from datetime import datetime
        
        if not self.is_valid_url(url):
            raise InvalidUrlError(f"Invalid Instagram URL format: {url}")
        
        post_id = self.extract_post_id(url)
        
        try:
            async with async_playwright() as p:
                # Browser setup (same as existing code)
                engine = getattr(p, self.browser_engine)
                launch_kwargs = {"headless": self.headless}
                
                browser = await engine.launch(**launch_kwargs)
                context = await browser.new_context(
                    user_agent=self.ua.random,
                    viewport={'width': 1024, 'height': 720},
                    locale='en-US',
                    timezone_id='UTC'
                )
                
                # Light stealth
                await context.add_init_script(
                    "Object.defineProperty(navigator, 'webdriver', { get: () => undefined });"
                )
                page = await context.new_page()
                
                try:
                    # Navigate to SaveClip.app (silent for JSON mode)
                    await page.goto("https://saveclip.app/en", wait_until="domcontentloaded", timeout=8000)
                    
                    # Handle consent banners (same as existing code)
                    consent_selectors = [
                        'button:has-text("Accept")',
                        'button:has-text("I Agree")',
                        'button:has-text("Allow all")',
                        '#ez-accept-all',
                        '.fc-cta-consent .fc-button:has-text("Agree")'
                    ]
                    for sel in consent_selectors:
                        try:
                            if await page.is_visible(sel, timeout=1000):
                                await page.click(sel)
                                await page.wait_for_timeout(500)
                                break
                        except:
                            continue
                    
                    # Enter Instagram URL (silent for JSON mode)
                    input_selector = 'input[name="q"], input#s_input'
                    await page.wait_for_selector(input_selector, timeout=10000)
                    await page.fill(input_selector, url)
                    
                    # Click download button (silent for JSON mode)
                    download_btn_selectors = [
                        'button:has-text("Download")',
                        '.btn:has-text("Download")',
                        'input[type="submit"][value*="Download"]',
                        'a:has-text("Download")',
                        '#download-btn',
                        '.download-button'
                    ]
                    
                    clicked = False
                    for btn_sel in download_btn_selectors:
                        try:
                            if await page.is_visible(btn_sel):
                                await page.click(btn_sel)
                                clicked = True
                                break
                        except:
                            continue
                    
                    if not clicked:
                        raise ServiceUnavailableError("Could not find download button on SaveClip.app")
                    
                    # Use EXACT same logic as working extractor (silent for JSON mode)
                    await page.wait_for_timeout(500)
                    
                    # Check for and close modal dialog (same as working extractor)
                    try:
                        modal_close_selector = '#closeModalBtn, .modal .btn:has-text("Close")'
                        if await page.is_visible(modal_close_selector):
                            await page.click(modal_close_selector)
                            await page.wait_for_timeout(2000)
                    except:
                        pass
                    
                    # Wait for loader to disappear (same as working extractor)
                    try:
                        loader_selector = '#loader-wrapper'
                        loader_visible = await page.is_visible(loader_selector)
                        loader_display = None
                        try:
                            loader_display = await page.eval_on_selector(loader_selector, 'el => getComputedStyle(el).display')
                        except Exception:
                            pass
                        if loader_visible or loader_display == 'block':
                            # Wait silently for processing in JSON mode
                            try:
                                await page.wait_for_selector(loader_selector, state='hidden', timeout=15000)
                            except Exception:
                                await page.wait_for_timeout(2000)
                    except Exception:
                        pass
                    
                    # Use EXACT same selector as working extractor
                    target_selector = (
                        'div.download-items__btn > '
                        'a[id^="photo_dl_"][href*="dl.snapcdn.app/saveinsta"][title^="Download Photo"]:has-text("Download Image")'
                    )
                    
                    # Analyze the results using working extractor logic
                    content_analysis = await self._analyze_saveclip_results(page, target_selector, url, post_id)
                    return content_analysis
                    
                finally:
                    await browser.close()
                    
        except Exception as e:
            logger.error(f"Error in Instagram JSON metadata extraction: {e}")
            return {
                "platform": "instagram",
                "url": url,
                "post_id": post_id,
                "extraction_method": "saveclip_button_analysis",
                "extraction_timestamp": datetime.now().isoformat(),
                "error": str(e),
                "content_type": "unknown",
                "counts": {
                    "total_items": 0,
                    "images": 0,
                    "videos": 0
                },
                "images": []
            }
    
    async def _analyze_download_buttons(self, page) -> List[Dict[str, Any]]:
        """Extract information about all download buttons on the page."""
        buttons = []
        
        # First try to analyze the page structure to detect content type
        page_content = await page.content()
        
        # Alternative approach: Look for result containers or media indicators
        media_containers = await page.query_selector_all('.result, .download-result, .media-item, [data-media]')
        
        # Count actual media elements in the page content
        if media_containers:
            for i, container in enumerate(media_containers):
                try:
                    container_text = await container.inner_text()
                    # Look for specific download buttons within containers
                    download_links = await container.query_selector_all('a[href], button')
                    
                    for link in download_links:
                        href = await link.get_attribute('href') or ''
                        text = await link.inner_text()
                        
                        if self._is_actual_content_button(text, href):
                            button_info = {
                                'text': text.strip(),
                                'href': href,
                                'type': self._determine_button_type(text, href),
                                'index': i + 1  # Use container index
                            }
                            buttons.append(button_info)
                except Exception:
                    continue
        
        # Fallback: Look for direct download buttons with file extensions
        if not buttons:
            button_selectors = [
                'a[href*=".jpg"]',
                'a[href*=".jpeg"]', 
                'a[href*=".png"]',
                'a[href*=".mp4"]',
                'a[href*=".webp"]',
                'a[href*=".gif"]',
                'a[download]',  # HTML5 download attribute
                'button[onclick*="download"]'
            ]
        
        for selector in button_selectors:
            try:
                elements = await page.query_selector_all(selector)
                for element in elements:
                    try:
                        # Extract button text and URL
                        text = await element.inner_text()
                        href = await element.get_attribute('href') or ''
                        
                        if not text.strip() and not href:
                            continue
                            
                        # Skip generic service buttons (not actual content)
                        if self._is_generic_service_button(text):
                            continue
                        
                        # Parse button information
                        button_info = {
                            'text': text.strip(),
                            'href': href,
                            'type': self._determine_button_type(text, href),
                            'index': self._extract_index_from_text(text)
                        }
                        
                        # Only add actual content buttons, avoid duplicates
                        if (button_info['type'] in ['image', 'video'] and 
                            button_info not in buttons):
                            buttons.append(button_info)
                            
                    except Exception as e:
                        continue
                        
            except Exception as e:
                continue
        
        return buttons
    
    async def _analyze_saveclip_results(self, page, target_selector: str, url: str, post_id: str) -> Dict[str, Any]:
        """Analyze SaveClip results using exact same logic as working extractor."""
        from datetime import datetime
        
        matched_links = []
        try:
            # Use exact same wait and selector logic as working extractor
            await page.wait_for_selector(target_selector, state='visible', timeout=8000)
            matched_links = await page.query_selector_all(target_selector)
            
        except Exception:
            # Silent error handling for JSON mode - no diagnostic prints
            try:
                body_text = await page.evaluate("document.body.innerText")
                # Store error info for potential JSON output but don't print
            except Exception:
                pass
        
        # Analyze results exactly like working extractor
        if matched_links:
            # --- IMAGE CONTENT FOUND ---
            image_count = len(matched_links)
            
            # Extract actual download URLs and metadata
            available_downloads = []
            for i, link in enumerate(matched_links):
                try:
                    href = await link.get_attribute('href')
                    title = await link.get_attribute('title') or ''
                    text = await link.inner_text()
                    
                    available_downloads.append({
                        'type': 'image',
                        'index': i + 1,
                        'filename': f"{post_id}_{i + 1}.jpg" if image_count > 1 else f"{post_id}.jpg",
                        'button_text': text.strip(),
                        'download_url': href,
                        'title': title
                    })
                except Exception as e:
                    logger.warning(f"Could not extract link {i}: {e}")
                    continue
            
            # Determine content type based on actual results
            if image_count == 1:
                content_type = 'image'
            else:
                content_type = 'carousel_images_only'  # SaveClip shows image links for image carousels
            
            return {
                'platform': 'instagram',
                'url': url,
                'post_id': post_id,
                'content_type': content_type,
                'extraction_method': 'saveclip_image_extractor',
                'extraction_timestamp': datetime.now().isoformat(),
                'counts': {
                    'total_items': image_count,
                    'images': image_count,
                    'videos': 0  # SaveClip image selector only finds images
                },
                'carousel_info': {
                    'is_carousel': image_count > 1,
                    'carousel_length': image_count if image_count > 1 else None,
                    'has_mixed_media': False  # Image-only results
                },
                'available_downloads': available_downloads,
                'saveclip_analysis': True
            }
        
        else:
            # --- NO IMAGES FOUND, CHECK FOR VIDEO ---
            video_selector = 'a[title^="Download Video"]:has-text("Download Video")'
            video_links = []
            try:
                video_links = await page.query_selector_all(video_selector)
            except Exception:
                pass

            if video_links:
                # Video content detected
                video_count = len(video_links)
                return {
                    'platform': 'instagram',
                    'url': url,
                    'post_id': post_id,
                    'content_type': 'video',
                    'extraction_method': 'saveclip_video_detected',
                    'extraction_timestamp': datetime.now().isoformat(),
                    'counts': {
                        'total_items': video_count,
                        'images': 0,
                        'videos': video_count
                    },
                    'carousel_info': {
                        'is_carousel': False,
                        'carousel_length': None,
                        'has_mixed_media': False
                    },
                    'available_downloads': [],
                    'saveclip_analysis': True,
                    'note': 'Video content detected. This tool is for image downloads only.'
                }
            else:
                # --- NEITHER IMAGES NOR VIDEO FOUND ---
                return {
                    'platform': 'instagram',
                    'url': url,
                    'post_id': post_id,
                    'content_type': 'unknown',
                    'extraction_method': 'saveclip_no_results_found',
                    'extraction_timestamp': datetime.now().isoformat(),
                    'counts': {
                        'total_items': 0,
                        'images': 0,
                        'videos': 0
                    },
                    'carousel_info': {
                        'is_carousel': False,
                        'carousel_length': None,
                        'has_mixed_media': False
                    },
                    'available_downloads': [],
                    'saveclip_analysis': True,
                    'note': 'No image or video download links found with specific selectors'
                }
    
    async def _analyze_page_content_fallback(self, page, url: str, post_id: str) -> Dict[str, Any]:
        """Fallback method to analyze content when no specific buttons are found."""
        from datetime import datetime
        
        try:
            # Get page content and analyze for clues
            page_content = await page.content()
            
            # Check URL pattern first
            is_reel = '/reel/' in url
            is_igtv = '/tv/' in url
            
            # Look for text indicators on the page
            has_carousel_indicators = any(indicator in page_content.lower() for indicator in [
                'carousel', 'multiple', 'items', 'slides', 'gallery'
            ])
            
            has_video_indicators = any(indicator in page_content.lower() for indicator in [
                'video', 'mp4', 'play', 'reel', 'igtv'
            ])
            
            has_image_indicators = any(indicator in page_content.lower() for indicator in [
                'image', 'photo', 'jpg', 'jpeg', 'png'
            ])
            
            # Make educated guess based on URL and page content
            if is_reel or is_igtv:
                content_type = 'video'
                image_count, video_count = 0, 1
            elif has_carousel_indicators:
                # Default to mixed carousel if we can't determine exact composition
                content_type = 'carousel_mixed'
                image_count, video_count = 1, 1  # Conservative estimate
            elif has_video_indicators and not has_image_indicators:
                content_type = 'video'
                image_count, video_count = 0, 1
            else:
                # Default to single image (most common case)
                content_type = 'image'
                image_count, video_count = 1, 0
            
            return {
                'platform': 'instagram',
                'url': url,
                'post_id': post_id,
                'content_type': content_type,
                'extraction_method': 'saveclip_page_analysis_fallback',
                'extraction_timestamp': datetime.now().isoformat(),
                'counts': {
                    'total_items': image_count + video_count,
                    'images': image_count,
                    'videos': video_count
                },
                'carousel_info': {
                    'is_carousel': content_type.startswith('carousel'),
                    'carousel_length': image_count + video_count if content_type.startswith('carousel') else None,
                    'has_mixed_media': content_type == 'carousel_mixed'
                },
                'available_downloads': [{
                    'type': content_type if content_type in ['image', 'video'] else 'mixed',
                    'index': 1,
                    'filename': f"{post_id}.{'mp4' if content_type == 'video' else 'jpg'}",
                    'button_text': 'Detected via page analysis',
                    'download_url': None
                }],
                'saveclip_analysis': True,
                'note': 'Content analysis based on page content, not specific download buttons'
            }
            
        except Exception as e:
            logger.error(f"Error in fallback page analysis: {e}")
            # Return minimal info if fallback fails
            return {
                'platform': 'instagram',
                'url': url,
                'post_id': post_id,
                'content_type': 'unknown',
                'extraction_method': 'saveclip_fallback_failed',
                'extraction_timestamp': datetime.now().isoformat(),
                'error': str(e),
                'counts': {'total_items': 0, 'images': 0, 'videos': 0},
                'carousel_info': {'is_carousel': False, 'carousel_length': None, 'has_mixed_media': False},
                'available_downloads': []
            }
    
    def _is_generic_service_button(self, text: str) -> bool:
        """Check if button text represents a generic service category, not actual content."""
        text_lower = text.lower()
        
        # These are SaveClip.app service categories, not actual content buttons
        generic_patterns = [
            'instagram video downloader',
            'instagram photo downloader', 
            'reels downloader',
            'igtv video downloader',
            'how to download',
            'instagram download',
            'photo downloader',
            'video downloader',
            'downloader for instagram',
            'instagram story downloader'
        ]
        
        # If text matches generic service patterns, it's not actual content
        for pattern in generic_patterns:
            if pattern in text_lower:
                return True
                
        # Also filter out buttons without specific numbering (not carousel items)
        # Real carousel buttons usually have numbers: "Download Image 1", "Download Video 2"
        if ('download' in text_lower and 
            ('image' in text_lower or 'video' in text_lower or 'photo' in text_lower) and
            not any(char.isdigit() for char in text)):
            return True
            
        return False
    
    def _is_actual_content_button(self, text: str, href: str) -> bool:
        """Check if this is an actual content download button, not a service category."""
        text_lower = text.lower()
        href_lower = href.lower()
        
        # Look for specific download indicators
        if any(ext in href_lower for ext in ['.jpg', '.jpeg', '.png', '.mp4', '.webp', '.gif']):
            return True
            
        # Look for numbered buttons (carousel items)
        if any(char.isdigit() for char in text) and 'download' in text_lower:
            return True
            
        # Look for specific download action words with content type
        if (any(action in text_lower for action in ['download', 'get', 'save']) and
            any(content in text_lower for content in ['image', 'video', 'photo']) and
            not self._is_generic_service_button(text)):
            return True
            
        return False
    
    def _determine_button_type(self, button_text: str, href: str = '') -> str:
        """Determine if button is for image or video based on text and href."""
        text = button_text.lower()
        href = href.lower()
        
        # Check text content
        if any(keyword in text for keyword in ['image', 'photo', 'pic', 'jpg', 'jpeg', 'png', 'webp']):
            return 'image'
        elif any(keyword in text for keyword in ['video', 'mp4', 'reel', 'mov']):
            return 'video'
        
        # Check href URL
        if any(ext in href for ext in ['.jpg', '.jpeg', '.png', '.webp', '.gif']):
            return 'image'
        elif any(ext in href for ext in ['.mp4', '.mov', '.avi', '.mkv']):
            return 'video'
        
        # Default to unknown if can't determine
        return 'unknown'
    
    def _extract_index_from_text(self, button_text: str) -> Optional[int]:
        """Extract carousel index from button text like 'Download Image 2'."""
        import re
        match = re.search(r'(\d+)', button_text)
        return int(match.group(1)) if match else None
    
    def _classify_instagram_content(self, buttons: List[Dict[str, Any]], url: str, post_id: str) -> Dict[str, Any]:
        """Classify Instagram content based on download button analysis."""
        from datetime import datetime
        
        # Count different button types
        image_buttons = [b for b in buttons if b['type'] == 'image']
        video_buttons = [b for b in buttons if b['type'] == 'video']
        
        image_count = len(image_buttons)
        video_count = len(video_buttons)
        total_count = image_count + video_count
        
        # Determine content type
        if total_count == 0:
            content_type = 'unknown'
        elif total_count == 1:
            content_type = 'image' if image_count == 1 else 'video'
        else:  # Carousel
            if video_count == 0:
                content_type = 'carousel_images_only'
            elif image_count == 0:
                content_type = 'carousel_videos_only'
            else:
                content_type = 'carousel_mixed'
        
        # Build comprehensive JSON response
        return {
            'platform': 'instagram',
            'url': url,
            'post_id': post_id,
            'content_type': content_type,
            'extraction_method': 'saveclip_button_analysis',
            'extraction_timestamp': datetime.now().isoformat(),
            'counts': {
                'total_items': total_count,
                'images': image_count,
                'videos': video_count
            },
            'carousel_info': {
                'is_carousel': total_count > 1,
                'carousel_length': total_count if total_count > 1 else None,
                'has_mixed_media': image_count > 0 and video_count > 0
            },
            'available_downloads': [
                {
                    'type': button['type'],
                    'index': button['index'],
                    'filename': self._generate_filename_from_button(button, post_id),
                    'button_text': button['text'],
                    'download_url': button['href'] if button['href'] else None
                }
                for button in buttons if button['type'] in ['image', 'video']
            ],
            'saveclip_analysis': True
        }
    
    def _generate_filename_from_button(self, button: Dict[str, Any], post_id: str) -> str:
        """Generate filename based on button information."""
        index = button.get('index')
        button_type = button.get('type', 'unknown')
        
        if button_type == 'image':
            ext = 'jpg'
        elif button_type == 'video':
            ext = 'mp4'
        else:
            ext = 'unknown'
        
        if index is not None and index > 1:
            return f"{post_id}_{index}.{ext}"
        else:
            return f"{post_id}.{ext}"
