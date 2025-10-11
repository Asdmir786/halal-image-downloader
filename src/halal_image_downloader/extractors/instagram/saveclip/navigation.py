#!/usr/bin/env python3
from __future__ import annotations

import os
import re
import time
from datetime import datetime
from urllib.parse import unquote

from playwright.async_api import async_playwright

from ...base_extractor import (
    logger,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError, PermanentError
)


class SaveClipNavigationMixin:
    async def _extract_with_saveclip_impl(self, instagram_url: str):
        """Implementation of SaveClip extraction (without retry logic)."""
        # Clear post identification logging (quiet by default)
        post_id = self.extract_post_id(instagram_url)
        post_type = "reel" if "/reel/" in instagram_url else "post"
        self._print(f"🔍 Detected Instagram {post_type}: {post_id}")

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

                self._print("Navigating to SaveClip.app...")
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
                            self._print("Dismissing cookie/consent banner...")
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
                            self._print("Dismissing advertisement overlay...")
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
                self._print("Entering Instagram URL...")
                input_selector = 'input[name="q"], input#s_input'
                await page.wait_for_selector(input_selector, timeout=10000)
                await page.fill(input_selector, instagram_url)

                # Click the download button with enhanced reliability
                self._print("Clicking download button...")
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
                            self._print(f"Successfully clicked download button: {btn_sel}")
                            break
                    except Exception as e:
                        self._print(f"Failed to click {btn_sel}: {e}")
                        continue

                if not download_btn_clicked:
                    raise Exception("Could not find or click any download button")

                # Wait for processing
                self._print("Waiting for processing...")
                await page.wait_for_timeout(500)  # quick settle

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
                        self._print("Loader detected. Waiting for processing to complete...")
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

                # Try to find results with retry logic
                matched_links = []
                retry_attempted = False

                for attempt in range(2):  # Try twice
                    try:
                        await page.wait_for_selector(target_selector, state='visible', timeout=8000)
                        matched_links = await page.query_selector_all(target_selector)
                        content_type = "carousel" if len(matched_links) > 1 else "single image"
                        self._print(f"✅ Found Instagram {content_type} - {len(matched_links)} image(s) detected")
                        break  # Success, exit retry loop
                    except Exception:
                        # Check if loader is still running
                        loader_still_running = False
                        try:
                            loader_selector = '#loader-wrapper'
                            loader_visible = await page.is_visible(loader_selector)
                            loader_display = None
                            try:
                                loader_display = await page.eval_on_selector(loader_selector, 'el => getComputedStyle(el).display')
                            except Exception:
                                pass
                            loader_still_running = loader_visible or loader_display == 'block'
                        except Exception:
                            pass

                        # If no loader AND no results AND haven't retried yet, try clicking download again
                        if not loader_still_running and not retry_attempted and attempt == 0:
                            self._print("No loader or results found. Trying to click download button again...")
                            retry_attempted = True
                            try:
                                # Try to click download button again using same selectors
                                for btn_sel in download_btn_selectors:
                                    try:
                                        if await page.is_visible(btn_sel):
                                            await page.click(btn_sel)
                                            self._print(f"Re-clicked download button: {btn_sel}")
                                            await page.wait_for_timeout(3000)  # Wait longer after re-click
                                            break
                                    except Exception as e:
                                        continue
                            except Exception:
                                pass
                        else:
                            break  # No retry or already retried, exit loop

                # Check for videos in the carousel (even if we have images)
                video_selector = (
                    'div.download-items__btn > '
                    'a[title^="Download Video"]:has-text("Download Video")'
                )
                video_links = []
                try:
                    video_links = await page.query_selector_all(video_selector)
                except Exception:
                    video_links = []
                
                # Notify user if videos were detected and skipped
                if video_links:
                    video_count = len(video_links)
                    if matched_links:
                        # Mixed content: we have both images and videos
                        self._print(f"⏭️  Skipped {video_count} video(s) (images only)")
                    else:
                        # Video-only post: fail with clear error
                        raise PermanentError("Instagram post contains video content only. This tool downloads images only.")
                
                if not matched_links:

                    if self.quiet:
                        # In quiet mode, skip diagnostics and raise a concise error
                        raise ServiceUnavailableError("No matching 'Download Image' links found on SaveClip page")
                    else:
                        # Enhanced diagnostics for debugging
                        self._print("\n=== DIAGNOSTIC INFO ===")
                        body_text = ""
                        try:
                            # Take screenshot for debugging if debug active or debug-wait is set
                            if (not self.headless) or (self.debug_wait_ms > 0):
                                screenshot_path = os.path.join(self.output_dir, f"debug_screenshot_{int(time.time())}.png")
                                await page.screenshot(path=screenshot_path)
                                self._print(f"Debug screenshot saved: {screenshot_path}")

                            # Get page title and URL for context
                            page_title = await page.title()
                            page_url = page.url
                            self._print(f"Page title: {page_title}")
                            self._print(f"Page URL: {page_url}")

                            # Check if we're still on SaveClip or got redirected
                            if "saveclip" not in page_url.lower():
                                self._print(f"WARNING: Page redirected away from SaveClip to: {page_url}")

                            # Look for any text that might indicate what happened
                            try:
                                body_text = await page.evaluate("document.body.innerText")
                            except Exception:
                                body_text = ""
                            if "rate limit" in body_text.lower():
                                self._print("DETECTED: Rate limiting may be in effect")
                            elif "blocked" in body_text.lower():
                                self._print("DETECTED: Request may be blocked")
                            elif "private" in body_text.lower():
                                self._print("DETECTED: Instagram post may be private")
                            elif "not found" in body_text.lower():
                                self._print("DETECTED: Instagram post may not exist")

                        except Exception as diag_error:
                            self._print(f"Diagnostic collection failed: {diag_error}")

                        self._print("=== END DIAGNOSTIC INFO ===\n")

                        # Classify the error based on diagnostic info
                        if "rate limit" in body_text.lower():
                            raise RateLimitError("SaveClip.app rate limit detected")
                        elif "blocked" in body_text.lower():
                            raise RateLimitError("Request blocked by SaveClip.app")
                        elif "private" in body_text.lower() or "not found" in body_text.lower():
                            raise InvalidUrlError("Instagram post is private or not found")
                        else:
                            raise ServiceUnavailableError("No matching 'Download Image' links found on SaveClip page")

                self._print(f"📋 Processing {len(matched_links)} image(s) for download...")

                image_downloads = []
                for i, link in enumerate(matched_links, 1):
                    try:
                        download_url = await link.get_attribute('href')
                        if not download_url:
                            self._print(f"❌ Image {i}/{len(matched_links)}: No download URL found")
                            continue

                        self._print(f"🔗 Image {i}/{len(matched_links)}: Download URL extracted")

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

                # Download all images concurrently for maximum speed
                self._print(f"\n⬇️  Starting download of {len(image_downloads)} image(s)...")
                downloaded_files = await self._download_images_concurrent(image_downloads)

                self._print(f"🎉 Successfully extracted {len(downloaded_files)} image(s) from Instagram {post_type}: {post_id}")
                return downloaded_files

            except Exception as e:
                logger.error(f"Error during SaveClip extraction: {e}")
                if browser:
                    if self.debug_wait_ms > 0:
                        try:
                            # Optional wait after error (silent)
                            await page.wait_for_timeout(self.debug_wait_ms)
                        except Exception:
                            pass
                    await browser.close()
                # Re-raise the exception to be handled by retry mechanism
                raise

    async def extract_with_saveclip(self, instagram_url: str):
        """Extract images using SaveClip.app service with strict error handling."""
        return await self.execute_with_error_handling(self._extract_with_saveclip_impl, instagram_url)

    async def extract_with_browser(self, instagram_url: str, browser_context):
        """Extract images using SaveClip.app with existing browser (browser reuse optimization)."""
        try:
            # Create new page in existing browser context
            page = await browser_context.new_page()

            # Use existing SaveClip logic but with reused browser
            return await self._extract_with_saveclip_impl_with_page(instagram_url, page)

        finally:
            # Close browser at the end
            try:
                await browser_context.close()
            except:
                pass

    async def _extract_with_saveclip_impl_with_page(self, instagram_url: str, page):
        """SaveClip extraction using existing page (for browser reuse)."""
        try:
            print("Navigating to SaveClip.app...")
            await page.goto("https://saveclip.app/en", wait_until="domcontentloaded", timeout=20000)

            # Rest of SaveClip logic using the provided page
            # Check for and dismiss cookie consent banner
            try:
                cookie_banner_selector = 'button:has-text("Accept"), button:has-text("OK"), button:has-text("Allow"), button:has-text("Agree")'
                if await page.is_visible(cookie_banner_selector):
                    await page.click(cookie_banner_selector)
                    await page.wait_for_timeout(1000)
            except Exception:
                pass

            print("Entering Instagram URL...")
            url_input_selector = 'input[type="text"], input[type="url"], textarea'
            await page.fill(url_input_selector, instagram_url)

            print("Clicking download button...")
            download_btn_selectors = [
                'button:has-text("Download")',
                'input[type="submit"]',
                'button[type="submit"]',
                '.download-btn',
                '.btn-download'
            ]

            download_btn_clicked = False
            for btn_sel in download_btn_selectors:
                try:
                    if await page.is_visible(btn_sel):
                        await page.click(btn_sel)
                        download_btn_clicked = True
                        print(f"Successfully clicked download button: {btn_sel}")
                        break
                except Exception as e:
                    print(f"Failed to click {btn_sel}: {e}")
                    continue

            if not download_btn_clicked:
                raise Exception("Could not find or click any download button")

            # Wait for processing
            print("Waiting for processing...")
            await page.wait_for_timeout(500)

            # Wait for loader to disappear
            try:
                loader_selector = '#loader-wrapper'
                loader_visible = await page.is_visible(loader_selector)
                loader_display = None
                try:
                    loader_display = await page.eval_on_selector(loader_selector, 'el => getComputedStyle(el).display')
                except Exception:
                    pass
                if loader_visible or loader_display == 'block':
                    print("Loader detected. Waiting for processing to complete...")
                    try:
                        await page.wait_for_selector(loader_selector, state='hidden', timeout=15000)
                    except Exception:
                        await page.wait_for_timeout(2000)
            except Exception:
                pass

            # Try to find results with retry logic (same as main method)
            target_selector = (
                'div.download-items__btn > '
                'a[id^="photo_dl_"][href*="dl.snapcdn.app/saveinsta"][title^="Download Photo"]:has-text("Download Image")'
            )

            matched_links = []
            retry_attempted = False

            for attempt in range(2):
                try:
                    await page.wait_for_selector(target_selector, state='visible', timeout=8000)
                    matched_links = await page.query_selector_all(target_selector)
                    print(f"Found {len(matched_links)} matching 'Download Image' link(s)")
                    break
                except Exception:
                    loader_still_running = False
                    try:
                        loader_visible = await page.is_visible(loader_selector)
                        loader_display = None
                        try:
                            loader_display = await page.eval_on_selector(loader_selector, 'el => getComputedStyle(el).display')
                        except Exception:
                            pass
                        loader_still_running = loader_visible or loader_display == 'block'
                    except Exception:
                        pass

                    if not loader_still_running and not retry_attempted and attempt == 0:
                        print("No loader or results found. Trying to click download button again...")
                        retry_attempted = True
                        try:
                            for btn_sel in download_btn_selectors:
                                try:
                                    if await page.is_visible(btn_sel):
                                        await page.click(btn_sel)
                                        print(f"Re-clicked download button: {btn_sel}")
                                        await page.wait_for_timeout(3000)
                                        break
                                except Exception as e:
                                    continue
                        except Exception:
                            pass
                    else:
                        break

            if not matched_links:
                # Explicitly detect video-only posts and fail fast with a clear error
                try:
                    video_selector = (
                        'div.download-items__btn > '
                        'a[title^="Download Video"]:has-text("Download Video")'
                    )
                    video_links = []
                    try:
                        video_links = await page.query_selector_all(video_selector)
                    except Exception:
                        video_links = []
                    if video_links:
                        raise PermanentError("Instagram post contains video content only. This tool downloads images only.")
                except PermanentError:
                    raise
                except Exception:
                    pass

                raise Exception("Instagram post is private or not found")

            # Extract download URLs and download images concurrently
            image_downloads = []
            for i, link in enumerate(matched_links, 1):
                try:
                    download_url = await link.get_attribute('href')
                    if download_url:
                        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                        filename = f"instagram_image_{i}_{timestamp}.jpg"
                        image_downloads.append((download_url, filename))
                except Exception as e:
                    print(f"Error processing item {i}: {e}")
                    continue

            if not image_downloads:
                raise Exception("No images found to download")

            # Download all images concurrently for maximum speed
            print(f"\nDownloading {len(image_downloads)} image(s) concurrently...")
            downloaded_files = await self._download_images_concurrent(image_downloads)

            return downloaded_files

        except Exception as e:
            logger.error(f"Error during SaveClip extraction: {e}")
            raise
