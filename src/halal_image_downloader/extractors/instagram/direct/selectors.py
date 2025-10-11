"""Instagram Direct Extractor Selector Configuration.

This module contains all CSS/JavaScript selectors used by the Instagram
direct extractor. Keeping them here makes it easy to update when Instagram
changes their UI without touching the core extraction logic.

Philosophy:
- Use semantic selectors (aria-label, role, time) over class names
- Use structural patterns (hierarchy) over specific classes
- Provide multi-tier fallbacks for each element
- Validate extracted elements to ensure correctness

Last Updated: 2025-10-11
Based on Instagram UI analysis from: instagram-ost-specific.html
"""

from typing import List, NamedTuple


class SelectorStrategy(NamedTuple):
    """A single selector strategy with metadata.
    
    Attributes:
        selector: CSS selector string
        tier: Priority level (1=primary, 2+=fallback)
        comment: Explanation of what this selector targets and why
    """
    selector: str
    tier: int
    comment: str


# ============================================================================
# MAIN IMAGE SELECTORS
# ============================================================================

MAIN_IMAGE_SELECTORS: List[SelectorStrategy] = [
    SelectorStrategy(
        selector='main[role="main"] img[alt]:not([alt*="profile picture"])',
        tier=1,
        comment="Semantic: main tag + descriptive alt, excludes profile pics (most stable)"
    ),
    SelectorStrategy(
        selector='img[crossorigin][src]:not([alt*="profile picture"])',
        tier=2,
        comment="Attribute: crossorigin attribute indicates content image, not UI chrome"
    ),
    SelectorStrategy(
        selector='div[style*="padding-bottom"] > img[src]',
        tier=3,
        comment="Structural: Instagram uses padding-bottom for aspect-ratio containers"
    ),
    SelectorStrategy(
        selector='main img[src]',
        tier=4,
        comment="Fallback: any image in main (risky, may pick wrong image)"
    ),
]


# ============================================================================
# CAROUSEL NAVIGATION
# ============================================================================

CAROUSEL_NEXT_SELECTORS: List[SelectorStrategy] = [
    SelectorStrategy(
        selector='button[aria-label="Next"]',
        tier=1,
        comment="Semantic aria-label: Instagram's standard accessibility label"
    ),
    SelectorStrategy(
        selector='[role="button"][aria-label="Next"]',
        tier=2,
        comment="Role-based alternative for when button tag changes"
    ),
]

CAROUSEL_PREV_SELECTORS: List[SelectorStrategy] = [
    SelectorStrategy(
        selector='button[aria-label="Go back"]',
        tier=1,
        comment="Semantic aria-label for previous button"
    ),
    SelectorStrategy(
        selector='[role="button"][aria-label="Go back"]',
        tier=2,
        comment="Role-based alternative"
    ),
]


# ============================================================================
# METADATA SELECTORS
# ============================================================================

USERNAME_SELECTORS: List[SelectorStrategy] = [
    SelectorStrategy(
        selector='a[href^="/"][href$="/"]',
        tier=1,
        comment="Extract from /username/ href pattern (needs validation in JS)"
    ),
    SelectorStrategy(
        selector='span._ap3a',
        tier=2,
        comment="Class fallback: _ap3a is current class but may break on UI updates"
    ),
]

VERIFIED_BADGE_SELECTORS: List[SelectorStrategy] = [
    SelectorStrategy(
        selector='svg[aria-label="Verified"]',
        tier=1,
        comment="Exact aria-label match (most reliable)"
    ),
    SelectorStrategy(
        selector='svg[aria-label*="Verified"]',
        tier=2,
        comment="Partial match for different languages or variations"
    ),
]

# Single stable selector (no fallback needed)
TIMESTAMP_SELECTOR = 'time[datetime]'

# Contextual selector (finds span inside likes link)
LIKES_SELECTOR = 'a[href*="/liked_by/"] span'

CAPTION_SELECTORS: List[SelectorStrategy] = [
    SelectorStrategy(
        selector='main h1[dir="auto"]',
        tier=1,
        comment="H1 element in main content area with dir=auto"
    ),
    SelectorStrategy(
        selector='h1[dir="auto"]',
        tier=2,
        comment="Any H1 with dir=auto (broader match)"
    ),
]


# ============================================================================
# INTERACTION SELECTORS (for clicking/hovering)
# ============================================================================

IMAGE_CONTAINER_SELECTORS: List[SelectorStrategy] = [
    SelectorStrategy(
        selector='div[style*="padding-bottom"]',
        tier=1,
        comment="Aspect-ratio container (Instagram's padding-bottom hack)"
    ),
    SelectorStrategy(
        selector='main img[crossorigin]',
        tier=2,
        comment="Main content image with crossorigin"
    ),
]


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def get_selector_list(strategies: List[SelectorStrategy]) -> List[str]:
    """Extract just the selector strings from strategies.
    
    Args:
        strategies: List of SelectorStrategy objects
        
    Returns:
        List of selector strings in priority order
    """
    return [s.selector for s in strategies]


def get_js_selector_chain(strategies: List[SelectorStrategy]) -> str:
    """Generate JavaScript selector chain with fallbacks.
    
    Creates: q('selector1') || q('selector2') || q('selector3')
    
    Args:
        strategies: List of SelectorStrategy objects
        
    Returns:
        JavaScript expression that tries each selector in order
    """
    selectors = [s.selector for s in strategies]
    # Escape single quotes in selectors to prevent JavaScript syntax errors
    escaped_selectors = [sel.replace("'", "\\'") for sel in selectors]
    return ' || '.join(f"q('{sel}')" for sel in escaped_selectors)


def get_playwright_selector(strategies: List[SelectorStrategy]) -> str:
    """Generate Playwright multi-selector string.
    
    Creates: 'selector1, selector2, selector3'
    This allows Playwright to try all selectors at once.
    
    Args:
        strategies: List of SelectorStrategy objects
        
    Returns:
        Comma-separated selector string for Playwright
    """
    selectors = [s.selector for s in strategies]
    return ', '.join(selectors)


def get_tier_selector(strategies: List[SelectorStrategy], tier: int) -> str:
    """Get selector for a specific tier.
    
    Args:
        strategies: List of SelectorStrategy objects
        tier: Tier number to retrieve
        
    Returns:
        Selector string for that tier, or empty string if not found
    """
    for strategy in strategies:
        if strategy.tier == tier:
            return strategy.selector
    return ''


# ============================================================================
# VALIDATION RULES
# ============================================================================

class ValidationRules:
    """Constants for validating extracted elements.
    
    These rules help ensure we're extracting the right elements,
    not just any element that matches the selector.
    """
    
    # Image validation
    MIN_IMAGE_WIDTH = 200
    MIN_IMAGE_HEIGHT = 200
    
    # Username validation
    USERNAME_MAX_LENGTH = 30
    USERNAME_PATTERN = r'^[A-Za-z0-9._]+$'
    USERNAME_EXCLUDE_PATTERNS = [
        r'/(p|reel|tv|accounts|explore|stories)/',
    ]
    
    # Profile picture exclusions
    PROFILE_PIC_ALT_KEYWORDS = [
        'profile picture',
        'Profile Picture',
        'profile pic',
    ]


# ============================================================================
# EXCLUSION PATTERNS
# ============================================================================

# Patterns to exclude from main image selection
PROFILE_PICTURE_EXCLUSIONS = [
    '[alt*="profile picture"]',
    '[alt*="Profile Picture"]',
    '[alt*="profile pic"]',
]

# UI chrome elements to exclude
UI_CHROME_EXCLUSIONS = [
    'header img',
    'nav img',
    'aside img',
    'footer img',
]


# ============================================================================
# LOGGING & MONITORING
# ============================================================================

def log_selector_tier_usage(element_name: str, tier: int, logger):
    """Log when fallback selectors are used (indicates potential UI changes).
    
    Args:
        element_name: Name of the element being selected
        tier: Which tier selector was used
        logger: Logger instance to use
    """
    if tier > 1:
        logger.warning(
            f"Instagram selector fallback: '{element_name}' used tier {tier}. "
            f"Primary selector (tier 1) may have failed. "
            f"Instagram UI may have changed - consider updating selectors."
        )
    else:
        logger.debug(f"Instagram selector: '{element_name}' used primary (tier 1)")


# ============================================================================
# METADATA
# ============================================================================

SELECTOR_CONFIG_VERSION = "1.0.0"
LAST_UPDATED = "2025-10-11"
UI_ANALYSIS_SOURCE = "instagram-ost-specific.html"

__all__ = [
    # Main exports
    'SelectorStrategy',
    'MAIN_IMAGE_SELECTORS',
    'CAROUSEL_NEXT_SELECTORS',
    'CAROUSEL_PREV_SELECTORS',
    'USERNAME_SELECTORS',
    'VERIFIED_BADGE_SELECTORS',
    'TIMESTAMP_SELECTOR',
    'LIKES_SELECTOR',
    'CAPTION_SELECTORS',
    'IMAGE_CONTAINER_SELECTORS',
    
    # Helper functions
    'get_selector_list',
    'get_js_selector_chain',
    'get_playwright_selector',
    'get_tier_selector',
    
    # Validation
    'ValidationRules',
    'PROFILE_PICTURE_EXCLUSIONS',
    'UI_CHROME_EXCLUSIONS',
    
    # Utilities
    'log_selector_tier_usage',
    
    # Metadata
    'SELECTOR_CONFIG_VERSION',
]
