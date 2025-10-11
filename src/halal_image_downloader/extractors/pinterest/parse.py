#!/usr/bin/env python3
"""
Parsing and detection mixin for Pinterest extractor.
Contains meta/LD-JSON/state parsing and helper detectors.
"""
from __future__ import annotations

import re
import json
from typing import List, Dict, Any, Optional

from bs4 import BeautifulSoup


class PinterestParseMixin:
    """Provides parsing helpers and detectors for Pinterest pages."""

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
