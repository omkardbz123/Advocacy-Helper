"""
Instagram Reels Scraper — Simple & Direct
==========================================
Flow:
  1. Open Chrome → Go to instagram.com/reels/ (or account reels)
  2. Collect all reel URLs visible in the grid
  3. For each reel: click it → yt-dlp downloads it → Gemini grades it → save → delete
  4. Scroll down → load more → repeat
"""

import os
import re
import time
import logging
import subprocess

from playwright.sync_api import Page

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# Accounts to scrape (known anti-vegan / pro-meat creators)
# ─────────────────────────────────────────────────────────────────────────────
REELS_SOURCES = [
    # Format: ("type", "value")
    # type = "feed"    → instagram.com/reels/  (For-You feed)
    ("feed",    "reels"),
]

SEED_ACCOUNTS = [s[1] for s in REELS_SOURCES if s[0] == "account"]


class InstagramReelsScraper:
    """
    Simplified direct scraper:
    Navigate → collect reel URLs from grid → download with yt-dlp → grade with Gemini.
    """

    def __init__(self, auth, grader, db_client, manager, socketio=None, stop_event=None):
        self.auth = auth
        self.grader = grader
        self.db_client = db_client
        self.manager = manager
        self.socketio = socketio
        self.stop_event = stop_event
        self._cookies_file = None

    # ─────────────── Logging ──────────────────────────────────────────────────

    def _log(self, action, detail, level="info"):
        from datetime import datetime
        self.db_client.log_activity(platform="instagram", action=action, detail=detail, level=level)
        if self.socketio:
            self.socketio.emit("scraper_log", {
                "platform": "instagram", "action": action,
                "detail": detail, "level": level,
                "timestamp": datetime.now().isoformat()
            })
        logger.info(f"[{level.upper()}] {action}: {detail}")

    def _status(self, query="", processed=0, relevant=0, irrelevant=0, running=True):
        if self.socketio:
            self.socketio.emit("scraper_status", {
                "running": running, "platform": "instagram",
                "current_query": query, "processed": processed,
                "relevant": relevant, "irrelevant": irrelevant
            })

    # ─────────────── Step 1: Collect reel URLs from a grid page ───────────────

    def _collect_reel_urls(self, page: Page, grid_url: str, max_reels: int = 30) -> list[str]:
        """
        Navigate to a reels grid page and return a list of reel post URLs.
        Scrolls the page to load more.
        """
        self._log("navigate", f"Going to: {grid_url}")
        page.goto(grid_url, wait_until="domcontentloaded")
        if self._sleep(5):
            return []

        if "login" in page.url or "accounts/login" in page.url:
            self._log("error", "Hit login wall — not logged in", "error")
            return []

        seen = set()
        urls = []

        for scroll_round in range(6):  # Scroll up to 6 times to load more
            # Grab all /reel/ or /reels/ links currently visible
            anchors = page.query_selector_all("a[href*='/reel/'], a[href*='/reels/']")
            for a in anchors:
                href = (a.get_attribute("href") or "").split("?")[0]
                m = re.search(r"/(?:reel|reels)/([^/]+)", href)
                if not m:
                    continue
                reel_id = m.group(1)
                if reel_id in seen:
                    continue
                seen.add(reel_id)
                urls.append(f"https://www.instagram.com/reel/{reel_id}/")
                if len(urls) >= max_reels:
                    break

            if len(urls) >= max_reels:
                break

            # Scroll down to load more thumbnails
            page.evaluate("window.scrollBy(0, window.innerHeight * 3)")
            if self._sleep(3):
                break

        self._log("collect", f"Found {len(urls)} reels at {grid_url}")
        return urls

    # ─────────────── Step 2: Download a reel with yt-dlp ─────────────────────

    def _download_reel(self, reel_url: str, output_path: str) -> bool:
        """
        Download an Instagram reel to output_path using yt-dlp.
        Uses cookies from the Chrome browser session for auth.
        Falls back to no-auth for public reels.
        """
        logger.info(f"Downloading: {reel_url} -> {output_path}")

        base = [
            "yt-dlp",
            "--no-warnings",
            "--no-check-certificate",
            "-f", "bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best",
            "--merge-output-format", "mp4",
            "-o", output_path,
        ]

        # Method 1: cookies from Chrome (most reliable — reads live Chrome session)
        cmd_chrome = base + ["--cookies-from-browser", "chrome", reel_url]
        try:
            r = subprocess.run(cmd_chrome, capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"Downloaded via Chrome cookies ({os.path.getsize(output_path)//1024} KB)")
                return True
            logger.warning(f"Chrome-cookie method failed: {r.stderr[-200:]}")
        except subprocess.TimeoutExpired:
            logger.warning("yt-dlp (chrome cookies) timed out")
        except Exception as e:
            logger.warning(f"yt-dlp chrome method error: {e}")

        # Method 2: cookies file exported by Playwright
        if self._cookies_file and os.path.exists(self._cookies_file):
            cmd_file = base + ["--cookies", self._cookies_file, reel_url]
            try:
                r = subprocess.run(cmd_file, capture_output=True, text=True, timeout=60)
                if r.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                    logger.info(f"Downloaded via cookies file ({os.path.getsize(output_path)//1024} KB)")
                    return True
                logger.warning(f"Cookies-file method failed: {r.stderr[-200:]}")
            except Exception as e:
                logger.warning(f"yt-dlp file method error: {e}")

        # Method 3: no auth — works for many public reels
        cmd_pub = base + [reel_url]
        try:
            r = subprocess.run(cmd_pub, capture_output=True, text=True, timeout=60)
            if r.returncode == 0 and os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
                logger.info(f"Downloaded (public, no auth) ({os.path.getsize(output_path)//1024} KB)")
                return True
            logger.error(f"All download methods failed. Last error: {r.stderr[-300:]}")
        except Exception as e:
            logger.error(f"yt-dlp public method error: {e}")

        return False

    # ─────────────── Step 3: Grade with Gemini ────────────────────────────────

    def _grade_and_save(self, reel_url: str, video_path: str, caption: str, username: str, thumbnail_url: str = None, thumbnail_base64: str = None) -> tuple[bool, bool]:
        """
        Send the downloaded video to Gemini, parse the grade, save to D1.
        Returns (success, is_relevant).
        """
        reel_id = re.search(r"/reel/([^/]+)", reel_url)
        reel_id = reel_id.group(1) if reel_id else os.path.basename(video_path)

        self._log("grade", f"Sending {reel_id} to Gemini ({os.path.getsize(video_path)//1024} KB)")

        grade = self.grader.grade_instagram(video_path, caption)
        if not grade:
            self._log("error", f"Gemini returned no grade for {reel_id}", "error")
            return False, False

        is_relevant = grade.get("relevant", False)
        grading_method = "api" if "GeminiAPI" in type(self.grader).__name__ else "browser"

        save_data = {
            "post_id": reel_id,
            "title": caption[:200] if caption else "Instagram Reel",
            "thumbnail_url": thumbnail_url,
            "thumbnail_base64": thumbnail_base64,
            "post_url": reel_url,
            "media_type": "reel",
            "username": username,
            "profile_url": f"https://www.instagram.com/{username}/",
            "published_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "grade_animal_friendly": grade.get("animal_friendly", "partial"),
            "grade_scientific": grade.get("scientific", "partial"),
            "grade_emotional_manipulation": grade.get("emotional_manipulation", "no"),
            "summary": grade.get("summary", ""),
            "raw_gemini_response": str(grade),
            "grading_method": grading_method,
            "status": "graded" if is_relevant else "skipped",
        }

        if self.db_client.instagram_exists(reel_id):
            self._log("skip", f"Reel {reel_id} already in database")
            return True, False

        if self.db_client.insert_instagram(save_data):
            animal = grade.get("animal_friendly", "?")
            self._log(
                "save",
                f"Saved reel '{caption[:40]}' | Animal-friendly: {animal} | Relevant: {is_relevant}",
                "success" if is_relevant else "info"
            )
        else:
            self._log("error", f"DB insert failed for {reel_id}", "error")

        return True, is_relevant

    # ─────────────── Step 4: Get caption from a reel page ─────────────────────

    def _sleep(self, seconds: float) -> bool:
        """Sleep for `seconds` but check `stop_event` periodically. Returns True if stopped."""
        start_time = time.time()
        while time.time() - start_time < seconds:
            if self.stop_event and self.stop_event.is_set():
                return True
            time.sleep(0.2)
        return False

    def _get_active_reel_metadata(self, page: Page) -> dict | None:
        """Extract all metadata for the currently active reel in the viewport."""
        js_code = r"""
        () => {
            const videos = Array.from(document.querySelectorAll('video'));
            if (videos.length === 0) return null;
            
            let activeVideo = null;
            let maxVisibleArea = 0;
            
            for (const video of videos) {
                const rect = video.getBoundingClientRect();
                const visibleWidth = Math.min(window.innerWidth, rect.right) - Math.max(0, rect.left);
                const visibleHeight = Math.min(window.innerHeight, rect.bottom) - Math.max(0, rect.top);
                
                if (visibleWidth > 0 && visibleHeight > 0) {
                    const area = visibleWidth * visibleHeight;
                    if (area > maxVisibleArea) {
                        maxVisibleArea = area;
                        activeVideo = video;
                    }
                }
            }
            
            // Fallback: on single reel pages, use the first video element if layout is not ready
            if (!activeVideo && videos.length > 0) {
                activeVideo = videos[0];
            }
            
            // Find the root card container (traverse up to 16 levels to find container with links)
            let root = activeVideo;
            let container = activeVideo.parentElement;
            for (let depth = 0; depth < 16 && container; depth++) {
                const hasReelLink = container.querySelector("a[href*='/reel/'], a[href*='/reels/']");
                const hasProfileLink = Array.from(container.querySelectorAll("a")).some(a => {
                    const href = a.getAttribute('href');
                    if (!href) return false;
                    const cleanHref = href.replace(/^\/|\/$/g, '');
                    const parts = cleanHref.split('/');
                    const isProfile = parts.length === 1 || (parts.length === 2 && parts[1] === 'reels');
                    return isProfile && !['explore', 'reels', 'p', 'reel', 'stories', 'direct', 'emails', 'audio', 'legal', 'developer'].includes(parts[0]);
                });
                
                if (container.tagName === 'ARTICLE' || (hasReelLink && hasProfileLink)) {
                    root = container;
                    break;
                }
                container = container.parentElement;
            }
            
            // Fallback to a high depth if root is still activeVideo
            if (root === activeVideo) {
                root = activeVideo.parentElement?.parentElement?.parentElement?.parentElement?.parentElement?.parentElement?.parentElement?.parentElement?.parentElement?.parentElement?.parentElement || activeVideo.parentElement;
            }
            
            let reelUrl = null;
            const anchors = Array.from(root.querySelectorAll("a[href*='/reel/'], a[href*='/reels/']"));
            for (const a of anchors) {
                const href = a.getAttribute('href');
                if (href) {
                    const match = href.match(/\/(?:reel|reels)\/([^/?#]+)/);
                    if (match && match[1] !== 'reels' && match[1] !== 'videos' && match[1] !== 'audio') {
                        reelUrl = `https://www.instagram.com/reel/${match[1]}/`;
                        break;
                    }
                }
            }
            
            // Fallback: use window URL on reels feed or single reel page
            if (!reelUrl) {
                const pageUrl = window.location.href;
                const match = pageUrl.match(/\/reels?\/([^/?#]+)/);
                if (match && match[1] !== 'reels' && match[1] !== 'videos' && match[1] !== 'audio') {
                    reelUrl = `https://www.instagram.com/reel/${match[1]}/`;
                }
            }
            
            // Extract username (creator username) robustly
            let username = 'unknown';
            const allAnchors = Array.from(root.querySelectorAll("a"));
            for (const a of allAnchors) {
                const href = a.getAttribute('href');
                if (!href) continue;
                const cleanHref = href.replace(/^\/|\/$/g, '');
                const parts = cleanHref.split('/');
                if (parts.length === 1 || (parts.length === 2 && parts[1] === 'reels')) {
                    const candidate = parts[0];
                    if (candidate && !['explore', 'reels', 'p', 'reel', 'stories', 'direct', 'emails', 'audio', 'legal', 'developer'].includes(candidate)) {
                        const text = a.innerText.trim();
                        if (text && !text.includes(' ') && text.length > 0) {
                            username = text.replace(/^@/, '');
                            break;
                        } else if (username === 'unknown') {
                            username = candidate;
                        }
                    }
                }
            }
            
            // If still unknown, try grabbing the first span that looks like a username near the Follow button
            if (username === 'unknown') {
                const spans = Array.from(root.querySelectorAll('span'));
                const followIndex = spans.findIndex(s => s.innerText?.trim() === 'Follow');
                if (followIndex > 0) {
                    const possibleUser = spans[followIndex - 1].innerText?.trim();
                    if (possibleUser && !possibleUser.includes(' ')) {
                        username = possibleUser;
                    }
                }
            }

            // Extract and clean caption
            let rawCaption = '';
            
            // First try h1, often used for captions in Reels
            const h1 = root.querySelector('h1');
            if (h1) {
                rawCaption = h1.innerText.trim();
            }
            
            // If no h1 or h1 is empty, try to find the longest block of text that isn't the username
            if (!rawCaption || rawCaption.length < 5) {
                const textDivs = Array.from(root.querySelectorAll('span[dir="auto"], div[dir="auto"]'));
                let longestText = '';
                for (const div of textDivs) {
                    const text = div.innerText?.trim() || '';
                    if (text.length > longestText.length && text.toLowerCase() !== username.toLowerCase() && text !== 'Follow') {
                        longestText = text;
                    }
                }
                rawCaption = longestText;
            }
            
            let cleanCaption = rawCaption;
            if (cleanCaption) {
                // Filter out non-caption lines (audio info, usernames, follow buttons)
                const lines = cleanCaption.split('\n').map(l => l.trim());
                const filteredLines = [];
                for (const line of lines) {
                    if (line.toLowerCase() === username.toLowerCase()) continue;
                    if (line === '•' || line === 'Follow' || line === 'Followed' || line.includes('• Follow') || line.includes('• Followed')) continue;
                    if (line.includes('·') || line.includes('Original audio') || line.toLowerCase().startsWith('original audio')) continue;
                    if (/^\d+[,.\d]*[KkMm]?$/.test(line)) continue; // skip pure numbers like "27.7K"
                    
                    filteredLines.push(line);
                }
                cleanCaption = filteredLines.join('\n').trim();
            }
            
            // Thumbnail extraction with circular profile avatar exclusion
            let thumbnailUrl = activeVideo.getAttribute('poster');
            if (!thumbnailUrl) {
                const imgs = Array.from(root.querySelectorAll("img"));
                
                // 1. Try to find larger images (cover images)
                for (const img of imgs) {
                    const src = img.getAttribute('src');
                    if (src && (src.includes('cdninstagram.com') || src.includes('fbcdn.net'))) {
                        const rect = img.getBoundingClientRect();
                        if (rect.width > 120 && rect.height > 120) {
                            thumbnailUrl = src;
                            break;
                        }
                    }
                }
                
                // 2. Try to find images not in headers or subheaders
                if (!thumbnailUrl) {
                    for (const img of imgs) {
                        const src = img.getAttribute('src');
                        if (src && !img.closest('header') && !img.closest('h2') && !img.classList.contains('_a3g8')) {
                            thumbnailUrl = src;
                            break;
                        }
                    }
                }
                
                // 3. Fallback to any Instagram/Facebook image
                if (!thumbnailUrl) {
                    for (const img of imgs) {
                        const src = img.getAttribute('src');
                        if (src && (src.includes('cdninstagram.com') || src.includes('fbcdn.net'))) {
                            thumbnailUrl = src;
                            break;
                        }
                    }
                }
            }
            
            return {
                url: reelUrl,
                username: username,
                caption: cleanCaption,
                thumbnail_url: thumbnailUrl
            };
        }
        """
        try:
            return page.evaluate(js_code)
        except Exception as e:
            logger.warning(f"Error evaluating active reel metadata: {e}")
            return None

    def _get_current_reel_caption_and_username(self, page: Page) -> tuple[str, str]:
        """
        Extract caption + username from the current reel view without navigating.
        """
        metadata = self._get_active_reel_metadata(page)
        if metadata:
            return metadata.get("caption", ""), metadata.get("username", "unknown")
        return "", "unknown"

    def _get_current_reel_thumbnail(self, page: Page) -> str | None:
        """Extract the thumbnail/poster URL from the current reel view."""
        metadata = self._get_active_reel_metadata(page)
        if metadata:
            return metadata.get("thumbnail_url")
        return None

    def _get_base64_from_url(self, page: Page, url: str) -> str | None:
        if not url:
            return None
        js_code = """
        async (url) => {
            try {
                const response = await fetch(url);
                const blob = await response.blob();
                return new Promise((resolve, reject) => {
                    const reader = new FileReader();
                    reader.onloadend = () => resolve(reader.result);
                    reader.onerror = reject;
                    reader.readAsDataURL(blob);
                });
            } catch (e) {
                return null;
            }
        }
        """
        try:
            return page.evaluate(js_code, url)
        except Exception as e:
            logger.warning(f"Failed to convert thumbnail to base64: {e}")
            return None

    def _get_reel_caption(self, page: Page, reel_url: str) -> tuple[str, str, str | None]:
        """
        Navigate to a reel and extract caption + username + thumbnail_url.
        Returns (caption, username, thumbnail_url).
        """
        try:
            page.goto(reel_url, wait_until="domcontentloaded")
            if self._sleep(4):
                return "", "unknown", None

            if "login" in page.url:
                return "", "unknown", None

            metadata = self._get_active_reel_metadata(page)
            if metadata:
                return metadata.get("caption", ""), metadata.get("username", "unknown"), metadata.get("thumbnail_url")
            return "", "unknown", None
        except Exception as e:
            logger.warning(f"Could not get caption for {reel_url}: {e}")
            return "", "unknown", None

    def _get_current_reel_url(self, page: Page) -> str | None:
        """Get the URL of the currently visible reel in the Reels Feed."""
        metadata = self._get_active_reel_metadata(page)
        if metadata and metadata.get("url"):
            return metadata["url"]
        return None

    def _pause_video(self, page: Page):
        """Pause the currently playing reel to prevent auto-scrolling/playing."""
        try:
            # Pause all video elements on the page to prevent autoplay/autoscroll
            page.evaluate("""
                () => {
                    const videos = Array.from(document.querySelectorAll('video'));
                    videos.forEach(v => v.pause());
                }
            """)
            logger.info("Paused the Instagram video playback to prevent auto-scroll.")
        except Exception as e:
            logger.warning(f"Could not pause video: {e}")

    def _advance_reel(self, page: Page):
        """Advance to the next reel in the Reels Feed using JS scroll or buttons."""
        try:
            # Method 1: Try JS scroll into view for the next video element (most reliable for background tasks)
            js_scroll = """
            () => {
                const videos = Array.from(document.querySelectorAll('video'));
                if (videos.length === 0) return false;
                
                let activeIndex = -1;
                let maxVisibleArea = 0;
                
                for (let i = 0; i < videos.length; i++) {
                    const rect = videos[i].getBoundingClientRect();
                    const visibleWidth = Math.min(window.innerWidth, rect.right) - Math.max(0, rect.left);
                    const visibleHeight = Math.min(window.innerHeight, rect.bottom) - Math.max(0, rect.top);
                    
                    if (visibleWidth > 0 && visibleHeight > 0) {
                        const area = visibleWidth * visibleHeight;
                        if (area > maxVisibleArea) {
                            maxVisibleArea = area;
                            activeIndex = i;
                        }
                    }
                }
                
                if (activeIndex !== -1 && activeIndex + 1 < videos.length) {
                    const nextVideo = videos[activeIndex + 1];
                    let container = nextVideo.parentElement;
                    let foundArticle = null;
                    for (let depth = 0; depth < 10 && container; depth++) {
                        if (container.tagName === 'ARTICLE') {
                            foundArticle = container;
                            break;
                        }
                        container = container.parentElement;
                    }
                    const target = foundArticle || nextVideo;
                    target.scrollIntoView({ behavior: 'smooth', block: 'start' });
                    return true;
                }
                return false;
            }
            """
            if page.evaluate(js_scroll):
                logger.info("Advanced to next reel via JS scrollIntoView.")
                return

            # Method 2: Try standard Next buttons
            advanced = False
            for sel in [
                "button[aria-label='Next']",
                "svg[aria-label='Next']",
                "div[aria-label='Next']",
                "div._aa2g button",
            ]:
                btn = page.query_selector(sel)
                if btn:
                    try:
                        btn.click()
                        advanced = True
                        break
                    except Exception:
                        pass

            if not advanced:
                # Method 3: Fallback to keyboard ArrowDown
                page.keyboard.press("ArrowDown")
                logger.info("Advanced to next reel via keyboard ArrowDown.")
        except Exception as e:
            logger.warning(f"Error advancing reel: {e}")

    # ─────────────── Main pipeline ────────────────────────────────────────────

    def run(self, playwright_instance=None):
        """
        Main entry point.
        NOTE: Always launches its own independent sync_playwright() context.
        This avoids conflicts with GeminiBrowserGrader which may be sharing
        the parent playwright_instance for Gemini grading.
        """
        from playwright.sync_api import sync_playwright as _sync_playwright

        self._log("system", "Starting Instagram Reels Scraper (direct mode)", "info")
        self._status("Initializing browser...")

        os.makedirs(self._temp_dir(), exist_ok=True)

        def _run(playwright_inst):
            ctx = self.auth.get_browser_context(playwright_inst)
            if not ctx:
                self._log("error", "Could not launch Playwright browser context.", "error")
                self._status("Launch Failed", running=False)
                return

            page = ctx.new_page()

            # ── Login ──────────────────────────────────────────────────────────
            self._status("Logging in to Instagram...")
            if not self.auth.login(page, stop_event=self.stop_event):
                self._log("error", "Instagram login failed. Aborting scraper.", "error")
                self._status("Login Failed", running=False)
                ctx.close()
                return

            # ── Export session cookies for yt-dlp ──────────────────────────────
            cookies_file = self.auth.export_cookies_for_ytdlp(page)
            if cookies_file:
                self._cookies_file = cookies_file
                self._log("system", f"Session cookies exported for yt-dlp: {cookies_file}", "info")
            else:
                self._cookies_file = None
                self._log("system", "Cookie export failed — yt-dlp will try public download only", "warning")

            total = {"processed": 0, "relevant": 0, "irrelevant": 0}

            # ── Process User Suggestion Queue Helper ──────────────────────────
            def _process_user_queue():
                processed_any = False
                while not (self.stop_event and self.stop_event.is_set()):
                    submission = self.db_client.get_next_pending_submission('instagram')
                    if not submission:
                        break
                    
                    processed_any = True
                    submission_id = submission.get('id')
                    url = submission.get('url')
                    self._log("queue", f"Found pending user submission: {url}", "info")
                    self.db_client.update_submission_status(submission_id, 'processing')
                    
                    # Process the URL
                    page.goto(url, wait_until="domcontentloaded")
                    if self._sleep(4): break
                    self._pause_video(page)
                    
                    reel_id = re.search(r"/reel/([^/]+)", url)
                    reel_id = reel_id.group(1) if reel_id else f"user_{submission_id}"
                    
                    if self.db_client.instagram_exists(reel_id):
                        self._log("skip", f"User submitted reel {reel_id} already in database. Skipping.")
                        self.db_client.update_submission_status(submission_id, 'graded')
                        continue
                        
                    total["processed"] += 1
                    self._status(query=f"Queue | {url}", processed=total["processed"], relevant=total["relevant"], irrelevant=total["irrelevant"])
                    
                    caption, username = self._get_current_reel_caption_and_username(page)
                    thumbnail_url = self._get_current_reel_thumbnail(page)
                    thumbnail_base64 = self._get_base64_from_url(page, thumbnail_url)
                    video_path = os.path.join(self._temp_dir(), f"{reel_id}.mp4")
                    
                    if not self._download_reel(url, video_path):
                        self._log("error", f"Failed to download user submitted reel: {url}", "error")
                        self.db_client.update_submission_status(submission_id, 'error')
                        continue
                        
                    success, is_relevant = self._grade_and_save(url, video_path, caption, username, thumbnail_url=thumbnail_url, thumbnail_base64=thumbnail_base64)
                    
                    try:
                        if os.path.exists(video_path): os.remove(video_path)
                    except Exception as e:
                        pass
                        
                    if success:
                        if is_relevant: total["relevant"] += 1
                        else: total["irrelevant"] += 1
                        self.db_client.update_submission_status(submission_id, 'graded')
                    else:
                        self.db_client.update_submission_status(submission_id, 'error')
                        
                return processed_any

            # Initial queue check before starting standard discovery
            _process_user_queue()

            # ── Process each source ───────────────────────────────────────────
            for source_type, val in REELS_SOURCES:
                if self.stop_event and self.stop_event.is_set():
                    self._log("system", "Scraper stopped by request", "warning")
                    break

                if source_type == "feed":
                    self._log("strategy", "Strategy: Scrolling Reels For-You feed", "info")
                    self._status(query="Reels Feed", processed=total["processed"], relevant=total["relevant"], irrelevant=total["irrelevant"])

                    # Navigate to Reels Feed
                    page.goto("https://www.instagram.com/reels/", wait_until="domcontentloaded")
                    if self._sleep(6):
                        continue

                    if "login" in page.url:
                        self._log("error", "Not logged in (redirected to login). Skipping feed scroll.", "error")
                        continue

                    # Direct feed scroll loop
                    consecutive_no_url = 0
                    seen_feed_ids = set()  # Track reel IDs already processed in this session
                    for feed_idx in range(25):  # Process up to 25 reels from feed
                        if self.stop_event and self.stop_event.is_set():
                            break

                        if self._sleep(4):  # Let video load
                            break

                        # Pause video to prevent auto-play auto-scrolling
                        self._pause_video(page)

                        url = self._get_current_reel_url(page)
                        if not url:
                            consecutive_no_url += 1
                            if consecutive_no_url > 3:
                                self._log("warning", "Could not detect reel URL multiple times. Ending feed scroll.", "warning")
                                break
                            self._advance_reel(page)
                            continue

                        consecutive_no_url = 0
                        reel_id = re.search(r"/reel/([^/]+)", url)
                        reel_id = reel_id.group(1) if reel_id else f"feed_{feed_idx}"

                        # In-memory dedup: skip if we already processed this reel in this session
                        if reel_id in seen_feed_ids:
                            self._log("skip", f"Reel {reel_id} already processed in this session. Skipping.")
                            self._advance_reel(page)
                            continue
                        seen_feed_ids.add(reel_id)

                        if self.db_client.instagram_exists(reel_id):
                            self._log("skip", f"Reel {reel_id} already in database. Skipping.")
                            self._advance_reel(page)
                            continue

                        total["processed"] += 1
                        self._status(query=f"Reels Feed | Reel {total['processed']}", processed=total["processed"], relevant=total["relevant"], irrelevant=total["irrelevant"])

                        caption, username = self._get_current_reel_caption_and_username(page)
                        thumbnail_url = self._get_current_reel_thumbnail(page)
                        thumbnail_base64 = self._get_base64_from_url(page, thumbnail_url)
                        video_path = os.path.join(self._temp_dir(), f"{reel_id}.mp4")

                        # Download
                        download_success = self._download_reel(url, video_path)
                        if not download_success:
                            self._log("error", f"Failed to download reel: {url}", "error")
                            self._advance_reel(page)
                            continue

                        # Grade and save
                        success, is_relevant = self._grade_and_save(url, video_path, caption, username, thumbnail_url=thumbnail_url, thumbnail_base64=thumbnail_base64)

                        # Clean up
                        try:
                            if os.path.exists(video_path):
                                os.remove(video_path)
                        except Exception as e:
                            logger.warning(f"Failed to delete temp file {video_path}: {e}")

                        if success:
                            if is_relevant:
                                total["relevant"] += 1
                            else:
                                total["irrelevant"] += 1

                        self._advance_reel(page)
                        if self._sleep(5):
                            break
                        
                        # Check queue periodically inside the feed loop
                        _process_user_queue()

                elif source_type == "account":
                    self._log("strategy", f"Strategy: Scraping reels from known account @{val}", "info")
                    self._status(query=f"@{val}", processed=total["processed"], relevant=total["relevant"], irrelevant=total["irrelevant"])

                    grid_url = f"https://www.instagram.com/{val}/reels/"
                    reel_urls = self._collect_reel_urls(page, grid_url, max_reels=15)
                    if not reel_urls:
                        continue

                    for url in reel_urls:
                        if self.stop_event and self.stop_event.is_set():
                            break

                        reel_id = re.search(r"/reel/([^/]+)", url)
                        reel_id = reel_id.group(1) if reel_id else f"account_{val}"

                        if self.db_client.instagram_exists(reel_id):
                            self._log("skip", f"Reel {reel_id} already in database. Skipping.")
                            continue

                        total["processed"] += 1
                        self._status(query=f"@{val} | Reel {total['processed']}", processed=total["processed"], relevant=total["relevant"], irrelevant=total["irrelevant"])

                        caption, username, thumbnail_url = self._get_reel_caption(page, url)
                        if not username or username == "unknown":
                            username = val
                        thumbnail_base64 = self._get_base64_from_url(page, thumbnail_url)

                        video_path = os.path.join(self._temp_dir(), f"{reel_id}.mp4")

                        # Download
                        download_success = self._download_reel(url, video_path)
                        if not download_success:
                            self._log("error", f"Failed to download reel: {url}", "error")
                            continue

                        # Grade and save
                        success, is_relevant = self._grade_and_save(url, video_path, caption, username, thumbnail_url=thumbnail_url, thumbnail_base64=thumbnail_base64)

                        # Clean up
                        try:
                            if os.path.exists(video_path):
                                os.remove(video_path)
                        except Exception as e:
                            logger.warning(f"Failed to delete temp file {video_path}: {e}")

                        if success:
                            if is_relevant:
                                total["relevant"] += 1
                            else:
                                total["irrelevant"] += 1

                        # Pause to avoid rate limiting
                        if self._sleep(5):
                            break

            ctx.close()
            self._log(
                "system",
                f"Finished. Processed: {total['processed']}, Saved: {total['relevant']}",
                "success"
            )
            self._status("Done", running=False)

        try:
            if playwright_instance:
                # Re-use same playwright instance
                _run(playwright_instance)
            else:
                with _sync_playwright() as p:
                    _run(p)
        except Exception as e:
            self._log("error", f"Critical pipeline error: {e}", "error")
            self._status("Error", running=False)

    def _temp_dir(self):
        from scraper.config import Config
        return Config.TEMP_MEDIA_DIR
