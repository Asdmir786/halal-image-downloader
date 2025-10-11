#!/usr/bin/env python3
from __future__ import annotations

from typing import Any, Dict, List, Optional

from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from .core import DirectPostMetadata
from .selectors import (
    CAROUSEL_NEXT_SELECTORS,
    CAROUSEL_PREV_SELECTORS,
    MAIN_IMAGE_SELECTORS,
    IMAGE_CONTAINER_SELECTORS,
    USERNAME_SELECTORS,
    VERIFIED_BADGE_SELECTORS,
    TIMESTAMP_SELECTOR,
    LIKES_SELECTOR,
    CAPTION_SELECTORS,
    get_playwright_selector,
    get_js_selector_chain,
    get_selector_list,
)
from ...base_extractor import logger


class DirectMediaMixin:
    async def _is_carousel(self, page) -> bool:
        """Determine if the current post is a carousel by presence of controls only.
        Uses robust aria-label selectors from config instead of fragile class names.
        """
        try:
            # Use selectors from config - semantic and stable
            next_selector = get_playwright_selector(CAROUSEL_NEXT_SELECTORS)
            next_count = await page.locator(next_selector).count()
        except Exception:
            next_count = 0
        try:
            prev_selector = get_playwright_selector(CAROUSEL_PREV_SELECTORS)
            prev_count = await page.locator(prev_selector).count()
        except Exception:
            prev_count = 0
        return (next_count > 0) or (prev_count > 0)

    async def _detect_video_or_carousel(self, page) -> Optional[str]:
        """Return 'video_post' if a video is detected; otherwise None."""
        try:
            signals = await page.evaluate(
                """
                () => {
                  const videoSelectors = [
                    'article div.x5yr21d video',
                    'article video',
                    'main video'
                  ];
                  let hasVideo = false;
                  for (const sel of videoSelectors) {
                    if (document.querySelector(sel)) { hasVideo = true; break; }
                  }

                  const hasOgVideo = !!document.querySelector(
                    'meta[property="og:video"], meta[name="medium"][content="video"], meta[property="og:type"][content*="video"]'
                  );
                  const hasVideoIcon = !!document.querySelector(
                    'svg[aria-label*="Video" i], svg[aria-label*="Reels" i]'
                  );
                  const hasPlayButton = !!document.querySelector(
                    'button[aria-label*="Play" i], [role=button][aria-label*="Play" i]'
                  );

                  return { hasVideo, hasOgVideo, hasVideoIcon, hasPlayButton };
                }
                """
            )
            if signals and (
                signals.get('hasVideo') or signals.get('hasOgVideo') or signals.get('hasVideoIcon') or signals.get('hasPlayButton')
            ):
                return "video_post"
        except Exception:
            pass
        return None

    async def _wait_for_main_image(self, page) -> bool:
        # Wait for any of the likely main image candidates to have a usable source (~15s total)
        # Use robust selectors from config
        selector_str = get_playwright_selector(MAIN_IMAGE_SELECTORS)
        logger.debug(f"Waiting for main image with selectors: {selector_str}")
        
        try:
            await page.wait_for_function(
                f"""
                () => {{
                  // Use config-based selectors (robust, not class-dependent)
                  const selectors = '{selector_str}'.split(', ');
                  let candidates = [];
                  for (const sel of selectors) {{
                    try {{
                      const found = Array.from(document.querySelectorAll(sel.trim()));
                      candidates = candidates.concat(found);
                    }} catch(e) {{
                      console.error('Selector failed:', sel, e);
                    }}
                  }}

                  function isContentImage(img) {{
                    if (!img) return false;
                    // Exclude header/nav images
                    const inHeader = !!img.closest('header, nav');
                    if (inHeader) return false;
                    // Exclude profile pictures (selector should already do this, but double-check)
                    const alt = (img.getAttribute('alt') || img.alt || '').toLowerCase();
                    if (alt.includes('profile picture') || alt.includes('avatar')) return false;
                    // Require a reasonably sized image to avoid tiny icons
                    const r = img.getBoundingClientRect();
                    if ((r?.width || 0) < 128 || (r?.height || 0) < 128) return false;
                    const src = img.getAttribute('src') || img.currentSrc || '';
                    const srcset = img.getAttribute('srcset') || '';
                    return !!(src || srcset);
                  }}

                  for (const img of candidates) {{
                    if (isContentImage(img)) {{
                      console.log('Found valid content image');
                      return true;
                    }}
                  }}
                  console.log('No valid content image found yet');
                  return false;
                }}
                """,
                timeout=15000,
            )
            logger.debug("Main image found successfully")
            return True
        except PlaywrightTimeoutError:
            logger.warning("Timeout waiting for main image")
            return False

    async def _extract_metadata(self, page) -> DirectPostMetadata:
        # Generate selector chains from config
        img_chain = get_js_selector_chain(MAIN_IMAGE_SELECTORS)
        username_selectors = get_selector_list(USERNAME_SELECTORS)
        verified_chain = get_js_selector_chain(VERIFIED_BADGE_SELECTORS)
        caption_chain = get_js_selector_chain(CAPTION_SELECTORS)
        
        logger.debug(f"Image selector chain: {img_chain}")
        
        # Build JavaScript with selectors from config
        js = f"""
        () => {{
          function q(sel){{ 
            try {{ 
              return document.querySelector(sel); 
            }} catch(e) {{ 
              console.error('Selector error:', sel, e); 
              return null; 
            }}
          }}
          function qa(sel){{ 
            try {{
              return Array.from(document.querySelectorAll(sel)); 
            }} catch(e) {{
              console.error('Selector error:', sel, e);
              return [];
            }}
          }}

          const result = {{
            author: null,
            verified: false,
            published_on: null,
            likes: null,
            caption: null,
            image_url: null,
            image_alt: null,
          }};

          // IMAGE SELECTOR from config
          const img = {img_chain};
          if (img) {{
            result.image_url = img.getAttribute('src');
            result.image_alt = (img.getAttribute('alt') || img.alt || null);
            console.log('Found image:', result.image_url ? 'YES' : 'NO');
          }} else {{
            console.log('No image found with selectors');
          }}

          // USERNAME: extract from href pattern (tier 1) or class (tier 2)
          const userLinks = qa('{username_selectors[0]}');
          for (const link of userLinks) {{
            const href = link.getAttribute('href');
            if (!href) continue;
            // Exclude /p/, /reel/, /tv/, /accounts/, etc.
            if (href.match(/^\\/[a-zA-Z0-9._]+\\/$/) && !href.match(/\\/(p|reel|tv|accounts|explore|stories)\\//)) {{
              if (href.length < 30) {{
                result.author = href.replace(/\\//g, '');
                break;
              }}
            }}
          }}
          // Fallback to class selector if available
          if (!result.author && '{username_selectors[1] if len(username_selectors) > 1 else ''}') {{
            const spans = qa('{username_selectors[1] if len(username_selectors) > 1 else ''}');
            for (const s of spans) {{
              const t = (s.textContent || '').trim();
              if (!t) continue;
              if (/^[A-Za-z0-9._]+$/.test(t)) {{ result.author = t; break; }}
            }}
          }}

          // VERIFIED BADGE from config
          const verifiedSvg = {verified_chain};
          result.verified = !!verifiedSvg;

          // TIMESTAMP from config
          const timeEl = q('{TIMESTAMP_SELECTOR}');
          if (timeEl) {{
            result.published_on = timeEl.getAttribute('datetime');
          }}

          // LIKES from config
          const likesLink = q('{LIKES_SELECTOR}');
          if (likesLink) {{
            const num = likesLink.textContent.replace(/[,.]/g, '');
            const n = parseInt(num, 10);
            if (!Number.isNaN(n)) result.likes = n;
          }}

          // CAPTION from config
          let caption = null;
          let capEl = {caption_chain};
          if (capEl) {{
            caption = (capEl.textContent || '').trim();
          }}
          // Fallback to image alt
          if (!caption && result.image_alt) caption = result.image_alt;
          result.caption = caption;

          return result;
        }}
        """
        try:
            data = await page.evaluate(js)
            logger.debug(f"Metadata extraction result: image_url={data.get('image_url') is not None}, author={data.get('author')}")
            meta = DirectPostMetadata(**data)
            
            if not meta.image_url:
                logger.error("Metadata extraction failed: image_url is None")
                logger.debug(f"Full metadata: {data}")
            
            return meta
        except Exception as e:
            logger.error(f"JavaScript evaluation failed: {e}")
            logger.debug(f"JavaScript that failed:\n{js}")
            raise

    async def _extract_all_images(self, page) -> List[Dict[str, Optional[str]]]:
        """Collect all image URLs (and alt when available) from the post."""
        try:
            collected_images: List[Dict[str, Optional[str]]] = []
            seen_urls: set = set()

            # Generate selector chain from config
            img_selector_chain = get_js_selector_chain(MAIN_IMAGE_SELECTORS)
            
            js_extract = f"""
            () => {{
              const q = (s)=>document.querySelector(s);
              // Robust selectors from config: hierarchy and attributes over class names
              const img = {img_selector_chain};
              if (!img) return [];
              const src = img.getAttribute('src');
              const alt = img.getAttribute('alt') || img.alt || null;
              return src ? [{{ url: src, alt }}] : [];
            }}
            """

            # Click/hover on main image container to ensure it's active
            try:
                # Use container selectors from config
                container_selector = get_playwright_selector(IMAGE_CONTAINER_SELECTORS)
                await page.locator(container_selector).first.click()
            except Exception:
                pass
            try:
                # Hover on main image to trigger any lazy loading
                main_img_selector = get_playwright_selector(MAIN_IMAGE_SELECTORS)
                await page.locator(main_img_selector).first.hover()
            except Exception:
                pass

            first_imgs = await page.evaluate(js_extract)
            for it in first_imgs:
                url = it.get('url') if isinstance(it, dict) else None
                alt = it.get('alt') if isinstance(it, dict) else None
                if url and url not in seen_urls:
                    print(f"[carousel] Found first image: {url}", flush=True)
                    seen_urls.add(url)
                    collected_images.append({'url': url, 'alt': alt})

            max_slides = 20
            slide_count = 0
            consecutive_no_new = 0  # Track consecutive clicks with no new images
            first_image_url = collected_images[0]['url'] if collected_images else None

            while slide_count < max_slides:
                try:
                    # Use Next button selector from config
                    next_selector = get_playwright_selector(CAROUSEL_NEXT_SELECTORS)
                    next_locator = page.locator(next_selector).first
                    await next_locator.wait_for(state="visible", timeout=3000)
                    prev_list = list(seen_urls)
                    await next_locator.click()
                    try:
                        # Generate selector chain for wait function
                        wait_img_chain = get_js_selector_chain(MAIN_IMAGE_SELECTORS)
                        await page.wait_for_function(
                            f"""
                            (prev) => {{
                              const q = (s)=>document.querySelector(s);
                              // Robust selectors from config
                              const img = {wait_img_chain};
                              if (!img) return false;
                              const src = img.getAttribute('src');
                              return src && !prev.includes(src);
                            }}
                            """,
                            arg=prev_list,
                            timeout=4000,
                        )
                    except Exception:
                        pass

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
                            consecutive_no_new = 0  # Reset counter on success
                        elif url == first_image_url:
                            # Detected loop back to first image
                            print("[carousel] Looped back to first image, ending carousel navigation.", flush=True)
                            break
                    
                    if not added:
                        consecutive_no_new += 1
                        print(f"[carousel] No new image detected after Next click (attempt {consecutive_no_new}/2).", flush=True)
                        if consecutive_no_new >= 2:
                            # If we get no new images twice in a row, we've reached the end or looped
                            print("[carousel] No new images after 2 consecutive clicks, ending carousel navigation.", flush=True)
                            break
                    
                    slide_count += 1
                except PlaywrightTimeoutError:
                    logger.info("No Next button found, reached last slide.")
                    break
                except Exception as e:
                    logger.warning(f"Carousel navigation click failed: {e}")
                    break

            return collected_images

        except Exception as e:
            logger.warning(f"Error extracting images: {e}")
            return []
