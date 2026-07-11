import asyncio
import weakref

class LockManager:
    def __init__(self):
        self._locks = weakref.WeakValueDictionary()
        self._global_lock = asyncio.Lock()

    async def get_lock(self, user_id: str) -> asyncio.Lock:
        async with self._global_lock:
            lock = self._locks.get(user_id)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[user_id] = lock
            return lock
