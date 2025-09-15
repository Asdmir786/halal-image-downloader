#!/usr/bin/env python3
"""
Instagram Image Extractor using SaveClip.app
Extracts images from Instagram posts using SaveClip.app service with Playwright automation.
"""

import asyncio
import os
import re
import time
from datetime import datetime
from pathlib import Path
from urllib.parse import unquote

import httpx
from fake_useragent import UserAgent
from playwright.async_api import async_playwright

class InstagramExtractor:
    def __init__(self, output_dir=".", headless: bool = True, debug_wait_seconds: float = 0.0, browser: str = "firefox"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)
        
        # Initialize fake user agent
        self.ua = UserAgent()
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
    
    def extract_post_id(self, url):
        """Extract post ID from Instagram URL."""
        # Match patterns like /p/POST_ID/ or /reel/POST_ID/
        match = re.search(r'/(?:p|reel)/([A-Za-z0-9_-]+)/', url)
        return match.group(1) if match else None
    
    def sanitize_filename(self, filename):
        """Sanitize filename for safe file system usage."""
        # Remove or replace invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove extra spaces and dots
        filename = re.sub(r'\s+', '_', filename)
        filename = filename.strip('.')
        return filename
    
    def download_image(self, image_url, filename):
        """Download an image from URL."""
        try:
            # Use fresh user agent for each request
            headers = self.headers.copy()
            headers['User-Agent'] = self.ua.random
            
            with httpx.stream('GET', image_url, headers=headers, timeout=30) as response:
                response.raise_for_status()
                
                filepath = self.output_dir / filename
                with open(filepath, 'wb') as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)
            
            return filepath
            
        except Exception as e:
            print(f"Error downloading image {image_url}: {e}")
            return None
    
    async def extract_with_saveclip(self, instagram_url):
        """Extract images using SaveClip.app service."""
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
                    raise Exception(f"Failed to load SaveClip.app: {e}")
                
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
                    raise Exception("No matching 'Download Image' links found on SaveClip page")
                
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
                    filepath = self.download_image(download_url, filename)
                    
                    if filepath:
                        downloaded_files.append(filepath)
                        print(f"✓ Downloaded: {filepath}")
                    else:
                        print(f"✗ Failed to download image {i}")
                
                return downloaded_files
                
            except Exception as e:
                print(f"Error during SaveClip extraction: {e}")
                if browser:
                    if not self.headless and self.debug_wait_ms > 0:
                        try:
                            # Optional wait after error (silent)
                            await page.wait_for_timeout(self.debug_wait_ms)
                        except Exception:
                            pass
                    await browser.close()
                return []
    
    def extract(self, url):
        """Main extraction method."""
        post_id = self.extract_post_id(url)
        if not post_id:
            print(f"Error: Could not extract post ID from URL: {url}")
            return []
        
        print(f"Extracting images from Instagram post: {post_id}")
        print(f"Using SaveClip.app service...")
        
        try:
            # Run the async extraction
            downloaded_files = asyncio.run(self.extract_with_saveclip(url))
            return downloaded_files
            
        except Exception as e:
            print(f"Error during extraction: {e}")
            return []
