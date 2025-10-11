#!/usr/bin/env python3
"""
Pinterest subpackage exposing a modular PinterestExtractor composed of mixins.
This mirrors the Instagram extractor structure without changing behavior.
"""
from halal_image_downloader.extractors.base_extractor import BaseExtractor
from .core import PinterestCoreMixin
from .parse import PinterestParseMixin
from .images import PinterestImagesMixin


class PinterestExtractor(PinterestImagesMixin, PinterestParseMixin, PinterestCoreMixin, BaseExtractor):
    pass


__all__ = ["PinterestExtractor"]
