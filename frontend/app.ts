// app.ts: LAUT SCAN Expo Exact TypeScript Data Seam
// Bridges app.contract shapes & resources to FastAPI (/v1/*) with strict null -> undefined Option conversion
// and graceful cached / offline seed fallbacks.

declare global {
  interface ImportMetaEnv {
    readonly API_BASE_URL?: string;
  }
  interface ImportMeta {
    readonly env?: ImportMetaEnv;
  }
}

export const grants = 'net.fetch http://127.0.0.1:8080';

export const API_BASE_URL: string =
  (typeof import.meta !== 'undefined' && import.meta.env?.API_BASE_URL) ||
  'http://127.0.0.1:8080';

export function getApiBaseUrl(): string {
  return API_BASE_URL;
}

export type Option<T> = T | undefined;

export interface HealthStatus {
  status: string;
  service: string;
  version: string;
  environment: string;
  db_ok: boolean;
  postgis_version: Option<string>;
  redis_ok: boolean;
  tile_cache_ok: boolean;
  timestamp_utc: string;
}

export interface WppZoneRecord {
  wpp_code: string;
  name: string;
  waters_id: string;
  waters_en: string;
  legal_basis: string;
  geometry_source: string;
  centroid_lat: number;
  centroid_lon: number;
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  area_km2: Option<number>;
  sst_mean_c: Option<number>;
  chlorophyll_mean_mg_m3: Option<number>;
  latest_observation_utc: Option<string>;
  geometry_geojson: Option<string>;
}

export interface WppZoneListResponse {
  items: WppZoneRecord[];
  total: number;
}

export interface MapPointInspection {
  lat: number;
  lon: number;
  requested_date: string;
  resolved_date: Option<string>;
  wpp_code: Option<string>;
  wpp_name: Option<string>;
  wpp_waters_id: Option<string>;
  sst_c: Option<number>;
  sst_f: Option<number>;
  chlorophyll_mg_m3: Option<number>;
  current_speed_ms: Option<number>;
  current_speed_knots: Option<number>;
  current_direction_deg: Option<number>;
  current_compass: Option<string>;
  salinity_psu: Option<number>;
  wave_height_m: Option<number>;
  interpolation_method: string;
  spatial_resolution_km: Option<number>;
  primary_source: Option<string>;
  attribution: string;
  acquired_at_utc: Option<string>;
  is_cached_fallback: boolean;
  disclaimer: string;
}

export interface SpeciesOccurrenceRecord {
  id: string;
  obis_id: Option<string>;
  scientific_name: string;
  common_name: Option<string>;
  taxon_rank: Option<string>;
  family: Option<string>;
  lat: number;
  lon: number;
  wpp_code: Option<string>;
  depth_m: Option<number>;
  event_date_utc: Option<string>;
  individual_count: Option<number>;
  habitat_note: Option<string>;
  dataset_name: Option<string>;
  attribution: string;
  license: Option<string>;
}

export interface SpeciesOccurrenceListResponse {
  items: SpeciesOccurrenceRecord[];
  total: number;
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface DataSourceStatusRecord {
  source_key: string;
  display_name: string;
  priority: string;
  enabled: boolean;
  requires_credentials: boolean;
  non_commercial_only: boolean;
  status: string;
  last_sync_utc: Option<string>;
  latest_data_timestamp_utc: Option<string>;
  last_error: Option<string>;
  attribution: string;
  license_summary: string;
  official_url: string;
}

export interface SourceSyncLogRecord {
  id: string;
  source_key: string;
  dataset_type: string;
  status: string;
  records_ingested: number;
  started_at_utc: string;
  finished_at_utc: Option<string>;
  duration_ms: Option<number>;
  error_message: Option<string>;
}

export interface DataSourcesResponse {
  sources: DataSourceStatusRecord[];
  recent_logs: SourceSyncLogRecord[];
  checked_at_utc: string;
}

export interface ErrorResponse {
  error_code: string;
  message: string;
  detail: Option<string>;
  timestamp_utc: string;
}

export interface UserPreferences {
  temp_unit: string;
  speed_unit: string;
  theme_mode: string;
  low_bandwidth: boolean;
}

// Option / Null Normalizers (JSON null -> undefined for Exact option<T>)

function optString(value: unknown): Option<string> {
  return typeof value === 'string' ? value : undefined;
}

function optNumber(value: unknown): Option<number> {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return value;
  }
  return undefined;
}

function reqString(value: unknown, fallback = ''): string {
  return typeof value === 'string' ? value : fallback;
}

function reqNumber(value: unknown, fallback = 0): number {
  return typeof value === 'number' && Number.isFinite(value) ? value : fallback;
}

function reqBool(value: unknown, fallback = false): boolean {
  return typeof value === 'boolean' ? value : fallback;
}

const MARINE_DISCLAIMER =
  'Satellite and historical observations are not real-time fish location guarantees and do not replace official maritime safety advisories (BMKG, Pushidrosal, Basarnas).';

const PREFS_STORAGE_KEY = 'lautscan:preferences:v1';

// Offline Seed Data (matches data/wpp-nri/wpp_nri_zones.json 1:1)

interface SeedWppInput {
  code: string;
  waters_id: string;
  waters_en: string;
  centroid_lat: number;
  centroid_lon: number;
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  area_km2: number;
  sst_mean_c: number;
  chlorophyll_mean_mg_m3: number;
  ring: [number, number][];
}

const OFFLINE_WPP_SEEDS: SeedWppInput[] = [
  {
    code: '571',
    waters_id: 'Perairan Selat Malaka dan Laut Andaman',
    waters_en: 'Malacca Strait and Andaman Sea',
    centroid_lat: 3.9604,
    centroid_lon: 99.3605,
    min_lon: 95.0,
    min_lat: 1.2,
    max_lon: 103.5,
    max_lat: 6.5,
    area_km2: 285186.0,
    sst_mean_c: 29.4,
    chlorophyll_mean_mg_m3: 0.68,
    ring: [
      [95.0, 5.5], [98.0, 3.0], [100.5, 1.5], [103.5, 1.2], [103.5, 2.5],
      [100.2, 5.5], [97.5, 6.5], [95.0, 6.5], [95.0, 5.5],
    ],
  },
  {
    code: '572',
    waters_id: 'Perairan Samudera Hindia sebelah Barat Sumatera dan Selat Sunda',
    waters_en: 'Indian Ocean West of Sumatra and Sunda Strait',
    centroid_lat: -3.2373,
    centroid_lon: 97.8677,
    min_lon: 92.0,
    min_lat: -10.0,
    max_lon: 106.0,
    max_lat: 6.0,
    area_km2: 1610475.0,
    sst_mean_c: 28.8,
    chlorophyll_mean_mg_m3: 0.34,
    ring: [
      [92.0, 6.0], [92.0, -4.0], [98.0, -10.0], [105.5, -10.0], [106.0, -6.0],
      [105.2, -5.8], [100.5, -1.0], [95.2, 5.6], [92.0, 6.0],
    ],
  },
  {
    code: '573',
    waters_id: 'Perairan Samudera Hindia sebelah Selatan Jawa hingga sebelah Selatan Nusa Tenggara, Laut Sawu, dan Laut Timor bagian Barat',
    waters_en: 'Indian Ocean South of Java to South of Nusa Tenggara, Savu Sea, and West Timor Sea',
    centroid_lat: -10.342,
    centroid_lon: 116.2171,
    min_lon: 105.5,
    min_lat: -13.0,
    max_lon: 127.5,
    max_lat: -6.8,
    area_km2: 1108247.0,
    sst_mean_c: 27.6,
    chlorophyll_mean_mg_m3: 0.49,
    ring: [
      [105.5, -6.8], [105.5, -12.0], [115.0, -12.5], [123.0, -13.0], [127.5, -11.5],
      [127.5, -8.5], [123.5, -8.3], [119.0, -8.6], [114.5, -8.7], [108.0, -7.7], [105.5, -6.8],
    ],
  },
  {
    code: '711',
    waters_id: 'Perairan Selat Karimata, Laut Natuna, dan Laut Cina Selatan',
    waters_en: 'Karimata Strait, Natuna Sea, and South China Sea',
    centroid_lat: 0.954,
    centroid_lon: 106.9615,
    min_lon: 103.5,
    min_lat: -3.5,
    max_lon: 110.5,
    max_lat: 6.0,
    area_km2: 729802.0,
    sst_mean_c: 29.2,
    chlorophyll_mean_mg_m3: 0.52,
    ring: [
      [103.5, 2.0], [103.5, -3.5], [110.0, -3.5], [110.5, 1.5],
      [109.8, 5.5], [105.0, 6.0], [103.5, 2.0],
    ],
  },
  {
    code: '712',
    waters_id: 'Perairan Laut Jawa',
    waters_en: 'Java Sea',
    centroid_lat: -5.1233,
    centroid_lon: 111.3205,
    min_lon: 105.8,
    min_lat: -7.2,
    max_lon: 116.5,
    max_lat: -3.2,
    area_km2: 463531.0,
    sst_mean_c: 29.7,
    chlorophyll_mean_mg_m3: 0.84,
    ring: [
      [105.8, -5.8], [106.0, -6.5], [114.5, -7.2], [116.5, -7.0],
      [116.5, -3.5], [110.0, -3.2], [105.8, -3.5], [105.8, -5.8],
    ],
  },
  {
    code: '713',
    waters_id: 'Perairan Selat Makassar, Teluk Bone, Laut Flores, dan Laut Bali',
    waters_en: 'Makassar Strait, Gulf of Bone, Flores Sea, and Bali Sea',
    centroid_lat: -4.781,
    centroid_lon: 119.137,
    min_lon: 115.0,
    min_lat: -8.5,
    max_lon: 123.5,
    max_lat: 1.5,
    area_km2: 668794.0,
    sst_mean_c: 29.0,
    chlorophyll_mean_mg_m3: 0.45,
    ring: [
      [115.0, -7.0], [115.0, -8.5], [123.5, -8.5], [123.5, -5.0], [121.5, -2.6],
      [119.5, -2.5], [119.3, 1.5], [117.0, 1.5], [116.5, -3.5], [115.0, -7.0],
    ],
  },
  {
    code: '714',
    waters_id: 'Perairan Teluk Tolo dan Laut Banda',
    waters_en: 'Gulf of Tolo and Banda Sea',
    centroid_lat: -5.1824,
    centroid_lon: 127.0168,
    min_lon: 121.5,
    min_lat: -8.2,
    max_lon: 132.5,
    max_lat: -1.5,
    area_km2: 733968.0,
    sst_mean_c: 28.5,
    chlorophyll_mean_mg_m3: 0.39,
    ring: [
      [121.5, -1.5], [121.5, -4.5], [123.5, -8.2], [132.5, -8.2],
      [132.5, -3.0], [125.0, -2.5], [123.5, -1.5], [121.5, -1.5],
    ],
  },
  {
    code: '715',
    waters_id: 'Perairan Teluk Tomini, Laut Maluku, Laut Halmahera, Laut Seram, dan Teluk Berau',
    waters_en: 'Tomini Bay, Molucca Sea, Halmahera Sea, Seram Sea, and Berau Bay',
    centroid_lat: -0.7729,
    centroid_lon: 127.3656,
    min_lon: 120.0,
    min_lat: -3.5,
    max_lon: 134.0,
    max_lat: 1.8,
    area_km2: 644607.0,
    sst_mean_c: 29.3,
    chlorophyll_mean_mg_m3: 0.36,
    ring: [
      [120.0, 0.8], [120.0, -1.2], [124.5, -1.5], [126.0, -3.5], [134.0, -3.2],
      [134.0, -1.5], [130.5, 1.5], [124.5, 1.8], [120.0, 0.8],
    ],
  },
  {
    code: '716',
    waters_id: 'Perairan Laut Sulawesi dan sebelah Utara Pulau Halmahera',
    waters_en: 'Sulawesi Sea and North of Halmahera Island',
    centroid_lat: 3.3728,
    centroid_lon: 123.6341,
    min_lon: 117.5,
    min_lat: 1.2,
    max_lon: 129.5,
    max_lat: 5.5,
    area_km2: 575047.0,
    sst_mean_c: 29.5,
    chlorophyll_mean_mg_m3: 0.24,
    ring: [
      [117.5, 4.5], [117.5, 1.2], [124.5, 1.5], [129.5, 1.5],
      [129.5, 5.5], [122.0, 5.5], [117.5, 4.5],
    ],
  },
  {
    code: '717',
    waters_id: 'Perairan Teluk Cendrawasih dan Samudera Pasifik',
    waters_en: 'Cenderawasih Bay and Pacific Ocean',
    centroid_lat: 1.4993,
    centroid_lon: 135.5468,
    min_lon: 129.5,
    min_lat: -3.5,
    max_lon: 141.0,
    max_lat: 5.5,
    area_km2: 1112321.0,
    sst_mean_c: 29.8,
    chlorophyll_mean_mg_m3: 0.22,
    ring: [
      [129.5, 5.5], [129.5, 0.5], [134.2, -3.5], [137.0, -3.0],
      [141.0, -2.5], [141.0, 5.5], [129.5, 5.5],
    ],
  },
  {
    code: '718',
    waters_id: 'Perairan Laut Aru, Laut Arafuru, dan Laut Timor bagian Timur',
    waters_en: 'Aru Sea, Arafura Sea, and East Timor Sea',
    centroid_lat: -8.115,
    centroid_lon: 134.457,
    min_lon: 127.5,
    min_lat: -11.5,
    max_lon: 141.0,
    max_lat: -4.0,
    area_km2: 919084.0,
    sst_mean_c: 28.4,
    chlorophyll_mean_mg_m3: 0.92,
    ring: [
      [127.5, -8.2], [127.5, -11.5], [138.0, -11.0], [141.0, -9.2],
      [141.0, -5.5], [134.0, -4.0], [132.5, -5.0], [127.5, -8.2],
    ],
  },
];

// In-Memory Response Cache

let cachedHealth: Option<HealthStatus> = undefined;
let cachedWppZones: Option<WppZoneListResponse> = undefined;
let cachedSources: Option<DataSourcesResponse> = undefined;
let cachedSpecies: Option<SpeciesOccurrenceListResponse> = undefined;
const cachedPoints = new Map<string, MapPointInspection>();
let cachedPrefs: UserPreferences = loadStoredPreferences();

// Internal Fetch & Normalization Helpers

async function fetchJson(path: string, timeoutMs = 6000): Promise<unknown> {
  const url = `${API_BASE_URL.replace(/\/+$/, '')}${path}`;
  const controller = typeof AbortController !== 'undefined' ? new AbortController() : undefined;
  const timer =
    controller && typeof setTimeout !== 'undefined'
      ? setTimeout(() => controller.abort(), timeoutMs)
      : undefined;

  try {
    const response = await fetch(url, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      signal: controller?.signal,
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status} for ${path}`);
    }
    return await response.json();
  } finally {
    if (timer !== undefined && typeof clearTimeout !== 'undefined') {
      clearTimeout(timer);
    }
  }
}

function normalizeHealth(raw: Record<string, unknown>): HealthStatus {
  return {
    status: reqString(raw.status, 'degraded'),
    service: reqString(raw.service, 'lautscan-api'),
    version: reqString(raw.version, '1.2.0'),
    environment: reqString(raw.environment, 'offline'),
    db_ok: reqBool(raw.db_ok, false),
    postgis_version: optString(raw.postgis_version),
    redis_ok: reqBool(raw.redis_ok, false),
    tile_cache_ok: reqBool(raw.tile_cache_ok, false),
    timestamp_utc: reqString(raw.timestamp_utc, new Date().toISOString()),
  };
}

function normalizeWppZone(raw: Record<string, unknown>): WppZoneRecord {
  return {
    wpp_code: reqString(raw.wpp_code),
    name: reqString(raw.name),
    waters_id: reqString(raw.waters_id),
    waters_en: reqString(raw.waters_en),
    legal_basis: reqString(raw.legal_basis, 'Permen-KP No. 18/PERMEN-KP/2014'),
    geometry_source: reqString(raw.geometry_source, 'p0_seed'),
    centroid_lat: reqNumber(raw.centroid_lat),
    centroid_lon: reqNumber(raw.centroid_lon),
    min_lon: reqNumber(raw.min_lon),
    min_lat: reqNumber(raw.min_lat),
    max_lon: reqNumber(raw.max_lon),
    max_lat: reqNumber(raw.max_lat),
    area_km2: optNumber(raw.area_km2),
    sst_mean_c: optNumber(raw.sst_mean_c),
    chlorophyll_mean_mg_m3: optNumber(raw.chlorophyll_mean_mg_m3),
    latest_observation_utc: optString(raw.latest_observation_utc),
    geometry_geojson: optString(raw.geometry_geojson),
  };
}

function normalizeMapPoint(raw: Record<string, unknown>): MapPointInspection {
  return {
    lat: reqNumber(raw.lat),
    lon: reqNumber(raw.lon),
    requested_date: reqString(raw.requested_date, 'latest'),
    resolved_date: optString(raw.resolved_date),
    wpp_code: optString(raw.wpp_code),
    wpp_name: optString(raw.wpp_name),
    wpp_waters_id: optString(raw.wpp_waters_id),
    sst_c: optNumber(raw.sst_c),
    sst_f: optNumber(raw.sst_f),
    chlorophyll_mg_m3: optNumber(raw.chlorophyll_mg_m3),
    current_speed_ms: optNumber(raw.current_speed_ms),
    current_speed_knots: optNumber(raw.current_speed_knots),
    current_direction_deg: optNumber(raw.current_direction_deg),
    current_compass: optString(raw.current_compass),
    salinity_psu: optNumber(raw.salinity_psu),
    wave_height_m: optNumber(raw.wave_height_m),
    interpolation_method: reqString(raw.interpolation_method, 'unavailable'),
    spatial_resolution_km: optNumber(raw.spatial_resolution_km),
    primary_source: optString(raw.primary_source),
    attribution: reqString(raw.attribution, 'NOAA CoastWatch / ERDDAP'),
    acquired_at_utc: optString(raw.acquired_at_utc),
    is_cached_fallback: reqBool(raw.is_cached_fallback, false),
    disclaimer: reqString(raw.disclaimer, MARINE_DISCLAIMER),
  };
}

function normalizeSpeciesRecord(raw: Record<string, unknown>): SpeciesOccurrenceRecord {
  return {
    id: reqString(raw.id),
    obis_id: optString(raw.obis_id),
    scientific_name: reqString(raw.scientific_name),
    common_name: optString(raw.common_name),
    taxon_rank: optString(raw.taxon_rank),
    family: optString(raw.family),
    lat: reqNumber(raw.lat),
    lon: reqNumber(raw.lon),
    wpp_code: optString(raw.wpp_code),
    depth_m: optNumber(raw.depth_m),
    event_date_utc: optString(raw.event_date_utc),
    individual_count: optNumber(raw.individual_count),
    habitat_note: optString(raw.habitat_note),
    dataset_name: optString(raw.dataset_name),
    attribution: reqString(raw.attribution, 'OBIS (Ocean Biodiversity Information System)'),
    license: optString(raw.license),
  };
}

function normalizeDataSource(raw: Record<string, unknown>): DataSourceStatusRecord {
  return {
    source_key: reqString(raw.source_key),
    display_name: reqString(raw.display_name),
    priority: reqString(raw.priority, 'P1'),
    enabled: reqBool(raw.enabled, false),
    requires_credentials: reqBool(raw.requires_credentials, false),
    non_commercial_only: reqBool(raw.non_commercial_only, false),
    status: reqString(raw.status, 'unconfigured'),
    last_sync_utc: optString(raw.last_sync_utc),
    latest_data_timestamp_utc: optString(raw.latest_data_timestamp_utc),
    last_error: optString(raw.last_error),
    attribution: reqString(raw.attribution),
    license_summary: reqString(raw.license_summary),
    official_url: reqString(raw.official_url),
  };
}

function normalizeSyncLog(raw: Record<string, unknown>): SourceSyncLogRecord {
  return {
    id: reqString(raw.id),
    source_key: reqString(raw.source_key),
    dataset_type: reqString(raw.dataset_type),
    status: reqString(raw.status, 'skipped'),
    records_ingested: reqNumber(raw.records_ingested, 0),
    started_at_utc: reqString(raw.started_at_utc, new Date().toISOString()),
    finished_at_utc: optString(raw.finished_at_utc),
    duration_ms: optNumber(raw.duration_ms),
    error_message: optString(raw.error_message),
  };
}

function pointInRing(lon: number, lat: number, ring: [number, number][]): boolean {
  let inside = false;
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const [xi, yi] = ring[i];
    const [xj, yj] = ring[j];
    const intersects = yi > lat !== yj > lat && lon < ((xj - xi) * (lat - yi)) / (yj - yi) + xi;
    if (intersects) {
      inside = !inside;
    }
  }
  return inside;
}

function findOfflineWppForCoord(lat: number, lon: number): Option<SeedWppInput> {
  for (const seed of OFFLINE_WPP_SEEDS) {
    if (
      lon >= seed.min_lon &&
      lon <= seed.max_lon &&
      lat >= seed.min_lat &&
      lat <= seed.max_lat &&
      pointInRing(lon, lat, seed.ring)
    ) {
      return seed;
    }
  }
  return undefined;
}

function applyThemeAttribute(themeMode: string): void {
  if (typeof document !== 'undefined' && document.documentElement) {
    document.documentElement.setAttribute('data-theme', themeMode);
  }
}

function getBrowserStorage(): Storage | undefined {
  try {
    if (typeof window !== 'undefined' && window.localStorage) {
      return window.localStorage;
    }
  } catch {
    // Storage unavailable in non-browser or restricted environments.
  }
  return undefined;
}

function loadStoredPreferences(): UserPreferences {
  const defaults = defaultPreferences();
  try {
    const storage = getBrowserStorage();
    if (storage) {
      const raw = storage.getItem(PREFS_STORAGE_KEY);
      if (raw) {
        const parsed = JSON.parse(raw) as Record<string, unknown>;
        const prefs: UserPreferences = {
          temp_unit: parsed.temp_unit === 'F' ? 'F' : 'C',
          speed_unit: parsed.speed_unit === 'ms' ? 'ms' : 'knots',
          theme_mode:
            parsed.theme_mode === 'daylight' || parsed.theme_mode === 'night'
              ? parsed.theme_mode
              : 'system',
          low_bandwidth: Boolean(parsed.low_bandwidth),
        };
        applyThemeAttribute(prefs.theme_mode);
        return prefs;
      }
    }
  } catch {
    // Ignore storage read errors in restricted environments.
  }
  applyThemeAttribute(defaults.theme_mode);
  return defaults;
}

// Offline Fallbacks

export function defaultPreferences(): UserPreferences {
  return {
    temp_unit: 'C',
    speed_unit: 'knots',
    theme_mode: 'system',
    low_bandwidth: false,
  };
}

export function fallbackHealth(): HealthStatus {
  return (
    cachedHealth ?? {
      status: 'degraded',
      service: 'lautscan-api',
      version: '1.2.0',
      environment: 'offline-fallback',
      db_ok: false,
      postgis_version: undefined,
      redis_ok: false,
      tile_cache_ok: false,
      timestamp_utc: new Date().toISOString(),
    }
  );
}

export function fallbackWppZones(includeGeometry = true): WppZoneListResponse {
  if (cachedWppZones) {
    return cachedWppZones;
  }
  const items: WppZoneRecord[] = OFFLINE_WPP_SEEDS.map((seed) => ({
    wpp_code: seed.code,
    name: `WPP-NRI ${seed.code}`,
    waters_id: seed.waters_id,
    waters_en: seed.waters_en,
    legal_basis: 'Permen-KP No. 18/PERMEN-KP/2014',
    geometry_source: 'p0_seed',
    centroid_lat: seed.centroid_lat,
    centroid_lon: seed.centroid_lon,
    min_lon: seed.min_lon,
    min_lat: seed.min_lat,
    max_lon: seed.max_lon,
    max_lat: seed.max_lat,
    area_km2: seed.area_km2,
    sst_mean_c: seed.sst_mean_c,
    chlorophyll_mean_mg_m3: seed.chlorophyll_mean_mg_m3,
    latest_observation_utc: undefined,
    geometry_geojson: includeGeometry
      ? JSON.stringify({ type: 'Polygon', coordinates: [seed.ring] })
      : undefined,
  }));
  return { items, total: items.length };
}

export function fallbackSources(): DataSourcesResponse {
  if (cachedSources) {
    return cachedSources;
  }
  const nowIso = new Date().toISOString();
  return {
    sources: [
      {
        source_key: 'noaa_erddap',
        display_name: 'NOAA CoastWatch / ERDDAP',
        priority: 'P1',
        enabled: true,
        requires_credentials: false,
        non_commercial_only: false,
        status: 'degraded',
        last_sync_utc: undefined,
        latest_data_timestamp_utc: undefined,
        last_error: 'Backend API offline; displaying cached/seed fallback',
        attribution: 'NOAA CoastWatch / NESDIS ERDDAP',
        license_summary: 'Public domain (U.S. Government)',
        official_url: 'https://coastwatch.pfeg.noaa.gov/erddap/',
      },
      {
        source_key: 'obis',
        display_name: 'OBIS (Ocean Biodiversity Information System)',
        priority: 'P1',
        enabled: true,
        requires_credentials: false,
        non_commercial_only: false,
        status: 'degraded',
        last_sync_utc: undefined,
        latest_data_timestamp_utc: undefined,
        last_error: 'Backend API offline; displaying baseline OBIS fallback',
        attribution: 'OBIS / UNESCO IOC',
        license_summary: 'CC0 / CC-BY per dataset attribution',
        official_url: 'https://api.obis.org/',
      },
      {
        source_key: 'copernicus_marine',
        display_name: 'Copernicus Marine Service',
        priority: 'P1',
        enabled: false,
        requires_credentials: true,
        non_commercial_only: false,
        status: 'unconfigured',
        last_sync_utc: undefined,
        latest_data_timestamp_utc: undefined,
        last_error: undefined,
        attribution: 'E.U. Copernicus Marine Service Information',
        license_summary: 'Free registration; attribution required',
        official_url: 'https://marine.copernicus.eu/',
      },
      {
        source_key: 'kkp_pdpi',
        display_name: 'KKP PDPI (Prakiraan Daerah Penangkapan Ikan)',
        priority: 'P1/P2',
        enabled: false,
        requires_credentials: false,
        non_commercial_only: false,
        status: 'unconfigured',
        last_sync_utc: undefined,
        latest_data_timestamp_utc: undefined,
        last_error: undefined,
        attribution: 'Kementerian Kelautan dan Perikanan RI (KKP)',
        license_summary: 'Pluggable adapter pending official endpoint config',
        official_url: 'https://portal-informasi.kkp.go.id/pdpi/',
      },
      {
        source_key: 'gfw',
        display_name: 'Global Fishing Watch (AIS)',
        priority: 'P2',
        enabled: false,
        requires_credentials: true,
        non_commercial_only: true,
        status: 'disabled',
        last_sync_utc: undefined,
        latest_data_timestamp_utc: undefined,
        last_error: undefined,
        attribution: 'Global Fishing Watch',
        license_summary: 'Opt-in NON-COMMERCIAL / public-interest only; BYO-Token for commercial use',
        official_url: 'https://globalfishingwatch.org/',
      },
    ],
    recent_logs: [],
    checked_at_utc: nowIso,
  };
}

export function fallbackSpecies(taxonFilter = '', wppFilter = ''): SpeciesOccurrenceListResponse {
  if (cachedSpecies && !taxonFilter && !wppFilter) {
    return cachedSpecies;
  }
  const baseline: SpeciesOccurrenceRecord[] = [
    {
      id: 'seed-obis-001',
      obis_id: 'obis:714:thunnus-albacares:1',
      scientific_name: 'Thunnus albacares',
      common_name: 'Yellowfin Tuna (Madidihang)',
      taxon_rank: 'Species',
      family: 'Scombridae',
      lat: -5.1824,
      lon: 127.0168,
      wpp_code: '714',
      depth_m: 45.0,
      event_date_utc: '2026-10-18T06:00:00Z',
      individual_count: 14,
      habitat_note: 'Epipelagic offshore waters near thermocline and Banda Sea upwellings.',
      dataset_name: 'OBIS Indonesian Pelagic Baseline',
      attribution: 'OBIS / UNESCO IOC (Indonesian Pelagic Dataset)',
      license: 'CC-BY-4.0',
    },
    {
      id: 'seed-obis-002',
      obis_id: 'obis:713:katsuwonus-pelamis:2',
      scientific_name: 'Katsuwonus pelamis',
      common_name: 'Skipjack Tuna (Cakalang)',
      taxon_rank: 'Species',
      family: 'Scombridae',
      lat: -4.781,
      lon: 119.137,
      wpp_code: '713',
      depth_m: 25.0,
      event_date_utc: '2026-10-22T03:30:00Z',
      individual_count: 32,
      habitat_note: 'Warm tropical surface waters along Makassar Strait and Flores Sea fronts.',
      dataset_name: 'OBIS Indonesian Pelagic Baseline',
      attribution: 'OBIS / UNESCO IOC (Indonesian Pelagic Dataset)',
      license: 'CC-BY-4.0',
    },
    {
      id: 'seed-obis-003',
      obis_id: 'obis:712:rastrelliger-kanagurta:3',
      scientific_name: 'Rastrelliger kanagurta',
      common_name: 'Indian Mackerel (Kembung)',
      taxon_rank: 'Species',
      family: 'Scombridae',
      lat: -5.1233,
      lon: 111.3205,
      wpp_code: '712',
      depth_m: 18.0,
      event_date_utc: '2026-10-25T09:15:00Z',
      individual_count: 68,
      habitat_note: 'Coastal and shelf waters with high chlorophyll-a plankton productivity.',
      dataset_name: 'OBIS Java Sea Shelf Survey',
      attribution: 'OBIS / UNESCO IOC (Java Sea Survey)',
      license: 'CC-BY-4.0',
    },
    {
      id: 'seed-obis-004',
      obis_id: 'obis:718:lutjanus-malabaricus:4',
      scientific_name: 'Lutjanus malabaricus',
      common_name: 'Malabar Blood Snapper (Kakap Merah)',
      taxon_rank: 'Species',
      family: 'Lutjanidae',
      lat: -8.115,
      lon: 134.457,
      wpp_code: '718',
      depth_m: 64.0,
      event_date_utc: '2026-10-20T04:45:00Z',
      individual_count: 9,
      habitat_note: 'Demersal Arafura Sea shelf reefs and sandy-muddy substrates.',
      dataset_name: 'OBIS Arafura Demersal Records',
      attribution: 'OBIS / UNESCO IOC (Arafura Survey)',
      license: 'CC-BY-4.0',
    },
    {
      id: 'seed-obis-005',
      obis_id: 'obis:573:thunnus-obesus:5',
      scientific_name: 'Thunnus obesus',
      common_name: 'Bigeye Tuna (Tuna Mata Besar)',
      taxon_rank: 'Species',
      family: 'Scombridae',
      lat: -10.342,
      lon: 116.2171,
      wpp_code: '573',
      depth_m: 120.0,
      event_date_utc: '2026-10-12T07:00:00Z',
      individual_count: 6,
      habitat_note: 'Deep pelagic Indian Ocean waters south of Java and Nusa Tenggara.',
      dataset_name: 'OBIS Indian Ocean Tuna Baseline',
      attribution: 'OBIS / UNESCO IOC (Indian Ocean Dataset)',
      license: 'CC-BY-4.0',
    },
  ];

  const q = taxonFilter.trim().toLowerCase();
  const wpp = wppFilter.trim();
  const filtered = baseline.filter((item) => {
    const matchesWpp = !wpp || item.wpp_code === wpp;
    const matchesTaxon =
      !q ||
      item.scientific_name.toLowerCase().includes(q) ||
      (item.common_name?.toLowerCase().includes(q) ?? false) ||
      (item.family?.toLowerCase().includes(q) ?? false);
    return matchesWpp && matchesTaxon;
  });

  return {
    items: filtered,
    total: filtered.length,
    limit: 50,
    offset: 0,
    has_more: false,
  };
}

export function fallbackPointInspection(
  lat = -5.1233,
  lon = 111.3205,
  date = 'latest',
): MapPointInspection {
  const key = `${lat.toFixed(3)}:${lon.toFixed(3)}:${date}`;
  const existing = cachedPoints.get(key);
  if (existing) {
    return existing;
  }
  const zone = findOfflineWppForCoord(lat, lon);
  const sstC = zone ? zone.sst_mean_c : undefined;
  const sstF = sstC !== undefined ? Number(((sstC * 9) / 5 + 32).toFixed(2)) : undefined;
  return {
    lat,
    lon,
    requested_date: date,
    resolved_date: undefined,
    wpp_code: zone?.code,
    wpp_name: zone ? `WPP-NRI ${zone.code}` : undefined,
    wpp_waters_id: zone?.waters_id,
    sst_c: sstC,
    sst_f: sstF,
    chlorophyll_mg_m3: zone?.chlorophyll_mean_mg_m3,
    current_speed_ms: zone ? 0.42 : undefined,
    current_speed_knots: zone ? Number((0.42 * 1.94384).toFixed(2)) : undefined,
    current_direction_deg: zone ? 115 : undefined,
    current_compass: zone ? 'ESE' : undefined,
    salinity_psu: undefined,
    wave_height_m: undefined,
    interpolation_method: zone ? 'nearest' : 'unavailable',
    spatial_resolution_km: zone ? 4.0 : undefined,
    primary_source: 'offline_seed_fallback',
    attribution: 'WPP-NRI P0 Seed & Cached Baseline (Backend Offline)',
    acquired_at_utc: undefined,
    is_cached_fallback: true,
    disclaimer: MARINE_DISCLAIMER,
  };
}

// Public Resource & Mutation Seam Functions

export async function loadHealth(_refreshNonce = 0): Promise<HealthStatus> {
  try {
    const data = (await fetchJson('/v1/health')) as Record<string, unknown>;
    const normalized = normalizeHealth(data);
    cachedHealth = normalized;
    return normalized;
  } catch {
    return fallbackHealth();
  }
}

export async function loadWppZones(
  includeGeometry = true,
  _refreshNonce = 0,
): Promise<WppZoneListResponse> {
  try {
    const query = includeGeometry ? 'true' : 'false';
    const data = (await fetchJson(`/v1/wpp?include_geometry=${query}`)) as Record<string, unknown>;
    const rawItems = Array.isArray(data.items) ? data.items : [];
    const items = rawItems.map((item) => normalizeWppZone(item as Record<string, unknown>));
    const response: WppZoneListResponse = {
      items,
      total: reqNumber(data.total, items.length),
    };
    cachedWppZones = response;
    return response;
  } catch {
    return fallbackWppZones(includeGeometry);
  }
}

export async function loadSources(_refreshNonce = 0): Promise<DataSourcesResponse> {
  try {
    const data = (await fetchJson('/v1/sources?include_recent_logs=true')) as Record<
      string,
      unknown
    >;
    const rawSources = Array.isArray(data.sources) ? data.sources : [];
    const rawLogs = Array.isArray(data.recent_logs) ? data.recent_logs : [];
    const response: DataSourcesResponse = {
      sources: rawSources.map((s) => normalizeDataSource(s as Record<string, unknown>)),
      recent_logs: rawLogs.map((l) => normalizeSyncLog(l as Record<string, unknown>)),
      checked_at_utc: reqString(data.checked_at_utc, new Date().toISOString()),
    };
    cachedSources = response;
    return response;
  } catch {
    return fallbackSources();
  }
}

function normalizeBboxParam(rawBbox: string): string {
  const trimmed = rawBbox.trim();
  if (!trimmed) return '';
  if (trimmed.startsWith('{')) {
    try {
      const parsed = JSON.parse(trimmed) as Record<string, unknown>;
      const minLon = Number(parsed.minLon);
      const minLat = Number(parsed.minLat);
      const maxLon = Number(parsed.maxLon);
      const maxLat = Number(parsed.maxLat);
      if ([minLon, minLat, maxLon, maxLat].every(Number.isFinite)) {
        return `${minLon.toFixed(4)},${minLat.toFixed(4)},${maxLon.toFixed(4)},${maxLat.toFixed(4)}`;
      }
    } catch {
      return '';
    }
  }
  return trimmed;
}

export async function loadSpecies(
  taxon = '',
  wpp = '',
  bbox = '',
  limit = 50,
  offset = 0,
): Promise<SpeciesOccurrenceListResponse> {
  const params = new URLSearchParams();
  const normalizedBbox = normalizeBboxParam(bbox);
  if (taxon.trim()) params.set('taxon', taxon.trim());
  if (wpp.trim()) params.set('wpp', wpp.trim());
  if (normalizedBbox) params.set('bbox', normalizedBbox);
  params.set('limit', String(Math.min(Math.max(limit, 1), 500)));
  params.set('offset', String(Math.max(offset, 0)));

  try {
    const data = (await fetchJson(`/v1/species?${params.toString()}`)) as Record<string, unknown>;
    const rawItems = Array.isArray(data.items) ? data.items : [];
    const response: SpeciesOccurrenceListResponse = {
      items: rawItems.map((item) => normalizeSpeciesRecord(item as Record<string, unknown>)),
      total: reqNumber(data.total, rawItems.length),
      limit: reqNumber(data.limit, limit),
      offset: reqNumber(data.offset, offset),
      has_more: reqBool(data.has_more, false),
    };
    if (!taxon && !wpp && !bbox && offset === 0) {
      cachedSpecies = response;
    }
    return response;
  } catch {
    return fallbackSpecies(taxon, wpp);
  }
}

export async function loadPointInspection(
  lat = -5.1233,
  lon = 111.3205,
  date = 'latest',
): Promise<MapPointInspection> {
  return fetchPointInspection(lat, lon, date);
}

export async function fetchPointInspection(
  lat: number,
  lon: number,
  date = 'latest',
): Promise<MapPointInspection> {
  const safeDate = date.trim() || 'latest';
  const params = new URLSearchParams({
    lat: lat.toFixed(5),
    lon: lon.toFixed(5),
    date: safeDate,
  });

  try {
    const data = (await fetchJson(`/v1/map/point?${params.toString()}`)) as Record<string, unknown>;
    const normalized = normalizeMapPoint(data);
    cachedPoints.set(`${lat.toFixed(3)}:${lon.toFixed(3)}:${safeDate}`, normalized);
    return normalized;
  } catch {
    return fallbackPointInspection(lat, lon, safeDate);
  }
}

export async function loadPreferences(): Promise<UserPreferences> {
  return { ...cachedPrefs };
}

export async function savePreferences(
  tempUnit: string,
  speedUnit: string,
  themeMode: string,
  lowBandwidth: boolean,
): Promise<UserPreferences> {
  const next: UserPreferences = {
    temp_unit: tempUnit === 'F' ? 'F' : 'C',
    speed_unit: speedUnit === 'ms' ? 'ms' : 'knots',
    theme_mode: themeMode === 'daylight' || themeMode === 'night' ? themeMode : 'system',
    low_bandwidth: Boolean(lowBandwidth),
  };
  cachedPrefs = next;
  applyThemeAttribute(next.theme_mode);
  try {
    const storage = getBrowserStorage();
    if (storage) {
      storage.setItem(PREFS_STORAGE_KEY, JSON.stringify(next));
    }
  } catch {
    // Ignore storage write failures in headless/private sessions.
  }
  return { ...next };
}

// Map Serialization Helpers for @lautscan/marine-map

export function buildWppGeoJsonCollection(zones: WppZoneRecord[]): string {
  const features = zones
    .filter((z) => typeof z.geometry_geojson === 'string' && z.geometry_geojson.length > 0)
    .map((z) => {
      let geometry: unknown = null;
      try {
        geometry = z.geometry_geojson ? JSON.parse(z.geometry_geojson) : null;
      } catch {
        geometry = null;
      }
      return {
        type: 'Feature',
        id: z.wpp_code,
        properties: {
          wpp_code: z.wpp_code,
          name: z.name,
          waters_id: z.waters_id,
          waters_en: z.waters_en,
          centroid_lat: z.centroid_lat,
          centroid_lon: z.centroid_lon,
          sst_mean_c: z.sst_mean_c ?? null,
          chlorophyll_mean_mg_m3: z.chlorophyll_mean_mg_m3 ?? null,
        },
        geometry,
      };
    })
    .filter((f) => f.geometry !== null);

  return JSON.stringify({
    type: 'FeatureCollection',
    name: 'wpp_nri_zones',
    features,
  });
}

export function buildSpeciesMarkersJson(items: SpeciesOccurrenceRecord[]): string {
  const markers = items.map((item) => ({
    id: item.id,
    lat: item.lat,
    lon: item.lon,
    scientific_name: item.scientific_name,
    common_name: item.common_name ?? item.scientific_name,
    wpp_code: item.wpp_code ?? '',
    depth_m: item.depth_m ?? null,
  }));
  return JSON.stringify(markers);
}

// Event Parsing Helpers for <marine-map> payloads in Contract

export function parsePointClickLat(payload: string): Option<number> {
  try {
    const parsed = JSON.parse(payload) as Record<string, unknown>;
    if (
      parsed &&
      parsed.type === 'pointclick' &&
      typeof parsed.lat === 'number' &&
      Number.isFinite(parsed.lat)
    ) {
      return parsed.lat;
    }
  } catch {
    return undefined;
  }
  return undefined;
}

export function parsePointClickLon(payload: string): Option<number> {
  try {
    const parsed = JSON.parse(payload) as Record<string, unknown>;
    if (
      parsed &&
      parsed.type === 'pointclick' &&
      typeof parsed.lon === 'number' &&
      Number.isFinite(parsed.lon)
    ) {
      return parsed.lon;
    }
  } catch {
    return undefined;
  }
  return undefined;
}

export function parseMoveEndBbox(payload: string): string {
  return normalizeBboxParam(payload);
}

export function parseMapChangeWpp(payload: string): string {
  const trimmed = payload.trim();
  return /^(57[1-3]|71[1-8])$/.test(trimmed) ? trimmed : '';
}
