import asyncio
import importlib
from pathlib import Path
import sys
import time
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))

class TransferTests(unittest.IsolatedAsyncioTestCase):
    async def test_shared_admission_and_release_after_send_failure(self):
        from transfer import budget
        from limited_response import LimitedStreamingResponse
        from fastapi import HTTPException
        lease=budget.acquire()
        with self.assertRaises(HTTPException) as caught:budget.acquire()
        self.assertEqual(caught.exception.status_code,429);self.assertEqual(caught.exception.headers['Retry-After'],'5')
        async def receive():await asyncio.Event().wait()
        async def send(message):raise RuntimeError('transport lost')
        response=LimitedStreamingResponse(iter([b'x']),slot=lease)
        try:await response({'type':'http','asgi':{'version':'3.0'},'method':'GET'},receive,send)
        except BaseException:pass
        lease.release() # A second release must not increase semaphore capacity.
        replacement=budget.acquire()
        with self.assertRaises(HTTPException):budget.acquire()
        replacement.release()

    async def test_real_rate_ten_seconds_and_cancel_wait(self):
        from transfer import budget
        from limited_response import LimitedStreamingResponse
        lease=budget.acquire();sent=0;max_chunk=0;ticks=0
        async def receive():await asyncio.Event().wait()
        async def send(message):
            nonlocal sent,max_chunk
            if message['type']=='http.response.body':sent+=len(message.get('body',b''));max_chunk=max(max_chunk,len(message.get('body',b'')))
        async def ticker():
            nonlocal ticks
            while True:ticks+=1;await asyncio.sleep(.01)
        tick=asyncio.create_task(ticker());start=time.monotonic()
        response=LimitedStreamingResponse(iter([b'x'*(1056*1024)]),slot=lease)
        await response({'type':'http','asgi':{'version':'3.0'},'method':'GET'},receive,send)
        elapsed=time.monotonic()-start;tick.cancel()
        self.assertGreaterEqual(elapsed,10);self.assertLess(sent/elapsed,102400*1.03);self.assertLessEqual(max_chunk,16384);self.assertGreater(ticks,500)
        lease=budget.acquire();response=LimitedStreamingResponse(iter([b'x'*102400]),slot=lease)
        job=asyncio.create_task(response({'type':'http','asgi':{'version':'3.0'},'method':'GET'},receive,send));await asyncio.sleep(.03);job.cancel()
        try:await job
        except asyncio.CancelledError:pass
        replacement=budget.acquire();replacement.release()
