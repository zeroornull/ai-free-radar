"""Same-origin application host: JSON API plus the built Vue single-page app."""

from __future__ import annotations

import asyncio
import ipaddress
import os
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from filelock import FileLock, Timeout
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import APP_VERSION, INVALID_INPUT, error_response, router
from .config import ConfigurationError, Settings, load_config_document
from .scheduler import Scheduler
from .service import TaskManager
from .settings_store import SettingsStore
from .storage import Repository

LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "testserver"}
PACKAGE_DIR = Path(__file__).resolve().parent
APP_DIR = PACKAGE_DIR / "static" / "app"
APP_INDEX = APP_DIR / "index.html"
NOT_BUILT_MESSAGE = "前端尚未构建，请先运行 pnpm --dir frontend build。"
PAGE_PATHS = frozenset({"/resources", "/tasks", "/briefings", "/leads"})
PAGE_PREFIXES = ("/resources/", "/tasks/", "/briefings/", "/leads/")
RESERVED_PREFIXES = ("/api", "/assets", "/static", "/health", "/docs", "/redoc", "/openapi.json")
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; connect-src 'self'; style-src 'self'; "
    "style-src-attr 'unsafe-inline'; font-src 'self'; img-src 'none'; object-src 'none'; "
    "form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
)


def _allowed_authority(value: str, *, origin: bool = False) -> tuple[str, int] | None:
    try:
        parsed = urlsplit(value if origin else "//" + value)
        if (
            parsed.hostname not in LOOPBACK_HOSTS
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
            or (origin and parsed.scheme not in {"http", "https"})
        ):
            return None
        return parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    except ValueError:
        return None


def _is_page(path: str) -> bool:
    if path in PAGE_PATHS:
        return True
    return any(
        path.startswith(prefix) and _single_segment(path[len(prefix) :])
        for prefix in PAGE_PREFIXES
    )


def _single_segment(remainder: str) -> bool:
    return bool(remainder) and "/" not in remainder


def _is_reserved(path: str) -> bool:
    return any(path == prefix or path.startswith(prefix + "/") for prefix in RESERVED_PREFIXES)


def _is_api(path: str) -> bool:
    return path == "/api" or path.startswith("/api/")


def create_app(
    settings: Settings | None = None,
    researcher=None,
    *,
    config_document: dict[str, object] | None = None,
) -> FastAPI:
    if settings is None:
        _, document, settings = load_config_document()
    else:
        document = config_document or {}
    dev_origin = os.environ.get("AIFREERADAR_DEV_ORIGIN")
    if dev_origin is not None and dev_origin not in {
        "http://127.0.0.1:15173",
        "http://localhost:15173",
    }:
        raise ConfigurationError(
            "AIFREERADAR_DEV_ORIGIN must be http://127.0.0.1:15173 or http://localhost:15173"
        )
    data_dir = Path(settings.data_dir).resolve()
    data_dir.mkdir(parents=True, exist_ok=True)
    repository = Repository(data_dir)
    settings_store = SettingsStore(repository, settings, document)
    settings = settings_store.effective()
    manager = TaskManager(settings, repository, researcher=researcher, settings_store=settings_store)
    scheduler = Scheduler(settings, manager, repository, settings_store=settings_store)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        lifetime_lock = FileLock(data_dir / "application.lock")
        try:
            lifetime_lock.acquire(timeout=0)
        except Timeout as exc:
            raise RuntimeError("此数据目录已有应用运行，请关闭已有实例后重试。") from exc
        scheduler_task = None
        try:
            repository.mark_interrupted()
            await scheduler.tick(startup=True)
            scheduler_task = asyncio.create_task(scheduler.run(), name="aifreeradar-scheduler")
            yield
        finally:
            try:
                scheduler.stop()
                if scheduler_task is not None:
                    scheduler_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await scheduler_task
            finally:
                try:
                    await manager.close()
                finally:
                    lifetime_lock.release()

    app_version = APP_VERSION
    app = FastAPI(
        title="AIFreeRadar",
        version=app_version,
        lifespan=lifespan,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.repository = repository
    app.state.manager = manager
    app.state.scheduler = scheduler
    app.state.settings_store = settings_store
    app.state.settings = settings
    app.include_router(router)

    @app.middleware("http")
    async def restrict_local_access(request: Request, call_next):
        api_request = _is_api(request.url.path)

        def denied(detail: str, status_code: int):
            if api_request:
                return error_response(settings, detail, status_code)
            return Response(detail, status_code=status_code, media_type="text/plain; charset=utf-8")

        authority = _allowed_authority(request.headers.get("host", ""))
        if authority is None:
            return denied("仅允许本机地址访问。", 400)
        if request.client and request.client.host not in {"testclient", "testserver"}:
            try:
                local = ipaddress.ip_address(request.client.host).is_loopback
            except ValueError:
                local = request.client.host == "localhost"
            if not local:
                return denied("仅允许本机访问。", 403)
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            allowed_dev_origin = api_request and dev_origin is not None and origin == dev_origin
            if (
                origin is not None
                and _allowed_authority(origin, origin=True) != authority
                and not allowed_dev_origin
            ):
                return denied("请求来源不受支持。请从本机应用页面发起任务。", 403)
            if request.headers.get("sec-fetch-site") == "cross-site":
                return denied("请求来源不受支持。请从本机应用页面发起任务。", 403)
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = CONTENT_SECURITY_POLICY
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Cache-Control"] = "no-store"
        return response

    assets_dir = APP_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    else:

        @app.get("/assets/{asset_path:path}", include_in_schema=False)
        async def missing_assets(asset_path: str):
            return Response(
                "未找到此资源。", status_code=404, media_type="text/plain; charset=utf-8"
            )

    def app_entry(status_code: int) -> Response:
        if not APP_INDEX.is_file():
            return Response(
                NOT_BUILT_MESSAGE,
                status_code=503,
                media_type="text/plain; charset=utf-8",
            )
        return HTMLResponse(
            APP_INDEX.read_text(encoding="utf-8"),
            status_code=status_code,
            media_type="text/html; charset=utf-8",
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request: Request, exc: StarletteHTTPException):
        detail = str(exc.detail)
        if _is_api(request.url.path):
            if exc.status_code == 404 and exc.detail == "Not Found":
                detail = "未找到此接口。"
            headers = dict(exc.headers) if exc.headers else None
            return error_response(settings, detail, exc.status_code, headers=headers)
        return Response(
            detail, status_code=exc.status_code, media_type="text/plain; charset=utf-8"
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, exc: RequestValidationError):
        if _is_api(request.url.path):
            return error_response(settings, INVALID_INPUT, 422)
        return Response(INVALID_INPUT, status_code=422, media_type="text/plain; charset=utf-8")

    @app.get("/health")
    async def health():
        return {"status": "ok", "version": app_version}

    @app.get("/")
    async def index():
        return app_entry(200)

    @app.get("/{full_path:path}", response_class=HTMLResponse)
    async def spa(request: Request):
        path = request.url.path
        if _is_api(path):
            return error_response(settings, "未找到此接口。", 404)
        if _is_reserved(path):
            return Response(
                "未找到此页面。", status_code=404, media_type="text/plain; charset=utf-8"
            )
        return app_entry(200 if _is_page(path) else 404)

    return app