"""
Extractors package for halal-image-downloader

This package contains platform-specific extractors for downloading images
from various social media platforms.
"""

from .instagram import InstagramExtractor
from .pinterest import PinterestExtractor

__all__ = ['InstagramExtractor', 'PinterestExtractor']
