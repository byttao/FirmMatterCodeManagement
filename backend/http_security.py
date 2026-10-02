"""HTTP boundary and bounded login throttling for direct IP deployments."""
import hashlib
import ipaddress
import os
import secrets
import socket
import threading
import time
from collections import OrderedDict
from urllib.parse import urlsplit
from fastapi import HTTPException
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from fastapi.exceptions import RequestValidationError
from error_messages import public_error, category, exception_location, validation_message

COOKIE = "firm_session"
CSRF_COOKIE = "firm_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def digest(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class LoginThrottle:
    def __init__(self):
        self.lock = threading.Lock()
        self.entries = OrderedDict()

    def check(self, account, client_ip):
        now = time.monotonic()
        with self.lock:
            for key, maximum in ((("account", account.casefold()[:100]), 6), (("ip", client_ip), 300)):
                count, until = self.entries.get(key, (0, 0))
                if until > now and count >= maximum:
                    raise HTTPException(429, "登录失败次数过多，请稍后重试")

    def record(self, account, client_ip, success):
        now = time.monotonic()
        with self.lock:
            if success:
                self.entries.pop(("account", account.casefold()[:100]), None)
                return
            for key in (("account", account.casefold()[:100]), ("ip", client_ip)):
                count, until = self.entries.pop(key, (0, 0))
                self.entries[key] = (count + 1 if until > now else 1, until if until > now else now + 300)
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)

    def consume(self, scope, actor, maximum=120, window=60):
        now = time.monotonic()
        key = (scope, str(actor))
        with self.lock:
            count, until = self.entries.pop(key, (0, 0))
            count = count + 1 if until > now else 1
            until = until if until > now else now + window
            self.entries[key] = (count, until)
            while len(self.entries) > 4096:
                self.entries.popitem(last=False)
            if count > maximum:
                raise HTTPException(429, "操作过于频繁，请稍后重试")


throttle = LoginThrottle()
password_slots = threading.BoundedSemaphore(2)


def set_session_cookies(response, secret, csrf, seconds):
    response.set_cookie(COOKIE, secret, max_age=seconds, httponly=True, samesite="lax", secure=False, path="/")
    response.set_cookie(CSRF_COOKIE, csrf, max_age=seconds, httponly=False, samesite="lax", secure=False, path="/")


def clear_session_cookies(response):
    response.delete_cookie(COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def check_csrf(request, session):
    if request.method not in SAFE_METHODS:
        supplied = request.headers.get("x-csrf-token", "")
        if not supplied or not secrets.compare_digest(digest(supplied), session.csrf_hash):
            raise HTTPException(403, "请求校验失败，请刷新页面")


class RequestSizeLimit:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in SAFE_METHODS:
            return await self.app(scope, receive, send)
        chunks, size = [], 0
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            size += len(message.get("body", b""))
            if size > 2 * 1024 * 1024:
                request_id = scope.get("state", {}).get("request_id", secrets.token_hex(16))
                response = JSONResponse(status_code=413, content={"detail": {"code": "request_too_large", "message": "请求超过大小限制", "request_id": request_id}})
                return await response(scope, receive, send)
            chunks.append(message)
            if not message.get("more_body"):
                break
        iterator = iter(chunks)
        async def replay():
            try:
                return next(iterator)
            except StopIteration:
                return await receive()
        await self.app(scope, replay, send)


def install_http_boundary(app, prefix, default_port):
    app.add_middleware(RequestSizeLimit)
    hosts = {"127.0.0.1", "localhost", "::1"}
    try:
        hosts.update(item[4][0] for item in socket.getaddrinfo(socket.gethostname(), None))
    except OSError:
        pass
    hosts.update(value.strip() for value in os.getenv(prefix + "_ALLOWED_HOSTS", "").split(",") if value.strip())

    async def checked_request(request, call_next):
        def rejected(code, message, status):
            request.state.reason_code = code
            return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message, "category": category(status), "request_id": request.state.request_id}},
                                headers={"X-Request-ID": request.state.request_id})
        try:
            authority = urlsplit("http://" + request.headers.get("host", ""))
            hostname, port = authority.hostname, authority.port or 80
        except ValueError:
            return rejected("invalid_host", "访问地址无效", 400)
        configured_ports = {default_port}
        configured_ports.update(int(p) for p in os.getenv(prefix + "_ALLOWED_PORTS", "").split(",") if p.strip().isdigit())
        if hostname not in hosts or port not in configured_ports:
            return rejected("invalid_host", "访问地址未配置，请联系管理员", 400)
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 2 * 1024 * 1024):
            return rejected("request_too_large", "请求超过大小限制", 413)
        if request.method not in SAFE_METHODS and request.url.path.startswith("/api/"):
            origin = request.headers.get("origin")
            if origin and origin != str(request.base_url).rstrip("/"):
                return rejected("invalid_origin", "不允许跨来源写入", 403)
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

    @app.middleware("http")
    async def http_boundary(request, call_next):
        from diagnostics import record_request
        request.state.request_id = secrets.token_hex(16)
        started = time.monotonic()
        try:
            response = await checked_request(request, call_next)
        except Exception as error:
            request.state.reason_code = "internal_error"
            request.state.exception_type = type(error).__name__
            request.state.exception_location = exception_location(error)
            response = JSONResponse(status_code=500, content={"detail": {
                **public_error(500), "request_id": request.state.request_id}})
        response.headers["X-Request-ID"] = request.state.request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
            # Logging failures must not change a completed business transaction's response.
            try: record_request(request, response.status_code, started)
            except Exception: pass
        return response

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, error):
        detail = public_error(error.status_code, error.detail)
        request.state.reason_code = detail["code"]
        if error.status_code >= 500 and (error.__cause__ or error.__context__):
            cause = error.__cause__ or error.__context__
            request.state.exception_type = type(cause).__name__
            request.state.exception_location = exception_location(cause)
        return JSONResponse(status_code=error.status_code, headers=error.headers,
                            content={"detail": {**detail, "request_id": getattr(request.state, "request_id", "")}})

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        request.state.reason_code = "invalid_input"
        return JSONResponse(status_code=422, content={"detail": {
            **public_error(422), "message": validation_message(error.errors()), "request_id": getattr(request.state, "request_id", "")}})
