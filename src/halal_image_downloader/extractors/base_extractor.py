"""
Base extractor with shared functionality for all platform extractors.

This module contains common error handling, retry logic, and utility functions
used across Instagram, Pinterest, and other platform extractors.
"""

import asyncio
import logging
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional, List, Dict, Any

from fake_useragent import UserAgent

# Set up logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Suppress verbose HTTP logs from httpx and requests
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("urllib3").setLevel(logging.WARNING)


class ExtractorError(Exception):
    """Base exception for extractor errors."""
    pass


class TemporaryError(ExtractorError):
    """Temporary error that should be retried."""
    pass


class PermanentError(ExtractorError):
    """Permanent error that should not be retried."""
    pass


class RateLimitError(TemporaryError):
    """Rate limiting detected."""
    pass


class ServiceUnavailableError(TemporaryError):
    """Service is temporarily unavailable."""
    pass


class InvalidUrlError(PermanentError):
    """Invalid or inaccessible URL."""
    pass


class NetworkError(TemporaryError):
    """Network connectivity issues."""
    pass


class BaseExtractor(ABC):
    """Base class for all platform extractors with shared functionality."""
    
    def __init__(self, strict_mode: bool = True):
        """Initialize base extractor with strict error handling."""
        # User agent management
        self.ua = UserAgent()
        
        # Strict mode - fail fast, no fallbacks
        self.strict_mode = strict_mode
        
        # Platform-specific initialization will be handled by subclasses
    
    def get_fresh_headers(self, base_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Get headers with fresh user agent."""
        headers = base_headers.copy() if base_headers else {}
        headers['User-Agent'] = self.ua.random
        return headers
    
    def classify_error(self, error: Exception) -> ExtractorError:
        """Classify errors - fail fast, no fallbacks."""
        error_msg = str(error).lower()
        
        # Network-related errors (permanent failure)
        if any(keyword in error_msg for keyword in [
            'timeout', 'connection', 'network', 'dns', 'resolve',
            'unreachable', 'refused', 'reset', 'read timed out'
        ]):
            return PermanentError(f"Network connection failed: {error}")
        
        # Rate limiting (permanent failure)
        if any(keyword in error_msg for keyword in [
            'rate limit', 'too many requests', 'throttle', 'blocked',
            'captcha', '429'
        ]):
            return PermanentError(f"Rate limited or blocked: {error}")
        
        # Service unavailable (permanent failure)
        if any(keyword in error_msg for keyword in [
            'service unavailable', '503', '502', '504', 'bad gateway',
            'server error', 'maintenance', '500'
        ]):
            return PermanentError(f"Service error: {error}")
        
        # Invalid URLs or content (permanent)
        if any(keyword in error_msg for keyword in [
            'not found', '404', 'invalid', 'private', 'deleted',
            'unavailable', 'does not exist', '403', 'forbidden'
        ]):
            return InvalidUrlError(f"Invalid URL or content: {error}")
        
        # Fail fast - no fallbacks for unknown errors
        return PermanentError(f"Extraction failed: {error}")
    
    async def execute_with_error_handling(self, func, *args, **kwargs):
        """Execute function with strict error handling - no retries, fail fast."""
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            error_type = self.classify_error(e)
            logger.error(f"Extraction failed: {error_type}")
            raise error_type
    
    def execute_with_error_handling_sync(self, func, *args, **kwargs):
        """Execute function with strict error handling - no retries, fail fast."""
        try:
            return func(*args, **kwargs)
        except Exception as e:
            error_type = self.classify_error(e)
            logger.error(f"Extraction failed: {error_type}")
            raise error_type
    
    @staticmethod
    def sanitize_filename(filename: str) -> str:
        """Sanitize filename for safe file system usage."""
        # Remove or replace invalid characters
        filename = re.sub(r'[<>:"/\\|?*]', '_', filename)
        # Remove extra spaces and dots
        filename = re.sub(r'\s+', '_', filename)
        filename = filename.strip('.')
        return filename
    
    @staticmethod
    @abstractmethod
    def is_valid_url(url: str) -> bool:
        """Check if the URL is valid for this platform."""
        pass
    
    # No abstract extraction method - each platform uses its own preferred method:
    # - InstagramExtractor: extract_with_saveclip()
    # - InstagramDirectExtractor: discover() 
    # - PinterestExtractor: extract_images()
    # - RedditExtractor: extract_images()
    # - TwitterExtractor: extract_images()
