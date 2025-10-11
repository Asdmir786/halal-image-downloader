#!/usr/bin/env python3
"""
Twitter/X.com subpackage exposing a modular TwitterExtractor composed of mixins.
Mirrors the Instagram/Pinterest/Reddit structure without changing behavior.
"""
from halal_image_downloader.extractors.base_extractor import BaseExtractor
from .core import TwitterCoreMixin
from .parse import TwitterParseMixin
from .images import TwitterImagesMixin


class TwitterExtractor(TwitterImagesMixin, TwitterParseMixin, TwitterCoreMixin, BaseExtractor):
    pass


__all__ = ["TwitterExtractor"]
