import os
import json
import time
import logging
from playwright.sync_api import sync_playwright
from .prompts import GEMINI_GRADING_PROMPT

logger = logging.getLogger(__name__)

class GeminiBrowserGrader:
    def __init__(self, session_dir, playwright_instance=None):
        self.session_dir = session_dir
        self.playwright = playwright_instance
        self.browser = None
        self.context = None
        self.page = None
        self._owns_playwright = False
        self._init_browser()

    def _init_browser(self):
        try:
            if not self.playwright:
                self.playwright = sync_playwright().start()
                self._owns_playwright = True
            # Launch persistent context to reuse user login
            gemini_session_dir = os.path.join(self.session_dir, 'gemini')
            os.makedirs(gemini_session_dir, exist_ok=True)
            self.context = self.playwright.chromium.launch_persistent_context(
                user_data_dir=gemini_session_dir,
                headless=False, # Keep it visible for login check & debugging
                args=["--disable-blink-features=AutomationControlled"]
            )
            self.page = self.context.new_page()
            self.page.set_default_timeout(45000)
            
            # Go to Gemini and check login
            logger.info("Opening gemini.google.com in browser...")
            self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
            time.sleep(3)
            
            # If not logged in (chat input not found), wait for manual login
            chat_input_exists = self.page.query_selector("div[contenteditable='true']") or self.page.query_selector("rich-textarea")
            if not chat_input_exists:
                logger.warning("User is not logged into Gemini. Pausing to allow manual login...")
                print("\n" + "!"*60)
                print("ACTION REQUIRED: Please log into Google/Gemini in the opened browser window.")
                print("Once logged in, the scraper will continue automatically.")
                print("!"*60 + "\n")
                
                # Poll until logged in (chat input becomes available)
                while not (self.page.query_selector("div[contenteditable='true']") or self.page.query_selector("rich-textarea")):
                    time.sleep(2)
                logger.info("Login detected. Proceeding...")

        except Exception as e:
            logger.error(f"Failed to initialize Gemini Browser: {e}")
            self.close()
            raise e

    def _send_prompt_and_get_response(self, prompt, media_path=None) -> dict | None:
        try:
            # Ensure we are on the main Gemini app page
            if not self.page.url.startswith("https://gemini.google.com/app"):
                self.page.goto("https://gemini.google.com/app", wait_until="domcontentloaded")
                time.sleep(2)

            # Upload file if provided (Instagram media)
            if media_path:
                logger.info(f"Uploading media via browser: {media_path}")
                uploaded = False

                # Click the attachment button and use file chooser
                upload_btn = None
                # List of candidate selectors for the upload/attach button
                upload_selectors = [
                    "button[aria-label*='Upload & tools']",
                    "button[aria-label*='Add files']",
                    "button[aria-label*='Attach']",
                    "button[aria-label*='Upload']",
                    "button[aria-label*='Plus']",
                    "button[aria-label*='plus']",
                    "button.uploader-button",
                    "div[aria-label*='Attach'] button",
                    "//button[contains(@aria-label, 'Upload')]",
                    "//button[contains(@aria-label, 'Add')]",
                    "//button[contains(@aria-label, 'Attach')]",
                ]
                
                # Try to find the button
                for sel in upload_selectors:
                    try:
                        btn = self.page.wait_for_selector(sel, timeout=1500)
                        if btn and btn.is_visible():
                            upload_btn = btn
                            logger.info(f"Found attachment button using selector: {sel}")
                            break
                    except Exception:
                        pass

                if upload_btn:
                    try:
                        logger.info("Clicking main upload button to open dropdown...")
                        upload_btn.click()
                        time.sleep(1.5)

                        # Locate sub-menu button: "Upload files"
                        sub_btn = None
                        for sub_sel in [
                            "button[role='menuitem']:has-text('Upload files')",
                            "button[aria-label*='Upload files']",
                            "[role='menuitem'][aria-label*='Upload files']",
                            "button:has-text('Upload files')",
                            "span:has-text('Upload files')",
                            "//button[contains(., 'Upload files')]",
                            "//span[contains(text(), 'Upload files')]",
                            "//li[contains(., 'Upload files')]",
                        ]:
                            try:
                                btn = self.page.wait_for_selector(sub_sel, timeout=1500)
                                if btn and btn.is_visible():
                                    sub_btn = btn
                                    logger.info(f"Found sub-menu upload option: {sub_sel}")
                                    break
                                elif btn:
                                    sub_btn = btn
                                    logger.info(f"Found sub-menu option (fallback check): {sub_sel}")
                                    break
                            except Exception:
                                pass

                        if sub_btn:
                            logger.info("Clicking sub-menu upload option and waiting for file chooser...")
                            with self.page.expect_file_chooser(timeout=6000) as fc_info:
                                sub_btn.click()
                            file_chooser = fc_info.value
                            file_chooser.set_files(media_path)
                            logger.info("Successfully uploaded file via FileChooser")
                            uploaded = True
                        else:
                            logger.warning("Could not find 'Upload files' option in the menu. Trying direct file input fallback.")
                            file_input = self.page.wait_for_selector("input[type='file']", timeout=3000)
                            if file_input:
                                file_input.set_input_files(media_path)
                                logger.info("Successfully set files on fallback input[type='file']")
                                uploaded = True
                    except Exception as click_err:
                        logger.error(f"Menu-based upload failed: {click_err}")

                if not uploaded:
                    logger.error("Failed to upload media file to Gemini Browser Grader.")
                    return None

                # Wait for the file to be processed/rendered in the UI
                logger.info("Waiting for file upload/processing in Gemini UI...")
                try:
                    # Wait up to 15s for the attachment chip to appear
                    self.page.wait_for_selector("gem-media-attachment, [class*='attachment'], mat-chip", timeout=15000)
                    logger.info("Attachment element appeared. Waiting for upload to complete...")
                    
                    # Wait up to 90s for the upload spinner/loading class to disappear
                    upload_settled = False
                    for _ in range(180): # 180 * 0.5s = 90s
                        loading_indicator = self.page.query_selector(
                            "gem-media-attachment .loading, "
                            "[class*='attachment'] .loading, "
                            ".gem-attachment-loading-container, "
                            "mat-spinner, "
                            "mat-progress-bar"
                        )
                        if not loading_indicator:
                            upload_settled = True
                            break
                        time.sleep(0.5)
                        
                    if upload_settled:
                        logger.info("File upload completed successfully!")
                    else:
                        logger.warning("File upload wait timed out, but proceeding anyway.")
                except Exception as wait_err:
                    logger.warning(f"Error while waiting for file attachment: {wait_err}")
                
                time.sleep(2)

            # Fill chat input
            logger.info("Entering grading prompt into Gemini chat...")
            chat_input = None
            for sel in ["div[contenteditable='true']", "rich-textarea", "textarea", "[role='textbox']"]:
                try:
                    elem = self.page.wait_for_selector(sel, timeout=3000)
                    if elem and elem.is_visible():
                        chat_input = elem
                        logger.info(f"Found chat input using: {sel}")
                        break
                except Exception:
                    pass

            if not chat_input:
                logger.error("Could not find chat input box on Gemini page.")
                return None

            chat_input.focus()
            self.page.keyboard.insert_text(prompt)
            time.sleep(1.5)

            # Click send
            send_btn = None
            for sel in [
                "button[aria-label*='Send message']",
                "button[aria-label*='Send']",
                "button[aria-label*='Submit']",
                "button[aria-label*='send']",
                "button.send-button",
                "button.send-icon-container",
                "//button[contains(@aria-label, 'Send')]",
                "//button[contains(@aria-label, 'send')]",
            ]:
                try:
                    btn = self.page.wait_for_selector(sel, timeout=2000)
                    if btn and btn.is_visible():
                        send_btn = btn
                        logger.info(f"Found send button using: {sel}")
                        break
                except Exception:
                    pass

            if send_btn:
                send_btn.hover()
                send_btn.click()
                logger.info("Message sent via clicking Send button.")
            else:
                logger.warning("Send button not found or not visible. Trying keyboard Enter.")
                self.page.keyboard.press("Enter")

            try:
                self.page.screenshot(path=r"C:\Users\Omkar\.gemini\antigravity\brain\4d576b99-3e5c-4c56-8f89-cf52d31f862b\scratch\post_send_click.png")
            except:
                pass

            logger.info("Message sent. Waiting for response...")
            time.sleep(6) # initial wait

            # Wait for response to finish generating
            response_selectors = [
                ".model-response-text",
                ".message-content",
                "message-content",
                ".model-response",
                "model-response",
                "[data-test-id='model-response']",
            ]
            
            response_selector = None
            for sel in response_selectors:
                try:
                    if self.page.locator(sel).count() > 0:
                        response_selector = sel
                        logger.info(f"Found active response selector: {sel}")
                        break
                except Exception:
                    pass

            if not response_selector:
                for sel in response_selectors:
                    try:
                        self.page.wait_for_selector(sel, timeout=6000)
                        response_selector = sel
                        logger.info(f"Found response selector after wait: {sel}")
                        break
                    except Exception:
                        pass

            if not response_selector:
                logger.error("Could not find any Gemini response element on the page.")
                try:
                    self.page.screenshot(path=r"C:\Users\Omkar\.gemini\antigravity\brain\4d576b99-3e5c-4c56-8f89-cf52d31f862b\scratch\response_not_found.png")
                except:
                    pass
                return None
            
            # Wait for text to settle (indicating generation is done)
            last_text = ""
            for _ in range(45): # max 90s
                time.sleep(2)
                responses = self.page.query_selector_all(response_selector)
                if responses:
                    current_text = responses[-1].inner_text().strip()
                    if current_text and current_text == last_text and len(current_text) > 10:
                        break
                    last_text = current_text

            # Extract response text
            responses = self.page.query_selector_all(response_selector)
            if not responses:
                logger.error("Could not find Gemini response element after generation")
                return None
            
            raw_response = responses[-1].inner_text().strip()
            
            # Parse JSON robustly
            start = raw_response.find('{')
            end = raw_response.rfind('}')
            if start != -1 and end != -1:
                json_str = raw_response[start:end+1]
                return json.loads(json_str)
            else:
                logger.error("No JSON block found in Gemini browser response")
                return None

        except Exception as e:
            logger.error(f"Error during browser grading: {e}")
            return None

    def grade_youtube(self, video_url, title='') -> dict | None:
        prompt = f"{GEMINI_GRADING_PROMPT}\n\nContent to analyze:\nTitle: {title}\nYouTube URL: {video_url}\n\nAnalyze this YouTube video and grade it."
        return self._send_prompt_and_get_response(prompt)

    def grade_instagram(self, media_path, title='') -> dict | None:
        prompt = f"{GEMINI_GRADING_PROMPT}\n\nContent to analyze:\nCaption/Title: {title}\n\nAnalyze this Instagram content and grade it."
        return self._send_prompt_and_get_response(prompt, media_path=media_path)

    def close(self):
        try:
            if self.context:
                try:
                    self.context.close()
                except Exception as e:
                    if "Event loop is closed" not in str(e):
                        logger.warning(f"Error closing browser context: {e}")
                self.context = None
            if self.playwright and getattr(self, '_owns_playwright', True):
                try:
                    self.playwright.stop()
                except Exception as e:
                    if "Event loop is closed" not in str(e):
                        logger.warning(f"Error stopping playwright: {e}")
                self.playwright = None
            logger.info("Gemini Browser closed.")
        except Exception as e:
            logger.error(f"Error closing Gemini Browser: {e}")
