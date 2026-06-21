import requests
import json
import logging
from scraper.grader.prompts import MINIMAX_MANAGER_PROMPT

logger = logging.getLogger(__name__)

class MiniMaxManager:
    def __init__(self, api_key):
        self.api_key = api_key
        self.url = 'https://integrate.api.nvidia.com/v1/chat/completions'
        self.model = 'minimaxai/minimax-m3'

    def generate_queries(self, platform, search_history, consecutive_irrelevant=0) -> list[str]:
        """
        Ask MiniMax to generate 5 new search queries based on history.
        
        Args:
            platform: 'youtube' or 'instagram'
            search_history: list of dicts with keys: search_query, total_results, relevant_count, irrelevant_count
            consecutive_irrelevant: how many consecutive irrelevant results triggered this call
        
        Returns:
            List of 5 query strings, or empty list on failure
        """
        history_text = "No previous searches." if not search_history else "\n".join(
            f"- Query: '{h.get('search_query', '')}' → {h.get('total_results', 0)} results, {h.get('relevant_count', 0)} relevant, {h.get('irrelevant_count', 0)} irrelevant"
            for h in search_history
        )

        user_message = f"""Platform: {platform}
Consecutive irrelevant results that triggered this: {consecutive_irrelevant}

Previous search history:
{history_text}

Generate 5 new search queries. Remember:
- For Instagram, return hashtags WITHOUT the # symbol.
- Do NOT repeat any previous queries.
- Focus on finding anti-vegan and anti-animal content."""

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Accept": "application/json",
            "Content-Type": "application/json"
        }

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": MINIMAX_MANAGER_PROMPT},
                {"role": "user", "content": user_message}
            ],
            "max_tokens": 1024,
            "temperature": 0.9,
            "top_p": 0.95,
            "stream": False
        }

        try:
            logger.info(f"Requesting new search strategy from MiniMax for {platform}...")
            response = requests.post(self.url, headers=headers, json=payload, timeout=30)
            response.raise_for_status()
            result = response.json()
            text = result['choices'][0]['message']['content'].strip()
            # Extract JSON robustly
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                json_str = text[start:end+1]
                data = json.loads(json_str)
            else:
                logger.error("No JSON block found in MiniMax response")
                data = {}
            queries = data.get('queries', [])
            logger.info(f"MiniMax generated queries: {queries}")
            return queries
        except Exception as e:
            logger.error(f"MiniMax error: {e}")
            return []
