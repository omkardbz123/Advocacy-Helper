import os
import json
import time
import logging
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

# Path to real Chrome — has H.264/AAC codecs (Playwright's Chromium does NOT)
CHROME_EXECUTABLE = r"C:\Program Files\Google\Chrome\Application\chrome.exe"


class InstagramAuth:
    def __init__(self, username, password, session_dir):
        self.username = username
        self.password = password
        self.session_dir = session_dir
        self.playwright = None
        self.context = None

    def is_logged_in(self, page) -> bool:
        """Check if the current page is logged into Instagram."""
        # Fastest check: are we NOT on the login page?
        if "accounts/login" in page.url:
            return False
        selectors = [
            "a[href*='/direct/inbox/']",
            "a[href*='/messages/']",
            "svg[aria-label='New post']",
            "svg[aria-label='Create']",
            "svg[aria-label='Reels']",
            "svg[aria-label='Search']",
            "svg[aria-label='Explore']",
            "svg[aria-label='Messenger']",
            "svg[aria-label='Direct']",
            "a[href='/']",  # Home link visible only when logged in
        ]
        try:
            for sel in selectors:
                if page.query_selector(sel):
                    return True
        except Exception:
            pass
        return False

    def login(self, page, stop_event=None) -> bool:
        """
        Navigate to Instagram and log in.
        Tries auto-login first; falls back to manual login with 10-minute wait.
        """
        try:
            logger.info("Navigating to instagram.com...")
            page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
            time.sleep(5)

            # Already logged in?
            if self.is_logged_in(page):
                logger.info("Already logged into Instagram via saved session.")
                return True

            logger.info("Not logged in. Attempting auto-login with credentials...")
            has_credentials = bool(
                self.username and self.username.strip()
                and self.password and self.password.strip()
            )

            if has_credentials:
                try:
                    # Dismiss cookie consent if present
                    for btn_text in ["Allow all cookies", "Accept All", "Allow essential and optional cookies"]:
                        btn = page.query_selector(f"button:has-text('{btn_text}')")
                        if btn:
                            btn.click()
                            time.sleep(1)
                            break

                    username_input = page.wait_for_selector("input[name='username']", timeout=8000)
                    password_input = page.wait_for_selector("input[name='password']", timeout=8000)

                    if username_input and password_input:
                        username_input.fill(self.username)
                        time.sleep(0.5)
                        password_input.fill(self.password)
                        time.sleep(0.5)

                        login_btn = page.wait_for_selector("button[type='submit']", timeout=5000)
                        if login_btn:
                            login_btn.click()
                            logger.info("Credentials submitted. Waiting for redirect...")
                            time.sleep(8)  # Wait for 2FA / redirect

                except Exception as e:
                    logger.warning(f"Auto-login failed: {e}. Falling back to manual login.")

            # Check again after auto-login attempt
            if self.is_logged_in(page):
                logger.info("Auto-login successful!")
                return True

            # Manual login fallback — wait up to 10 minutes
            logger.warning("Not logged in. Waiting for manual login in browser window...")
            print("\n" + "!" * 60)
            print("ACTION REQUIRED: Please log into Instagram manually")
            print("in the opened browser window. The scraper will")
            print("continue automatically once you are logged in.")
            print("!" * 60 + "\n")

            for attempt in range(300):  # 300 × 2s = 10 minutes
                if stop_event and stop_event.is_set():
                    logger.info("Aborted waiting for manual Instagram login by stop request.")
                    return False
                time.sleep(2)
                if self.is_logged_in(page):
                    logger.info("Manual login detected!")
                    time.sleep(3)  # Let page fully settle
                    return True
                if attempt % 15 == 0 and attempt > 0:
                    logger.info(f"Still waiting for manual Instagram login... ({attempt * 2}s)")

            logger.error("Timed out waiting for manual Instagram login.")
            return False

        except Exception as e:
            logger.error(f"Error during Instagram login: {e}")
            return False

    def export_cookies_for_ytdlp(self, page) -> str | None:
        """
        Export browser cookies in Netscape format for yt-dlp --cookies flag.
        Returns path to the cookies file, or None on failure.
        """
        try:
            cookies = page.context.cookies()
            cookies_path = os.path.join(self.session_dir, "instagram_cookies.txt")

            with open(cookies_path, "w") as f:
                f.write("# Netscape HTTP Cookie File\n")
                f.write("# Exported by Instagram scraper for yt-dlp\n\n")
                for c in cookies:
                    domain = c.get("domain", "")
                    flag = "TRUE" if domain.startswith(".") else "FALSE"
                    secure = "TRUE" if c.get("secure", False) else "FALSE"
                    expiry = int(c.get("expires", 0))
                    if expiry < 0:
                        expiry = 0
                    name = c.get("name", "")
                    value = c.get("value", "")
                    path = c.get("path", "/")
                    f.write(f"{domain}\t{flag}\t{path}\t{secure}\t{expiry}\t{name}\t{value}\n")

            logger.info(f"Exported {len(cookies)} cookies to {cookies_path}")
            return cookies_path

        except Exception as e:
            logger.error(f"Failed to export cookies: {e}")
            return None

    def get_browser_context(self, playwright_instance):
        """
        Launch a persistent Chrome context with real codecs (H.264/AAC).
        Uses the system Chrome installation — NOT Playwright's bundled Chromium.
        This fixes 'Sorry, we're having trouble playing this video' on Instagram.
        """
        try:
            instagram_session_dir = os.path.join(self.session_dir, "instagram")
            os.makedirs(instagram_session_dir, exist_ok=True)

            launch_args = {
                "user_data_dir": instagram_session_dir,
                "headless": False,  # Must stay visible for manual login + video detection
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--autoplay-policy=no-user-gesture-required",
                    "--disable-features=VizDisplayCompositor",
                ],
            }

            # Try real Chrome first (has H.264 codec support)
            if os.path.exists(CHROME_EXECUTABLE):
                launch_args["executable_path"] = CHROME_EXECUTABLE
                logger.info(f"Using real Chrome: {CHROME_EXECUTABLE}")
            else:
                # Fallback: use Playwright's bundled Chromium with channel hint
                logger.warning("Real Chrome not found. Using Playwright Chromium (videos may not play in browser, but yt-dlp will still download them).")

            context = playwright_instance.chromium.launch_persistent_context(**launch_args)
            context.set_default_timeout(60000)
            return context

        except Exception as e:
            logger.error(f"Failed to launch browser context: {e}")
            return None
