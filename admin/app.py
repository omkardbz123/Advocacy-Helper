import os
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_from_directory
from flask_socketio import SocketIO, emit
from flask_login import LoginManager, login_user, logout_user, login_required, current_user

from scraper.config import Config
from scraper.db.cloudflare_client import CloudflareClient
from scraper.youtube.searcher import YouTubeSearcher
from scraper.youtube.processor import YouTubeProcessor
from scraper.instagram.auth import InstagramAuth
from scraper.instagram.scraper import InstagramReelsScraper
from scraper.grader.gemini_api import GeminiAPIGrader
from scraper.grader.gemini_browser import GeminiBrowserGrader
from scraper.manager.minimax import MiniMaxManager
from .auth import get_user_by_id, verify_login

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

socketio = SocketIO(cors_allowed_origins="*")

# Scraper tracking
active_scrapers = {
    'youtube': {
        'thread': None,
        'stop_event': None,
        'grader': None
    },
    'instagram': {
        'thread': None,
        'stop_event': None,
        'grader': None
    }
}

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'advocacy-helper-session-secret-9988'
    
    # Setup Login Manager
    login_manager = LoginManager()
    login_manager.login_view = 'login'
    login_manager.init_app(app)
    
    @login_manager.user_loader
    def load_user(user_id):
        return get_user_by_id(user_id)
        
    # Cloudflare client builder helper
    def get_db():
        return CloudflareClient(Config.CLOUDFLARE_WORKER_URL, Config.CLOUDFLARE_API_SECRET)

    # Routes
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            if verify_login(username, password):
                user = get_user_by_id('1')
                login_user(user)
                flash('Successfully logged in!', 'success')
                return redirect(url_for('dashboard'))
            flash('Invalid username or password.', 'error')
        return render_template('login.html')

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('Successfully logged out.', 'info')
        return redirect(url_for('login'))

    @app.route('/')
    @login_required
    def dashboard():
        db = get_db()
        stats = {'youtube': {'total': 0, 'friendly': 0, 'partial': 0, 'not_friendly': 0},
                 'instagram': {'total': 0, 'friendly': 0, 'partial': 0, 'not_friendly': 0}}
        try:
            # Let's fetch stats from Worker API
            url = f"{db.base_url}/api/stats"
            import requests
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                stats = resp.json()
        except Exception as e:
            logger.error(f"Failed to fetch stats for dashboard: {e}")
            
        return render_template('dashboard.html', stats=stats)

    @app.route('/youtube')
    @login_required
    def youtube_list():
        db = get_db()
        items = db.get_all_youtube()
        import html
        for item in items:
            item['title'] = html.unescape(item.get('title', ''))
        return render_template('youtube.html', items=items)

    @app.route('/instagram')
    @login_required
    def instagram_list():
        db = get_db()
        items = db.get_all_instagram()
        import html
        for item in items:
            item['title'] = html.unescape(item.get('title', ''))
        return render_template('instagram.html', items=items)

    @app.route('/search-history')
    @login_required
    def search_history():
        db = get_db()
        history = db.get_search_history()
        return render_template('search_history.html', history=history)

    @app.route('/edit/<platform>/<id>', methods=['GET', 'POST'])
    @login_required
    def edit_content(platform, id):
        db = get_db()
        
        # Load content item
        # We fetch all and find the item in local Python code as Worker has no direct GET single item endpoint
        item = None
        if platform == 'youtube':
            items = db.get_all_youtube()
        else:
            items = db.get_all_instagram()
            
        for i in items:
            if str(i.get('id')) == str(id):
                import html
                item = i
                item['title'] = html.unescape(item.get('title', ''))
                break
                
        if not item:
            flash('Item not found.', 'error')
            return redirect(url_for(f'{platform}_list'))
            
        if request.method == 'POST':
            update_data = {
                'title': request.form.get('title'),
                'grade_animal_friendly': request.form.get('grade_animal_friendly'),
                'grade_scientific': request.form.get('grade_scientific'),
                'grade_emotional_manipulation': request.form.get('grade_emotional_manipulation'),
                'summary': request.form.get('summary'),
                'status': request.form.get('status')
            }
            
            success = False
            if platform == 'youtube':
                success = db.update_youtube(id, update_data)
            else:
                success = db.update_instagram(id, update_data)
                
            if success:
                flash('Content updated successfully!', 'success')
                return redirect(url_for(f'{platform}_list'))
            flash('Failed to update content in database.', 'error')
            
        return render_template('edit_content.html', item=item, platform=platform)

    @app.route('/delete/<platform>/<id>', methods=['POST'])
    @login_required
    def delete_content(platform, id):
        db = get_db()
        success = False
        if platform == 'youtube':
            success = db.delete_youtube(id)
        else:
            success = db.delete_instagram(id)
            
        if success:
            flash('Content deleted successfully.', 'success')
        else:
            flash('Failed to delete content.', 'error')
        return redirect(url_for(f'{platform}_list'))

    @app.route('/api/bulk-delete/<platform>', methods=['POST'])
    @login_required
    def bulk_delete(platform):
        """Delete multiple content items at once."""
        if platform not in ('youtube', 'instagram'):
            return jsonify({'error': 'Invalid platform'}), 400
        data = request.json or {}
        ids = data.get('ids', [])
        if not ids:
            return jsonify({'error': 'No IDs provided'}), 400
        db = get_db()
        deleted = 0
        for item_id in ids:
            if platform == 'youtube':
                if db.delete_youtube(item_id):
                    deleted += 1
            else:
                if db.delete_instagram(item_id):
                    deleted += 1
        return jsonify({'success': True, 'deleted': deleted})

    @app.route('/api/delete-all/<platform>', methods=['POST'])
    @login_required
    def delete_all(platform):
        """Delete ALL content for a platform."""
        if platform not in ('youtube', 'instagram'):
            return jsonify({'error': 'Invalid platform'}), 400
        db = get_db()
        if platform == 'youtube':
            items = db.get_all_youtube()
        else:
            items = db.get_all_instagram()
        deleted = 0
        for item in items:
            item_id = item.get('id')
            if item_id:
                if platform == 'youtube':
                    if db.delete_youtube(item_id):
                        deleted += 1
                else:
                    if db.delete_instagram(item_id):
                        deleted += 1
        return jsonify({'success': True, 'deleted': deleted})

    @app.route('/settings', methods=['GET', 'POST'])
    @login_required
    def settings():
        if request.method == 'POST':
            # Helper to update key if provided
            def update_if_present(env_key, form_key):
                val = request.form.get(form_key)
                if val and val.strip(): # Only update if not empty
                    Config.update_env(env_key, val.strip())

            update_if_present('YOUTUBE_API_KEY', 'youtube_api_key')
            update_if_present('INSTAGRAM_USERNAME', 'instagram_username')
            update_if_present('INSTAGRAM_PASSWORD', 'instagram_password')
            update_if_present('GEMINI_API_KEY', 'gemini_api_key')
            update_if_present('NVIDIA_API_KEY', 'nvidia_api_key')
            update_if_present('CLOUDFLARE_WORKER_URL', 'cloudflare_worker_url')
            update_if_present('CLOUDFLARE_API_SECRET', 'cloudflare_api_secret')
            update_if_present('ADMIN_USERNAME', 'admin_username')
            update_if_present('ADMIN_PASSWORD', 'admin_password')
            
            flash('Settings updated successfully!', 'success')
            return redirect(url_for('settings'))
            
        return render_template('settings.html', config=Config)

    # Scraper Control APIs
    @app.route('/api/scraper-status', methods=['GET'])
    @login_required
    def get_scraper_status():
        status = {}
        for platform in ['youtube', 'instagram']:
            status[platform] = {
                'running': active_scrapers[platform]['thread'] is not None and active_scrapers[platform]['thread'].is_alive()
            }
        return jsonify(status)

    @app.route('/api/start-scraper', methods=['POST'])
    @login_required
    def start_scraper():
        data = request.json or {}
        platform = data.get('platform')
        gemini_mode = data.get('gemini_mode', 'api')
        
        if platform not in ('youtube', 'instagram'):
            return jsonify({'error': 'Invalid platform'}), 400
            
        if active_scrapers[platform]['thread'] and active_scrapers[platform]['thread'].is_alive():
            return jsonify({'error': 'Scraper already running'}), 400

        stop_event = threading.Event()
        active_scrapers[platform]['stop_event'] = stop_event

        # Define the run execution function
        def run_scraper_thread():
            db_client = get_db()
            
            # Validation checks
            errors = []
            if not Config.CLOUDFLARE_WORKER_URL or not Config.CLOUDFLARE_API_SECRET:
                errors.append("Cloudflare Worker URL/Secret is not configured.")
            if not Config.NVIDIA_API_KEY:
                errors.append("NVIDIA NIM API key is not configured.")
            if platform == 'youtube' and not Config.YOUTUBE_API_KEY:
                errors.append("YouTube API Key is not configured.")
            if gemini_mode == 'api' and not Config.GEMINI_API_KEY:
                errors.append("Gemini API Key is not configured.")
            if platform == 'instagram' and (not Config.INSTAGRAM_USERNAME and not Config.INSTAGRAM_PASSWORD):
                errors.append("Instagram credentials not set. Scraper will wait for manual login in browser.")

            if errors:
                error_msg = " | ".join(errors)
                logger.error(f"Configuration error: {error_msg}")
                socketio.emit('scraper_log', {
                    'platform': platform,
                    'action': 'error',
                    'detail': f"Configuration error: {error_msg} Please go to Settings and configure all keys.",
                    'level': 'error',
                    'timestamp': datetime.now().isoformat()
                })
                # Update status UI
                socketio.emit('scraper_status', {
                    'running': False,
                    'platform': platform,
                    'current_query': 'Config Error'
                })
                return

            manager = MiniMaxManager(Config.NVIDIA_API_KEY)
            
            # Determine if we need Playwright at all
            need_playwright = (gemini_mode == 'browser') or (platform == 'instagram')
            
            grader = None
            try:
                if need_playwright:
                    from playwright.sync_api import sync_playwright
                    with sync_playwright() as p:
                        # Setup Grader
                        if gemini_mode == 'api':
                            grader = GeminiAPIGrader(Config.GEMINI_API_KEY)
                        else:
                            grader = GeminiBrowserGrader(Config.PLAYWRIGHT_SESSION_DIR, playwright_instance=p)
                            
                        active_scrapers[platform]['grader'] = grader

                        if platform == 'youtube':
                            searcher = YouTubeSearcher(Config.YOUTUBE_API_KEY)
                            processor = YouTubeProcessor(
                                searcher=searcher,
                                grader=grader,
                                db_client=db_client,
                                manager=manager,
                                socketio=socketio,
                                stop_event=stop_event
                            )
                            processor.run()
                        else:
                            # Instagram: use simple direct reels scraper
                            auth = InstagramAuth(
                                Config.INSTAGRAM_USERNAME,
                                Config.INSTAGRAM_PASSWORD,
                                Config.PLAYWRIGHT_SESSION_DIR
                            )
                            ig_scraper = InstagramReelsScraper(
                                auth=auth,
                                grader=grader,
                                db_client=db_client,
                                manager=manager,
                                socketio=socketio,
                                stop_event=stop_event
                            )
                            ig_scraper.run(playwright_instance=p)
                else:
                    # Setup Grader (API Grader only)
                    grader = GeminiAPIGrader(Config.GEMINI_API_KEY)
                    active_scrapers[platform]['grader'] = grader

                    if platform == 'youtube':
                        searcher = YouTubeSearcher(Config.YOUTUBE_API_KEY)
                        processor = YouTubeProcessor(
                            searcher=searcher,
                            grader=grader,
                            db_client=db_client,
                            manager=manager,
                            socketio=socketio,
                            stop_event=stop_event
                        )
                        processor.run()
            except Exception as thread_err:
                logger.error(f"Error in scraper thread: {thread_err}")
                db_client.log_activity(platform, 'error', str(thread_err), 'error')
                socketio.emit('scraper_log', {
                    'platform': platform,
                    'action': 'error',
                    'detail': f"Critical thread error: {thread_err}",
                    'level': 'error',
                    'timestamp': datetime.now().isoformat()
                })
            finally:
                # Clean up resources
                if grader and hasattr(grader, 'close'):
                    try:
                        grader.close()
                    except Exception as close_err:
                        logger.error(f"Error closing grader: {close_err}")
                active_scrapers[platform]['thread'] = None
                active_scrapers[platform]['stop_event'] = None
                active_scrapers[platform]['grader'] = None
                
                socketio.emit('scraper_status', {
                    'running': False,
                    'platform': platform,
                    'current_query': 'Stopped'
                })

        # Start thread
        thread = threading.Thread(target=run_scraper_thread, daemon=True)
        active_scrapers[platform]['thread'] = thread
        thread.start()
        
        return jsonify({'success': f'{platform} scraper started'})

    @app.route('/api/stop-scraper', methods=['POST'])
    @login_required
    def stop_scraper():
        data = request.json or {}
        platform = data.get('platform')
        
        if platform not in ('youtube', 'instagram'):
            return jsonify({'error': 'Invalid platform'}), 400
            
        info = active_scrapers[platform]
        if info['stop_event']:
            info['stop_event'].set()
            
            # Let's close grader immediately if browser mode is running
            if info['grader'] and hasattr(info['grader'], 'close'):
                try:
                    info['grader'].close()
                except Exception as close_err:
                    logger.error(f"Error closing grader on stop: {close_err}")
            
            return jsonify({'success': f'{platform} scraper requested to stop'})
            
        return jsonify({'error': 'Scraper is not running'}), 400

    # Public Website Route (Access at http://localhost:5000/feed/)
    @app.route('/feed/')
    @app.route('/feed/<path:path>')
    def serve_public(path='index.html'):
        return send_from_directory('../website', path)

    # SocketIO events
    @socketio.on('connect')
    def handle_connect():
        emit('connection_response', {'data': 'Connected to admin live monitor'})

    socketio.init_app(app)
    return app
