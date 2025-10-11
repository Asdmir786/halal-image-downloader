#!/usr/bin/env python3
"""
Images mixin for Pinterest extractor: image collection and extraction orchestration.
"""
from __future__ import annotations

import re
from typing import List, Dict, Any, Optional

from bs4 import BeautifulSoup

from ..base_extractor import (
    logger,
    PermanentError,
)


class PinterestImagesMixin:
    """Provides image collection and high-level extraction for Pinterest."""

    def _collect_images_from_pinobj(self, pin: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Collect image URLs from a normalized pin-like dict, skipping any video parts."""
        results: List[Dict[str, Any]] = []

        # 1) Idea pin / story pages
        pages = pin.get('story_pin_data') or pin.get('story') or pin.get('pages')
        if isinstance(pages, list) and pages:
            idx = 1
            for page in pages:
                # skip page if video present
                if self._looks_like_video_obj(page):
                    idx += 1
                    continue
                # images could be under page.images or page.block.images
                img_map = None
                if isinstance(page, dict):
                    if 'images' in page and isinstance(page['images'], dict):
                        img_map = page['images']
                    elif 'blocks' in page and isinstance(page['blocks'], list):
                        for b in page['blocks']:
                            if isinstance(b, dict) and isinstance(b.get('images'), dict):
                                img_map = b['images']
                                break
                best = self._best_image_from_map(img_map) if img_map else None
                if best and best.get('url'):
                    results.append({'url': best['url'], 'index': idx})
                idx += 1
            return results

        # 2) Carousel items
        carousel = pin.get('carousel') or pin.get('carousel_data') or pin.get('items')
        if isinstance(carousel, list) and carousel:
            idx = 1
            for item in carousel:
                if not isinstance(item, dict):
                    idx += 1
                    continue
                if self._looks_like_video_obj(item):
                    idx += 1
                    continue
                images_map = item.get('images') if isinstance(item.get('images'), dict) else None
                best = self._best_image_from_map(images_map) if images_map else None
                if not best:
                    # sometimes nested under item.image or item.story_pin_data.images
                    if isinstance(item.get('image'), dict):
                        best = self._best_image_from_map(item['image'].get('images', {}))
                if best and best.get('url'):
                    results.append({'url': best['url'], 'index': idx})
                idx += 1
            return results

        # 3) Single image map
        images_map = pin.get('images') if isinstance(pin.get('images'), dict) else None
        best = self._best_image_from_map(images_map) if images_map else None
        if best and best.get('url'):
            results.append({'url': best['url'], 'index': 1})
        return results

    def extract_images(self, url: str) -> List[Dict[str, Any]]:
        """Extract image URLs and metadata from Pinterest pin with comprehensive error handling."""
        try:
            pin_info = self.execute_with_error_handling_sync(self.get_pin_info, url)
            html = pin_info.get('html') or self._fetch_html(url)
            soup = BeautifulSoup(html, 'html.parser')
        except PermanentError as e:
            logger.error(f"Permanent error extracting from {url}: {e}")
            return []
        except Exception as e:
            logger.error(f"Error extracting images from {url}: {e}")
            return []

        # 1) Quick meta rejection only if pure-video and no image fallback is possible
        metas = self._extract_meta_signals(soup)
        # We do not outright reject anymore; we will try to find images and skip videos.

        # 2) Parse structured data
        ld_items = self._extract_ld_json(soup)
        rooted_states = self._extract_embedded_state(soup)

        collected: List[Dict[str, Any]] = []
        video_hint = False
        image_hint = False

        def add_results(items: List[Dict[str, Any]]):
            for it in items:
                if not isinstance(it, dict):
                    continue
                url_ = it.get('url')
                idx = it.get('index')
                if url_:
                    collected.append({'url': url_, 'index': idx})

        # From JSON-LD first (ImageObject / VideoObject)
        for obj in ld_items:
            atype = obj.get('@type')
            if isinstance(atype, list):
                atypes = [a.lower() for a in atype if isinstance(a, str)]
            else:
                atypes = [atype.lower()] if isinstance(atype, str) else []
            if 'videoobject' in atypes:
                video_hint = True
                # skip, we only want images
                continue
            if 'imageobject' in atypes or obj.get('image'):
                # Normalize ImageObject
                if isinstance(obj.get('image'), dict) and obj['image'].get('url'):
                    add_results([{'url': obj['image']['url'], 'index': 1}])
                    image_hint = True
                elif isinstance(obj.get('contentUrl'), str):
                    add_results([{'url': obj['contentUrl'], 'index': 1}])
                    image_hint = True

        # From embedded Pinterest state(s)
        for state in rooted_states:
            # Heuristics: look for a pin-like object
            # Common paths observed historically (names may vary over time)
            candidates: List[Dict[str, Any]] = []
            # direct 'pin' key
            if isinstance(state.get('pin'), dict):
                candidates.append(state['pin'])
            # nested resources or redux-like structures
            for key in ('resources', 'initialReduxState', 'bootstrap', 'data'):
                sub = state.get(key)
                if isinstance(sub, dict):
                    # try common pin collections
                    for k2 in ('Pin', 'pins', 'pin', 'pinPage', 'pin_detail'):
                        v = sub.get(k2)
                        if isinstance(v, dict):
                            candidates.append(v)
                        elif isinstance(v, list):
                            candidates.extend([x for x in v if isinstance(x, dict)])

            for cand in candidates:
                # video signal at root candidate
                if isinstance(cand, dict) and self._looks_like_video_obj(cand):
                    video_hint = True
                imgs = self._collect_images_from_pinobj(cand)
                if imgs:
                    add_results(imgs)
                    image_hint = True

        # If no collected images yet, use og:image only when we don't have strong video signals
        if not collected:
            # Meta video hints
            tw_card = (metas.get('twitter:card') or '').lower()
            if metas.get('og:video') or metas.get('og:video:url') or metas.get('og:video:secure_url') or tw_card == 'player':
                video_hint = True

            if video_hint and not image_hint:
                # Detected as video-only -> do NOT download thumbnail
                return []

            # Otherwise allow og:image fallback
            og_img = soup.find('meta', attrs={'property': 'og:image'})
            if og_img and og_img.get('content'):
                collected.append({'url': og_img.get('content'), 'index': 1})

        # Normalize filenames and ordering
        pin_id = pin_info['id']
        results: List[Dict[str, Any]] = []
        # de-duplicate by URL preserving order
        seen = set()
        collected.sort(key=lambda x: (x.get('index') or 1))
        idx = 1
        for item in collected:
            url_ = item.get('url')
            if not url_ or url_ in seen:
                continue
            seen.add(url_)
            ext = 'jpg'
            m = re.search(r'\.([a-zA-Z0-9]{3,4})(?:\?|$)', url_)
            if m:
                ext = m.group(1).lower()
            filename = f"{pin_id}_{idx}.{ext}" if len(collected) > 1 else f"{pin_id}.{ext}"
            results.append({
                'url': url_,
                'filename': filename,
                'format': ext,
                'width': None,
                'height': None,
                'filesize': None,
                'quality': 'best',
            })
            idx += 1

        return results
