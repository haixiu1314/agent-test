"""对分块请求也生效的请求体上限，避免绕过 Content-Length 校验。"""
from uuid import uuid4
from starlette.responses import JSONResponse


class BodyLimitMiddleware:
    def __init__(self, app, max_bytes=1024 * 1024):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or scope['method'] not in ['POST', 'PUT', 'PATCH']:
            return await self.app(scope, receive, send)
        parts, size = [], 0
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > self.max_bytes:
                identifier = str(uuid4())
                response = JSONResponse({'error': {'code':'body_too_large','message':'请求体超过 1 MiB'},
                    'request_id':identifier},status_code=413,headers={'X-Request-ID':identifier})
                return await response(scope, receive, send)
            parts.append(message.get('body', b''))
            if not message.get('more_body', False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if not delivered:
                delivered = True
                return {'type':'http.request','body':b''.join(parts),'more_body':False}
            return await receive()
        await self.app(scope, replay, send)
