"""
Pinterest extractor for halal-image-downloader

This module handles extraction of images from Pinterest pins, boards, and profiles.
"""

import re
import json
from typing import List, Dict, Any, Optional
from urllib.parse import urlparse
import requests
from bs4 import BeautifulSoup

from .base_extractor import (
    BaseExtractor, logger,
    ExtractorError, TemporaryError, PermanentError,
    RateLimitError, ServiceUnavailableError, InvalidUrlError, NetworkError
)


class PinterestExtractor(BaseExtractor):
    """Extractor for Pinterest content."""
    
    def __init__(self, max_retries: int = 3):
        # Initialize base extractor
        super().__init__(max_retries=max_retries)
        
        # Pinterest-specific settings
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': self.ua.random,
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1'
        })
    
    @staticmethod
    def is_valid_url(url: str) -> bool:
        """Check if the URL is a valid Pinterest URL."""
        pinterest_patterns = [
            r'https?://(?:www\.)?pinterest\.com/pin/[0-9]+/?',
            r'https?://(?:www\.)?pinterest\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+/?',
            r'https?://(?:www\.)?pinterest\.com/[A-Za-z0-9_.-]+/?',
        ]
        
        return any(re.match(pattern, url) for pattern in pinterest_patterns)
    
    
    def extract_pin_id(self, url: str) -> Optional[str]:
        """Extract pin ID from Pinterest URL."""
        match = re.search(r'/pin/([0-9]+)', url)
        return match.group(1) if match else None

    # --------------------
    # Fetch and parse utils
    # --------------------

    def _fetch_html_impl(self, url: str) -> str:
        """Implementation of HTML fetching (without retry logic)."""
        # Use fresh user agent for each request
        headers = self.get_fresh_headers(self.session.headers)
        
        try:
            resp = self.session.get(url, headers=headers, timeout=30)
            resp.raise_for_status()
            return resp.text
        except requests.exceptions.RequestException as e:
            # Let the classify_error method handle the specific error type
            raise
    
    def _fetch_html(self, url: str) -> str:
        """Fetch HTML with retry logic."""
        return self.retry_with_backoff_sync(self._fetch_html_impl, url)

    def _extract_meta_signals(self, soup: BeautifulSoup) -> Dict[str, Any]:
        """Extract key OpenGraph/Twitter meta signals for type detection."""
        metas = {
            'og:video': None,
            'og:video:url': None,
            'og:video:secure_url': None,
            'twitter:card': None,
            'twitter:player': None,
        }
        for tag in soup.find_all('meta'):
            prop = tag.get('property') or tag.get('name')
            if not prop:
                continue
            prop = prop.strip().lower()
            if prop in metas:
                metas[prop] = tag.get('content')
        return metas

    def _extract_ld_json(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Collect JSON-LD objects from the page."""
        items: List[Dict[str, Any]] = []
        for script in soup.find_all('script', attrs={'type': 'application/ld+json'}):
            try:
                data = json.loads(script.string or script.text or '{}')
                if isinstance(data, list):
                    items.extend([d for d in data if isinstance(d, dict)])
                elif isinstance(data, dict):
                    items.append(data)
            except Exception:
                continue
        return items

    def _extract_embedded_state(self, soup: BeautifulSoup) -> List[Dict[str, Any]]:
        """Extract Pinterest embedded JSON states (e.g., __PWS_DATA__, initial Redux).
        Returns a list of root JSON dicts to inspect.
        """
        states: List[Dict[str, Any]] = []
        # Common script ids or patterns Pinterest has used
        candidates = [
            {'id': '__PWS_DATA__'},
            {'id': 'initial-state'},
            {'id': 'react-init-state'},
        ]
        for attrs in candidates:
            node = soup.find('script', attrs=attrs)
            if node and (node.string or node.text):
                try:
                    data = json.loads(node.string or node.text)
                    if isinstance(data, dict):
                        states.append(data)
                except Exception:
                    # Sometimes Pinterest wraps JSON in JSON.parse("...")
                    raw = (node.string or node.text).strip()
                    m = re.search(r'JSON\.parse\(\"(.+?)\"\)', raw)
                    if m:
                        try:
                            unescaped = bytes(m.group(1), 'utf-8').decode('unicode_escape')
                            data = json.loads(unescaped)
                            if isinstance(data, dict):
                                states.append(data)
                        except Exception:
                            pass
        # Fallback: scan all scripts for large JSON dicts with a few known keys
        if not states:
            for script in soup.find_all('script'):
                txt = (script.string or script.text or '').strip()
                if not txt or len(txt) < 50:
                    continue
                if '__PWS_DATA__' in txt or 'resources' in txt or 'initialReduxState' in txt:
                    try:
                        data = json.loads(txt)
                        if isinstance(data, dict):
                            states.append(data)
                    except Exception:
                        continue
        return states

    # --------------------
    # Detection helpers
    # --------------------

    @staticmethod
    def _dict_get(d: Dict[str, Any], path: List[str], default=None):
        cur: Any = d
        for p in path:
            if isinstance(cur, dict) and p in cur:
                cur = cur[p]
            else:
                return default
        return cur

    @staticmethod
    def _looks_like_video_obj(obj: Dict[str, Any]) -> bool:
        # Direct video flags
        if any(k in obj for k in ('videos', 'video_list', 'video_url', 'hls')):
            return True
        # URLs with video extensions
        for k, v in obj.items():
            if isinstance(v, str) and (v.endswith('.mp4') or v.endswith('.m3u8')):
                return True
        return False

    @staticmethod
    def _best_image_from_map(images: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        # Pinterest often provides sizes: orig, 1200x, 736x, 564x, etc.
        if not isinstance(images, dict):
            return None
        prefer = ['orig', '1200x', '736x', '564x']
        candidates: List[Dict[str, Any]] = []
        for key in prefer:
            item = images.get(key)
            if isinstance(item, dict) and item.get('url'):
                return item
        # fallback: pick any dict with url
        for v in images.values():
            if isinstance(v, dict) and v.get('url'):
                candidates.append(v)
        if candidates:
            return candidates[0]
        return None

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
    
    def get_pin_info(self, url: str) -> Dict[str, Any]:
        """Extract basic information about the Pinterest pin with error handling."""
        if not self.is_valid_url(url):
            raise InvalidUrlError(f"Invalid Pinterest URL format: {url}")

        pin_id = self.extract_pin_id(url)
        if not pin_id:
            # Handle board/profile URLs
            pin_id = self._generate_id_from_url(url)

        try:
            # Fetch page to populate metadata (best-effort)
            html = self._fetch_html(url)
            soup = BeautifulSoup(html, 'html.parser')
            title = soup.title.string.strip() if soup.title and soup.title.string else f'Pinterest Pin {pin_id}'
            desc_meta = soup.find('meta', attrs={'name': 'description'})
            description = desc_meta.get('content') if desc_meta else None

            return {
                'id': pin_id,
                'url': url,
                'title': title,
                'uploader': 'unknown',
                'upload_date': None,
                'description': description,
                'images': [],
                'thumbnail': None,
                'board_name': None,
                'save_count': None,
                'comment_count': None,
                'html': html,
            }
        except Exception as e:
            logger.error(f"Error fetching pin info for {url}: {e}")
            # Re-raise to be handled by retry mechanism
            raise
    
    def _generate_id_from_url(self, url: str) -> str:
        """Generate an ID from Pinterest URL for non-pin URLs."""
        parsed = urlparse(url)
        path_parts = [part for part in parsed.path.split('/') if part]
        return '_'.join(path_parts) if path_parts else 'pinterest_content'
    
    def extract_images(self, url: str) -> List[Dict[str, Any]]:
        """Extract image URLs and metadata from Pinterest pin with comprehensive error handling."""
        try:
            pin_info = self.retry_with_backoff_sync(self.get_pin_info, url)
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
    
    def get_board_pins(self, board_url: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Extract all pins from a Pinterest board."""
        # TODO: Implement board extraction
        return []
    
    def get_profile_pins(self, profile_url: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Extract pins from a Pinterest profile."""
        # TODO: Implement profile extraction
        return []
    
    def download_image(self, image_url: str, output_path: str) -> bool:
        """Download a single image from Pinterest with retry logic."""
        try:
            return self.retry_with_backoff_sync(self._download_image_impl, image_url, output_path)
        except Exception as e:
            logger.error(f"Failed to download image after all retries: {e}")
            return False
    
    def _download_image_impl(self, image_url: str, output_path: str) -> bool:
        """Implementation of image downloading (without retry logic)."""
        try:
            # Use fresh user agent for each request
            headers = self.get_fresh_headers(self.session.headers)
            
            response = self.session.get(image_url, headers=headers, stream=True, timeout=30)
            response.raise_for_status()
            
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            return True
        except Exception as e:
            logger.error(f"Error downloading image: {e}")
            # Re-raise to be handled by retry mechanism
            raise
    
    def extract(self, url: str) -> List[Dict[str, Any]]:
        """Main extraction method - implements BaseExtractor abstract method."""
        return self.extract_images(url)
    
    def search_pins(self, query: str, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Search for pins based on a query."""
        # TODO: Implement Pinterest search
        return []
    
    def close(self):
        """Close the session."""
        self.session.close()
