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
    
    def __init__(self, max_retries: int = 3):
        """Initialize base extractor with common settings."""
        # User agent management
        self.ua = UserAgent()
        
        # Retry configuration
        self.max_retries = max_retries
        self.base_delay = 1.0  # Base delay in seconds
        self.max_delay = 60.0  # Maximum delay in seconds
        
        # Platform-specific initialization will be handled by subclasses
    
    def get_fresh_headers(self, base_headers: Optional[Dict[str, str]] = None) -> Dict[str, str]:
        """Get headers with fresh user agent."""
        headers = base_headers.copy() if base_headers else {}
        headers['User-Agent'] = self.ua.random
        return headers
    
    def classify_error(self, error: Exception) -> ExtractorError:
        """Classify errors to determine if they should be retried."""
        error_msg = str(error).lower()
        
        # Network-related errors (temporary)
        if any(keyword in error_msg for keyword in [
            'timeout', 'connection', 'network', 'dns', 'resolve',
            'unreachable', 'refused', 'reset', 'read timed out'
        ]):
            return NetworkError(f"Network error: {error}")
        
        # Rate limiting (temporary)
        if any(keyword in error_msg for keyword in [
            'rate limit', 'too many requests', 'throttle', 'blocked',
            'captcha', '429'
        ]):
            return RateLimitError(f"Rate limited: {error}")
        
        # Service unavailable (temporary)
        if any(keyword in error_msg for keyword in [
            'service unavailable', '503', '502', '504', 'bad gateway',
            'server error', 'maintenance', '500'
        ]):
            return ServiceUnavailableError(f"Service unavailable: {error}")
        
        # Invalid URLs or content (permanent)
        if any(keyword in error_msg for keyword in [
            'not found', '404', 'invalid', 'private', 'deleted',
            'unavailable', 'does not exist', '403', 'forbidden'
        ]):
            return InvalidUrlError(f"Invalid URL or content: {error}")
        
        # Default to temporary error for unknown issues
        return TemporaryError(f"Temporary error: {error}")
    
    async def retry_with_backoff_async(self, func, *args, **kwargs):
        """Retry a function with exponential backoff (async version)."""
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return await func(*args, **kwargs)
            except PermanentError:
                # Don't retry permanent errors
                raise
            except Exception as e:
                last_exception = e
                error_type = self.classify_error(e)
                
                if isinstance(error_type, PermanentError):
                    raise error_type
                
                if attempt == self.max_retries:
                    logger.error(f"Max retries ({self.max_retries}) exceeded. Last error: {e}")
                    break
                
                # Calculate delay with exponential backoff
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                await asyncio.sleep(delay)
        
        raise last_exception or ExtractorError("Unknown error occurred")
    
    def retry_with_backoff_sync(self, func, *args, **kwargs):
        """Retry a function with exponential backoff (sync version)."""
        last_exception = None
        
        for attempt in range(self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except PermanentError:
                # Don't retry permanent errors
                raise
            except Exception as e:
                last_exception = e
                error_type = self.classify_error(e)
                
                if isinstance(error_type, PermanentError):
                    raise error_type
                
                if attempt == self.max_retries:
                    logger.error(f"Max retries ({self.max_retries}) exceeded. Last error: {e}")
                    break
                
                # Calculate delay with exponential backoff
                delay = min(self.base_delay * (2 ** attempt), self.max_delay)
                logger.warning(f"Attempt {attempt + 1} failed: {e}. Retrying in {delay:.1f}s...")
                time.sleep(delay)
        
        raise last_exception or ExtractorError("Unknown error occurred")
    
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
    
    @abstractmethod
    def extract(self, url: str):
        """Main extraction method - must be implemented by subclasses."""
        pass
