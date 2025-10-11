#!/usr/bin/env python3
"""
Instagram Direct extractor composition.
Keeps the public class name: InstagramDirectExtractor.
"""
from halal_image_downloader.extractors.base_extractor import BaseExtractor
from .core import DirectCoreMixin, DirectPostMetadata
from .media import DirectMediaMixin
from .overlays import DirectOverlaysMixin
from .navigate_download import DirectNavigateDownloadMixin


class InstagramDirectExtractor(DirectNavigateDownloadMixin, DirectCoreMixin, BaseExtractor):
    pass


__all__ = ["InstagramDirectExtractor", "DirectPostMetadata"]
