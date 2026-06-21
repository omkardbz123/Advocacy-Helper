import google.generativeai as genai
import json
import os
import logging
import time
from .prompts import GEMINI_GRADING_PROMPT

logger = logging.getLogger(__name__)

class GeminiAPIGrader:
    def __init__(self, api_key):
        genai.configure(api_key=api_key)
        self.model = genai.GenerativeModel('gemini-2.0-flash')

    def _parse_json(self, text) -> dict | None:
        try:
            if not text:
                return None
            start = text.find('{')
            end = text.rfind('}')
            if start != -1 and end != -1:
                json_str = text[start:end+1]
                return json.loads(json_str)
            logger.error("No JSON block found in Gemini API response")
            return None
        except Exception as e:
            logger.error(f"JSON parsing error: {e}. Raw text: {text[:200]}")
            return None

    def grade_youtube(self, video_url, title='') -> dict | None:
        """
        Send YouTube URL to Gemini with grading prompt.
        Gemini can analyze YouTube videos by URL.
        Returns parsed JSON dict or None on failure.
        """
        prompt = f"{GEMINI_GRADING_PROMPT}\n\nContent to analyze:\nTitle: {title}\nYouTube URL: {video_url}\n\nAnalyze this YouTube video and grade it."

        try:
            response = self.model.generate_content(prompt)
            return self._parse_json(response.text)
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None

    def grade_instagram(self, media_path, title='') -> dict | None:
        """
        Upload Instagram image/video file to Gemini with grading prompt.
        media_path: absolute path to downloaded image or video file.
        Returns parsed JSON dict or None on failure.
        """
        try:
            logger.info(f"Uploading media file to Gemini: {media_path}")
            media_file = genai.upload_file(media_path)
            prompt = f"{GEMINI_GRADING_PROMPT}\n\nContent to analyze:\nCaption/Title: {title}\n\nAnalyze this Instagram content and grade it."
            
            # Wait for file to process if it's a video
            while media_file.state.name == "PROCESSING":
                logger.info("Waiting for uploaded video to process...")
                time.sleep(2)
                media_file = genai.get_file(media_file.name)
            
            if media_file.state.name == "FAILED":
                raise Exception("File processing failed on Gemini servers")

            response = self.model.generate_content([prompt, media_file])
            text = response.text
            
            # Clean up file on Gemini
            try:
                genai.delete_file(media_file.name)
            except Exception as delete_err:
                logger.warning(f"Failed to delete temp file from Gemini: {delete_err}")

            return self._parse_json(text)
        except Exception as e:
            logger.error(f"Gemini API error: {e}")
            return None
