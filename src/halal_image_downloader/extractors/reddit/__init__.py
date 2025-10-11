#!/usr/bin/env python3
"""
Reddit subpackage exposing a modular RedditExtractor composed of mixins.
Mirrors the Instagram/Pinterest structure without changing behavior.
"""
from halal_image_downloader.extractors.base_extractor import BaseExtractor
from .core import RedditCoreMixin
from .parse import RedditParseMixin
from .images import RedditImagesMixin


class RedditExtractor(RedditImagesMixin, RedditParseMixin, RedditCoreMixin, BaseExtractor):
    pass


__all__ = ["RedditExtractor"]
