"""Playwright browser interaction for M365 Copilot."""

import os
import sys
import time
import fcntl
from pathlib import Path
from playwright.sync_api import sync_playwright

# Store browser profile outside the repo — never inside the project directory
PERSISTENT_DIR = Path(os.environ.get(
    "CONSULT_COPILOT_PROFILE",
    Path.home() / ".cache" / "consult_with_copilot" / "browser_profile"
))
TARGET_URL = "https://m365.cloud.microsoft/chat"


class ProfileLock:
    """File-based lock to prevent concurrent Chromium access to the same profile."""

    def __init__(self, profile_dir):
        self._path = Path(profile_dir) / ".consult_lock"
        self._fd = None

    def acquire(self):
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._fd = open(self._path, "w")
        try:
            fcntl.flock(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self._fd.close()
            self._fd = None
            raise RuntimeError(
                f"Browser profile is locked by another process. "
                f"If no other consult instance is running, delete: {self._path}"
            )

    def release(self):
        if self._fd:
            try:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
                self._fd.close()
            except OSError:
                pass
            self._fd = None

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *args):
        self.release()


class CopilotSession:
    """Manages a browser session with M365 Copilot."""

    def __init__(self, headless=True, profile_dir=None, conversation_url=None, skip_login_check=False):
        self.headless = headless
        self.profile_dir = Path(profile_dir) if profile_dir else PERSISTENT_DIR
        self.conversation_url = conversation_url
        self.skip_login_check = skip_login_check
        self._pw = None
        self._context = None
        self._page = None
        self._lock = None

    def start(self):
        """Launch browser and navigate to Copilot."""
        # Acquire profile lock to prevent concurrent access
        self._lock = ProfileLock(self.profile_dir)
        self._lock.acquire()

        self._pw = sync_playwright().start()
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir=str(self.profile_dir),
            headless=self.headless,
            viewport={"width": 1280, "height": 900},
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        self._page = (
            self._context.pages[0]
            if self._context.pages
            else self._context.new_page()
        )

        url = self.conversation_url if self.conversation_url else TARGET_URL
        self._page.goto(url, wait_until="domcontentloaded", timeout=30000)

        # Smart wait instead of networkidle (Copilot always has background connections)
        if self.conversation_url and "conversation" in self.conversation_url:
            self._wait_for_conversation()
        else:
            self._wait_for_chat_ready()

        if not self.skip_login_check:
            if "login" in self._page.url.lower() or "sign" in self._page.url.lower():
                self._release_lock()
                raise RuntimeError("Not logged in — run browser in headed mode to authenticate first")

    def stop(self):
        """Close browser and release profile lock."""
        if self._context:
            self._context.close()
        if self._pw:
            self._pw.stop()
        self._release_lock()

    def _release_lock(self):
        if self._lock:
            self._lock.release()
            self._lock = None

    def _wait_for_chat_ready(self):
        """Wait until chat input is visible (smart wait)."""
        for i in range(20):
            try:
                if self._page.locator('[contenteditable="true"]').is_visible(timeout=500):
                    return
            except:
                pass
            self._page.wait_for_timeout(500)

    def _wait_for_conversation(self):
        """Wait until conversation messages are visible."""
        for i in range(20):
            try:
                articles = self._page.locator('[role="article"]').all()
                if len(articles) >= 1:
                    return
            except:
                pass
            self._page.wait_for_timeout(500)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *args):
        self.stop()

    @property
    def page(self):
        return self._page

    def set_model(self, model="GPT 5.6 Think deeper"):
        """Set the model via the UI menu. Skips if already correct."""
        current = self.verify_model()
        if "5.6" in current and "Think" in current:
            return

        p = self._page
        p.locator('button[aria-label="Model Selector"]').first.click(timeout=5000)
        p.wait_for_timeout(1000)

        if "5.6" in model or "think" in model.lower():
            p.locator('text="GPT"').first.click(timeout=3000)
            p.wait_for_timeout(1000)
            p.locator('text="GPT 5.6 Think deeper"').first.click(timeout=3000)
        elif "quick" in model.lower():
            p.locator('text="Quick response"').first.click(timeout=3000)
        else:
            p.locator('text="Auto"').first.click(timeout=3000)

        p.wait_for_timeout(1500)

    def verify_model(self):
        """Check the currently selected model (reads button text, no click)."""
        try:
            btn = self._page.locator('button[aria-label="Model Selector"]').first
            btn.wait_for(state="visible", timeout=5000)
            return btn.inner_text().strip()
        except:
            return "unknown"

    def attach_files(self, file_paths):
        """Attach files to the chat input. Returns list of attached paths."""
        from lib.security import is_image
        attached = []
        file_input = self._page.locator('input[type="file"]').first
        paths = []
        for fp in file_paths:
            p = Path(fp)
            if not p.exists():
                print(f"Warning: {fp} not found, skipping")
                continue
            paths.append(str(p.resolve()))
        if paths:
            file_input.set_input_files(paths)
            # Wait for attachment processing — Send button stays disabled until ready
            send_btn = self._page.locator('button[aria-label="Send"]').first
            for _ in range(30):  # up to 30s
                self._page.wait_for_timeout(1000)
                try:
                    if send_btn.is_enabled(timeout=500):
                        break
                except Exception:
                    pass
            attached = paths
        return attached

    def send_message(self, text, file_paths=None, download_dir=None, max_retries=3):
        """Send a message with optional file attachments.

        Args:
            text: Message to send
            file_paths: Optional list of files to attach
            download_dir: If set, download any files Copilot generates to this dir
            max_retries: Max retries on transient errors

        Returns:
            tuple: (response_text, list_of_downloaded_file_paths)
        """
        p = self._page

        for attempt in range(max_retries):
            if file_paths:
                attached = self.attach_files(file_paths)
                if attached:
                    print(f"Attached {len(attached)} file(s)")

            chat_input = p.locator('[contenteditable="true"]').first
            chat_input.click()
            chat_input.fill(text)
            p.wait_for_timeout(500)

            send_btn = p.locator('button[aria-label="Send"]').first
            send_btn.wait_for(state="visible", timeout=5000)
            t_send = time.time()
            send_btn.click()

            # Wait for response — detect when generation completes.
            # Strategy: wait for article to appear, then wait for Stop button to disappear.
            prev_count = len(p.locator('[role="article"]').all())
            response_text = None
            last_text = ""
            stable_count = 0
            stop_seen = False
            for i in range(180):  # up to 3 min
                p.wait_for_timeout(1000)
                articles = p.locator('[role="article"]').all()
                if len(articles) > prev_count:
                    current_text = articles[-1].inner_text()
                    last_text = current_text

                    # Check if Stop button is visible (generation in progress)
                    stop_btn = p.locator('button[aria-label="Stop generating"]').all()
                    if len(stop_btn) > 0:
                        stop_seen = True
                        stable_count = 0
                        continue

                    # Stop button gone — generation may be complete
                    if stop_seen:
                        if current_text == last_text:
                            stable_count += 1
                            if stable_count >= 3:
                                response_text = current_text
                                break
                        else:
                            last_text = current_text
                            stable_count = 0
                    else:
                        # Stop button never appeared (fast response) — use stability
                        if current_text == last_text:
                            stable_count += 1
                            if stable_count >= 5 and len(current_text) > 10:
                                response_text = current_text
                                break
                        else:
                            last_text = current_text
                            stable_count = 0
                # Also check for text changes even if no new article
                elif len(articles) > 0 and last_text:
                    current_text = articles[-1].inner_text()
                    if current_text != last_text:
                        last_text = current_text
                        stable_count = 0
                        stop_btn = p.locator('button[aria-label="Stop generating"]').all()
                        if len(stop_btn) == 0 and stop_seen:
                            pass
            if not response_text and last_text:
                response_text = last_text
            if not response_text:
                articles = p.locator('[role="article"]').all()
                if articles:
                    response_text = articles[-1].inner_text()
            t_response = time.time()
            if attempt == 0:
                print(f"  Copilot response time: {t_response - t_send:.1f}s")

            # Check for transient error and retry
            if response_text and "Oops" in response_text and attempt < max_retries - 1:
                print(f"Transient error, reloading page ({attempt + 1}/{max_retries})...")
                p.reload(wait_until="domcontentloaded", timeout=30000)
                self._wait_for_chat_ready()
                p.wait_for_timeout(1000)
                continue

            # Capture conversation URL for follow-ups
            if "/conversation/" not in p.url:
                for i in range(5):
                    p.wait_for_timeout(1000)
                    if "/conversation/" in p.url:
                        break

            # Download any file attachments from the response
            downloaded = []
            if download_dir and response_text:
                dl_dir = Path(download_dir)
                dl_dir.mkdir(parents=True, exist_ok=True)
                dl_links = p.locator('a[download]').all()
                for link in dl_links:
                    try:
                        with p.expect_download(timeout=10000) as dl_info:
                            link.click()
                        dl = dl_info.value
                        save_path = dl_dir / dl.suggested_filename
                        dl.save_as(str(save_path))
                        downloaded.append(str(save_path))
                        print(f"Downloaded: {dl.suggested_filename}")
                    except Exception as e:
                        print(f"Download failed: {e}")

            return response_text, downloaded

        return None, []

    def get_conversation_id(self):
        """Extract current conversation ID from the URL."""
        url = self._page.url
        if "/conversation/" in url:
            return url.split("/conversation/")[-1].split("?")[0]
        return None
