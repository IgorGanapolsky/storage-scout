#!/usr/bin/env python3
"""
Neighbor.com Space Listing - Email Login
"""

import asyncio
import os

EMAIL = os.environ.get("NEIGHBOR_EMAIL", "")
PASSWORD = os.environ.get("NEIGHBOR_PASSWORD", "")

if not EMAIL or not PASSWORD:
    raise ValueError("Set NEIGHBOR_EMAIL and NEIGHBOR_PASSWORD environment variables")

async def list_space_on_neighbor():
    from patchright.async_api import async_playwright

    print("=" * 60)
    print("NEIGHBOR.COM - EMAIL LOGIN")
    print("=" * 60)

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=['--disable-blink-features=AutomationControlled'],
        )

        context = await browser.new_context(viewport={"width": 1280, "height": 900})
        page = await context.new_page()

        print("\n1. Going to Neighbor login...")
        await page.goto("https://www.neighbor.com/auth/register", wait_until="domcontentloaded")
        await asyncio.sleep(2)

        print("2. Clicking 'Continue with Email'...")
        try:
            await page.click('text=Continue with Email', timeout=5000)
            await asyncio.sleep(2)
        except:
            print("   Email option not found, trying direct...")

        await page.screenshot(path="/tmp/neighbor-email-form.png")

        print(f"3. Entering email: {EMAIL}")
        email_input = page.locator('input[type="email"], input[placeholder*="Email"]').first
        await email_input.fill(EMAIL)
        await asyncio.sleep(1)

        print("4. Clicking Continue...")
        await page.click('button:has-text("Continue")', timeout=5000)
        await asyncio.sleep(3)

        await page.screenshot(path="/tmp/neighbor-after-email.png")
        print(f"   URL: {page.url}")

        # Check if password field appears
        password_input = page.locator('input[type="password"]')
        if await password_input.count() > 0:
            print(f"5. Entering password...")
            await password_input.first.fill(PASSWORD)
            await asyncio.sleep(1)

            # Click login/continue
            await page.click('button:has-text("Continue"), button:has-text("Log in"), button:has-text("Sign in")', timeout=5000)
            await asyncio.sleep(3)

        await page.screenshot(path="/tmp/neighbor-logged-in.png")
        print(f"   URL: {page.url}")

        # Go to listing flow if logged in
        if "neighbor.com" in page.url and "auth" not in page.url:
            print("\n6. Starting listing flow...")
            await page.goto("https://www.neighbor.com/become-a-host/intro", wait_until="domcontentloaded")
            await asyncio.sleep(3)
            await page.screenshot(path="/tmp/neighbor-listing.png")
            print("   Screenshot: /tmp/neighbor-listing.png")

        print("\n" + "=" * 60)
        print("BROWSER OPEN - Ctrl+C when done")
        print("=" * 60)

        try:
            while True:
                await asyncio.sleep(10)
        except KeyboardInterrupt:
            pass

        await browser.close()

if __name__ == "__main__":
    asyncio.run(list_space_on_neighbor())
