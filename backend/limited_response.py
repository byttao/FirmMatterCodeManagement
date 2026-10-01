from fastapi.responses import StreamingResponse


class LimitedStreamingResponse(StreamingResponse):
    """Keep the resource slot until transfer completes or disconnects."""
    def __init__(self, *args, slot, **kwargs):
        self.slot = slot
        super().__init__(*args, **kwargs)

    async def __call__(self, scope, receive, send):
        try:
            await super().__call__(scope, receive, send)
        finally:
            self.slot.release()
