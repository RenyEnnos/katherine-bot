import asyncio
from contextlib import asynccontextmanager
from typing import Dict, List

class UserLockManager:
    """
    Manages per-user locks to ensure serial processing of requests from the same user.
    Includes a reference-counting mechanism to clean up locks for inactive users.
    """
    def __init__(self):
        self._locks: Dict[str, List] = {} # user_id -> [asyncio.Lock, ref_count]
        self._dict_lock = asyncio.Lock()

    @asynccontextmanager
    async def lock(self, user_id: str):
        # 1. Get or create lock and increment reference count
        async with self._dict_lock:
            if user_id not in self._locks:
                self._locks[user_id] = [asyncio.Lock(), 0]
            self._locks[user_id][1] += 1
            user_lock = self._locks[user_id][0]

        try:
            # 2. Wait for the user-specific lock
            # We use a try-finally block here specifically to handle
            # cancellations and errors during 'yield'
            async with user_lock:
                yield
        finally:
            # 3. Decrement reference count and cleanup if zero
            # This 'finally' block is critical: it runs even if 'yield'
            # was cancelled or raised an exception.
            async with self._dict_lock:
                if user_id in self._locks:
                    self._locks[user_id][1] -= 1
                    if self._locks[user_id][1] <= 0:
                        del self._locks[user_id]
