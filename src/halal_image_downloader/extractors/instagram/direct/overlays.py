#!/usr/bin/env python3
from __future__ import annotations

import asyncio
from typing import Optional

from ...base_extractor import logger


class DirectOverlaysMixin:
    async def _close_any_modal(self, page) -> None:
        # Try common close buttons/dialogs
        selectors = [
            'div[role="dialog"] svg[aria-label="Close"]',
            'div[role="button"] svg[aria-label="Close"]',
            '[role="dialog"] [aria-label="Close"]',
            'button[aria-label="Close"]',
            '[aria-label="Close"]',
            # Cookie banners (click accept)
            'button:has-text("Allow all cookies")',
            'button:has-text("Allow all")',
            'button:has-text("Accept all")',
            'button:has-text("Accept")',
        ]
        try:
            # Attempt up to 3 times in case the first click doesn't take effect
            for _ in range(3):
                handled = False
                for sel in selectors:
                    try:
                        el = await page.query_selector(sel)
                        if not el:
                            continue
                        # Prefer clickable ancestor (button or role=button)
                        try:
                            ancestor = await page.evaluate_handle(
                                '(el) => el.closest("button,[role=\\"button\\"]")', el
                            )
                            anc_el = ancestor.as_element()
                        except Exception:
                            anc_el = None
                        try:
                            if anc_el:
                                await anc_el.click()
                            else:
                                await el.click()
                            await page.wait_for_timeout(500)
                            handled = True
                            break
                        except Exception:
                            continue
                    except Exception:
                        continue
                if not handled:
                    # Try pressing Escape as a generic dismiss
                    try:
                        await page.keyboard.press('Escape')
                        await page.wait_for_timeout(350)
                    except Exception:
                        pass
                    break
        except Exception:
            pass

    async def _has_modal(self, page) -> bool:
        selectors = [
            '[role="dialog"]',
            'div[role="dialog"] svg[aria-label="Close"]',
            'div[role="button"] svg[aria-label="Close"]',
            '[role="dialog"] [aria-label="Close"]',
            'button[aria-label="Close"]',
            '[aria-label="Close"]',
            'a[href*="applink.instagram.com"]',
            'text=See this post in the app',
        ]
        for sel in selectors:
            try:
                el = await page.query_selector(sel)
                if el:
                    return True
            except Exception:
                continue
        return False

    async def _try_click_continue_on_web(self, page) -> bool:
        """Detect and click the 'Continue on the web' CTA if the interstitial is present.
        Returns True if clicked, False otherwise.
        """
        # Combine all likely variations into a single locator to avoid sequential 400ms waits
        combined = ", ".join([
            "button:has-text('Continue on the web')",
            "button:has-text('Continue on web')",
            "[role=button]:has-text('Continue on the web')",
            "[role=button]:has-text('Continue on web')",
            "a:has-text('Continue on the web')",
            "a:has-text('Continue on web')",
        ])
        try:
            loc = page.locator(combined).first
            exists = (await loc.count()) > 0
            if not exists:
                # Quick text fallback (regex) without auto-wait
                text_loc = page.locator("text=/^Continue on (the )?web$/i").first
                if (await text_loc.count()) == 0:
                    return False
                loc = text_loc
            try:
                await loc.click(timeout=800)
            except Exception:
                # Try clicking a clickable ancestor
                try:
                    el = await loc.element_handle()
                    if not el:
                        return False
                    anc = await page.evaluate_handle('(el)=>el.closest("button,[role=\\"button\\"]")', el)
                    anc_el = anc.as_element()
                    if anc_el:
                        await anc_el.click(timeout=800)
                    else:
                        return False
                except Exception:
                    return False
            await page.wait_for_timeout(250)
            try:
                logger.info("Clicked 'Continue on the web'.")
            except Exception:
                pass
            return True
        except Exception:
            return False

    async def _dismiss_overlays(self, page) -> None:
        """Handle only the 'Continue on the web' interstitial by default.
        If --ig-accept-cookies is enabled, also accept cookie banners.
        """
        print("Checking for 'Continue on the web' interstitial...", flush=True)
        try:
            if await self._try_click_continue_on_web(page):
                try:
                    print("- Clicked 'Continue on the web'", flush=True)
                except Exception:
                    pass
        except Exception:
            pass

        # Optional cookie acceptance (explicit opt-in)
        if getattr(self, 'ig_accept_cookies', False):
            try:
                cookie_ctas = [
                    "button:has-text('Allow all cookies')",
                    "button:has-text('Allow all')",
                    "button:has-text('Accept all')",
                    "button:has-text('Accept')",
                    "text=/^Allow all cookies$/i",
                ]
                for sel in cookie_ctas:
                    try:
                        loc = page.locator(sel).first
                        await loc.wait_for(state="visible", timeout=700)
                        await loc.click()
                        await page.wait_for_timeout(350)
                        try:
                            print(f"- Clicked cookie CTA: {sel}", flush=True)
                        except Exception:
                            pass
                        break
                    except Exception:
                        continue
            except Exception:
                pass
