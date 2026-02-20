"""
llm.py — Google AI Studio client wrapper using google.genai.
         Defaults to gemma-3-27b-it.
"""

import time
import logging
from google import genai
from google.genai import types

from src.config import GEMINI_API_KEY

logger = logging.getLogger(__name__)

MODEL_NAME = "gemma-3-27b-it"
MAX_RETRIES = 3
RETRY_DELAY_SECONDS = 5


class GeminiClient:
    """Thin wrapper around the google.genai SDK for Gemma 3 27B IT."""

    def __init__(self):
        if not GEMINI_API_KEY:
            raise ValueError(
                "GEMINI_API_KEY is not set. "
                "Add it to your .env file or GitHub Secrets."
            )
        self.client = genai.Client(api_key=GEMINI_API_KEY)
        logger.info(f"GeminiClient initialized with model: {MODEL_NAME}")

    def generate(self, system_prompt: str, user_content: str) -> str:
        """
        Sends a prompt to Gemma 3 27B and returns the generated text.
        Retries up to MAX_RETRIES times on transient errors.

        Args:
            system_prompt: The persona/directive for the model.
            user_content:  The raw scraped data for the model to synthesize.

        Returns:
            Generated text as a string.
        """
        # Gemma via Google AI Studio doesn't support a separate system role,
        # so we prepend the system prompt into the user turn.
        full_prompt = f"{system_prompt}\n\n---\n\nHere is the raw data to work with:\n\n{user_content}"

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                logger.info(f"LLM call attempt {attempt}/{MAX_RETRIES}")
                response = self.client.models.generate_content(
                    model=MODEL_NAME,
                    contents=full_prompt,
                    config=types.GenerateContentConfig(
                        temperature=0.4,
                    ),
                )
                return response.text.strip()
            except Exception as e:
                logger.warning(f"LLM attempt {attempt} failed: {e}")
                if attempt < MAX_RETRIES:
                    time.sleep(RETRY_DELAY_SECONDS * attempt)
                else:
                    logger.error("All LLM retries exhausted.")
                    raise
