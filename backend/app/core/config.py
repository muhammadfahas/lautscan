"""Application settings loaded from environment variables and `.env` files."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

_WPP_RELATIVE_PATH = Path("data") / "wpp-nri" / "wpp_nri_zones.json"


def resolve_wpp_seed_path(override: Path | str | None = None) -> Path:
    """Resolve `data/wpp-nri/wpp_nri_zones.json` for both Docker and local dev."""
    if override is not None:
        raw = str(override).strip()
        if raw:
            candidate = Path(raw)
            if candidate.is_file():
                return candidate
            if not candidate.is_absolute():
                for base in (Path("/app"), Path.cwd(), *Path(__file__).resolve().parents[:4]):
                    resolved = base / candidate
                    if resolved.is_file():
                        return resolved
            return candidate

    candidates: list[Path] = []
    for parent in Path(__file__).resolve().parents[:4]:
        candidates.append(parent / _WPP_RELATIVE_PATH)
    candidates.extend(
        [
            Path("/app") / _WPP_RELATIVE_PATH,
            Path.cwd() / _WPP_RELATIVE_PATH,
            Path.cwd().parent / _WPP_RELATIVE_PATH,
        ]
    )

    for candidate in candidates:
        if candidate.is_file():
            return candidate

    parents = Path(__file__).resolve().parents
    fallback_root = parents[3] if len(parents) > 3 else parents[-1]
    return fallback_root / _WPP_RELATIVE_PATH


class Settings(BaseSettings):
    """Runtime configuration aligned with `infra/.env.example` and `infra/docker-compose.yml`."""

    model_config = SettingsConfigDict(
        env_file=(".env", "backend/.env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    DATABASE_URL: str = (
        "postgresql+asyncpg://lautscan:your_secure_db_password_here@127.0.0.1:5432/lautscan"
    )
    REDIS_URL: str = "redis://127.0.0.1:6379/0"
    TILE_CACHE_DIR: Path = Path("/data/tiles")
    API_BASE_URL: str = "http://127.0.0.1:8080"
    API_PORT: int = 8080
    ENVIRONMENT: str = "development"
    LOG_LEVEL: str = "INFO"

    NOAA_ERDDAP_BASE_URL: str = "https://coastwatch.pfeg.noaa.gov/erddap"
    OBIS_API_BASE_URL: str = "https://api.obis.org/v3"

    COPERNICUS_USERNAME: str = ""
    COPERNICUS_PASSWORD: str = Field(default="", repr=False)
    PDPI_BASE_URL: str = ""
    GFW_API_TOKEN: str = Field(default="", repr=False)

    WPP_SEED_PATH: Path = Field(default_factory=resolve_wpp_seed_path)

    @field_validator("TILE_CACHE_DIR", mode="before")
    @classmethod
    def _parse_tile_cache_dir(cls, value: object) -> Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, str) and value.strip():
            return Path(value.strip())
        return Path("/data/tiles")

    @field_validator("WPP_SEED_PATH", mode="before")
    @classmethod
    def _parse_wpp_seed_path(cls, value: object) -> Path:
        if isinstance(value, Path):
            return resolve_wpp_seed_path(value)
        if isinstance(value, str) and value.strip():
            return resolve_wpp_seed_path(value)
        return resolve_wpp_seed_path()


@lru_cache
def get_settings() -> Settings:
    """Return cached singleton `Settings` instance."""
    return Settings()
