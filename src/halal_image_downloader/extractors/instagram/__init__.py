#!/usr/bin/env python3
"""
Instagram subpackage exposing the SaveClip-based and Direct extractors.
"""
from .saveclip import InstagramExtractor
from .direct import InstagramDirectExtractor

__all__ = ["InstagramExtractor", "InstagramDirectExtractor"]
