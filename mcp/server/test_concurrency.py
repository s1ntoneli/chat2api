import asyncio
import unittest
from concurrency import SharedToolLimit


class SharedToolLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_bounds_work_across_clients(self):
        guard = SharedToolLimit(4)
        active = maximum = 0
        async def work(context):
            nonlocal active, maximum
            active += 1
            maximum = max(maximum, active)
            await asyncio.sleep(0.01)
            active -= 1
            return context
        results = await asyncio.gather(*(guard.on_call_tool(i, work) for i in range(20)))
        self.assertEqual(results, list(range(20)))
        self.assertEqual(maximum, 4)
        self.assertEqual(active, 0)

    async def test_failure_and_cancellation_release_capacity(self):
        guard = SharedToolLimit(1)
        async def fail(_):
            raise ValueError('expected fixture failure')
        with self.assertRaises(ValueError):
            await guard.on_call_tool(None, fail)
        entered = asyncio.Event()
        async def pending(_):
            entered.set()
            await asyncio.Event().wait()
        task = asyncio.create_task(guard.on_call_tool(None, pending))
        await entered.wait()
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task
        async def result(value):
            return value
        self.assertEqual(await asyncio.wait_for(guard.on_call_tool(42, result), 1), 42)

if __name__ == '__main__':
    unittest.main()
