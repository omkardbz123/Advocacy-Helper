import os
import time
import requests
import logging
import subprocess
from datetime import datetime
from scraper.config import Config, INSTAGRAM_SEED_QUERIES
from scraper.instagram.searcher import SEED_ACCOUNTS

logger = logging.getLogger(__name__)

class InstagramProcessor:
    def __init__(self, auth, searcher, grader, db_client, manager, socketio=None, stop_event=None):
        """
        auth: InstagramAuth instance
        searcher: InstagramSearcher instance
        grader: GeminiAPIGrader or GeminiBrowserGrader instance
        db_client: CloudflareClient instance
        manager: MiniMaxManager instance
        socketio: Flask-SocketIO instance for live updates (optional)
        stop_event: threading.Event to stop the scraper (optional)
        """
        self.auth = auth
        self.searcher = searcher
        self.grader = grader
        self.db_client = db_client
        self.manager = manager
        self.socketio = socketio
        self.stop_event = stop_event
        self.consecutive_irrelevant = 0

    def emit_log(self, action, detail, level='info'):
        """Emit to WebSocket AND log to Cloudflare"""
        timestamp = datetime.now().isoformat()
        log_data = {
            'platform': 'instagram',
            'action': action,
            'detail': detail,
            'level': level,
            'timestamp': timestamp
        }
        
        # 1. Log to Cloudflare D1
        self.db_client.log_activity(
            platform='instagram',
            action=action,
            detail=detail,
            level=level
        )
        
        # 2. Emit to SocketIO client
        if self.socketio:
            self.socketio.emit('scraper_log', log_data)
            
        logger.info(f"[{level.upper()}] Instagram Scraper: {action} - {detail}")

    def update_status(self, running=True, current_query='', processed=0, relevant=0, irrelevant=0):
        if self.socketio:
            self.socketio.emit('scraper_status', {
                'running': running,
                'platform': 'instagram',
                'current_query': current_query,
                'processed': processed,
                'relevant': relevant,
                'irrelevant': irrelevant
            })

    def download_media(self, url, file_path, headers=None) -> bool:
        """Download any media from a direct URL (image or video CDN URL)."""
        try:
            default_headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Referer': 'https://www.instagram.com/',
            }
            if headers:
                default_headers.update(headers)
            resp = requests.get(url, stream=True, timeout=30, headers=default_headers)
            if resp.status_code == 200:
                with open(file_path, 'wb') as f:
                    for chunk in resp.iter_content(8192):
                        f.write(chunk)
                logger.info(f"Downloaded media to {file_path} ({os.path.getsize(file_path)} bytes)")
                return True
            logger.error(f"HTTP {resp.status_code} downloading {url}")
            return False
        except Exception as e:
            logger.error(f"Failed to download media {url}: {e}")
            return False

    def download_video_ytdlp(self, url, file_path, cookies_file=None) -> bool:
        """
        Download Instagram reel/video using yt-dlp with session cookies.
        Uses --cookies <file> (Instagram blocked --username/--password in 2024).
        """
        try:
            logger.info(f"Downloading via yt-dlp: {url}")
            os.makedirs(os.path.dirname(file_path), exist_ok=True)

            base_cmd = [
                'yt-dlp',
                '--no-check-certificate',
                '--merge-output-format', 'mp4',
                '-f', 'bestvideo[ext=mp4]+bestaudio[ext=m4a]/best[ext=mp4]/best',
                '-o', file_path,
            ]

            # Method 1: Use exported cookies file (most reliable)
            if cookies_file and os.path.exists(cookies_file):
                cmd = base_cmd + ['--cookies', cookies_file, url]
                logger.info(f"yt-dlp: using cookies file {cookies_file}")
                result = subprocess.run(
                    cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    text=True, timeout=60
                )
                if result.returncode == 0 and os.path.exists(file_path):
                    logger.info(f"yt-dlp: download successful via cookies")
                    return True
                logger.warning(f"yt-dlp with cookies failed: {result.stderr[-300:]}")

            # Method 2: No auth — works for many public reels
            cmd_pub = base_cmd + [url]
            result2 = subprocess.run(
                cmd_pub, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, timeout=60
            )
            if result2.returncode == 0 and os.path.exists(file_path):
                logger.info("yt-dlp: download successful (public, no auth)")
                return True

            logger.error(f"yt-dlp download failed: {result2.stderr[-300:]}")
            return False

        except subprocess.TimeoutExpired:
            logger.error("yt-dlp timed out after 60s")
            return False
        except Exception as e:
            logger.error(f"yt-dlp error: {e}")
            return False

    def process_items(self, page, items: list, source_label: str) -> dict:
        """
        Process a list of discovered post/reel items through download → grade → save pipeline.
        `source_label` is a human-readable string like '#carnivorediet' or '@shawnbaker1967'.
        """
        stats = {'total': len(items), 'relevant': 0, 'irrelevant': 0, 'skipped': 0}

        if not items:
            self.emit_log('search', f'No posts found for {source_label}', 'warning')
            return stats

        for i, item in enumerate(items):
            if self.stop_event and self.stop_event.is_set():
                break

            post_id = item['post_id']
            post_url = item['post_url']
            
            # Check dedup
            self.emit_log('dedup', f'Checking database for post: {post_id}', 'info')
            if self.db_client.instagram_exists(post_id):
                stats['skipped'] += 1
                self.emit_log('skip', f'Post {post_id} already in database. Skipping.', 'info')
                continue

            # Fetch details (also intercepts CDN video URL)
            self.emit_log('metadata', f'Fetching details for post {post_id}', 'info')
            details = self.searcher.get_post_details(page, post_url)
            if not details:
                stats['skipped'] += 1
                self.emit_log('error', f'Failed to fetch details for post {post_id}', 'error')
                continue

            media_type = details['media_type']
            thumbnail_url = details.get('thumbnail_url') or item.get('thumbnail_url')
            title = details['title']

            # CDN video URL may have been intercepted during get_post_details
            cdn_video_url = details.get('video_cdn_url') or item.get('video_cdn_url')

            # ── Download media for Gemini ──────────────────────────────────
            media_filename = f"{post_id}.mp4" if media_type in ('video', 'reel') else f"{post_id}.jpg"
            temp_path = os.path.join(Config.TEMP_MEDIA_DIR, media_filename)
            download_success = False

            if media_type in ('video', 'reel'):
                self.emit_log('download', f'Downloading reel {post_id}', 'info')

                # Priority 1: Direct CDN URL (fastest, no auth needed)
                if cdn_video_url:
                    logger.info(f"Trying direct CDN URL download: {cdn_video_url[:80]}...")
                    download_success = self.download_media(cdn_video_url, temp_path)

                # Priority 2: yt-dlp with cookies file
                if not download_success:
                    cookies_file = getattr(self.auth, '_cookies_file_path', None)
                    download_success = self.download_video_ytdlp(post_url, temp_path, cookies_file)

            # Fallback: thumbnail image for non-video or failed downloads
            if not download_success and thumbnail_url:
                temp_path = os.path.join(Config.TEMP_MEDIA_DIR, f"{post_id}.jpg")
                self.emit_log('download', f'Falling back to thumbnail for post {post_id}', 'warning')
                download_success = self.download_media(thumbnail_url, temp_path)

            if not download_success or not os.path.exists(temp_path):
                self.emit_log('error', f'Could not download media for post {post_id}. Skipping.', 'error')
                stats['skipped'] += 1
                continue

            # Grade with Gemini
            self.emit_log('grade', f'Sending media file to Gemini for grading: {temp_path}', 'info')
            
            # Identify grading method
            grading_method = 'browser' if 'browser' in type(self.grader).__name__.lower() else 'api'
            
            grade = self.grader.grade_instagram(temp_path, title)
            
            # Clean up local file immediately
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
                    logger.info(f"Removed local temp file: {temp_path}")
            except Exception as delete_err:
                logger.warning(f"Failed to delete temp file {temp_path}: {delete_err}")

            if not grade:
                self.emit_log('error', f'Gemini grading failed for post {post_id}', 'error')
                stats['skipped'] += 1
                continue

            is_relevant = grade.get('relevant', False)
            
            # Save or skip based on relevance
            if is_relevant:
                self.consecutive_irrelevant = 0 # Reset counter
                stats['relevant'] += 1
                
                # Insert to D1
                save_data = {
                    'post_id': post_id,
                    'title': title,
                    'thumbnail_url': thumbnail_url,
                    'post_url': post_url,
                    'media_type': media_type,
                    'username': details['username'],
                    'profile_url': details['profile_url'],
                    'published_at': details['published_at'],
                    'grade_animal_friendly': grade.get('animal_friendly'),
                    'grade_scientific': grade.get('scientific'),
                    'grade_emotional_manipulation': grade.get('emotional_manipulation'),
                    'summary': grade.get('summary'),
                    'raw_gemini_response': str(grade),
                    'grading_method': grading_method,
                    'status': 'graded'
                }
                
                if self.db_client.insert_instagram(save_data):
                    self.emit_log(
                        'save', 
                        f"Saved Instagram post '{title[:30]}...' to D1. Grade: {grade.get('animal_friendly')}", 
                        'success'
                    )
                else:
                    self.emit_log('error', f"Failed to save post '{title[:30]}' to D1 database", 'error')
            else:
                self.consecutive_irrelevant += 1
                stats['irrelevant'] += 1
                self.emit_log(
                    'irrelevant', 
                    f"Post '{title[:30]}...' marked irrelevant by Gemini. Consecutive irrelevant: {self.consecutive_irrelevant}", 
                    'warning'
                )
                
                # Save as skipped in D1
                save_data = {
                    'post_id': post_id,
                    'title': title,
                    'thumbnail_url': thumbnail_url,
                    'post_url': post_url,
                    'media_type': media_type,
                    'username': details['username'],
                    'profile_url': details['profile_url'],
                    'published_at': details['published_at'],
                    'grade_animal_friendly': 'partial',
                    'grade_scientific': 'partial',
                    'grade_emotional_manipulation': 'no',
                    'summary': 'Skipped by AI Grader (unrelated)',
                    'raw_gemini_response': str(grade),
                    'grading_method': grading_method,
                    'status': 'skipped'
                }
                self.db_client.insert_instagram(save_data)

            # Update live stats
            self.update_status(
                running=True,
                current_query=source_label,
                processed=stats['relevant'] + stats['irrelevant'] + stats['skipped'],
                relevant=stats['relevant'],
                irrelevant=stats['irrelevant']
            )

            # Slow down to avoid rate limits
            time.sleep(8)

        # Log search to history
        self.db_client.log_search(
            platform='instagram',
            query=source_label,
            total=stats['total'],
            relevant=stats['relevant'],
            irrelevant=stats['irrelevant'],
            notes=f"Strategy: {source_label}. Consecutive irrelevant at end: {self.consecutive_irrelevant}"
        )

        return stats

    def run(self, queries=None, playwright_instance=None):
        """
        Main run loop — uses three strategies in priority order:
          1. Account reels (known pro-meat / anti-vegan influencers) — highest signal
          2. Reels For-You feed scroll                                 — algorithm seeded
          3. Hashtag search (pro-meat tags, NOT #antivegan)            — fallback
        """
        from playwright.sync_api import sync_playwright

        self.emit_log('system', 'Starting Instagram Scraper pipeline (multi-strategy)', 'info')
        self.update_status(running=True, current_query='Initializing Browser...')

        # Ensure temp_media exists
        os.makedirs(Config.TEMP_MEDIA_DIR, exist_ok=True)

        total_processed_stats = {'total': 0, 'relevant': 0, 'irrelevant': 0}

        try:
            if playwright_instance:
                context = self.auth.get_browser_context(playwright_instance)
                self._run_with_context(context, queries, total_processed_stats)
            else:
                with sync_playwright() as p:
                    context = self.auth.get_browser_context(p)
                    self._run_with_context(context, queries, total_processed_stats)
        except Exception as e:
            self.emit_log('error', f"Critical error in Instagram Scraper pipeline: {e}", 'error')

        self.emit_log(
            'system',
            f"Instagram Scraper finished. Total: {total_processed_stats['total']}, Relevant: {total_processed_stats['relevant']}",
            'success'
        )
        self.update_status(running=False, current_query='Finished')

    def _run_with_context(self, context, queries, total_processed_stats):
        if not context:
            self.emit_log('error', "Could not launch Playwright browser context.", 'error')
            self.update_status(running=False, current_query='Launch Failed')
            return

        page = context.new_page()

        # ── Login ──────────────────────────────────────────────────────────
        self.update_status(running=True, current_query='Logging in to Instagram...')
        if not self.auth.login(page):
            self.emit_log('error', "Instagram login failed. Aborting scraper.", 'error')
            self.update_status(running=False, current_query='Login Failed')
            context.close()
            return

        # ── Export session cookies for yt-dlp ──────────────────────────────
        cookies_file = self.auth.export_cookies_for_ytdlp(page)
        if cookies_file:
            self.auth._cookies_file_path = cookies_file
            self.emit_log('system', f'Session cookies exported for yt-dlp: {cookies_file}', 'info')
        else:
            self.auth._cookies_file_path = None
            self.emit_log('system', 'Cookie export failed — yt-dlp will try public download only', 'warning')

        # ── STRATEGY 1: Scrape known pro-meat / anti-vegan accounts ────────
        self.emit_log('strategy', 'Strategy 1: Scraping reels from known anti-vegan accounts', 'info')
        for account in SEED_ACCOUNTS:

            if self.stop_event and self.stop_event.is_set():
                break
            self.update_status(running=True, current_query=f'@{account} (account reels)')
            items = self.searcher.scrape_account_reels(page, account, max_results=15)
            stats = self.process_items(page, items, source_label=f'@{account}')
            total_processed_stats['total'] += stats['total']
            total_processed_stats['relevant'] += stats['relevant']
            total_processed_stats['irrelevant'] += stats['irrelevant']
            time.sleep(5)

        # ── STRATEGY 2: Scroll Reels For-You feed ──────────────────────────
        if not (self.stop_event and self.stop_event.is_set()):
            self.emit_log('strategy', 'Strategy 2: Scrolling Reels For-You feed', 'info')
            self.update_status(running=True, current_query='Reels feed scroll')
            feed_items = self.searcher.scrape_reels_feed(page, max_results=25)
            stats = self.process_items(page, feed_items, source_label='reels_feed')
            total_processed_stats['total'] += stats['total']
            total_processed_stats['relevant'] += stats['relevant']
            total_processed_stats['irrelevant'] += stats['irrelevant']

        # ── STRATEGY 3: Hashtag search (pro-meat tags only) ────────────────
        hashtag_list = list(queries) if queries else list(INSTAGRAM_SEED_QUERIES)
        self.emit_log('strategy', f'Strategy 3: Hashtag search ({len(hashtag_list)} tags)', 'info')

        query_index = 0
        while query_index < len(hashtag_list):
            if self.stop_event and self.stop_event.is_set():
                self.emit_log('system', 'Scraper stopped by request', 'warning')
                break

            current_hashtag = hashtag_list[query_index]
            self.update_status(running=True, current_query=f'#{current_hashtag}')

            items = self.searcher.search_hashtag(page, current_hashtag, max_results=10)
            stats = self.process_items(page, items, source_label=f'#{current_hashtag}')
            total_processed_stats['total'] += stats['total']
            total_processed_stats['relevant'] += stats['relevant']
            total_processed_stats['irrelevant'] += stats['irrelevant']

            # MiniMax strategy adaptation if too many irrelevant results
            if self.consecutive_irrelevant >= 3:
                self.emit_log(
                    'strategy_change',
                    f"Triggering MiniMax adaptation: {self.consecutive_irrelevant} consecutive irrelevant",
                    'warning'
                )
                history = self.db_client.get_search_history(platform='instagram')
                new_hashtags = self.manager.generate_queries(
                    platform='instagram',
                    search_history=history,
                    consecutive_irrelevant=self.consecutive_irrelevant
                )
                if new_hashtags:
                    self.emit_log(
                        'strategy_change',
                        f"MiniMax new hashtags: {new_hashtags}",
                        'success'
                    )
                    for h in reversed(new_hashtags):
                        hashtag_list.insert(query_index + 1, h)
                    self.consecutive_irrelevant = 0
                else:
                    self.emit_log('error', 'MiniMax gave no hashtags. Continuing.', 'error')

            query_index += 1
            time.sleep(5)

        context.close()
