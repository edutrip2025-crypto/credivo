from pathlib import Path
import json
import logging
import time
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.core.config import get_settings
from app.core.ops_metrics import ops_metrics
from app.core.rate_limit import InMemoryRateLimiter, LimitRule
from app.db.init_db import init_db

settings = get_settings()
app = FastAPI(title=settings.app_name, version="0.1.0")
request_logger = logging.getLogger("credivo.request")
APP_DIR = Path(__file__).resolve().parent
ASSESSMENT_WEB_DIST_DIR = APP_DIR / "web_assessment_react" / "dist"
MEDIA_DIR = Path(settings.resolved_media_dir)
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
rate_limiter = InMemoryRateLimiter()

if settings.cors_origins_list:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

if settings.trusted_hosts_list:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.trusted_hosts_list)

if settings.enable_gzip:
    app.add_middleware(GZipMiddleware, minimum_size=max(256, int(settings.gzip_minimum_size)))


@app.middleware("http")
async def apply_security_headers(request: Request, call_next):
    started_at = time.perf_counter()
    request_id = request.headers.get("x-request-id") or uuid4().hex
    request.state.request_id = request_id
    method = request.method
    path = request.url.path or "/"
    status_code = 500
    try:
        response = await call_next(request)
        status_code = int(response.status_code)
    except Exception:
        elapsed_ms = (time.perf_counter() - started_at) * 1000.0
        ops_metrics.record(route=path, status_code=status_code, latency_ms=elapsed_ms)
        request_logger.exception("request_error", extra={"request_id": request_id, "method": method, "path": path})
        raise
    elapsed_ms = (time.perf_counter() - started_at) * 1000.0
    ops_metrics.record(route=path, status_code=status_code, latency_ms=elapsed_ms)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Request-ID", request_id)
    if settings.security_enable_csp:
        csp_parts = ["default-src 'self'", "img-src 'self' data: blob: https:", "media-src 'self' blob: https:", "connect-src 'self' https: wss:", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com", "font-src 'self' https://fonts.gstatic.com", f"frame-ancestors {settings.security_csp_frame_ancestors}"]
        if settings.security_csp_extra:
            csp_parts.append(settings.security_csp_extra)
        response.headers.setdefault("Content-Security-Policy", "; ".join(csp_parts))
    return response


@app.middleware("http")
async def apply_rate_limit(request: Request, call_next):
    if not settings.rate_limit_enabled:
        return await call_next(request)
    path = request.url.path or "/"
    if path.startswith("/media/") or path in {"/health", "/favicon.ico", "/site.webmanifest"}:
        return await call_next(request)
    xff = (request.headers.get("x-forwarded-for") or "").split(",")[0].strip()
    client_ip = xff or (request.client.host if request.client else "unknown")
    auth_route = path.startswith("/auth/") or path.startswith("/config/firebase")
    rule = LimitRule(max_requests=settings.rate_limit_auth_requests_per_minute if auth_route else settings.rate_limit_requests_per_minute, window_seconds=60)
    allowed, retry_after = rate_limiter.allow(f"{client_ip}:{'auth' if auth_route else 'api'}", rule)
    if not allowed:
        return Response(content=json.dumps({"detail": "Rate limit exceeded", "retry_after_seconds": retry_after}), media_type="application/json", status_code=429, headers={"Retry-After": str(retry_after)})
    return await call_next(request)


@app.on_event("startup")
def on_startup() -> None:
    init_db()


@app.get("/health")
def health():
    return {"status": "ok"}


@app.get("/site.webmanifest")
def site_webmanifest():
    return Response(status_code=204)


@app.get("/config/firebase")
def firebase_config():
    return {
        "auth_mode": settings.auth_mode,
        "apiKey": settings.firebase_web_api_key,
        "authDomain": settings.firebase_auth_domain,
        "projectId": settings.firebase_project_id,
        "storageBucket": settings.firebase_storage_bucket,
        "messagingSenderId": settings.firebase_messaging_sender_id,
        "appId": settings.firebase_app_id,
        "measurementId": settings.firebase_measurement_id,
    }


app.include_router(api_router)
app.mount("/media", StaticFiles(directory=str(MEDIA_DIR)), name="media")


@app.get("/")
def root_frontend():
    return RedirectResponse(url="/assessment")


@app.get("/assessment")
def assessment_frontend():
    index_file = ASSESSMENT_WEB_DIST_DIR / "index.html"
    if index_file.exists():
        return FileResponse(str(index_file))
    return Response(
        content="Assessment React frontend is not built yet. Run: cd app/web_assessment_react && npm install && npm run build",
        media_type="text/plain",
        status_code=503,
    )


@app.get("/assessment/{path:path}")
def assessment_frontend_routes(path: str):
    index_file = ASSESSMENT_WEB_DIST_DIR / "index.html"
    if index_file.exists():
        direct_file = ASSESSMENT_WEB_DIST_DIR / path
        if direct_file.exists() and direct_file.is_file():
            return FileResponse(str(direct_file))
        return FileResponse(str(index_file))
    return Response(
        content="Assessment React frontend is not built yet. Run: cd app/web_assessment_react && npm install && npm run build",
        media_type="text/plain",
        status_code=503,
    )
