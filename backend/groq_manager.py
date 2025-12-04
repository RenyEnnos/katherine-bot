import random
import time
import logging
from typing import List, Optional, Any
from groq import Groq, RateLimitError, APIError
from .groq_keys import GROQ_API_KEYS

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("GroqManager")

class GroqClientManager:
    def __init__(self):
        self.keys = [k for k in GROQ_API_KEYS if k and k.strip()]
        if not self.keys:
            logger.warning("No Groq API keys found in groq_keys.py! Please add them.")
        
        # Track cooldowns: {key: timestamp_when_available}
        self.cooldowns = {}
        self.cooldown_duration = 60 * 2  # 2 minutes penalty for rate limits

    def _get_available_key(self) -> Optional[str]:
        now = time.time()
        
        # Filter out keys that are in cooldown
        available_keys = []
        for k in self.keys:
            if k in self.cooldowns:
                if now >= self.cooldowns[k]:
                    del self.cooldowns[k] # Cooldown expired
                    available_keys.append(k)
                # else: key is still cooling down
            else:
                available_keys.append(k)
        
        if not available_keys:
            return None
            
        # Random selection for "blurring" usage patterns
        return random.choice(available_keys)

    def _mark_key_rate_limited(self, key: str):
        logger.warning(f"Key {key[:10]}... hit Rate Limit. Cooling down for {self.cooldown_duration}s.")
        self.cooldowns[key] = time.time() + self.cooldown_duration

    def chat_completion(self, messages: List[dict], model: str, **kwargs) -> Any:
        """
        Attempts to get a chat completion, rotating keys on failure.
        """
        attempts = 0
        max_attempts = len(self.keys) * 2 # Try enough times to cover all keys plus some retries

        while attempts < max_attempts:
            api_key = self._get_available_key()
            
            if not api_key:
                raise Exception("All Groq API keys are currently in cooldown or none are configured.")

            client = Groq(api_key=api_key)
            
            try:
                # logger.info(f"Using key {api_key[:10]}... for request.")
                return client.chat.completions.create(
                    messages=messages,
                    model=model,
                    **kwargs
                )

            except RateLimitError:
                self._mark_key_rate_limited(api_key)
                attempts += 1
                continue # Retry loop will pick a new key
            
            except APIError as e:
                # If it's a 401 (Invalid Key), maybe we should remove it?
                if "401" in str(e):
                    logger.error(f"Key {api_key[:10]}... is INVALID. Removing from pool.")
                    if api_key in self.keys:
                        self.keys.remove(api_key)
                else:
                    logger.error(f"Groq API Error with key {api_key[:10]}...: {e}")
                
                attempts += 1
                continue

            except Exception as e:
                logger.error(f"Unexpected error: {e}")
                raise e

        raise Exception("Failed to generate response after multiple retries with different keys.")
