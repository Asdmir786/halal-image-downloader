#!/usr/bin/env python3
"""
Instagram Direct Image Extractor (image-only)
- Navigates to the Instagram post URL directly with Playwright (Chromium by default)
- Pauses for user input between steps
- Extracts image URL(s) + metadata (author, verified, published_on, likes, caption [best-effort])
- Rejects videos (reels/any <video> content). Carousels with multiple images are supported.
- Downloads images as: instagram_image__by_{author}__{index}of{total}.EXT (or without index for single-image posts)
"""
from __future__ import annotations

import asyncio
import os
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import httpx
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from .base_extractor import (
    BaseExtractor, logger,
    ExtractorError, TemporaryError, PermanentError,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError
)


@dataclass
class DirectPostMetadata:
    author: Optional[str] = None
    verified: bool = False
    published_on: Optional[str] = None  # ISO8601
    likes: Optional[int] = None
    caption: Optional[str] = None
    image_url: Optional[str] = None
    image_alt: Optional[str] = None


class InstagramDirectExtractor(BaseExtractor):
    def __init__(
        self,
        output_dir: str = ".",
        headless: bool = True,
        debug_wait_seconds: float = 0.0,
        browser: str = "chromium",
        max_retries: int = 3,
        interactive_pauses: bool = True,
        output_template: Optional[str] = None,
        skip_download: bool = False,
    ) -> None:
        super().__init__(strict_mode=True)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.headless = headless
        self.debug_wait_ms = int(max(0.0, debug_wait_seconds) * 1000)
        self.browser_engine = (browser or "chromium").strip().lower()
        if self.browser_engine not in {"chromium", "firefox", "webkit"}:
            self.browser_engine = "chromium"

        self.interactive_pauses = interactive_pauses
        self.output_template = output_template
        self.skip_download = skip_download

        self.headers = {
            "User-Agent": self.ua.random,
            "Accept": "image/webp,image/apng,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "DNT": "1",
            "Connection": "keep-alive",
            "Upgrade-Insecure-Requests": "1",
        }
        # HTTP client (initialized only during download phase for pooling/HTTP2)
        self._http: Optional[httpx.Client] = None

    @staticmethod
    def is_valid_url(url: str) -> bool:
        patterns = [
            r"https?://(?:www\.)?instagram\.com/p/[A-Za-z0-9_-]+/?",
            r"https?://(?:www\.)?instagram\.com/reel/[A-Za-z0-9_-]+/?",
        ]
        return any(re.match(p, url) for p in patterns)

    @staticmethod
    def extract_post_id(url: str) -> Optional[str]:
        m = re.search(r"/(?:p|reel)/([A-Za-z0-9_-]+)/", url)
        return m.group(1) if m else None


    async def _wait_for_enter(self, prompt: str, timeout_seconds: Optional[float] = None) -> bool:
        """No-op pause (disabled). Always returns False; no interactive pauses used."""
        return False

    async def _save_screenshot(self, page, tag: str) -> Optional[Path]:
        """Best-effort screenshot utility. Returns path if saved, else None."""
        try:
            ts = datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
            name = f"debug_screenshot__{tag}__{ts}.png"
            out = self.output_dir / name
            await page.screenshot(path=str(out), full_page=False)
            try:
                print(f"Saved screenshot: {out}", flush=True)
            except Exception:
                pass
            return out
        except Exception:
            return None

        # (interactive pauses removed)

    def _blocking_input_wait(self) -> None:
        """Blocking input wait with Windows-specific handling."""
        try:
            if os.name == 'nt':
                try:
                    import msvcrt
                    # Consume until Enter
                    while True:
                        ch = msvcrt.getwch()
                        if ch in ('\r', '\n'):
                            break
                    return
                except Exception:
                    # Fallback to stdin
                    pass
            # Non-Windows or fallback
            input()
        except EOFError:
            return

    async def _wait_for_enter_timeout(self, prompt: str, timeout_seconds: float) -> bool:
        """Wait for Enter with a timeout. Returns True if Enter pressed, False if timed out.
        Useful when STDIN may not be interactive (e.g., some runners).
        """
        if not self.interactive_pauses:
            return False
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(loop.run_in_executor(None, lambda: input(prompt)), timeout=timeout_seconds)
            return True
        except Exception:
            try:
                print(f"No input within {timeout_seconds}s, auto-proceeding...", flush=True)
            except Exception:
                pass
            return False

    async def _close_any_modal(self, page) -> None:
        # Try common close buttons/dialogs
        selectors = [
            'div[role="dialog"] svg[aria-label="Close"]',
            'div[role="button"] svg[aria-label="Close"]',
            '[role="dialog"] [aria-label="Close"]',
            'button[aria-label="Close"]',
            '[aria-label="Close"]',
            # Cookie banners (click accept)
            'button:has-text("Allow all cookies")',
            'button:has-text("Allow all")',
            'button:has-text("Accept all")',
            'button:has-text("Accept")',
        ]
        try:
            # Attempt up to 3 times in case the first click doesn't take effect
            for _ in range(3):
                handled = False
                for sel in selectors:
                    try:
                        el = await page.query_selector(sel)
                        if not el:
                            continue
                        # Prefer clickable ancestor (button or role=button)
                        try:
                            ancestor = await page.evaluate_handle(
                                '(el) => el.closest("button,[role=\\"button\\"]")', el
                            )
                            anc_el = ancestor.as_element()
                        except Exception:
                            anc_el = None
                        try:
                            if anc_el:
                                await anc_el.click()
                            else:
                                await el.click()
                            await page.wait_for_timeout(500)
                            handled = True
                            break
                        except Exception:
                            continue
                    except Exception:
                        continue
                if not handled:
                    # Try pressing Escape as a generic dismiss
                    try:
                        await page.keyboard.press('Escape')
                        await page.wait_for_timeout(350)
                    except Exception:
                        pass
                    break
        except Exception:
            pass

    async def _has_modal(self, page) -> bool:
        selectors = [
            '[role="dialog"]',
            'div[role="dialog"] svg[aria-label="Close"]',
            'div[role="button"] svg[aria-label="Close"]',
            '[role="dialog"] [aria-label="Close"]',
            'button[aria-label="Close"]',
            '[aria-label="Close"]',
            'a[href*="applink.instagram.com"]',
            'text=See this post in the app',
        ]
        for sel in selectors:
            try:
                # Non-blocking check: if selector exists, assume modal/overlay is present
                el = await page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue
        return False

    async def _try_click_continue_on_web(self, page) -> bool:
        """Detect and click the 'Continue on the web' CTA if the interstitial is present.
        Returns True if clicked, False otherwise.
        """
        candidates = [
            "button:has-text('Continue on the web')",
            "button:has-text('Continue on web')",
            "[role=button]:has-text('Continue on the web')",
            "[role=button]:has-text('Continue on web')",
            "a:has-text('Continue on the web')",
            "a:has-text('Continue on web')",
            "text=/^Continue on (the )?web$/i",
        ]
        for sel in candidates:
            try:
                loc = page.locator(sel).first
                # Prefer a quick visibility check; fall back to existence
                visible = False
                try:
                    visible = await loc.is_visible(timeout=400)
                except Exception:
                    visible = False
                if not visible:
                    try:
                        exists = (await loc.count()) > 0
                    except Exception:
                        exists = False
                    if not exists:
                        continue
                await loc.click()
                await page.wait_for_timeout(400)
                logger.info("Clicked 'Continue on the web'.")
                return True
            except Exception:
                continue
        return False

    async def _dismiss_overlays(self, page) -> None:
        """Best-effort dismissal of common Instagram overlays: interstitials and cookies.
        Tries multiple strategies a few times with short waits in between.
        """
        print("Dismissing overlays (up to 3 quick passes)...", flush=True)
        for i in range(3):
            did_anything = False
            # 1) Try the 'Continue on the web' CTA if present
            try:
                if await self._try_click_continue_on_web(page):
                    try:
                        print("- Clicked 'Continue on the web'", flush=True)
                    except Exception:
                        pass
                    did_anything = True
            except Exception:
                pass
            # 2) Try cookie banners / accept buttons
            cookie_ctas = [
                "button:has-text('Allow all cookies')",
                "button:has-text('Allow all')",
                "button:has-text('Accept all')",
                "button:has-text('Accept')",
                "text=/^Allow all cookies$/i",
            ]
            for sel in cookie_ctas:
                try:
                    loc = page.locator(sel).first
                    await loc.wait_for(state="visible", timeout=400)
                    await loc.click()
                    await page.wait_for_timeout(400)
                    try:
                        print(f"- Clicked cookie CTA: {sel}", flush=True)
                    except Exception:
                        pass
                    did_anything = True
                    break
                except Exception:
                    continue
            # 3) Try closing dialogs via Close icon
            try:
                await self._close_any_modal(page)
            except Exception:
                pass
            # 4) As a last resort, press Escape
            try:
                await page.keyboard.press('Escape')
            except Exception:
                pass
            await page.wait_for_timeout(350)
            # If nothing was done this iteration and no modal detected, stop early
            try:
                if not did_anything and not await self._has_modal(page):
                    break
            except Exception:
                break
        try:
            print("Overlay dismissal done.", flush=True)
        except Exception:
            pass

    async def _is_carousel(self, page) -> bool:
        """Determine if the current post is a carousel by presence of controls only.
        No clicks, no confirmation, no fallbacks.
        Returns True if either Next or Go back buttons exist in the DOM.
        """
        try:
            next_count = await page.locator("button[aria-label='Next']._afxw._al46._al47, article button[aria-label='Next']").count()
        except Exception:
            next_count = 0
        try:
            prev_count = await page.locator("button[aria-label='Go back']._afxv._al46._al47, article button[aria-label='Go back']").count()
        except Exception:
            prev_count = 0
        return (next_count > 0) or (prev_count > 0)

    async def _detect_video_or_carousel(self, page) -> Optional[str]:
        """Return 'video_post' if a video is detected; otherwise None."""
        try:
            # Video detection: look for <video> element in the specific media container structure
            has_video = await page.evaluate("""
                () => {
                  // Check for video in the main media container structure you provided
                  const videoSelectors = [
                    'article div.x5yr21d video',
                    'article video',
                    'main video'
                  ];
                  for (const sel of videoSelectors) {
                    if (document.querySelector(sel)) return true;
                  }
                  return false;
                }
            """)
            if has_video:
                return "video_post"
        except Exception:
            pass
        return None

    async def _wait_for_main_image(self, page) -> bool:
        # Wait for any of the likely main image selectors to be present (~8s total)
        try:
            await page.wait_for_function(
                """
                () => {
                  const sels = [
                    'ul._acay li._acaz img[src]',
                    'article div._aagu div._aagv img[src]',
                    'article img[decoding][src]',
                    'main img[decoding][src]'
                  ];
                  for (const sel of sels) {
                    const el = document.querySelector(sel);
                    if (el && el.getAttribute('src')) return true;
                  }
                  return false;
                }
                """,
                timeout=8000,
            )
            return True
        except PlaywrightTimeoutError:
            return False

    async def _extract_metadata(self, page) -> DirectPostMetadata:
        # Run JS in page to extract fields based on your sample HTML structure
        js = r"""
        () => {
          function q(sel){ return document.querySelector(sel); }
          function qa(sel){ return Array.from(document.querySelectorAll(sel)); }

          const result = {
            author: null,
            verified: false,
            published_on: null,
            likes: null,
            caption: null,
            image_url: null,
            image_alt: null,
          };

          // Image (scoped to the main article). Prefer an <img> with alt when available.
          const img =
            q('article div._aagu div._aagv img[alt][src]') ||
            q('article div._aagu div._aagv img[src]') ||
            q('article img[alt][src]') ||
            q('article img[src]') ||
            q('main img[alt][src]') ||
            q('main img[src]');
          if (img) {
            result.image_url = img.getAttribute('src');
            result.image_alt = (img.getAttribute('alt') || img.alt || null);
            if (!result.image_alt) {
              // Fallback: search within the same media container for any img[alt]
              const cont = img.closest('div._aagv, div._aagu, article') || document;
              const altImg = cont.querySelector('img[alt]');
              if (altImg) result.image_alt = (altImg.getAttribute('alt') || altImg.alt || null);
            }
          }

          // Author (first reasonable username span._ap3a)
          const spans = qa('span._ap3a');
          for (const s of spans) {
            const t = (s.textContent || '').trim();
            if (!t) continue;
            if (/^[A-Za-z0-9._]+$/.test(t)) { result.author = t; break; }
          }

          // Verified badge: strictly use the provided structure
          // Look for: .html-div ... <svg aria-label="Verified" ...>
          {
            const v = q('.html-div svg[aria-label="Verified"]');
            result.verified = !!v;
          }

          // Published time: nearest time[datetime]
          const timeEl = q('time[datetime]');
          if (timeEl) {
            result.published_on = timeEl.getAttribute('datetime');
          }

          // Likes: search any element whose text contains "likes"
          const txtEls = qa('span, a, div');
          for (const el of txtEls) {
            const tx = (el.textContent || '').trim();
            if (!tx) continue;
            const m = tx.match(/([\d,.]+)\s+likes/i);
            if (m) {
              const num = m[1].replace(/[,.]/g, '');
              const n = parseInt(num, 10);
              if (!Number.isNaN(n)) { result.likes = n; break; }
            }
          }

          // Caption: use the specific caption heading just after the author block
          let caption = null;
          let capEl = q('article h1._ap3a') || q('article span._ap3a > div > h1') || q('article h1[dir="auto"]');
          if (capEl) {
            caption = (capEl.textContent || '').trim();
          }
          if (!caption && result.image_alt) caption = result.image_alt;
          result.caption = caption;

          return result;
        }
        """
        data = await page.evaluate(js)
        meta = DirectPostMetadata(**data)
        return meta

    async def _extract_all_images(self, page) -> List[Dict[str, Optional[str]]]:
        """Collect all image URLs (and alt when available) from the post.

        Handles both single-image and carousel posts. For carousels, navigates through
        all slides by clicking the 'Next' button to load each image before extracting.
        Uses the specific button selector with ~3–4 second waits.
        """
        try:
            collected_images: List[Dict[str, Optional[str]]] = []
            seen_urls: set = set()
            
            # Extract the first/current image
            js_extract = r"""
            () => {
              const q = (s)=>document.querySelector(s);
              const img = q('ul._acay li._acaz img[src]') || q('article div._aagu div._aagv img[src]') || q('article img[decoding][src]') || q('main img[decoding][src]');
              if (!img) return [];
              const src = img.getAttribute('src');
              const alt = img.getAttribute('alt') || img.alt || null;
              return src ? [{ url: src, alt }] : [];
            }
            """
            
            # Ensure media container has focus to reveal navigation controls
            try:
                await page.locator('article div._aagu').first.click()
            except Exception:
                pass
            # Also try hover on the carousel list to reveal arrows
            try:
                await page.locator('ul._acay').first.hover()
            except Exception:
                try:
                    await page.locator('article div._aagu').first.hover()
                except Exception:
                    pass

            # Get first/current image
            first_imgs = await page.evaluate(js_extract)
            for it in first_imgs:
                url = it.get('url') if isinstance(it, dict) else None
                alt = it.get('alt') if isinstance(it, dict) else None
                if url and url not in seen_urls:
                    print(f"[carousel] Found first image: {url}", flush=True)
                    seen_urls.add(url)
                    collected_images.append({'url': url, 'alt': alt})
            
            # Now try to navigate carousel if it exists
            # Keep clicking Next until it's not found (indicating last slide)
            max_slides = 20  # Safety limit to prevent infinite loops
            slide_count = 0
            
            while slide_count < max_slides:
                try:
                    # Wait for Next button to appear (up to 3 seconds)
                    # Button selector (user-provided): aria-label="Next" with classes _afxw _al46 _al47
                    next_locator = page.locator('button[aria-label="Next"]._afxw._al46._al47, article button[aria-label="Next"]').first
                    await next_locator.wait_for(state="visible", timeout=3000)
                    # Capture currently seen URLs snapshot for change detection
                    prev_list = list(seen_urls)
                    # Click the Next button
                    await next_locator.click()
                    # Wait for main image src to change to something not in seen
                    try:
                        await page.wait_for_function(
                            """
                            (prev) => {
                              const q = (s)=>document.querySelector(s);
                              const img = q('ul._acay li._acaz img[src]') || q('article div._aagu div._aagv img[src]') || q('article img[decoding][src]') || q('main img[decoding][src]');
                              if (!img) return false;
                              const src = img.getAttribute('src');
                              return src && !prev.includes(src);
                            }
                            """,
                            arg=prev_list,
                            timeout=4000,
                        )
                    except Exception:
                        pass

                    # Extract the new current image
                    new_imgs = await page.evaluate(js_extract)
                    added = False
                    for it in new_imgs:
                        url = it.get('url') if isinstance(it, dict) else None
                        alt = it.get('alt') if isinstance(it, dict) else None
                        if url and url not in seen_urls:
                            print(f"[carousel] Next image: {url}", flush=True)
                            seen_urls.add(url)
                            collected_images.append({'url': url, 'alt': alt})
                            added = True
                    if not added:
                        print("[carousel] No new image detected after Next click.", flush=True)
                    slide_count += 1
                except PlaywrightTimeoutError:
                    # Next button not found within ~3s = likely last slide
                    logger.info("No Next button found, reached last slide.")
                    break
                except Exception as e:
                    logger.warning(f"Carousel navigation click failed: {e}")
                    break
            
            return collected_images
            
        except Exception as e:
            logger.warning(f"Error extracting images: {e}")
            return []

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
        if not self.output_template:
            filename = self._build_filename(meta, index=index, total=total, image_url=candidate_url)
            return (self.output_dir / filename)

        # Build value map for %(...)s
        post_id = self.extract_post_id(url) or ""
        # Upload date normalization: prefer YYYYMMDD if possible
        upload_date = None
        if meta.published_on:
            try:
                # Try to parse ISO8601
                dt = datetime.fromisoformat(meta.published_on.replace("Z", "+00:00"))
                upload_date = dt.strftime("%Y%m%d")
            except Exception:
                # Fallback: strip non-digits
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
        # If template has no index tokens and it's a multi-image set, append suffix
        if total and total > 1 and index is not None and ("%(playlist_index)s" not in self.output_template and "%(autonumber)s" not in self.output_template):
            dest = dest.with_name(f"{dest.stem}__{index}of{total}{dest.suffix}")

        # Ensure directory exists (best-effort)
        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        # Append timestamp suffix to avoid filename collisions (YYYYMMDDHH)
        try:
            ts = datetime.now().strftime("%Y%m%d%H")
            dest = dest.with_name(f"{dest.stem}_{ts}{dest.suffix}")
        except Exception:
            pass
        return dest

    async def _navigate_and_collect(self, page, url: str) -> tuple[DirectPostMetadata, List[Dict[str, Optional[str]]]]:
        """Navigate to the URL, handle interstitial/modals, wait for the main image,
        reject videos, and return (metadata, images).
        """
        print("Navigating to Instagram URL (domcontentloaded, 20s timeout)...", flush=True)
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            print("DOM content loaded.", flush=True)
        except Exception as e:
            print(f"Navigation timeout/error: {e}. Continuing with rendered state...", flush=True)
        await self._save_screenshot(page, 'after_load')

        # Try to dismiss overlays/interstitials/cookies with multiple attempts
        try:
            print("Handling overlays/interstitials...", flush=True)
        except Exception:
            pass
        try:
            # Hard cap overlay handling to avoid stalls
            await asyncio.wait_for(self._dismiss_overlays(page), timeout=8)
        except Exception:
            try:
                print("Overlay handling timed out or failed; proceeding.", flush=True)
            except Exception:
                pass
        # Generic escape one more time
        try:
            await page.keyboard.press('Escape')
            await page.wait_for_timeout(200)
        except Exception:
            pass

        # Wait for main media to be present
        print("Locating main image (up to ~8s)...", flush=True)
        ok = await self._wait_for_main_image(page)
        if not ok:
            raise ServiceUnavailableError("Could not locate main image on the page. The post might be blocked or requires login.")
        print("Main image located.", flush=True)

        # Reject videos only (carousels supported for images)
        kind = await self._detect_video_or_carousel(page)
        if kind == "video_post":
            raise PermanentError("This post appears to be a video. Image-only is supported right now.")

        # Try to ensure the main image is in view
        try:
            img_loc = page.locator('article div._aagu div._aagv img').first
            await img_loc.scroll_into_view_if_needed()
        except Exception:
            pass
        # Best-effort wait for alt
        try:
            await page.wait_for_function(
                """
                () => {
                  const sel = 'article div._aagu div._aagv img[src]';
                  const img = document.querySelector(sel) || document.querySelector('article img[src]');
                  if (!img) return false;
                  const alt = img.getAttribute('alt');
                  return !!(alt && alt.trim().length > 0);
                }
                """,
                timeout=3000,
            )
        except Exception:
            pass

        meta = await self._extract_metadata(page)
        print("Checking if carousel...", flush=True)
        is_car = False
        try:
            is_car = await self._is_carousel(page)
        except Exception:
            is_car = False
        if is_car:
            print("Carousel detected. Collecting all slides...", flush=True)
            images = await self._extract_all_images(page)
            if not images:
                raise ServiceUnavailableError("Carousel detected but no images could be collected.")
        else:
            print("Single-image post. Collecting the image...", flush=True)
            images: List[Dict[str, Optional[str]]] = []
            if meta.image_url:
                images = [{"url": meta.image_url, "alt": meta.image_alt}]
            else:
                # Fallback: read the currently displayed image directly from DOM
                js_single = r"""
                () => {
                  const q = (s)=>document.querySelector(s);
                  const img = q('ul._acay li._acaz img[src]') || q('article div._aagu div._aagv img[src]') || q('article img[decoding][src]') || q('main img[decoding][src]');
                  if (!img) return null;
                  return { url: img.getAttribute('src') || null, alt: img.getAttribute('alt') || img.alt || null };
                }
                """
                try:
                    one = await page.evaluate(js_single)
                    if isinstance(one, dict) and one.get('url'):
                        images = [{"url": one.get('url'), "alt": one.get('alt') }]
                except Exception:
                    pass
            if not images:
                raise ServiceUnavailableError("Failed to find image URL on single-image post.")
        print(f"Collected {len(images)} image(s).", flush=True)

        return meta, images

    async def _navigate_and_collect_analysis_only(self, url: str) -> tuple[DirectPostMetadata, List[Dict[str, Optional[str]]]]:
        """Navigate and collect metadata + carousel detection ONLY (no image extraction).
        Used by hybrid system for initial analysis phase.
        """
        async with async_playwright() as p:
            browser = None
            try:
                engine = getattr(p, self.browser_engine)
                browser = await engine.launch(headless=self.headless)
                context = await browser.new_context(
                    user_agent=self.ua.random,
                    viewport={'width': 1024, 'height': 720},
                )
                page = await context.new_page()
                
                # Navigate to Instagram and handle overlays
                print("Navigating to Instagram URL for analysis...", flush=True)
                await page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await self._save_screenshot(page, 'analysis_after_load')
                
                # Handle overlays
                try:
                    await asyncio.wait_for(self._dismiss_overlays(page), timeout=8)
                except Exception:
                    pass
                
                # Wait for main image
                ok = await self._wait_for_main_image(page)
                if not ok:
                    raise ServiceUnavailableError("Could not locate main image for analysis.")
                
                # Reject video posts
                kind = await self._detect_video_or_carousel(page)
                if kind == "video_post":
                    raise PermanentError("This post appears to be a video. Image-only is supported right now.")
                
                # Extract metadata
                meta = await self._extract_metadata(page)
                
                # Detect carousel - ANALYSIS ONLY, no navigation or slide collection
                is_carousel = await self._is_carousel(page)
                
                print(f"Analysis complete: {'Carousel' if is_carousel else 'Single'} detected", flush=True)
                
                # Create minimal image info for analysis (no actual URL extraction)
                if is_carousel:
                    # Just indicate it's a carousel, don't collect actual images
                    images = [{"url": "carousel_detected", "alt": None}]
                else:
                    # For single image, get the current displayed one
                    if meta.image_url:
                        images = [{"url": meta.image_url, "alt": meta.image_alt}]
                    else:
                        images = [{"url": "single_image_detected", "alt": None}]
                
                return meta, images
                
            finally:
                if browser:
                    await browser.close()

    async def _navigate_and_collect_analysis_keep_browser(self, url: str) -> tuple[DirectPostMetadata, List[Dict[str, Optional[str]]], Any]:
        """Navigate and collect metadata + carousel detection ONLY, keep browser open.
        Returns: (metadata, images_info, browser_context)
        """
        from playwright.async_api import async_playwright
        
        async with async_playwright() as p:
            engine = getattr(p, self.browser_engine)
            browser = await engine.launch(headless=self.headless)
            context = await browser.new_context(
                user_agent=self.ua.random,
                viewport={'width': 1024, 'height': 720},
            )
            page = await context.new_page()
            
            # Navigate to Instagram and handle overlays
            print("Navigating to Instagram URL for analysis...", flush=True)
            await page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await self._save_screenshot(page, 'analysis_after_load')
            
            # Handle overlays
            try:
                await asyncio.wait_for(self._dismiss_overlays(page), timeout=8)
            except Exception:
                pass
            
            # Wait for main image
            ok = await self._wait_for_main_image(page)
            if not ok:
                raise ServiceUnavailableError("Could not locate main image for analysis.")
            
            # Reject video posts
            kind = await self._detect_video_or_carousel(page)
            if kind == "video_post":
                raise PermanentError("This post appears to be a video. Image-only is supported right now.")
            
            # Extract metadata
            meta = await self._extract_metadata(page)
            
            # Detect carousel - ANALYSIS ONLY, no navigation or slide collection
            is_carousel = await self._is_carousel(page)
            
            print(f"Analysis complete: {'Carousel' if is_carousel else 'Single'} detected", flush=True)
            
            # Create minimal image info for analysis (no actual URL extraction)
            if is_carousel:
                # Just indicate it's a carousel, don't collect actual images
                images = [{"url": "carousel_detected", "alt": None}]
            else:
                # For single image, get the current displayed one
                if meta.image_url:
                    images = [{"url": meta.image_url, "alt": meta.image_alt}]
                else:
                    images = [{"url": "single_image_detected", "alt": None}]
            
            # Return analysis results (browser will be closed automatically by async with)
            return meta, images, None  # Return None for browser_context since we can't keep it open safely

    async def _download_from_analysis(self, url: str, metadata: DirectPostMetadata, images_info: List[Dict]) -> List[Path]:
        """Download single image using pre-analyzed metadata (skip re-analysis).
        Used by hybrid system for single image downloads.
        """
        if not images_info:
            raise ServiceUnavailableError("No images to download")
        
        # For single image, just download the first one
        image_info = images_info[0]
        image_url = image_info.get('url')
        if not image_url:
            raise ServiceUnavailableError("No image URL found")
        
        # Build filename using metadata
        dest_path = self._format_output_path(
            url, metadata, 
            index=None, total=None, 
            image_url=image_url
        )
        
        print(f"Downloading: {dest_path.name}")
        
        # Initialize HTTP client if not already done
        if not self._http:
            self._http = httpx.Client(timeout=30)
        
        try:
            downloaded_path = self.download_image(image_url, dest_path)
            print(f"✓ Downloaded: {downloaded_path}")
            return [downloaded_path]
        finally:
            if self._http:
                self._http.close()
                self._http = None

    async def _download_from_analysis_with_browser(self, url: str, metadata: DirectPostMetadata, images_info: List[Dict], browser_context) -> List[Path]:
        """Download single image using pre-analyzed metadata with browser reuse.
        Used by hybrid system for single image downloads with existing browser.
        """
        try:
            if not images_info:
                raise ServiceUnavailableError("No images to download")
            
            # For single image, just download the first one
            image_info = images_info[0]
            image_url = image_info.get('url')
            if not image_url:
                raise ServiceUnavailableError("No image URL found")
            
            # Build filename using metadata
            dest_path = self._format_output_path(
                url, metadata, 
                index=None, total=None, 
                image_url=image_url
            )
            
            print(f"Downloading: {dest_path.name}")
            
            # Initialize HTTP client if not already done
            if not self._http:
                self._http = httpx.Client(timeout=30)
            
            try:
                downloaded_path = self.download_image(image_url, dest_path)
                print(f"✓ Downloaded: {downloaded_path}")
                return [downloaded_path]
            finally:
                if self._http:
                    self._http.close()
                    self._http = None
        
        finally:
            # Close browser at the end
            try:
                await browser_context.close()
            except:
                pass

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

    async def _extract_impl(self, url: str) -> List[Path]:
        if not self.is_valid_url(url):
            raise InvalidUrlError(f"Invalid Instagram URL format: {url}")
        if "/reel/" in url:
            raise PermanentError("Video posts (reels) are not supported. Image-only for now.")

        async with async_playwright() as p:
            engine = getattr(p, self.browser_engine, p.chromium)
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

                # Main extraction wrapped to capture error screenshot
                try:
                    # Navigate and collect image data
                    meta, images = await self._navigate_and_collect(page, url)

                    # Show metadata
                    print("\nExtracted metadata:", flush=True)
                    print(f"  Author:        {meta.author or 'NA'}", flush=True)
                    print(f"  Verified:      {'yes' if meta.verified else 'no'}", flush=True)
                    print(f"  Published on:  {meta.published_on or 'NA'}", flush=True)
                    print(f"  Likes:         {meta.likes if meta.likes is not None else 'NA'}", flush=True)
                    print(f"  Caption:       {meta.caption or 'NA'}", flush=True)
                    print(f"  Total images:  {len(images)}", flush=True)
                    if images:
                        print(f"  First image:   {images[0]['url']}", flush=True)

                    # Screenshot just before downloads and JSON
                    await self._save_screenshot(page, 'before_download')

                    # Download and write JSON (unless skip_download)
                    downloaded_paths: List[Path] = []
                    total = len(images)
                    all_image_urls = [it.get("url") for it in images if isinstance(it, dict) and it.get("url")]

                    # If skip_download is requested, return early after planning destinations
                    if self.skip_download:
                        planned = []
                        for idx, item in enumerate(images, start=1):
                            img_url = item.get("url") or ""
                            dest = self._format_output_path(url, meta, index=idx, total=total, image_url=img_url)
                            planned.append(dest)
                        # Optional hold in debug mode
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

                            # Per-image JSON (inside loop: one file per image)
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
                                    "downloaded_at": datetime.utcnow().isoformat() + "Z",
                                }
                                import json
                                with open(Path(dest_path).with_suffix(".info.json"), "w", encoding="utf-8") as f:
                                    json.dump(info, f, ensure_ascii=False, indent=2)
                            except Exception as e:
                                logger.warning(f"Failed to write metadata JSON: {e}")
                        self._http = None

                    # Consolidated post-level JSON
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
                            "downloaded_at": datetime.utcnow().isoformat() + "Z",
                        }
                        import json
                        post_id = self.extract_post_id(url) or ""
                        post_json_name = f"instagram_post__by_{(meta.author or 'unknown').replace(' ', '_')}" + (f"__{post_id}" if post_id else "") + ".info.json"
                        with open(self.output_dir / post_json_name, "w", encoding="utf-8") as f:
                            json.dump(post_info, f, ensure_ascii=False, indent=2)
                    except Exception as e:
                        logger.warning(f"Failed to write consolidated post metadata JSON: {e}")

                    # Optional hold in debug mode before closing
                    if not self.headless and self.debug_wait_ms > 0:
                        print(f"Debug wait: keeping browser open for {self.debug_wait_ms/1000:.1f}s...", flush=True)
                        await page.wait_for_timeout(self.debug_wait_ms)
                    return downloaded_paths
                except Exception:
                    # Error screenshot
                    try:
                        await self._save_screenshot(page, 'error')
                    except Exception:
                        pass
                    raise
            finally:
                await browser.close()


    def extract_image_list(self, url: str) -> List[Dict[str, Any]]:
        """Discovery-only helper used by CLI --skip-download to list images and their
        would-be destination paths without downloading.
        """
        async def _discover(url: str) -> List[Dict[str, Any]]:
            async with async_playwright() as p:
                engine = getattr(p, self.browser_engine, p.chromium)
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
                        # Optional hold in debug mode
                        if not self.headless and self.debug_wait_ms > 0:
                            print(f"Debug wait: keeping browser open for {self.debug_wait_ms/1000:.1f}s...", flush=True)
                            await page.wait_for_timeout(self.debug_wait_ms)
                        return results
                    except Exception:
                        try:
                            await self._save_screenshot(page, 'error')
                        except Exception:
                            pass
                        raise
                finally:
                    await browser.close()

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
        """Download a single image from URL to dest_path. Returns dest_path on success."""
        try:
            if not self._http:
                self._http = httpx.Client(timeout=30)
            
            response = self._http.get(image_url, headers=self.headers)
            response.raise_for_status()
            
            # Ensure directory exists
            dest_path.parent.mkdir(parents=True, exist_ok=True)
            
            # Write image data
            with open(dest_path, 'wb') as f:
                for chunk in response.iter_bytes():
                    f.write(chunk)
            
            return dest_path
            
        except Exception as e:
            logger.error(f"Failed to download {image_url}: {e}")
            raise PermanentError(f"Download failed: {e}") from e
