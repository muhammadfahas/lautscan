# LAUT SCAN

**Know the Ocean. Find the Fish.**

LAUT SCAN is an open-source marine intelligence platform built for Indonesian waters. It brings together satellite oceanography, Indonesian Fisheries Management Area boundaries (**WPP-NRI 571 to 718**), and open marine biodiversity records in a fast, map-first interface designed for coastal researchers, fisheries managers, fleet operators, and fishers on both desktop and mobile browsers.

---

## Key Features

- **Marine Intelligence Map (`/`)**: Full-bleed interactive workspace powered by the custom [`@lautscan/marine-map`](frontend/modules/marine-map/README.md) module, featuring multi-layer XYZ raster overlays for Sea Surface Temperature (SST), Chlorophyll-a, and Ocean Currents with independent opacity sliders, colorblind-safe perceptually uniform palettes (`plasma`, `viridis`, `cividis`), and **Daylight Maritime** / **Night Maritime** themes.
- **WPP-NRI 571 to 718 Boundaries**: Spatial boundary overlays and metadata for all 11 Indonesian Fisheries Management Areas defined under *Permen-KP No. 18/PERMEN-KP/2014*, stored in PostgreSQL/PostGIS (`SRID 4326`) with zone filtering and accessible low-bandwidth summary tables.
- **Ocean Conditions Point Inspector**: Click or tap any ocean coordinate (`GET /v1/map/point`) to inspect bilinear or nearest-neighbor interpolated SST (`°C` and `°F`), Chlorophyll-a (`mg/m³`), ocean current speed (`m/s` and `knots`), current bearing and 16-point compass direction, optional salinity and wave height, plus source attribution and acquisition timestamps.
- **Species Explorer (`/species`)**: Search PostGIS-indexed marine species and fish occurrence records synced from OBIS (`GET /v1/species`) by scientific name, common name, family, WPP-NRI zone, or map viewport bounding box.
- **Historical Trends (`/trends`)**: Compare oceanographic conditions across dates (`YYYY-MM-DD` or `latest`) and WPP-NRI zones to review seasonal patterns and monsoon shifts.
- **Data Sources & Settings (`/sources`, `/settings`)**: Monitor external provider health, recent ETL sync logs, attribution, and licensing compliance, and configure display units (`°C`/`°F`, `knots`/`m/s`), theme mode, and low-bandwidth preferences.
- **Post-MVP Forecasting Roadmap (P3)**: Planned machine learning and statistical forecasting models for fishing ground potential scoring once multi-season historical observations are accumulated and validated.

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend Runtime** | [Expo Exact](https://github.com/expo/exact) (`app.contract`, `app.tamber`, `app.ts`, `shapes.contract`) + custom `@lautscan/marine-map` Web Mercator module |
| **Backend API** | FastAPI (Python 3.11+), Pydantic v2, Uvicorn ASGI, SQLAlchemy 2.0 (`asyncpg`), GeoAlchemy2, Alembic |
| **Database & Cache** | PostgreSQL 16 + PostGIS 3.4 (`SRID 4326`, GIST spatial indexes) and Redis 7 |
| **Geospatial ETL & Tiling** | ARQ background worker (`app.etl.worker.WorkerSettings`), `xarray`, `netCDF4`, `numpy`, `Pillow`, `matplotlib` |
| **API Specification** | OpenAPI 3.1.0 ([`docs/openapi-contract.yaml`](docs/openapi-contract.yaml)) |

---

## Repository Structure

```text
lautscan/
├── backend/              # FastAPI app, Alembic migrations, PostGIS models, ARQ ETL & tile renderer
├── data/wpp-nri/         # WPP-NRI 571-718 GeoJSON seed dataset and official KKP conversion guide
├── docs/                 # Product requirements (PRD.md), architecture spec, and OpenAPI contract
├── frontend/             # Expo Exact contracts, TypeScript API seam, design tokens, and @lautscan/marine-map
└── infra/                # Docker Compose stack, .env.example, WSL2 setup, and Windows environment checks
```

---

## Quick Start

### 1. Start the Backend Stack with Docker Compose

1. Copy the example environment file and adjust credentials if needed:

   ```bash
   cp infra/.env.example infra/.env
   ```

2. Build and start PostgreSQL/PostGIS, Redis, the FastAPI API server, and the ARQ ETL worker:

   ```bash
   docker compose -f infra/docker-compose.yml up -d --build
   ```

3. Run database migrations and seed the 11 WPP-NRI zones:

   ```bash
   docker compose -f infra/docker-compose.yml exec api alembic upgrade head
   docker compose -f infra/docker-compose.yml exec api python -m app.db_seed
   ```

4. Check the API health endpoint:

   ```bash
   curl http://127.0.0.1:8080/v1/health
   ```

   Interactive API documentation is served at `http://127.0.0.1:8080/docs`.

### 2. Local Backend Development & Tests (Without Docker)

Ensure PostgreSQL/PostGIS and Redis are running locally (update `DATABASE_URL` and `REDIS_URL` in your `.env` from `db`/`redis` to `127.0.0.1`), then install and run:

```bash
cd backend
pip install -e ".[dev]"
alembic upgrade head
python -m app.db_seed
uvicorn app.main:app --host 127.0.0.1 --port 8080 --reload
```

Run code quality checks and the test suite:

```bash
cd backend
ruff check .
ruff format --check .
mypy app
pytest
```

### 3. Local Expo Exact Web Development

Expo Exact requires a Linux or WSL2 environment with Bun `1.4.2`, a stable Rust toolchain, Chrome or Chromium, and a sibling checkout of `expo/exact`.

On Windows, verify your local prerequisites first:

```powershell
powershell -ExecutionPolicy Bypass -File infra/scripts/dev-check.ps1
```

Inside Ubuntu/Debian or WSL2, install the toolchain and set up the sibling `../exact` directory:

```bash
bash infra/scripts/setup-wsl.sh
```

Validate the Exact Contract files against the sibling `../exact` checkout:

```bash
bun ../exact/scripts/exact.mjs contract build --json frontend/app.contract
```

Keep the FastAPI backend running at `http://127.0.0.1:8080` (matching `API_BASE_URL` in [`frontend/app.json`](frontend/app.json)) when previewing or running Exact web host checks.

---

## Data Sources, Licenses & Attribution

LAUT SCAN prioritizes open oceanographic and biodiversity feeds and separates optional credentialed or restricted integrations at the backend configuration layer:

| Source | Data Provided | Tier | License & Compliance Notes |
|---|---|---|---|
| **NOAA CoastWatch / ERDDAP** | SST, Chlorophyll-a, Ocean Currents | P1 (Default) | Public domain / open scientific data; no API token required. |
| **OBIS (`api.obis.org/v3`)** | Marine fish & species occurrences | P1 (Default) | Open REST API; retains original dataset attribution and per-record licenses. |
| **Copernicus Marine Service** | Multi-parameter NetCDF ocean grids | P1 (Optional ETL) | Requires free user credentials (`COPERNICUS_USERNAME` and `COPERNICUS_PASSWORD` in `infra/.env`). |
| **KKP PDPI Adapter** | Indonesian fishing ground advisories | P1/P2 (Adapter) | Pluggable adapter disabled by default unless an authorized `PDPI_BASE_URL` is configured. |
| **Global Fishing Watch (GFW)** | AIS fishing effort & vessel activity | P2 (Opt-in) | Disabled by default (`GFW_API_TOKEN`). Free-tier GFW tokens are restricted to **non-commercial / public-interest** use. Commercial deployments must supply a separate licensed GFW BYO-Token so GFW terms do not conflict with LAUT SCAN's MIT license. |
| **WPP-NRI Boundaries** | Indonesian Fisheries Management Areas 571 to 718 | P0 Seed | Based on *Permen-KP No. 18/PERMEN-KP/2014*. See [`data/wpp-nri/README.md`](data/wpp-nri/README.md) for replacing P0 seed polygons with official KKP/BIG shapefiles. |

Every map view and `/v1/map/point` payload surfaces source attribution, spatial resolution, and satellite acquisition timestamps. External credentials are kept strictly on the backend and are never exposed in API responses or frontend bundles.

---

## Disclaimer

LAUT SCAN visualizes historical observations and satellite-derived oceanographic data that carry acquisition latency and spatial resolution limits. Ocean metrics, biodiversity records, and fishing ground overlays **do not guarantee** the real-time presence of fish at any coordinate. For maritime navigation, weather warnings, and safety at sea, always rely on official notices from authorized national agencies (**BMKG**, **Pushidrosal**, **Basarnas**, and **KKP**).

---

## License

LAUT SCAN is released under the [MIT License](LICENSE). Third-party marine datasets retain their respective upstream licenses and attribution terms listed above.
