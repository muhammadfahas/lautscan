"""FastAPI entrypoint for the LAUT SCAN Marine Intelligence API."""

from __future__ import annotations

import importlib
import importlib.util
import logging
from datetime import UTC, datetime
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.routers import health, wpp
from app.schemas.common import ErrorResponse

logger = logging.getLogger(__name__)

_HTTP_ERROR_CODES: dict[int, str] = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_SERVER_ERROR",
    503: "SERVICE_UNAVAILABLE",
}

_OPTIONAL_ROUTER_MODULES: tuple[str, ...] = (
    "tiles",
    "map_point",
    "species",
    "sources",
)


def _error_json_response(
    status_code: int,
    *,
    error_code: str,
    message: str,
    detail: str | None = None,
) -> JSONResponse:
    payload = ErrorResponse(
        error_code=error_code,
        message=message,
        detail=detail,
        timestamp_utc=datetime.now(UTC),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def _status_phrase(status_code: int) -> str:
    try:
        return HTTPStatus(status_code).phrase
    except ValueError:
        return "HTTP Error"


def _format_validation_detail(exc: RequestValidationError) -> str:
    parts: list[str] = []
    for err in exc.errors():
        loc = ".".join(str(segment) for segment in err.get("loc", ()))
        msg = str(err.get("msg", "Invalid value"))
        parts.append(f"{loc}: {msg}" if loc else msg)
    return "; ".join(parts) if parts else "Invalid request parameters."


def _mount_routers(application: FastAPI) -> None:
    application.include_router(health.router)
    application.include_router(wpp.router)
    for module_name in _OPTIONAL_ROUTER_MODULES:
        full_name = f"app.routers.{module_name}"
        if importlib.util.find_spec(full_name) is not None:
            module = importlib.import_module(full_name)
            application.include_router(module.router)


def create_app() -> FastAPI:
    """Construct and configure the FastAPI application instance."""
    application = FastAPI(
        title="LAUT SCAN Marine Intelligence API",
        version="1.2.0",
        summary=(
            "Open-source geospatial REST & XYZ raster tile API "
            "for Indonesian marine intelligence."
        ),
    )

    application.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["GET", "HEAD", "OPTIONS"],
        allow_headers=["*"],
        expose_headers=[
            "Cache-Control",
            "ETag",
            "X-Tile-Cache",
            "X-Data-Source",
            "X-Dataset-Timestamp-UTC",
        ],
    )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request
        return _error_json_response(
            422,
            error_code="VALIDATION_ERROR",
            message="Request parameter validation failed.",
            detail=_format_validation_detail(exc),
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        del request
        raw_detail: Any = exc.detail
        default_code = _HTTP_ERROR_CODES.get(exc.status_code, f"HTTP_{exc.status_code}")

        if isinstance(raw_detail, dict):
            error_code = str(raw_detail.get("error_code") or default_code)
            message = str(raw_detail.get("message") or _status_phrase(exc.status_code))
            detail_val = raw_detail.get("detail")
            detail = str(detail_val) if detail_val is not None else None
        else:
            error_code = default_code
            message = str(raw_detail) if raw_detail else _status_phrase(exc.status_code)
            detail = None

        return _error_json_response(
            exc.status_code,
            error_code=error_code,
            message=message,
            detail=detail,
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            "Unhandled error while processing %s %s: %s",
            request.method,
            request.url.path,
            type(exc).__name__,
        )
        return _error_json_response(
            500,
            error_code="INTERNAL_SERVER_ERROR",
            message="An unexpected internal server error occurred.",
            detail=None,
        )

    _mount_routers(application)
    return application


app = create_app()
