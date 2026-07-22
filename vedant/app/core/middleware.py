"""Standard request boundaries.

Four things every request crosses, in order:
  1. CorrelationIdMiddleware — assign/propagate the trace id
  2. BodySizeLimitMiddleware — reject oversized bodies before parsing
  3. TimeoutMiddleware      — no request hangs forever
  4. AccessLogMiddleware    — one structured line per request, with latency
"""

from __future__ import annotations

import asyncio
import time
import uuid

from fastapi import Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.core.logging import correlation_id_ctx, get_logger

log = get_logger("causalcut.access")

CORRELATION_HEADER = "X-Correlation-ID"


class CorrelationIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        cid = request.headers.get(CORRELATION_HEADER) or str(uuid.uuid4())
        token = correlation_id_ctx.set(cid)
        request.state.correlation_id = cid
        try:
            response = await call_next(request)
        finally:
            correlation_id_ctx.reset(token)
        response.headers[CORRELATION_HEADER] = cid
        return response


class BodySizeLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        declared = request.headers.get("content-length")
        if declared and declared.isdigit() and int(declared) > self.max_bytes:
            return JSONResponse(
                status_code=413,
                content={
                    "error": "payload_too_large",
                    "detail": f"body exceeds {self.max_bytes} bytes",
                    "correlation_id": correlation_id_ctx.get(),
                },
            )
        return await call_next(request)


class TimeoutMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, timeout_seconds: float) -> None:
        super().__init__(app)
        self.timeout = timeout_seconds

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        try:
            return await asyncio.wait_for(call_next(request), timeout=self.timeout)
        except asyncio.TimeoutError:
            log.error(
                "request timeout",
                extra={"path": request.url.path, "timeout_s": self.timeout},
            )
            return JSONResponse(
                status_code=504,
                content={
                    "error": "request_timeout",
                    "detail": f"exceeded {self.timeout}s",
                    "correlation_id": correlation_id_ctx.get(),
                },
            )


class AccessLogMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint):
        start = time.perf_counter()
        response: Response = await call_next(request)
        elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
        response.headers["X-Response-Time-ms"] = str(elapsed_ms)
        log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "latency_ms": elapsed_ms,
                "client": request.client.host if request.client else None,
            },
        )
        return response
