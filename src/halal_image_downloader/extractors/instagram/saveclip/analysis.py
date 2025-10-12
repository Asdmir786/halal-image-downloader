#!/usr/bin/env python3
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional

from playwright.async_api import async_playwright

from ...base_extractor import (
    logger,
    RateLimitError, ServiceUnavailableError, InvalidUrlError,
)
from ....utils.browser import launch_browser_smart


class SaveClipAnalysisMixin:
    def extract_json_metadata(self, url: str) -> Dict[str, Any]:
        """Extract JSON metadata by analyzing SaveClip.app download buttons."""
        import asyncio
        return asyncio.run(self._extract_json_metadata_async(url))

    async def _extract_json_metadata_async(self, url: str) -> Dict[str, Any]:
        """Async implementation of JSON metadata extraction."""
        if not self.is_valid_url(url):
            raise InvalidUrlError(f"Invalid Instagram URL format: {url}")

        post_id = self.extract_post_id(url)

        try:
            async with async_playwright() as p:
                # Use smart browser launcher (tries Chrome -> Edge -> Chromium)
                browser = await launch_browser_smart(
                    p,
                    browser_type=self.browser_engine,
                    headless=self.headless
                )
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

                    # Handle consent banners (same as working code)
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
                        except Exception:
                            continue

                    # Enter Instagram URL (silent for JSON mode)
                    input_selector = 'input[name="q"], input#s_input'
                    await page.wait_for_selector(input_selector, timeout=10000)
                    await page.fill(input_selector, url)
                    
                    # Wait a moment for JavaScript to be ready
                    await page.wait_for_timeout(500)

                    # Click the main Download button next to the input
                    # Based on the HTML you provided: <button type="button" onclick="..." class="btn btn-default"><b>Download</b></button>
                    download_btn_selectors = [
                        'button.btn.btn-default:has-text("Download")',  # Most specific
                        'button:has-text("Download")',
                        '.input-group-btn button:has-text("Download")',
                        'button[onclick*="ksearchvideo"]',
                        '.btn:has-text("Download")',
                    ]

                    clicked = False
                    for btn_sel in download_btn_selectors:
                        try:
                            logger.info(f"Trying to click button with selector: {btn_sel}")
                            if await page.is_visible(btn_sel):
                                # Try direct click first
                                await page.click(btn_sel, timeout=2000)
                                clicked = True
                                logger.info(f"Successfully clicked Download button with selector: {btn_sel}")
                                
                                # Also try to trigger the onclick handler directly as backup
                                try:
                                    await page.evaluate('''
                                        () => {
                                            const btn = document.querySelector('button.btn.btn-default');
                                            if (btn && btn.onclick) {
                                                btn.onclick();
                                            }
                                        }
                                    ''')
                                    logger.info("Also triggered onclick handler directly")
                                except Exception:
                                    pass
                                
                                break
                            else:
                                logger.debug(f"Button not visible: {btn_sel}")
                        except Exception as e:
                            logger.debug(f"Failed to click {btn_sel}: {e}")
                            continue

                    if not clicked:
                        # Take screenshot to see what's on the page
                        try:
                            await page.screenshot(path='saveclip_no_button.png')
                            logger.error("Screenshot saved to saveclip_no_button.png")
                        except Exception:
                            pass
                        raise ServiceUnavailableError("Could not find download button on SaveClip.app")

                    # Target selector for download links in the results box
                    # Use a broad selector first to see what's available
                    target_selector = '#search-result a[href*="dl.snapcdn.app"]'
                    
                    # Actively check for buttons while waiting (up to 15 seconds)
                    # Check every 500ms for buttons to appear
                    matched_links = []
                    max_wait_ms = 15000
                    check_interval_ms = 500
                    elapsed_ms = 0
                    
                    logger.info(f"Starting active polling for Download Image buttons (max {max_wait_ms/1000}s)...")
                    
                    while elapsed_ms < max_wait_ms:
                        try:
                            # Check if buttons are visible
                            count = await page.locator(target_selector).count()
                            logger.debug(f"Check at {elapsed_ms/1000:.1f}s: found {count} buttons")
                            if count > 0:
                                # Found buttons! Get them immediately
                                matched_links = await page.query_selector_all(target_selector)
                                logger.info(f"Found {len(matched_links)} Download Image buttons after {elapsed_ms/1000:.1f}s")
                                break
                        except Exception as e:
                            logger.debug(f"Error checking buttons at {elapsed_ms/1000:.1f}s: {e}")
                            pass
                        
                        # Wait a bit before next check
                        await page.wait_for_timeout(check_interval_ms)
                        elapsed_ms += check_interval_ms
                    
                    if not matched_links:
                        logger.error(f"No Download Image buttons found after {max_wait_ms/1000}s")
                        # Take screenshot for debugging
                        try:
                            await page.screenshot(path='saveclip_timeout.png')
                            logger.info("Screenshot saved to saveclip_timeout.png")
                        except Exception:
                            pass
                    
                    # If we found links, extract them
                    if matched_links:
                        # Extract download URLs from <a> tags, filtering out videos
                        available_downloads = []
                        video_count = 0
                        
                        for i, link in enumerate(matched_links):
                            try:
                                href = await link.get_attribute('href')
                                title = await link.get_attribute('title') or ''
                                text = (await link.inner_text()).strip() if await link.inner_text() else ''
                                
                                logger.info(f"Link {i}: href={href}, title={title}, text={text}")
                                
                                # Skip video links
                                if 'video' in title.lower() or 'video' in text.lower():
                                    video_count += 1
                                    logger.info(f"Skipping video link: {title}")
                                    continue
                                
                                if href and href.startswith('http'):
                                    available_downloads.append({
                                        'type': 'image',
                                        'index': len(available_downloads) + 1,
                                        'filename': f"{post_id}_{len(available_downloads) + 1}.jpg" if len(matched_links) > 1 else f"{post_id}.jpg",
                                        'button_text': text,
                                        'download_url': href,
                                        'title': title
                                    })
                                    logger.info(f"Added image download URL: {href}")
                                else:
                                    logger.warning(f"Link {i} has invalid href: {href}")
                            except Exception as e:
                                logger.warning(f"Could not extract link {i}: {e}")
                                continue
                        
                        image_count = len(available_downloads)
                        
                        # video_count already set during filtering above
                        if video_count > 0:
                            logger.info(f"Found {video_count} video(s) in post (skipped - images only)")
                        
                        content_type = 'image' if image_count == 1 else 'carousel_images_only'
                        
                        return {
                            'platform': 'instagram',
                            'url': url,
                            'post_id': post_id,
                            'content_type': content_type,
                            'extraction_method': 'saveclip_image_extractor',
                            'extraction_timestamp': datetime.now().isoformat(),
                            'counts': {
                                'total_items': image_count + video_count,
                                'images': image_count,
                                'videos': video_count
                            },
                            'available_downloads': available_downloads,
                            'saveclip_analysis': True
                        }
                    else:
                        # No image links found - check if it's a video-only post
                        video_count = 0
                        try:
                            video_selector = '.download-items__btn a[title*="Download Video"]'
                            video_links = await page.query_selector_all(video_selector)
                            video_count = len(video_links)
                        except Exception:
                            pass
                        
                        if video_count > 0:
                            # Video-only post
                            raise ServiceUnavailableError(f"Post contains only video content ({video_count} video(s)). This tool downloads images only.")
                        else:
                            # No content found at all
                            raise ServiceUnavailableError("No Download Image buttons found after 15 seconds")

                except Exception as inner_e:
                    logger.error(f"Error during SaveClip navigation: {inner_e}")
                    raise

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
        buttons: List[Dict[str, Any]] = []

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

                        except Exception:
                            continue

                except Exception:
                    continue

        return buttons

    async def _analyze_saveclip_results(self, page, target_selector: str, url: str, post_id: str) -> Dict[str, Any]:
        """Analyze SaveClip results using exact same logic as working extractor."""
        matched_links = []
        
        # Try with retry logic (SaveClip might need more time for age-restricted content)
        for attempt in range(3):
            try:
                # Use exact same wait and selector logic as working extractor
                await page.wait_for_selector(target_selector, state='visible', timeout=8000)
                matched_links = await page.query_selector_all(target_selector)
                if matched_links:
                    break  # Success!
                # If no links found, wait a bit and retry
                if attempt < 2:
                    await page.wait_for_timeout(2000)
            except Exception as e:
                # If timeout on last attempt, check what's on the page
                if attempt == 2:
                    try:
                        # Take screenshot for debugging if in debug mode
                        if not getattr(self, 'headless', True):
                            await page.screenshot(path='saveclip_no_results.png')
                        body_text = await page.evaluate("document.body.innerText")
                        logger.warning(f"SaveClip analysis failed after 3 attempts. Page text sample: {body_text[:200]}")
                    except Exception:
                        pass
                else:
                    # Not last attempt, wait and retry
                    await page.wait_for_timeout(2000)

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
            # --- NO IMAGES FOUND, TRY GENERIC BUTTON ANALYSIS BEFORE VIDEO CHECK ---
            try:
                buttons = await self._analyze_download_buttons(page)
            except Exception:
                buttons = []

            if buttons:
                # Classify based on discovered buttons (image/video/mixed)
                return self._classify_instagram_content(buttons, url, post_id)

            # --- STILL NO IMAGES, CHECK FOR VIDEO ---
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
        match = re.search(r'(\d+)', button_text)
        return int(match.group(1)) if match else None

    def _classify_instagram_content(self, buttons: List[Dict[str, Any]], url: str, post_id: str) -> Dict[str, Any]:
        """Classify Instagram content based on download button analysis."""
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
