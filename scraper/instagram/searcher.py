import time
import logging
import re
from playwright.sync_api import Page

logger = logging.getLogger(__name__)

# Known pro-meat / anti-vegan / carnivore influencer accounts
SEED_ACCOUNTS = [
    "shawnbaker1967",
    "paul.saladino.md",
    "liver.king",
    "dranthonychaffee",
    "carnivoremichael",
    "meatrx",
    "theprimaledgehealth",
    "ketocarnivore_",
    "georgiaedereats",
    "sovegan2carnivore",
]


class InstagramSearcher:
    def __init__(self, auth):
        self.auth = auth

    # ─────────────────────────────────────────────────────────────────────────
    # INTERNAL: Network-interception-based video URL capture
    # ─────────────────────────────────────────────────────────────────────────
    def _intercept_and_collect_reels(self, page: Page, navigate_url: str,
                                     scroll_count: int = 8, max_results: int = 20,
                                     scroll_fn=None) -> list[dict]:
        """
        General-purpose reel collector using two parallel methods:
          1. Network request interception → captures real CDN video URLs
          2. DOM scraping of <a href='/reel/...'> links → captures reel IDs

        Returns a list of dicts with post_id, post_url, video_cdn_url, thumbnail_url, media_type.
        """
        captured_videos: dict[str, str] = {}  # post_id → CDN video URL
        seen_ids: set = set()
        posts: list[dict] = []

        # ── Intercept network requests for CDN video URLs ──────────────────
        def on_request(request):
            url = request.url
            # Instagram CDN video URLs contain 'scontent' and '.mp4' or 'video'
            if ("scontent" in url or "cdninstagram" in url) and (
                ".mp4" in url or "video" in url
            ):
                # Try to extract reel ID from referrer header or just store the URL
                post_id = _extract_post_id_from_page(page)
                if post_id:
                    captured_videos[post_id] = url

        def _extract_post_id_from_page(p: Page) -> str | None:
            try:
                current_url = p.url
                m = re.search(r'/reel/([^/?]+)', current_url)
                if m:
                    return m.group(1)
            except Exception:
                pass
            return None

        page.on("request", on_request)

        try:
            logger.info(f"Navigating to: {navigate_url}")
            page.goto(navigate_url, wait_until="domcontentloaded")
            time.sleep(5)

            if "login" in page.url or "accounts/login" in page.url:
                logger.warning("Redirected to login page — session expired.")
                return []

            # ── Scroll / advance through reels ────────────────────────────
            for scroll_idx in range(scroll_count):
                time.sleep(3)

                # Collect DOM-visible reel links
                links = page.query_selector_all("a[href*='/reel/']")
                for link in links:
                    if len(posts) >= max_results:
                        break
                    href = link.get_attribute("href") or ""
                    m = re.search(r'/reel/([^/?]+)', href)
                    if not m:
                        continue
                    post_id = m.group(1)
                    if post_id in seen_ids:
                        continue
                    seen_ids.add(post_id)

                    post_url = f"https://www.instagram.com/reel/{post_id}/"
                    thumbnail_url = None
                    img = link.query_selector("img")
                    if img:
                        thumbnail_url = img.get_attribute("src")

                    posts.append({
                        "post_id": post_id,
                        "post_url": post_url,
                        "thumbnail_url": thumbnail_url,
                        "video_cdn_url": captured_videos.get(post_id),
                        "media_type": "reel",
                    })

                if len(posts) >= max_results:
                    break

                # Advance to next reel using the provided scroll function or defaults
                if scroll_fn:
                    scroll_fn(page, scroll_idx)
                else:
                    # Try clicking the "Next reel" chevron button
                    next_clicked = False
                    for chevron_sel in [
                        "button[aria-label='Next']",
                        "svg[aria-label='Next']",
                        "div[aria-label='Next']",
                        "[class*='coreSpriteRightChevron']",
                    ]:
                        btn = page.query_selector(chevron_sel)
                        if btn:
                            try:
                                btn.click()
                                next_clicked = True
                                break
                            except Exception:
                                pass
                    if not next_clicked:
                        # Fallback: keyboard down arrow
                        page.keyboard.press("ArrowDown")

            logger.info(f"Collected {len(posts)} reel entries from {navigate_url}")
            return posts

        except Exception as e:
            logger.error(f"Error in _intercept_and_collect_reels for {navigate_url}: {e}")
            return []
        finally:
            page.remove_listener("request", on_request)

    # ─────────────────────────────────────────────────────────────────────────
    # STRATEGY 1: Scrape reels from specific pro-meat accounts
    # ─────────────────────────────────────────────────────────────────────────
    def scrape_account_reels(self, page: Page, username: str, max_results: int = 15) -> list[dict]:
        """
        Navigate to instagram.com/{username}/reels/ and collect reel links.
        No network interception needed here — we go to each reel individually for download.
        """
        url = f"https://www.instagram.com/{username}/reels/"
        logger.info(f"[Account] Scraping reels from @{username}")

        try:
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(5)

            if "login" in page.url:
                logger.warning(f"[Account] Login required for @{username}. Skipping.")
                return []

            # Scroll to load more reels
            for _ in range(4):
                page.keyboard.press("End")
                time.sleep(2)

            links = page.query_selector_all("a[href*='/reel/']")
            posts = []
            seen_ids = set()

            for link in links:
                if len(posts) >= max_results:
                    break
                href = link.get_attribute("href") or ""
                m = re.search(r'/reel/([^/?]+)', href)
                if not m:
                    continue
                post_id = m.group(1)
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                post_url = f"https://www.instagram.com/reel/{post_id}/"
                thumbnail_url = None
                img = link.query_selector("img")
                if img:
                    thumbnail_url = img.get_attribute("src")

                posts.append({
                    "post_id": post_id,
                    "post_url": post_url,
                    "thumbnail_url": thumbnail_url,
                    "video_cdn_url": None,  # Will be captured during download
                    "media_type": "reel",
                    "source_account": username,
                })

            logger.info(f"[Account] Found {len(posts)} reels from @{username}")
            return posts

        except Exception as e:
            logger.error(f"[Account] Error scraping @{username}: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # STRATEGY 2: Scroll the Reels For-You feed (instagram.com/reels/)
    # ─────────────────────────────────────────────────────────────────────────
    def scrape_reels_feed(self, page: Page, max_results: int = 25) -> list[dict]:
        """
        Scroll through instagram.com/reels/ (For-You feed).
        Uses the ↓ button / Next chevron to advance through reels.
        """
        logger.info("[Feed] Scrolling Reels For-You feed")

        captured_video_urls: dict[str, str] = {}
        seen_ids: set = set()
        posts: list[dict] = []

        def on_response(response):
            """Intercept CDN video responses to capture direct MP4 URLs."""
            url = response.url
            if ("scontent" in url or "cdninstagram" in url) and ".mp4" in url:
                try:
                    current_url = page.url
                    m = re.search(r'/reel/([^/?]+)', current_url)
                    if m:
                        captured_video_urls[m.group(1)] = url
                except Exception:
                    pass

        page.on("response", on_response)

        try:
            page.goto("https://www.instagram.com/reels/", wait_until="domcontentloaded")
            time.sleep(6)

            if "login" in page.url:
                logger.warning("[Feed] Not logged in. Skipping feed scroll.")
                return []

            for _ in range(max_results * 3):  # Over-iterate to find enough
                time.sleep(3)

                # Current reel URL may be embedded in page URL or in the reel player
                current_url = page.url
                m = re.search(r'/reel(?:s)?/([^/?]+)', current_url)
                post_id = m.group(1) if m else None

                # Also look for reel links in DOM
                links = page.query_selector_all("a[href*='/reel/']")
                for link in links:
                    href = link.get_attribute("href") or ""
                    lm = re.search(r'/reel/([^/?]+)', href)
                    if lm and lm.group(1) not in seen_ids:
                        post_id = lm.group(1)
                        break

                if post_id and post_id not in seen_ids:
                    seen_ids.add(post_id)
                    post_url = f"https://www.instagram.com/reel/{post_id}/"

                    # Try to get thumbnail
                    thumbnail_url = None
                    img = page.query_selector("article img, video[poster]")
                    if img:
                        thumbnail_url = (
                            img.get_attribute("poster")
                            or img.get_attribute("src")
                        )

                    posts.append({
                        "post_id": post_id,
                        "post_url": post_url,
                        "thumbnail_url": thumbnail_url,
                        "video_cdn_url": captured_video_urls.get(post_id),
                        "media_type": "reel",
                        "source_account": "reels_feed",
                    })

                if len(posts) >= max_results:
                    break

                # Advance to next reel — try multiple methods
                advanced = False
                for sel in [
                    "svg[aria-label='Next']",
                    "button[aria-label='Next']",
                    "div[aria-label='Next']",
                ]:
                    el = page.query_selector(sel)
                    if el:
                        try:
                            el.click()
                            advanced = True
                            break
                        except Exception:
                            pass

                if not advanced:
                    page.keyboard.press("ArrowDown")

            logger.info(f"[Feed] Collected {len(posts)} reels from feed")
            return posts

        except Exception as e:
            logger.error(f"[Feed] Error scrolling Reels feed: {e}")
            return []
        finally:
            page.remove_listener("response", on_response)

    # ─────────────────────────────────────────────────────────────────────────
    # STRATEGY 3: Hashtag search (pro-meat tags only)
    # ─────────────────────────────────────────────────────────────────────────
    def search_hashtag(self, page: Page, hashtag: str, max_results: int = 10) -> list[dict]:
        """
        Navigate to instagram.com/explore/tags/{hashtag}/ and collect reel links.
        """
        hashtag_clean = hashtag.replace("#", "").strip()
        url = f"https://www.instagram.com/explore/tags/{hashtag_clean}/"
        logger.info(f"[Hashtag] Searching #{hashtag_clean}")

        try:
            page.goto(url, wait_until="domcontentloaded")
            time.sleep(5)

            if "login" in page.url:
                logger.warning("[Hashtag] Login wall. Skipping.")
                return []

            # Scroll to load more content
            for _ in range(3):
                page.keyboard.press("End")
                time.sleep(2)

            links = page.query_selector_all("a[href*='/reel/'], a[href*='/p/']")
            posts = []
            seen_ids = set()

            for link in links:
                if len(posts) >= max_results:
                    break
                href = link.get_attribute("href") or ""
                m = re.search(r'/(?:p|reel)/([^/?]+)', href)
                if not m:
                    continue
                post_id = m.group(1)
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                is_reel = "/reel/" in href
                post_url = f"https://www.instagram.com{href.split('?')[0]}"
                if not post_url.endswith("/"):
                    post_url += "/"

                thumbnail_url = None
                img = link.query_selector("img")
                if img:
                    thumbnail_url = img.get_attribute("src")

                posts.append({
                    "post_id": post_id,
                    "post_url": post_url,
                    "thumbnail_url": thumbnail_url,
                    "video_cdn_url": None,
                    "media_type": "reel" if is_reel else "image",
                    "source_account": f"#{hashtag_clean}",
                })

            logger.info(f"[Hashtag] Found {len(posts)} posts for #{hashtag_clean}")
            return posts

        except Exception as e:
            logger.error(f"[Hashtag] Error for #{hashtag_clean}: {e}")
            return []

    # ─────────────────────────────────────────────────────────────────────────
    # Post detail extraction (username, caption, published_at)
    # ─────────────────────────────────────────────────────────────────────────
    def get_post_details(self, page: Page, post_url: str) -> dict | None:
        """
        Navigate to individual reel/post and extract metadata.
        Also intercepts the CDN video URL via network requests.
        """
        captured_cdn_url = {"url": None}

        def on_response(response):
            url = response.url
            if ("scontent" in url or "cdninstagram" in url) and ".mp4" in url:
                if not captured_cdn_url["url"]:
                    captured_cdn_url["url"] = url

        page.on("response", on_response)

        try:
            logger.info(f"[Details] Loading: {post_url}")
            page.goto(post_url, wait_until="domcontentloaded")
            time.sleep(5)

            if "login" in page.url:
                logger.warning("[Details] Login wall. Skipping.")
                return None

            # ── Username ──
            username = "unknown"
            # Header link pattern: /username/ (exactly two slashes)
            for link in page.query_selector_all("header a, article a"):
                href = (link.get_attribute("href") or "").rstrip("/")
                parts = href.split("/")
                if len(parts) == 2 and parts[0] == "" and parts[1]:
                    candidate = parts[1]
                    if candidate not in ("explore", "reels", "p", "reel", "stories", "direct"):
                        txt = link.inner_text().strip()
                        if txt and " " not in txt:
                            username = txt
                            break

            # ── Caption ──
            caption = ""
            for sel in ["h1", "div._a9zs", "span._ap3a", "div[class*='Caption'] span"]:
                elem = page.query_selector(sel)
                if elem:
                    txt = elem.inner_text().strip()
                    if txt and len(txt) > 3:
                        caption = txt
                        break

            # ── Media type ──
            media_type = "image"
            if "/reel/" in post_url:
                media_type = "reel"
            elif page.query_selector("video"):
                media_type = "video"

            # ── Published at ──
            published_at = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            time_elem = page.query_selector("time[datetime]")
            if time_elem:
                dt = time_elem.get_attribute("datetime")
                if dt:
                    published_at = dt

            # ── Thumbnail ──
            thumbnail_url = None
            for img_sel in ["article img", "video[poster]", "div[role='presentation'] img"]:
                img_elem = page.query_selector(img_sel)
                if img_elem:
                    thumbnail_url = (
                        img_elem.get_attribute("poster")
                        or img_elem.get_attribute("src")
                    )
                    if thumbnail_url:
                        break

            return {
                "username": username,
                "profile_url": f"https://www.instagram.com/{username}/",
                "title": caption[:200] if caption else "No Caption",
                "media_type": media_type,
                "thumbnail_url": thumbnail_url,
                "published_at": published_at,
                "video_cdn_url": captured_cdn_url["url"],
            }

        except Exception as e:
            logger.error(f"[Details] Error for {post_url}: {e}")
            return None
        finally:
            page.remove_listener("response", on_response)
