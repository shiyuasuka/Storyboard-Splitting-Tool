from __future__ import annotations

import asyncio
import os


class LLMConcurrencyLimiter:
    def __init__(self) -> None:
        value = int(os.getenv("LLM_MAX_CONCURRENCY", "1"))
        self.max_concurrency = max(1, value)
        self._sem = asyncio.Semaphore(self.max_concurrency)

    async def run(self, coro):
        async with self._sem:
            return await coro
