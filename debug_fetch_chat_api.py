#!/usr/bin/env python3
"""Fetch Chat and Chat over stream API pages."""
from playwright.sync_api import sync_playwright

def fetch(url):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        page.wait_for_timeout(3000)
        text = page.inner_text("main") if page.locator("main").count() > 0 else page.inner_text("body")
        browser.close()
        return text

pages = [
    ("CHAT (sync)", "https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chat"),
    ("CHAT OVER STREAM", "https://learn.microsoft.com/en-us/microsoft-365/copilot/extensibility/api/ai-services/chat/copilotconversation-chatoverstream"),
]

for label, url in pages:
    text = fetch(url)
    print(f"\n{'='*60}")
    print(f"{label}")
    print(f"{'='*60}")
    print(text[:8000])
