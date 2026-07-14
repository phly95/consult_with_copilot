#!/usr/bin/env python3
"""Find the real 'continue conversation' links from the main API page."""
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto("https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotroot-post-conversations",
              wait_until="domcontentloaded", timeout=30000)
    page.wait_for_timeout(4000)

    # Get all links on the page
    links = page.eval_on_selector_all('a[href]', 'els => els.map(e => ({text: e.textContent.trim().substring(0,100), href: e.href}))')

    # Find links to other chat API pages
    api_links = [l for l in links if '/chat/' in l.get('href', '').lower() and '#' not in l['href'] and 'overview' not in l['href']]
    seen = set()
    for l in api_links:
        if l['href'] not in seen:
            seen.add(l['href'])
            print(f"  {l['text'][:60]:60s} -> {l['href']}")

    # Also find related content links at the bottom
    print("\nAll page links (first 30):")
    seen2 = set()
    count = 0
    for l in links:
        if l['href'] not in seen2 and 'learn.microsoft.com' in l['href']:
            seen2.add(l['href'])
            print(f"  {l['text'][:60]:60s} -> {l['href']}")
            count += 1
            if count >= 30:
                break

    browser.close()
