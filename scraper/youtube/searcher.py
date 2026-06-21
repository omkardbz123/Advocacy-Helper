from googleapiclient.discovery import build
import logging
import html

logger = logging.getLogger(__name__)

class YouTubeSearcher:
    def __init__(self, api_key):
        self.youtube = build('youtube', 'v3', developerKey=api_key)

    def search(self, query, max_results=10) -> list[dict]:
        """
        Search YouTube for videos matching query.
        Returns list of dicts with keys: video_id, title, thumbnail_url, channel_name, channel_url, published_at
        Each search costs 100 quota units. Max 10,000 units/day ≈ 100 searches.
        """
        try:
            logger.info(f"Searching YouTube for: '{query}'")
            request = self.youtube.search().list(
                q=query,
                part='snippet',
                type='video',
                maxResults=max_results,
                order='relevance'
            )
            response = request.execute()
            results = []
            for item in response.get('items', []):
                results.append({
                    'video_id': item['id']['videoId'],
                    'title': html.unescape(item['snippet']['title']),
                    'thumbnail_url': item['snippet']['thumbnails']['high']['url'],
                    'channel_name': item['snippet']['channelTitle'],
                    'channel_url': f"https://www.youtube.com/channel/{item['snippet']['channelId']}",
                    'video_url': f"https://www.youtube.com/watch?v={item['id']['videoId']}",
                    'published_at': item['snippet']['publishedAt'],
                })
            logger.info(f"Found {len(results)} videos on YouTube")
            return results
        except Exception as e:
            logger.error(f"YouTube search error: {e}")
            return []

    def get_video_details(self, video_id) -> dict | None:
        """Get duration and description for a video. Costs 1 quota unit."""
        try:
            request = self.youtube.videos().list(
                part='contentDetails,snippet',
                id=video_id
            )
            response = request.execute()
            if response['items']:
                item = response['items'][0]
                return {
                    'duration': item['contentDetails']['duration'],
                    'description': item['snippet'].get('description', ''),
                }
            return None
        except Exception as e:
            logger.error(f"YouTube get_video_details error: {e}")
            return None
