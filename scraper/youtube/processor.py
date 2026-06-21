import time
import logging
from datetime import datetime
from scraper.config import YOUTUBE_SEED_QUERIES

logger = logging.getLogger(__name__)

class YouTubeProcessor:
    def __init__(self, searcher, grader, db_client, manager, socketio=None, stop_event=None):
        """
        searcher: YouTubeSearcher instance
        grader: GeminiAPIGrader or GeminiBrowserGrader instance
        db_client: CloudflareClient instance
        manager: MiniMaxManager instance
        socketio: Flask-SocketIO instance for live updates (optional)
        stop_event: threading.Event to stop the scraper (optional)
        """
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
            'platform': 'youtube',
            'action': action,
            'detail': detail,
            'level': level,
            'timestamp': timestamp
        }
        
        # 1. Log to Cloudflare Worker D1
        self.db_client.log_activity(
            platform='youtube',
            action=action,
            detail=detail,
            level=level
        )
        
        # 2. Emit to SocketIO client if available
        if self.socketio:
            self.socketio.emit('scraper_log', log_data)
            
        logger.info(f"[{level.upper()}] YouTube Scraper: {action} - {detail}")

    def update_status(self, running=True, current_query='', processed=0, relevant=0, irrelevant=0):
        if self.socketio:
            self.socketio.emit('scraper_status', {
                'running': running,
                'platform': 'youtube',
                'current_query': current_query,
                'processed': processed,
                'relevant': relevant,
                'irrelevant': irrelevant
            })

    def _process_user_queue(self):
        processed_any = False
        while not (self.stop_event and self.stop_event.is_set()):
            submission = self.db_client.get_next_pending_submission('youtube')
            if not submission:
                break
            
            processed_any = True
            submission_id = submission.get('id')
            url = submission.get('url')
            self.emit_log('queue', f"Found pending user submission: {url}", 'info')
            self.db_client.update_submission_status(submission_id, 'processing')
            
            # For YouTube, the url is the video_url
            video_id_match = re.search(r"(?:v=|\/)([0-9A-Za-z_-]{11}).*", url)
            video_id = video_id_match.group(1) if video_id_match else f"user_{submission_id}"
            
            if self.db_client.youtube_exists(video_id):
                self.emit_log('skip', f"User submitted video {video_id} already exists. Skipping.", 'info')
                self.db_client.update_submission_status(submission_id, 'graded')
                continue
                
            self.update_status(running=True, current_query=f"Queue | {url}")
            
            details = self.searcher.get_video_details(video_id)
            duration = details.get('duration', 'N/A') if details else 'N/A'
            title = details.get('title', 'User Submitted Video') if details else 'User Submitted Video'
            
            grade = self.grader.grade_youtube(url, title)
            if not grade:
                self.emit_log('error', f"Gemini grading failed for user video {url}", 'error')
                self.db_client.update_submission_status(submission_id, 'error')
                continue
                
            is_relevant = grade.get('relevant', False)
            grading_method = 'browser' if 'browser' in type(self.grader).__name__.lower() else 'api'
            
            save_data = {
                'video_id': video_id,
                'title': title,
                'thumbnail_url': details.get('thumbnail_url', f"https://img.youtube.com/vi/{video_id}/hqdefault.jpg") if details else "",
                'channel_name': details.get('channel_title', 'Unknown') if details else 'Unknown',
                'channel_url': '',
                'video_url': url,
                'duration': duration,
                'published_at': details.get('published_at', '') if details else '',
                'grade_animal_friendly': grade.get('animal_friendly') if is_relevant else 'partial',
                'grade_scientific': grade.get('scientific') if is_relevant else 'partial',
                'grade_emotional_manipulation': grade.get('emotional_manipulation') if is_relevant else 'no',
                'summary': grade.get('summary') if is_relevant else 'Skipped by AI Grader (unrelated)',
                'raw_gemini_response': str(grade),
                'grading_method': grading_method,
                'status': 'graded' if is_relevant else 'skipped'
            }
            
            if self.db_client.insert_youtube(save_data):
                self.emit_log('save', f"Saved user submitted video to database. Relevant: {is_relevant}", 'success')
                self.db_client.update_submission_status(submission_id, 'graded')
            else:
                self.emit_log('error', f"Failed to save user video to D1", 'error')
                self.db_client.update_submission_status(submission_id, 'error')
                
        return processed_any

    def process_query(self, query) -> dict:
        """
        Execute one search query and process all results.
        Returns: {'total': int, 'relevant': int, 'irrelevant': int, 'skipped': int}
        """
        stats = {'total': 0, 'relevant': 0, 'irrelevant': 0, 'skipped': 0}
        
        if self.stop_event and self.stop_event.is_set():
            return stats

        self.emit_log('search', f'Searching YouTube for: "{query}"', 'info')
        results = self.searcher.search(query)
        stats['total'] = len(results)
        
        if not results:
            self.emit_log('search', f'No results found for query: "{query}"', 'warning')
            return stats

        for i, item in enumerate(results):
            if self.stop_event and self.stop_event.is_set():
                break

            video_id = item['video_id']
            title = item['title']
            video_url = item['video_url']
            
            # Check dedup
            self.emit_log('dedup', f'Checking database for video: {video_id} ({title[:30]}...)', 'info')
            if self.db_client.youtube_exists(video_id):
                stats['skipped'] += 1
                self.emit_log('skip', f'Video {video_id} already exists in database. Skipping.', 'info')
                continue

            # Fetch video details
            self.emit_log('metadata', f'Fetching duration and details for video {video_id}', 'info')
            details = self.searcher.get_video_details(video_id)
            duration = details.get('duration', 'N/A') if details else 'N/A'

            # Grade with Gemini
            self.emit_log('grade', f'Sending video to Gemini for grading: {video_url}', 'info')
            
            # Identify grading method based on grader type
            grading_method = 'browser' if 'browser' in type(self.grader).__name__.lower() else 'api'
            
            grade = self.grader.grade_youtube(video_url, title)
            
            if not grade:
                self.emit_log('error', f'Gemini grading failed for video {video_id}', 'error')
                stats['skipped'] += 1
                continue

            is_relevant = grade.get('relevant', False)
            
            # Save or skip based on relevance
            if is_relevant:
                self.consecutive_irrelevant = 0 # Reset counter
                stats['relevant'] += 1
                
                # Insert to D1
                save_data = {
                    'video_id': video_id,
                    'title': title,
                    'thumbnail_url': item['thumbnail_url'],
                    'channel_name': item['channel_name'],
                    'channel_url': item['channel_url'],
                    'video_url': video_url,
                    'duration': duration,
                    'published_at': item['published_at'],
                    'grade_animal_friendly': grade.get('animal_friendly'),
                    'grade_scientific': grade.get('scientific'),
                    'grade_emotional_manipulation': grade.get('emotional_manipulation'),
                    'summary': grade.get('summary'),
                    'raw_gemini_response': str(grade),
                    'grading_method': grading_method,
                    'status': 'graded'
                }
                
                if self.db_client.insert_youtube(save_data):
                    self.emit_log(
                        'save', 
                        f"Saved video '{title[:30]}...' to D1. Grade: {grade.get('animal_friendly')}", 
                        'success'
                    )
                else:
                    self.emit_log('error', f"Failed to save video '{title[:30]}' to D1 database", 'error')
            else:
                self.consecutive_irrelevant += 1
                stats['irrelevant'] += 1
                self.emit_log(
                    'irrelevant', 
                    f"Video '{title[:30]}...' marked irrelevant by Gemini. Consecutive irrelevant: {self.consecutive_irrelevant}", 
                    'warning'
                )
                
                # Save as skipped in D1 for audit
                save_data = {
                    'video_id': video_id,
                    'title': title,
                    'thumbnail_url': item['thumbnail_url'],
                    'channel_name': item['channel_name'],
                    'channel_url': item['channel_url'],
                    'video_url': video_url,
                    'duration': duration,
                    'published_at': item['published_at'],
                    'grade_animal_friendly': 'partial',
                    'grade_scientific': 'partial',
                    'grade_emotional_manipulation': 'no',
                    'summary': 'Skipped by AI Grader (unrelated)',
                    'raw_gemini_response': str(grade),
                    'grading_method': grading_method,
                    'status': 'skipped'
                }
                self.db_client.insert_youtube(save_data)

            # Update live stats
            self.update_status(
                running=True,
                current_query=query,
                processed=stats['relevant'] + stats['irrelevant'] + stats['skipped'],
                relevant=stats['relevant'],
                irrelevant=stats['irrelevant']
            )

            # Slow down to avoid rate limits
            time.sleep(5)

        # Log query to history database
        self.db_client.log_search(
            platform='youtube',
            query=query,
            total=stats['total'],
            relevant=stats['relevant'],
            irrelevant=stats['irrelevant'],
            notes=f"Processed with YouTubeProcessor. Consecutive irrelevant at end: {self.consecutive_irrelevant}"
        )
        
        return stats

    def run(self, queries=None):
        """
        Main run loop.
        """
        self.emit_log('system', 'Starting YouTube Scraper pipeline', 'info')
        self.update_status(running=True, current_query='Starting...')

        # Check queue initially
        self._process_user_queue()

        if not queries:
            queries = list(YOUTUBE_SEED_QUERIES)

        query_index = 0
        total_processed_stats = {'total': 0, 'relevant': 0, 'irrelevant': 0}

        while query_index < len(queries):
            if self.stop_event and self.stop_event.is_set():
                self.emit_log('system', 'Scraper stopped by request', 'warning')
                break

            current_query = queries[query_index]
            self.update_status(running=True, current_query=current_query)
            
            # Process query
            query_stats = self.process_query(current_query)
            total_processed_stats['total'] += query_stats['total']
            total_processed_stats['relevant'] += query_stats['relevant']
            total_processed_stats['irrelevant'] += query_stats['irrelevant']

            # Check queue again
            self._process_user_queue()

            # Check if MiniMax needs to intervene (3+ consecutive irrelevant results)
            if self.consecutive_irrelevant >= 3:
                self.emit_log(
                    'strategy_change', 
                    f"Triggering MiniMax strategy adaptation due to {self.consecutive_irrelevant} consecutive irrelevant results.", 
                    'warning'
                )
                
                # Fetch recent search history for context
                history = self.db_client.get_search_history(platform='youtube')
                
                # Generate new queries
                new_queries = self.manager.generate_queries(
                    platform='youtube',
                    search_history=history,
                    consecutive_irrelevant=self.consecutive_irrelevant
                )
                
                if new_queries:
                    self.emit_log(
                        'strategy_change', 
                        f"MiniMax suggested new strategy. Appending new queries: {new_queries}", 
                        'success'
                    )
                    # Insert the new queries directly ahead of the queue
                    for q in reversed(new_queries):
                        queries.insert(query_index + 1, q)
                    
                    self.consecutive_irrelevant = 0 # reset counter after action
                else:
                    self.emit_log('error', "MiniMax failed to generate queries. Continuing with original list.", 'error')

            query_index += 1
            time.sleep(3)

        self.emit_log(
            'system', 
            f"YouTube Scraper finished. Total results discovered: {total_processed_stats['total']}, Relevant: {total_processed_stats['relevant']}", 
            'success'
        )
        self.update_status(running=False, current_query='Finished')
