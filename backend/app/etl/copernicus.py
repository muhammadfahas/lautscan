"""Optional Copernicus Marine Service batch ETL adapter with strict credential isolation."""

from __future__ import annotations

import asyncio
import importlib
import inspect
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from app.etl.base import (
    CATALOG,
    INDONESIA_BBOX,
    AdapterSyncStatus,
    BoundingBox,
    ProviderAdapter,
    ProviderSyncResult,
    SourceMetadata,
    redact_secrets,
    resolve_setting,
)


@dataclass(frozen=True, slots=True)
class CopernicusDatasetSpec:
    """Dataset identifier and variable mapping for Copernicus Marine subsetting."""

    layer: str
    dataset_id: str
    variables: tuple[str, ...]


DEFAULT_COPERNICUS_DATASETS: Final[dict[str, CopernicusDatasetSpec]] = {
    "sst": CopernicusDatasetSpec(
        layer="sst",
        dataset_id="cmems_obs-sst_glo_phy_nrt_l4_0.01deg-t24_P1D-m",
        variables=("analysed_sst",),
    ),
    "chlorophyll": CopernicusDatasetSpec(
        layer="chlorophyll",
        dataset_id="cmems_obs-oc_glo_bgc-plankton_my_l4-gapfree-multi-4km_P1D",
        variables=("CHL",),
    ),
    "currents": CopernicusDatasetSpec(
        layer="currents",
        dataset_id="cmems_mod_glo_phy_anfc_0.083deg_P1D-m",
        variables=("uo", "vo"),
    ),
}


SubsetRunner = Callable[..., Any]


class CopernicusMarineAdapter(ProviderAdapter):
    """Optional batch adapter for Copernicus Marine Toolbox (`copernicusmarine`).

    Credentials (`COPERNICUS_USERNAME`, `COPERNICUS_PASSWORD`) are kept strictly private
    in memory and redacted from all error strings, repr output, and sync metadata.
    """

    metadata: SourceMetadata = CATALOG["copernicus_marine"]

    def __init__(
        self,
        username: str | None = None,
        password: str | None = None,
        *,
        datasets: dict[str, CopernicusDatasetSpec] | None = None,
        subset_runner: SubsetRunner | None = None,
    ) -> None:
        resolved_user = (
            username if username is not None else resolve_setting("COPERNICUS_USERNAME", "")
        )
        resolved_pass = (
            password if password is not None else resolve_setting("COPERNICUS_PASSWORD", "")
        )
        self._username: str = resolved_user.strip()
        self._password: str = resolved_pass.strip()
        self.datasets: dict[str, CopernicusDatasetSpec] = dict(
            datasets or DEFAULT_COPERNICUS_DATASETS
        )
        self._subset_runner = subset_runner

    def __repr__(self) -> str:
        return f"CopernicusMarineAdapter(configured={self.is_configured()})"

    def __str__(self) -> str:
        return self.__repr__()

    def is_configured(self) -> bool:
        """Return True only when both Copernicus username and password are non-empty."""
        return bool(self._username and self._password)

    def safe_status_summary(self) -> dict[str, Any]:
        """Return non-sensitive configuration readiness metadata."""
        return {
            "source_key": self.metadata.source_key,
            "configured": self.is_configured(),
            "toolbox_available": self._resolve_runner() is not None,
        }

    def _resolve_runner(self) -> SubsetRunner | None:
        if self._subset_runner is not None:
            return self._subset_runner
        try:
            toolbox = importlib.import_module("copernicusmarine")
        except ImportError:
            return None
        subset_fn = getattr(toolbox, "subset", None)
        return subset_fn if callable(subset_fn) else None

    async def sync(
        self,
        *,
        output_dir: Path | None = None,
        target_date: str | None = None,
        layers: Sequence[str] = ("sst", "chlorophyll", "currents"),
        bbox: BoundingBox = INDONESIA_BBOX,
    ) -> ProviderSyncResult:
        """Run optional Copernicus batch NetCDF subsetting, skipping cleanly if unconfigured."""
        started = datetime.now(UTC)

        if not self.is_configured():
            finished = datetime.now(UTC)
            return ProviderSyncResult(
                source_key="copernicus_marine",
                dataset_type="batch_netcdf",
                status="unconfigured",
                records_ingested=0,
                started_at_utc=started,
                finished_at_utc=finished,
                error_message=None,
                metadata={
                    "configured": False,
                    "disposition": "skipped",
                    "reason": "COPERNICUS_USERNAME and COPERNICUS_PASSWORD are not configured",
                },
            )

        runner = self._resolve_runner()
        if runner is None:
            finished = datetime.now(UTC)
            return ProviderSyncResult(
                source_key="copernicus_marine",
                dataset_type="batch_netcdf",
                status="skipped",
                records_ingested=0,
                started_at_utc=started,
                finished_at_utc=finished,
                error_message="Optional 'copernicusmarine' package is not installed",
                metadata={
                    "configured": True,
                    "toolbox_available": False,
                    "disposition": "skipped",
                },
            )

        date_label = (
            target_date
            if target_date and target_date != "latest"
            else datetime.now(UTC).strftime("%Y-%m-%d")
        )
        dest_dir = output_dir or Path("/data/tiles/raw/copernicus_marine")
        dest_dir.mkdir(parents=True, exist_ok=True)

        secrets = (self._username, self._password)
        succeeded = 0
        errors: list[str] = []
        layer_summary: dict[str, dict[str, Any]] = {}
        last_file_path: str | None = None

        for layer in layers:
            spec = self.datasets.get(layer)
            if spec is None:
                errors.append(f"{layer}: unsupported Copernicus layer")
                layer_summary[layer] = {"ok": False, "error": "unsupported layer"}
                continue

            out_file = f"copernicus_{layer}_{date_label}.nc"
            call_kwargs: dict[str, Any] = {
                "dataset_id": spec.dataset_id,
                "variables": list(spec.variables),
                "minimum_longitude": bbox.min_lon,
                "maximum_longitude": bbox.max_lon,
                "minimum_latitude": bbox.min_lat,
                "maximum_latitude": bbox.max_lat,
                "start_datetime": f"{date_label}T00:00:00",
                "end_datetime": f"{date_label}T23:59:59",
                "output_directory": str(dest_dir),
                "output_filename": out_file,
                "username": self._username,
                "password": self._password,
            }

            try:
                if inspect.iscoroutinefunction(runner):
                    result = await runner(**call_kwargs)
                else:
                    result = await asyncio.to_thread(runner, **call_kwargs)
                if inspect.isawaitable(result):
                    result = await result
                succeeded += 1
                resolved_path = str(dest_dir / out_file)
                last_file_path = resolved_path
                layer_summary[layer] = {
                    "ok": True,
                    "dataset_id": spec.dataset_id,
                    "file_path": resolved_path,
                    "result": redact_secrets(str(result), secrets) if result is not None else None,
                }
            except Exception as exc:  # noqa: BLE001 (isolate optional toolbox failures cleanly)
                clean_err = redact_secrets(f"{type(exc).__name__}: {exc}", secrets)
                errors.append(f"{layer}: {clean_err}")
                layer_summary[layer] = {
                    "ok": False,
                    "dataset_id": spec.dataset_id,
                    "error": clean_err,
                }

        finished = datetime.now(UTC)
        total = len(layers)
        status: AdapterSyncStatus
        if total == 0:
            status = "skipped"
        elif succeeded == total:
            status = "success"
        elif succeeded > 0:
            status = "partial"
        else:
            status = "failed"

        return ProviderSyncResult(
            source_key="copernicus_marine",
            dataset_type="batch_netcdf",
            status=status,
            records_ingested=succeeded,
            file_path=last_file_path,
            acquired_at_utc=finished if succeeded > 0 else None,
            started_at_utc=started,
            finished_at_utc=finished,
            error_message="; ".join(errors) if errors else None,
            metadata={
                "configured": True,
                "toolbox_available": True,
                "bbox": bbox.to_csv(),
                "layers": layer_summary,
            },
        )
