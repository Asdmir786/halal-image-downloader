"""
Extractors package for halal-image-downloader

This package contains platform-specific extractors for downloading images
from various social media platforms.
"""

from .base_extractor import BaseExtractor
from .instagram import InstagramExtractor
from .pinterest import PinterestExtractor
from .reddit import RedditExtractor
from .twitter import TwitterExtractor

__all__ = ['BaseExtractor', 'InstagramExtractor', 'PinterestExtractor', 'RedditExtractor', 'TwitterExtractor']
