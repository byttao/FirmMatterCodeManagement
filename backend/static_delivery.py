"""Compress static resources and cache only content-hashed assets long term."""
import re
from starlette.middleware.gzip import GZipMiddleware


class StaticDelivery:
    def __init__(self,app):
        self.app=app
        self.compressed=GZipMiddleware(self.with_headers,minimum_size=500,compresslevel=6)

    async def with_headers(self,scope,receive,send):
        path=scope.get('path','')
        async def cache(message):
            if message['type']=='http.response.start':
                value=b'public, max-age=31536000, immutable' if re.search(r'/(?:assets)/[^/]+-[A-Za-z0-9_-]{8,}\.(?:js|css|woff2?|png|svg)$',path) else b'no-cache'
                headers=[(key,val) for key,val in message.get('headers',[]) if key.lower()!=b'cache-control']
                message['headers']=headers+[(b'cache-control',value)]
            await send(message)
        await self.app(scope,receive,cache)

    async def __call__(self,scope,receive,send):
        if scope['type']=='http' and not scope.get('path','').startswith('/api/'):
            return await self.compressed(scope,receive,send)
        return await self.app(scope,receive,send)
