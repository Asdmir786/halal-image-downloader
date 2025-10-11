#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from pathlib import Path
from datetime import datetime
import re
from typing import Any, Dict, List, Optional

import httpx
from playwright.async_api import async_playwright

from .core import DirectPostMetadata
from .media import DirectMediaMixin
from .overlays import DirectOverlaysMixin
from .selectors import (
    MAIN_IMAGE_SELECTORS,
    USERNAME_SELECTORS,
    get_playwright_selector,
    get_js_selector_chain,
    get_selector_list,
)
from ...base_extractor import (
    logger,
    PermanentError, ServiceUnavailableError, InvalidUrlError, NetworkError, RateLimitError,
)


class DirectNavigateDownloadMixin(DirectMediaMixin, DirectOverlaysMixin):
    def _format_output_path(
        self,
        url: str,
        meta: DirectPostMetadata,
        index: Optional[int] = None,
        total: Optional[int] = None,
        image_url: Optional[str] = None,
    ) -> Path:
        """Render the destination file path using either the custom output template
        (if provided) or the Instagram default naming scheme.

        If a template is used and it does not include any index token, append
        "__{index}of{total}" for multi-image posts to avoid overwrites.
        """
        # Determine extension
        ext = "jpg"
        candidate_url = image_url or meta.image_url or ""
        m = re.search(r"\.([a-zA-Z0-9]{3,4})(?:[?#].*)?$", candidate_url)
        if m:
            ext = m.group(1).lower()

        # If no template provided, use the existing IG-default naming in output_dir
        if not getattr(self, 'output_template', None):
            filename = self._build_filename(meta, index=index, total=total, image_url=candidate_url)
            return (self.output_dir / filename)

        # Build value map for %(...)s
        post_id = self.extract_post_id(url) or ""
        upload_date = None
        if meta.published_on:
            try:
                dt = datetime.fromisoformat(meta.published_on.replace("Z", "+00:00"))
                upload_date = dt.strftime("%Y%m%d")
            except Exception:
                digits = re.sub(r"\D", "", meta.published_on)
                upload_date = digits[:8] if len(digits) >= 8 else digits or None

        mapping = {
            "uploader": (meta.author or "unknown"),
            "title": (meta.caption or "instagram_image"),
            "upload_date": (upload_date or "NA"),
            "id": post_id,
            "ext": ext,
            "playlist_index": str(index) if index is not None else "",
            "autonumber": str(index) if index is not None else "",
        }

        def repl(mo: re.Match) -> str:
            key = mo.group(1)
            return str(mapping.get(key, "NA"))

        rendered = re.sub(r"%\(([^)]+)\)s", repl, self.output_template)
        dest = Path(rendered)
        if total and total > 1 and index is not None and ("%(playlist_index)s" not in self.output_template and "%(autonumber)s" not in self.output_template):
            dest = dest.with_name(f"{dest.stem}__{index}of{total}{dest.suffix}")

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        return dest

    def _build_filename(self, meta: DirectPostMetadata, index: Optional[int] = None, total: Optional[int] = None, image_url: Optional[str] = None) -> str:
        # Template: instagram_image__by_{author}[__{index}of{total}]
        author = meta.author or "unknown"
        # Determine extension from URL
        ext = ".jpg"
        candidate_url = image_url or meta.image_url
        if candidate_url:
            m = re.search(r"\.([a-zA-Z0-9]{3,4})(?:[?#].*)?$", candidate_url)
            if m:
                ext = "." + m.group(1).lower()
        suffix = ""
        if index is not None and total is not None and total > 1:
            suffix = f"__{index}of{total}"
        return f"instagram_image__by_{author}{suffix}{ext}"
    async def _navigate_and_collect(self, page, url: str) -> tuple[DirectPostMetadata, List[Dict[str, Optional[str]]]]:
        """Navigate to the URL, handle interstitial/modals, wait for the main image,
        reject videos, and return (metadata, images).
        """
        self._print("Navigating to Instagram URL (domcontentloaded, 20s timeout)...")
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            self._print("DOM content loaded.")
        except Exception as e:
            self._print(f"Navigation timeout/error: {e}. Continuing with rendered state...")
        try:
            if (not self.headless) or (self.debug_wait_ms > 0):
                await self._save_screenshot(page, 'after_load')
        except Exception:
            pass

        # Try to dismiss overlays/interstitials/cookies with multiple attempts
        try:
            self._print("Handling overlays/interstitials...")
        except Exception:
            pass
        try:
            # Hard cap overlay handling to avoid stalls
            await asyncio.wait_for(self._dismiss_overlays(page), timeout=3)
        except Exception:
            try:
                self._print("Overlay handling timed out or failed; proceeding.")
            except Exception:
                pass

        # Prime page for lazy-loaded media
        try:
            await page.wait_for_selector('article', timeout=7000)
        except Exception:
            pass
        try:
            await page.evaluate('window.scrollBy(0, 400)')
            await page.wait_for_timeout(300)
            await page.evaluate('window.scrollBy(0, -400)')
            await page.wait_for_timeout(200)
        except Exception:
            pass

        # Reject videos early (carousels supported for images)
        kind = await self._detect_video_or_carousel(page)
        if kind == "video_post":
            raise PermanentError("This post appears to be a video. Image-only is supported right now.")

        # Wait for main media to be present
        self._print("Locating main image (up to ~15s)...")
        ok = await self._wait_for_main_image(page)
        if not ok:
            raise ServiceUnavailableError("Could not locate main image on the page. The post might be blocked or requires login.")
        self._print("Main image located.")

        # Try to ensure the main image is in view
        try:
            # Use selector from config
            main_img_selector = get_playwright_selector(MAIN_IMAGE_SELECTORS)
            img_loc = page.locator(main_img_selector).first
            await img_loc.scroll_into_view_if_needed()
        except Exception:
            pass
        # Best-effort wait for alt
        try:
            img_chain = get_js_selector_chain(MAIN_IMAGE_SELECTORS)
            await page.wait_for_function(
                f"""
                () => {{
                  const q = (s)=>document.querySelector(s);
                  const img = {img_chain};
                  if (!img) return false;
                  const alt = img.getAttribute('alt');
                  return !!(alt && alt.trim().length > 0);
                }}
                """,
                timeout=3000,
            )
        except Exception:
            pass

        meta = await self._extract_metadata(page)
        self._print("Checking if carousel...")
        is_car = False
        try:
            is_car = await self._is_carousel(page)
        except Exception:
            is_car = False
        if is_car:
            self._print("Carousel detected. Collecting all slides...")
            images = await self._extract_all_images(page)
            if not images:
                raise ServiceUnavailableError("Carousel detected but no images could be collected.")
        else:
            self._print("Single-image post. Collecting the image...")
            images: List[Dict[str, Optional[str]]] = []
            if meta.image_url:
                images = [{"url": meta.image_url, "alt": meta.image_alt}]
            else:
                # Use selector from config for single image fallback
                img_chain = get_js_selector_chain(MAIN_IMAGE_SELECTORS)
                js_single = f"""
                () => {{
                  const q = (s)=>document.querySelector(s);
                  const img = {img_chain};
                  if (!img) return null;
                  return {{ url: img.getAttribute('src') || null, alt: img.getAttribute('alt') || img.alt || null }};
                }}
                """
                try:
                    one = await page.evaluate(js_single)
                    if isinstance(one, dict) and one.get('url'):
                        images = [{"url": one.get('url'), "alt": one.get('alt') }]
                except Exception:
                    pass
            if not images:
                raise ServiceUnavailableError("Failed to find image URL on single-image post.")
        self._print(f"Collected {len(images)} image(s).")

        return meta, images

    async def _extract_minimal_metadata_for_analysis(self, page) -> DirectPostMetadata:
        """Extract only minimal fields for Phase 1 (author + image_url)."""
        # Use selectors from config for consistency
        img_chain = get_js_selector_chain(MAIN_IMAGE_SELECTORS)
        username_selectors = get_selector_list(USERNAME_SELECTORS)
        
        js = f"""
        () => {{
          function q(sel){{ 
            try {{ return document.querySelector(sel); }} 
            catch(e) {{ return null; }}
          }}
          function qa(sel){{ 
            try {{ return Array.from(document.querySelectorAll(sel)); }} 
            catch(e) {{ return []; }}
          }}

          const result = {{ author: null, image_url: null }};

          // IMAGE from config
          const img = {img_chain};
          if (img) {{
            result.image_url = img.getAttribute('src');
          }}

          // USERNAME from config (same logic as full metadata extraction)
          const userLinks = qa('{username_selectors[0]}');
          for (const link of userLinks) {{
            const href = link.getAttribute('href');
            if (!href) continue;
            if (href.match(/^\\/[a-zA-Z0-9._]+\\/$/) && !href.match(/\\/(p|reel|tv|accounts|explore|stories)\\//)) {{
              if (href.length < 30) {{
                result.author = href.replace(/\\//g, '');
                break;
              }}
            }}
          }}
          // Fallback to class selector
          if (!result.author && '{username_selectors[1] if len(username_selectors) > 1 else ''}') {{
            const spans = qa('{username_selectors[1] if len(username_selectors) > 1 else ''}');
            for (const s of spans) {{
              const t = (s.textContent || '').trim();
              if (!t) continue;
              if (/^[A-Za-z0-9._]+$/.test(t)) {{ result.author = t; break; }}
            }}
          }}

          return result;
        }}
        """
        data = await page.evaluate(js)
        meta = DirectPostMetadata(
            author=data.get('author'),
            verified=False,
            published_on=None,
            likes=None,
            caption=None,
            image_url=data.get('image_url'),
            image_alt=None,
        )
        return meta

    async def _navigate_and_collect_analysis_only(self, url: str) -> tuple[DirectPostMetadata, List[Dict[str, Optional[str]]]]:
        """Navigate and collect metadata + carousel detection ONLY (no image extraction).
        Explicitly closes page, context, and browser to avoid dangling tasks.
        """
        async with async_playwright() as p:
            browser = None
            context = None
            page = None
            try:
                engine = getattr(p, self.browser_engine)
                launch_kwargs = {"headless": self.headless}
                if self.browser_engine == "chromium" and getattr(self, "use_chrome_channel", False):
                    launch_kwargs["channel"] = "chrome"
                browser = await engine.launch(**launch_kwargs)
                context = await browser.new_context(
                    viewport={'width': 1024, 'height': 720},
                )
                page = await context.new_page()

                # Navigate to Instagram and handle overlays
                self._print("Navigating to Instagram URL for analysis...")
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                try:
                    if (not self.headless) or (self.debug_wait_ms > 0):
                        await self._save_screenshot(page, 'analysis_after_load')
                except Exception:
                    pass

                # Handle overlays
                try:
                    await asyncio.wait_for(self._dismiss_overlays(page), timeout=8)
                except Exception:
                    pass

                # Prime page for lazy-loaded media
                try:
                    await page.wait_for_selector('article', timeout=7000)
                except Exception:
                    pass
                try:
                    await page.evaluate('window.scrollBy(0, 400)')
                    await page.wait_for_timeout(300)
                    await page.evaluate('window.scrollBy(0, -400)')
                    await page.wait_for_timeout(200)
                except Exception:
                    pass

                # Reject video posts early in analysis-only flow
                kind = await self._detect_video_or_carousel(page)
                if kind == "video_post":
                    raise PermanentError("This post appears to be a video. Image-only is supported right now.")

                # Wait for main image
                ok = await self._wait_for_main_image(page)
                if not ok:
                    raise ServiceUnavailableError("Could not locate main image for analysis.")

                # Extract minimal metadata (author + image_url only) for Phase 1
                meta = await self._extract_minimal_metadata_for_analysis(page)

                # Detect carousel - ANALYSIS ONLY, no navigation or slide collection
                is_carousel = await self._is_carousel(page)

                self._print(f"Analysis complete: {'Carousel' if is_carousel else 'Single'} detected")

                # Create minimal image info for analysis (no actual URL extraction)
                if is_carousel:
                    images = [{"url": "carousel_detected", "alt": None}]
                else:
                    if meta.image_url:
                        images = [{"url": meta.image_url, "alt": None}]
                    else:
                        images = [{"url": "single_image_detected", "alt": None}]

                return meta, images

            finally:
                # Best-effort orderly shutdown to prevent TargetClosedError logs
                # Close in reverse order: page -> context -> browser
                if page:
                    try:
                        await page.close()
                        logger.debug("Closed page successfully")
                    except Exception as e:
                        logger.warning(f"Failed to close page: {e}")
                
                if context:
                    try:
                        await context.close()
                        logger.debug("Closed browser context successfully")
                    except Exception as e:
                        logger.warning(f"Failed to close context: {e}")
                
                if browser:
                    try:
                        await browser.close()
                        logger.debug("Closed browser successfully")
                    except Exception as e:
                        logger.warning(f"Failed to close browser: {e}")

    async def _navigate_and_collect_analysis_keep_browser(self, url: str) -> tuple[DirectPostMetadata, List[Dict[str, Optional[str]]], Any]:
        """Navigate and collect metadata + carousel detection ONLY, keep browser open.
        Returns: (metadata, images_info, browser_context)
        """
        async with async_playwright() as p:
            engine = getattr(p, self.browser_engine)
            launch_kwargs = {"headless": self.headless}
            if self.browser_engine == "chromium" and getattr(self, "use_chrome_channel", False):
                launch_kwargs["channel"] = "chrome"
            browser = await engine.launch(**launch_kwargs)
            context = await browser.new_context(
                viewport={'width': 1024, 'height': 720},
            )
            page = await context.new_page()

            print("Navigating to Instagram URL for analysis...", flush=True)
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            try:
                if (not self.headless) or (self.debug_wait_ms > 0):
                    await self._save_screenshot(page, 'analysis_after_load')
            except Exception:
                pass

            try:
                await asyncio.wait_for(self._dismiss_overlays(page), timeout=8)
            except Exception:
                pass

            ok = await self._wait_for_main_image(page)
            if not ok:
                raise ServiceUnavailableError("Could not locate main image for analysis.")

            kind = await self._detect_video_or_carousel(page)
            if kind == "video_post":
                raise PermanentError("This post appears to be a video. Image-only is supported right now.")

            meta = await self._extract_metadata(page)
            is_carousel = await self._is_carousel(page)

            print(f"Analysis complete: {'Carousel' if is_carousel else 'Single'} detected", flush=True)

            if is_carousel:
                images = [{"url": "carousel_detected", "alt": None}]
            else:
                if meta.image_url:
                    images = [{"url": meta.image_url, "alt": meta.image_alt}]
                else:
                    images = [{"url": "single_image_detected", "alt": None}]

            return meta, images, context  # keep context open for reuse

    async def _download_from_analysis(self, url: str, metadata: DirectPostMetadata, images_info: List[Dict]) -> List[Path]:
        """Download single image using pre-analyzed metadata (skip re-analysis)."""
        if not images_info:
            raise ServiceUnavailableError("No images to download")

        image_info = images_info[0]
        image_url = image_info.get('url')
        if not image_url:
            raise ServiceUnavailableError("No image URL found")

        dest_path = self._format_output_path(
            url, metadata,
            index=None, total=None,
            image_url=image_url
        )

        self._print(f"Downloading: {dest_path.name}")

        if not self._http:
            self._http = httpx.Client(timeout=30)

        try:
            downloaded_path = self.download_image(image_url, dest_path)
            self._print(f"✓ Downloaded: {downloaded_path}")
            return [downloaded_path]
        finally:
            if self._http:
                self._http.close()
                self._http = None

    async def _download_from_analysis_with_browser(self, url: str, metadata: DirectPostMetadata, images_info: List[Dict], browser_context) -> List[Path]:
        """Download single image using pre-analyzed metadata with browser reuse."""
        try:
            if not images_info:
                raise ServiceUnavailableError("No images to download")

            image_info = images_info[0]
            image_url = image_info.get('url')
            if not image_url:
                raise ServiceUnavailableError("No image URL found")

            dest_path = self._format_output_path(
                url, metadata,
                index=None, total=None,
                image_url=image_url
            )

            self._print(f"Downloading: {dest_path.name}")

            if not self._http:
                self._http = httpx.Client(timeout=30)

            try:
                downloaded_path = self.download_image(image_url, dest_path)
                self._print(f"✓ Downloaded: {downloaded_path}")
                return [downloaded_path]
            finally:
                if self._http:
                    self._http.close()
                    self._http = None

        finally:
            try:
                await browser_context.close()
            except Exception:
                pass

    def extract_image_list(self, url: str) -> List[Dict[str, Any]]:
        """Discovery-only helper used by CLI --skip-download to list images and their would-be destination paths without downloading."""
        async def _discover(url: str) -> List[Dict[str, Any]]:
            async with async_playwright() as p:
                engine = getattr(p, self.browser_engine)
                launch_kwargs = {"headless": self.headless}
                if not self.headless:
                    launch_kwargs["slow_mo"] = 150
                browser = await engine.launch(**launch_kwargs)
                try:
                    context = await browser.new_context(
                        user_agent=self.ua.random,
                        viewport={"width": 1200, "height": 900},
                        locale="en-US",
                        timezone_id="UTC",
                    )
                    await context.add_init_script("""
                      Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    """)
                    page = await context.new_page()
                    try:
                        meta, images = await self._navigate_and_collect(page, url)
                        total = len(images)
                        results: List[Dict[str, Any]] = []
                        for idx, item in enumerate(images, start=1):
                            img_url = item.get("url") or ""
                            dest = self._format_output_path(url, meta, index=idx, total=total, image_url=img_url)
                            results.append({"url": img_url, "dest": str(dest)})
                        if not self.headless and self.debug_wait_ms > 0:
                            self._print(f"Debug wait: keeping browser open for {self.debug_wait_ms/1000:.1f}s...")
                            await page.wait_for_timeout(self.debug_wait_ms)
                        return results
                    except Exception:
                        try:
                            if (not self.headless) or (self.debug_wait_ms > 0):
                                await self._save_screenshot(page, 'error')
                        except Exception:
                            pass
                        raise
                finally:
                    try:
                        await browser.close()
                        logger.debug("Browser closed successfully in extract_image_list")
                    except Exception as e:
                        logger.warning(f"Failed to close browser in extract_image_list: {e}")

        try:
            return asyncio.run(_discover(url))
        except PermanentError as e:
            logger.error(f"Permanent error: {e}")
            return []
        except (RateLimitError, ServiceUnavailableError, NetworkError) as e:
            logger.error(f"Temporary error: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error: {e}")
            return []

    def download_image(self, image_url: str, dest_path: Path) -> Path:
        """Download a single image from URL to dest_path. Returns dest_path on success.
        Includes timeout handling and retry logic for transient failures.
        """
        max_attempts = 3
        last_exception = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                if not self._http:
                    # 30s total timeout: 10s connect, 30s read
                    self._http = httpx.Client(timeout=httpx.Timeout(30.0, connect=10.0))

                response = self._http.get(image_url, headers=self.headers, follow_redirects=True)
                response.raise_for_status()

                dest_path.parent.mkdir(parents=True, exist_ok=True)

                with open(dest_path, 'wb') as f:
                    for chunk in response.iter_bytes(chunk_size=8192):
                        f.write(chunk)

                return dest_path

            except httpx.TimeoutException as e:
                last_exception = e
                logger.warning(f"Download timeout (attempt {attempt}/{max_attempts}): {image_url}")
                if attempt < max_attempts:
                    import time
                    time.sleep(1)  # Brief delay before retry
                    continue
            except httpx.HTTPStatusError as e:
                # Don't retry on 4xx errors (permanent failures)
                if 400 <= e.response.status_code < 500:
                    logger.error(f"HTTP {e.response.status_code} error for {image_url}")
                    raise PermanentError(f"Download failed with HTTP {e.response.status_code}: {e}") from e
                # Retry on 5xx errors (server issues)
                last_exception = e
                logger.warning(f"HTTP {e.response.status_code} error (attempt {attempt}/{max_attempts}): {image_url}")
                if attempt < max_attempts:
                    import time
                    time.sleep(2)  # Longer delay for server errors
                    continue
            except Exception as e:
                last_exception = e
                logger.warning(f"Download error (attempt {attempt}/{max_attempts}): {e}")
                if attempt < max_attempts:
                    import time
                    time.sleep(1)
                    continue

        # All attempts failed
        logger.error(f"Failed to download {image_url} after {max_attempts} attempts: {last_exception}")
        raise PermanentError(f"Download failed after {max_attempts} attempts: {last_exception}") from last_exception

    async def _extract_impl(self, url: str) -> List[Path]:
        if not self.is_valid_url(url):
            raise InvalidUrlError(f"Invalid Instagram URL format: {url}")
        # Instant rejection for known video URLs (no page load needed)
        if "/reel/" in url or "/tv/" in url:
            raise PermanentError("Video posts (reels/IGTV) are not supported. This tool downloads images only.")

        async with async_playwright() as p:
            engine = getattr(p, self.browser_engine)
            launch_kwargs = {"headless": self.headless}
            if not self.headless:
                launch_kwargs["slow_mo"] = 150
            browser = await engine.launch(**launch_kwargs)
            try:
                context = await browser.new_context(
                    user_agent=self.ua.random,
                    viewport={"width": 1200, "height": 900},
                    locale="en-US",
                    timezone_id="UTC",
                )
                await context.add_init_script("""
                  Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                """)
                page = await context.new_page()

                try:
                    meta, images = await self._navigate_and_collect(page, url)

                    print("\nExtracted metadata:", flush=True)
                    print(f"  Author:        {meta.author or 'NA'}", flush=True)
                    print(f"  Verified:      {'yes' if meta.verified else 'no'}", flush=True)
                    print(f"  Published on:  {meta.published_on or 'NA'}", flush=True)
                    print(f"  Likes:         {meta.likes if meta.likes is not None else 'NA'}", flush=True)
                    print(f"  Caption:       {meta.caption or 'NA'}", flush=True)
                    print(f"  Total images:  {len(images)}", flush=True)
                    if images:
                        print(f"  First image:   {images[0]['url']}", flush=True)

                    if (not self.headless) or (self.debug_wait_ms > 0):
                        await self._save_screenshot(page, 'before_download')

                    downloaded_paths: List[Path] = []
                    total = len(images)
                    all_image_urls = [it.get("url") for it in images if isinstance(it, dict) and it.get("url")]

                    if self.skip_download:
                        planned = []
                        for idx, item in enumerate(images, start=1):
                            img_url = item.get("url") or ""
                            dest = self._format_output_path(url, meta, index=idx, total=total, image_url=img_url)
                            planned.append(dest)
                        if not self.headless and self.debug_wait_ms > 0:
                            print(f"Debug wait: keeping browser open for {self.debug_wait_ms/1000:.1f}s...", flush=True)
                            await page.wait_for_timeout(self.debug_wait_ms)
                        return planned

                    with httpx.Client(http2=True, timeout=30) as _client:
                        self._http = _client
                        for idx, item in enumerate(images, start=1):
                            img_url = item.get("url") or ""
                            img_alt = item.get("alt")
                            dest_path = self._format_output_path(url, meta, index=idx, total=total, image_url=img_url)
                            path = await asyncio.get_running_loop().run_in_executor(
                                None, lambda: self.download_image(img_url, dest_path)
                            )
                            downloaded_paths.append(path)

                            try:
                                info = {
                                    "platform": "instagram",
                                    "url": url,
                                    "author": meta.author,
                                    "verified": meta.verified,
                                    "published_on": meta.published_on,
                                    "likes": meta.likes,
                                    "caption": meta.caption,
                                    "image_url": img_url,
                                    "image_alt": img_alt,
                                    "index": idx,
                                    "total_images": total,
                                    "all_image_urls": all_image_urls,
                                }
                                import json
                                with open(Path(dest_path).with_suffix(".info.json"), "w", encoding="utf-8") as f:
                                    json.dump(info, f, ensure_ascii=False, indent=2)
                            except Exception as e:
                                logger.warning(f"Failed to write metadata JSON: {e}")
                        self._http = None

                    try:
                        post_info = {
                            "platform": "instagram",
                            "url": url,
                            "author": meta.author,
                            "verified": meta.verified,
                            "published_on": meta.published_on,
                            "likes": meta.likes,
                            "caption": meta.caption,
                            "total_images": total,
                            "images": [{"url": it.get("url"), "alt": it.get("alt")} for it in images if isinstance(it, dict) and it.get("url")],
                        }
                        import json
                        post_id = self.extract_post_id(url) or ""
                        safe_author = (meta.author or 'unknown').replace(' ', '_')
                        post_json_name = f"instagram_post__by_{safe_author}" + (f"__{post_id}" if post_id else "") + ".info.json"
                        with open(self.output_dir / post_json_name, "w", encoding="utf-8") as f:
                            json.dump(post_info, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        logger.warning(f"Failed to write consolidated post metadata JSON: {e}")

                    if not self.headless and self.debug_wait_ms > 0:
                        print(f"Debug wait: keeping browser open for {self.debug_wait_ms/1000:.1f}s...", flush=True)
                        await page.wait_for_timeout(self.debug_wait_ms)
                    return downloaded_paths
                except Exception:
                    try:
                        if (not self.headless) or (self.debug_wait_ms > 0):
                            await self._save_screenshot(page, 'error')
                    except Exception:
                        pass
                    raise
            finally:
                # Clean up browser resources
                try:
                    await browser.close()
                    logger.debug("Browser closed successfully in _extract_impl")
                except Exception as e:
                    logger.warning(f"Failed to close browser in _extract_impl: {e}")
