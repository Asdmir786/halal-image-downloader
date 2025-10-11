#!/usr/bin/env python3
"""
SaveClip-based Instagram extractor composition.
Keeps the public class name: InstagramExtractor.
"""
from halal_image_downloader.extractors.base_extractor import BaseExtractor
from .core import SaveClipCoreMixin
from .navigation import SaveClipNavigationMixin
from .analysis import SaveClipAnalysisMixin


class InstagramExtractor(SaveClipAnalysisMixin, SaveClipNavigationMixin, SaveClipCoreMixin, BaseExtractor):
    pass


__all__ = ["InstagramExtractor"]
