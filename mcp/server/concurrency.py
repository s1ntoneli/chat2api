"""Bound expensive upstream calls across all transports and sessions."""
import asyncio
from fastmcp.server.middleware import Middleware


class SharedToolLimit(Middleware):
    def __init__(self, limit=4):
        self.slots = asyncio.Semaphore(limit)

    async def on_call_tool(self, context, call_next):
        async with self.slots:
            return await call_next(context)
