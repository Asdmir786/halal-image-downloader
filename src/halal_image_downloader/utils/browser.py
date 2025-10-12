#!/usr/bin/env python3
"""Browser management utilities for Playwright."""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger("hi-dlp")


async def launch_browser_smart(playwright_instance, browser_type: str = "chromium", headless: bool = True, **kwargs) -> Any:
    """
    Smart browser launcher that tries Chrome first, then falls back to Chromium.
    
    Priority:
    1. Try Google Chrome (system installation)
    2. Try Microsoft Edge (system installation)
    3. Fall back to Playwright's Chromium
    
    Args:
        playwright_instance: The Playwright instance (from async_playwright())
        browser_type: Browser type - "chromium", "firefox", or "webkit"
        headless: Run in headless mode
        **kwargs: Additional launch arguments
    
    Returns:
        Browser instance
    """
    engine = getattr(playwright_instance, browser_type)
    
    # For chromium, try Chrome first
    if browser_type == "chromium":
        # Try Google Chrome
        try:
            logger.info("Attempting to launch Google Chrome...")
            browser = await engine.launch(
                headless=headless,
                channel="chrome",
                **kwargs
            )
            logger.info("✓ Using Google Chrome")
            return browser
        except Exception as e:
            logger.debug(f"Chrome not available: {e}")
        
        # Try Microsoft Edge
        try:
            logger.info("Attempting to launch Microsoft Edge...")
            browser = await engine.launch(
                headless=headless,
                channel="msedge",
                **kwargs
            )
            logger.info("✓ Using Microsoft Edge")
            return browser
        except Exception as e:
            logger.debug(f"Edge not available: {e}")
        
        # Fall back to Chromium
        logger.info("Falling back to Playwright Chromium...")
        try:
            browser = await engine.launch(headless=headless, **kwargs)
            logger.info("✓ Using Playwright Chromium")
            return browser
        except Exception as e:
            logger.error(f"Failed to launch Chromium: {e}")
            logger.info("Run 'playwright install chromium' to install Playwright browsers")
            raise
    
    # For other browsers (firefox, webkit), use directly
    else:
        logger.info(f"Launching {browser_type}...")
        try:
            browser = await engine.launch(headless=headless, **kwargs)
            logger.info(f"✓ Using {browser_type}")
            return browser
        except Exception as e:
            logger.error(f"Failed to launch {browser_type}: {e}")
            logger.info(f"Run 'playwright install {browser_type}' to install")
            raise


def get_supported_browsers() -> list[str]:
    """Get list of supported browser types."""
    return ["chromium", "firefox", "webkit"]


def validate_browser_type(browser_type: str) -> str:
    """Validate and normalize browser type."""
    browser_type = browser_type.lower()
    if browser_type not in get_supported_browsers():
        raise ValueError(
            f"Unsupported browser: {browser_type}. "
            f"Supported browsers: {', '.join(get_supported_browsers())}"
        )
    return browser_type
