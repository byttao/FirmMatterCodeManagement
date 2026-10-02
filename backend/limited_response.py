import asyncio
from fastapi.responses import StreamingResponse

class LimitedStreamingResponse(StreamingResponse):
    """A lease covers generation plus transmission; cancellation releases it once."""
    def __init__(self, *args, slot, **kwargs):
        self.slot=slot
        super().__init__(*args, **kwargs)
        self.body_iterator=slot.pace(self.body_iterator)

    async def __call__(self, scope, receive, send):
        async def bounded_send(message):
            # A progressing 50MiB download can take 8.5 minutes. Only a stalled send expires.
            await asyncio.wait_for(send(message),timeout=60)
        try:await super().__call__(scope, receive, bounded_send)
        finally:
            try:await self.body_iterator.aclose()
            finally:self.slot.release()
