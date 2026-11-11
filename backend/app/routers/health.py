"""Health and dependency readiness endpoint (`GET /v1/health`)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from uuid import uuid4

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.core.config import get_settings
from app.core.db import check_db_health
from app.core.redis import check_redis_health
from app.schemas.common import ErrorResponse, HealthStatus

router = APIRouter(prefix="/v1", tags=["health"])

SERVICE_NAME = "lautscan-api"
API_VERSION = "1.2.0"


def _check_tile_cache_writable(cache_dir: Path) -> bool:
    """Return True if `TILE_CACHE_DIR` exists (or can be created) and accepts writes."""
    try:
        cache_dir.mkdir(parents=True, exist_ok=True)
        if not cache_dir.is_dir():
            return False
        probe_path = cache_dir / f".health-{uuid4().hex}"
        try:
            probe_path.write_bytes(b"ok")
        finally:
            probe_path.unlink(missing_ok=True)
        return True
    except OSError:
        return False


async def _safe_check_db() -> tuple[bool, str | None]:
    try:
        return await check_db_health()
    except Exception:
        return False, None


async def _safe_check_redis() -> bool:
    try:
        return await check_redis_health()
    except Exception:
        return False


def _service_unavailable(error_code: str, message: str, detail: str | None = None) -> JSONResponse:
    payload = ErrorResponse(
        error_code=error_code,
        message=message,
        detail=detail,
        timestamp_utc=datetime.now(UTC),
    )
    return JSONResponse(status_code=503, content=payload.model_dump(mode="json"))


@router.get(
    "/health",
    response_model=HealthStatus,
    responses={
        503: {
            "model": ErrorResponse,
            "description": "Service degraded or dependency unavailable",
        }
    },
    summary="Health and dependency readiness check",
    operation_id="getHealth",
)
async def get_health() -> HealthStatus | JSONResponse:
    """Report FastAPI health alongside PostGIS, Redis, and tile cache readiness."""
    try:
        settings = get_settings()
        db_ok, postgis_version = await _safe_check_db()
        redis_ok = await _safe_check_redis()
        tile_cache_ok = _check_tile_cache_writable(Path(settings.TILE_CACHE_DIR))
    except Exception:
        return _service_unavailable(
            error_code="HEALTH_CHECK_FAILED",
            message="Health check failed due to an unexpected internal error.",
        )

    if settings.ENVIRONMENT.strip().lower() == "production" and not db_ok:
        return _service_unavailable(
            error_code="DATABASE_UNAVAILABLE",
            message="Primary PostGIS spatial database is unavailable.",
        )

    overall_status: Literal["ok", "degraded", "error"] = (
        "ok" if (db_ok and redis_ok and tile_cache_ok) else "degraded"
    )
    return HealthStatus(
        status=overall_status,
        service=SERVICE_NAME,
        version=API_VERSION,
        environment=settings.ENVIRONMENT,
        db_ok=db_ok,
        postgis_version=postgis_version,
        redis_ok=redis_ok,
        tile_cache_ok=tile_cache_ok,
        timestamp_utc=datetime.now(UTC),
    )
