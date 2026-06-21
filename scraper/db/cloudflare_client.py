import requests
import logging

logger = logging.getLogger(__name__)

class CloudflareClient:
    def __init__(self, worker_url, api_secret):
        self.base_url = worker_url.rstrip('/')
        self.headers = {
            'X-API-Secret': api_secret,
            'Content-Type': 'application/json'
        }

    # Dedup checks
    def youtube_exists(self, video_id) -> bool:
        try:
            url = f"{self.base_url}/api/youtube/check/{video_id}"
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('exists', False)
            logger.error(f"Error checking youtube dedup: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to check youtube dedup: {e}")
            return False

    def instagram_exists(self, post_id) -> bool:
        try:
            url = f"{self.base_url}/api/instagram/check/{post_id}"
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('exists', False)
            logger.error(f"Error checking instagram dedup: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to check instagram dedup: {e}")
            return False

    # Insert content
    def insert_youtube(self, data: dict) -> bool:
        try:
            url = f"{self.base_url}/api/youtube"
            resp = requests.post(url, headers=self.headers, json=data, timeout=10)
            if resp.status_code in (200, 201):
                return True
            logger.error(f"Error inserting youtube content: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to insert youtube content: {e}")
            return False

    def insert_instagram(self, data: dict) -> bool:
        try:
            url = f"{self.base_url}/api/instagram"
            resp = requests.post(url, headers=self.headers, json=data, timeout=10)
            if resp.status_code in (200, 201):
                return True
            logger.error(f"Error inserting instagram content: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to insert instagram content: {e}")
            return False

    # Update content
    def update_youtube(self, id: int, data: dict) -> bool:
        try:
            url = f"{self.base_url}/api/youtube/{id}"
            resp = requests.put(url, headers=self.headers, json=data, timeout=10)
            if resp.status_code == 200:
                return True
            logger.error(f"Error updating youtube content: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to update youtube content: {e}")
            return False

    def update_instagram(self, id: int, data: dict) -> bool:
        try:
            url = f"{self.base_url}/api/instagram/{id}"
            resp = requests.put(url, headers=self.headers, json=data, timeout=10)
            if resp.status_code == 200:
                return True
            logger.error(f"Error updating instagram content: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to update instagram content: {e}")
            return False

    # Delete content
    def delete_youtube(self, id: int) -> bool:
        try:
            url = f"{self.base_url}/api/youtube/{id}"
            resp = requests.delete(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return True
            logger.error(f"Error deleting youtube content: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete youtube content: {e}")
            return False

    def delete_instagram(self, id: int) -> bool:
        try:
            url = f"{self.base_url}/api/instagram/{id}"
            resp = requests.delete(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return True
            logger.error(f"Error deleting instagram content: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to delete instagram content: {e}")
            return False

    # Get content (for admin)
    def get_all_youtube(self) -> list:
        try:
            url = f"{self.base_url}/api/youtube/all"
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('data', [])
            logger.error(f"Error fetching all youtube content: {resp.status_code} - {resp.text}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch all youtube content: {e}")
            return []

    def get_all_instagram(self) -> list:
        try:
            url = f"{self.base_url}/api/instagram/all"
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('data', [])
            logger.error(f"Error fetching all instagram content: {resp.status_code} - {resp.text}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch all instagram content: {e}")
            return []

    # Search history
    def log_search(self, platform, query, total, relevant, irrelevant, notes='') -> bool:
        try:
            url = f"{self.base_url}/api/search-history"
            data = {
                'platform': platform,
                'search_query': query,
                'total_results': total,
                'relevant_count': relevant,
                'irrelevant_count': irrelevant,
                'strategy_notes': notes
            }
            resp = requests.post(url, headers=self.headers, json=data, timeout=10)
            if resp.status_code in (200, 201):
                return True
            logger.error(f"Error logging search: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to log search: {e}")
            return False

    def get_search_history(self, platform=None) -> list:
        try:
            url = f"{self.base_url}/api/search-history"
            params = {}
            if platform:
                params['platform'] = platform
            resp = requests.get(url, headers=self.headers, params=params, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('data', [])
            logger.error(f"Error getting search history: {resp.status_code} - {resp.text}")
            return []
        except Exception as e:
            logger.error(f"Failed to fetch search history: {e}")
            return []

    # User Submissions
    def submit_user_video(self, url: str, platform: str) -> bool:
        try:
            api_url = f"{self.base_url}/api/submissions"
            data = {'url': url, 'platform': platform}
            resp = requests.post(api_url, headers=self.headers, json=data, timeout=10)
            if resp.status_code == 201:
                return True
            logger.error(f"Error submitting user video: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to submit user video: {e}")
            return False

    def get_next_pending_submission(self, platform: str) -> dict:
        try:
            url = f"{self.base_url}/api/submissions/pending?platform={platform}"
            resp = requests.get(url, headers=self.headers, timeout=10)
            if resp.status_code == 200:
                return resp.json().get('data')
            logger.error(f"Error fetching pending submission: {resp.status_code} - {resp.text}")
            return None
        except Exception as e:
            logger.error(f"Failed to fetch pending submission: {e}")
            return None

    def update_submission_status(self, submission_id: str, status: str) -> bool:
        try:
            url = f"{self.base_url}/api/submissions/{submission_id}/status"
            resp = requests.put(url, headers=self.headers, json={'status': status}, timeout=10)
            if resp.status_code == 200:
                return True
            logger.error(f"Error updating submission status: {resp.status_code} - {resp.text}")
            return False
        except Exception as e:
            logger.error(f"Failed to update submission status: {e}")
            return False

    # Scraper log (Bypassed - local Socket.IO is used instead of database logging)
    def log_activity(self, platform, action, detail='', level='info') -> bool:
        return True

    def get_logs(self, limit=50, after_id=None) -> list:
        return []
