/**
 * TypeScript contract helpers and schemas for `@lautscan/marine-map`.
 *
 * All props arrive across the Expo Exact native module boundary as primitive
 * values or JSON strings, and all emitted events carry string/JSON payloads.
 */

export type BaseMapStyle = 'daylight' | 'night';

export type OceanOverlayLayer = 'potential' | 'sst' | 'chlorophyll' | 'currents';

export interface MarineMapProps {
  centerLat: number;
  centerLon: number;
  zoom: number;
  zoomLevel?: number;
  baseStyle: BaseMapStyle;
  potentialVisible: boolean;
  potentialOpacity: number;
  sstVisible: boolean;
  sstOpacity: number;
  chlorophyllVisible: boolean;
  chlorophyllOpacity: number;
  currentsVisible: boolean;
  currentsOpacity: number;
  currentsRasterVisible?: boolean;
  showSpeciesPins: boolean;
  selectedDate: string;
  tileBaseUrl: string;
  wppGeoJsonCollection: string;
  selectedWppCode: string;
  speciesMarkers: string;
}

export interface MarineMapRawProps {
  centerLat?: number | string | null;
  centerLon?: number | string | null;
  zoom?: number | string | null;
  zoomLevel?: number | string | null;
  baseStyle?: string | null;
  potentialVisible?: boolean | string | null;
  potentialOpacity?: number | string | null;
  sstVisible?: boolean | string | null;
  sstOpacity?: number | string | null;
  chlorophyllVisible?: boolean | string | null;
  chlorophyllOpacity?: number | string | null;
  currentsVisible?: boolean | string | null;
  currentsOpacity?: number | string | null;
  currentsRasterVisible?: boolean | string | null;
  showSpeciesPins?: boolean | string | null;
  selectedDate?: string | null;
  tileBaseUrl?: string | null;
  wppGeoJsonCollection?: string | null;
  selectedWppCode?: string | null;
  speciesMarkers?: string | null;
}

export interface MarineMapPointClickMessage {
  type: 'pointclick';
  lat: number;
  lon: number;
}

export interface MarineMapCameraBbox {
  minLon: number;
  minLat: number;
  maxLon: number;
  maxLat: number;
  centerLat: number;
  centerLon: number;
  latitude: number;
  longitude: number;
  zoom: number;
}

export type MarineMapChangeEvent =
  | { kind: 'clear'; value: '' }
  | { kind: 'wpp'; value: string }
  | { kind: 'species'; value: string };

export interface GeoJsonPolygonGeometry {
  type: 'Polygon';
  coordinates: number[][][];
}

export interface GeoJsonMultiPolygonGeometry {
  type: 'MultiPolygon';
  coordinates: number[][][][];
}

export type WppGeoJsonGeometry =
  | GeoJsonPolygonGeometry
  | GeoJsonMultiPolygonGeometry;

export interface WppFeatureProperties {
  wpp_code: string;
  name: string;
  waters_id?: string;
  waters_en?: string;
  centroid_lat?: number;
  centroid_lon?: number;
  min_lon?: number;
  min_lat?: number;
  max_lon?: number;
  max_lat?: number;
  sst_mean_c?: number | null;
  chlorophyll_mean_mg_m3?: number | null;
}

export interface WppGeoJsonFeature {
  type: 'Feature';
  id?: string;
  properties: WppFeatureProperties;
  geometry: WppGeoJsonGeometry;
}

export interface WppGeoJsonCollection {
  type: 'FeatureCollection';
  name?: string;
  features: WppGeoJsonFeature[];
}

export interface WppZoneRecordInput {
  wpp_code: string;
  name: string;
  waters_id?: string;
  waters_en?: string;
  centroid_lat: number;
  centroid_lon: number;
  min_lon: number;
  min_lat: number;
  max_lon: number;
  max_lat: number;
  sst_mean_c?: number | null;
  chlorophyll_mean_mg_m3?: number | null;
  geometry_geojson?: string | null;
}

export interface SpeciesMarkerItem {
  id: string;
  lat: number;
  lon: number;
  scientificName: string;
  commonName?: string | null;
  wppCode?: string | null;
  depthM?: number | null;
  habitatNote?: string | null;
}

export interface SpeciesMarkerInput {
  id: string;
  lat?: number;
  lon?: number;
  latitude?: number;
  longitude?: number;
  scientific_name?: string;
  common_name?: string | null;
  title?: string | null;
  wpp_code?: string | null;
  depth_m?: number | null;
  habitat_note?: string | null;
}

export const INDONESIA_DEFAULT_CENTER = {
  centerLat: -2.5,
  centerLon: 118.0,
  zoom: 5,
} as const;

export const WPP_NRI_CODES = new Set([
  '571',
  '572',
  '573',
  '711',
  '712',
  '713',
  '714',
  '715',
  '716',
  '717',
  '718',
]);

export function buildMarineMapDefaults(
  overrides: Partial<MarineMapProps> = {},
): MarineMapProps {
  return {
    centerLat: INDONESIA_DEFAULT_CENTER.centerLat,
    centerLon: INDONESIA_DEFAULT_CENTER.centerLon,
    zoom: INDONESIA_DEFAULT_CENTER.zoom,
    baseStyle: 'daylight',
    potentialVisible: true,
    potentialOpacity: 0.88,
    sstVisible: false,
    sstOpacity: 0.62,
    chlorophyllVisible: false,
    chlorophyllOpacity: 0.65,
    currentsVisible: false,
    currentsOpacity: 0.88,
    currentsRasterVisible: false,
    showSpeciesPins: true,
    selectedDate: 'latest',
    tileBaseUrl: 'http://127.0.0.1:8080',
    wppGeoJsonCollection: '{"type":"FeatureCollection","features":[]}',
    selectedWppCode: '',
    speciesMarkers: '[]',
    ...overrides,
  };
}

export function normalizeTileBaseUrl(tileBaseUrl: string): string {
  const trimmed = tileBaseUrl.trim();
  if (!trimmed || trimmed === 'none' || trimmed === 'offline') {
    return '';
  }
  return trimmed.replace(/\/+$/, '');
}

export function buildOverlayTileTemplate(
  tileBaseUrl: string,
  layer: OceanOverlayLayer,
  selectedDate: string,
): string {
  const base = normalizeTileBaseUrl(tileBaseUrl);
  const safeDate = selectedDate.trim() || 'latest';
  return `${base}/v1/tiles/${encodeURIComponent(layer)}/${encodeURIComponent(safeDate)}/{z}/{x}/{y}.png`;
}

function bboxFallbackPolygon(zone: WppZoneRecordInput): GeoJsonPolygonGeometry {
  return {
    type: 'Polygon',
    coordinates: [
      [
        [zone.min_lon, zone.min_lat],
        [zone.max_lon, zone.min_lat],
        [zone.max_lon, zone.max_lat],
        [zone.min_lon, zone.max_lat],
        [zone.min_lon, zone.min_lat],
      ],
    ],
  };
}

function parseZoneGeometry(zone: WppZoneRecordInput): WppGeoJsonGeometry {
  if (zone.geometry_geojson) {
    try {
      const parsed: unknown = JSON.parse(zone.geometry_geojson);
      if (
        parsed &&
        typeof parsed === 'object' &&
        'type' in parsed &&
        'coordinates' in parsed
      ) {
        const candidate = parsed as { type: unknown; coordinates: unknown };
        if (
          (candidate.type === 'Polygon' || candidate.type === 'MultiPolygon') &&
          Array.isArray(candidate.coordinates)
        ) {
          return candidate as WppGeoJsonGeometry;
        }
      }
    } catch {
      // Fall back to zone bounding box polygon if geometry JSON is malformed.
    }
  }
  return bboxFallbackPolygon(zone);
}

/**
 * Serializes either an existing GeoJSON FeatureCollection or `WppZoneRecord[]`
 * into an RFC 7946 FeatureCollection JSON string for `<marine-map>`.
 */
export function serializeWppGeoJsonCollection(
  input: WppGeoJsonCollection | readonly WppZoneRecordInput[] | null | undefined,
): string {
  if (!input) {
    return '{"type":"FeatureCollection","features":[]}';
  }
  if (!Array.isArray(input) && input.type === 'FeatureCollection') {
    return JSON.stringify(input);
  }
  const zones = Array.isArray(input) ? input : [];
  const features: WppGeoJsonFeature[] = zones.map((zone) => ({
    type: 'Feature',
    id: zone.wpp_code,
    properties: {
      wpp_code: zone.wpp_code,
      name: zone.name,
      waters_id: zone.waters_id,
      waters_en: zone.waters_en,
      centroid_lat: zone.centroid_lat,
      centroid_lon: zone.centroid_lon,
      min_lon: zone.min_lon,
      min_lat: zone.min_lat,
      max_lon: zone.max_lon,
      max_lat: zone.max_lat,
      sst_mean_c: zone.sst_mean_c ?? null,
      chlorophyll_mean_mg_m3: zone.chlorophyll_mean_mg_m3 ?? null,
    },
    geometry: parseZoneGeometry(zone),
  }));
  return JSON.stringify({
    type: 'FeatureCollection',
    name: 'wpp_nri_zones',
    features,
  });
}

export function serializeSpeciesMarkers(
  records: readonly SpeciesMarkerInput[] | null | undefined,
): string {
  if (!records || records.length === 0) {
    return '[]';
  }
  const normalized: SpeciesMarkerItem[] = [];
  for (const item of records) {
    const lat = typeof item.lat === 'number' ? item.lat : item.latitude;
    const lon = typeof item.lon === 'number' ? item.lon : item.longitude;
    if (
      typeof item.id !== 'string' ||
      !item.id ||
      typeof lat !== 'number' ||
      typeof lon !== 'number' ||
      !Number.isFinite(lat) ||
      !Number.isFinite(lon)
    ) {
      continue;
    }
    normalized.push({
      id: item.id,
      lat,
      lon,
      scientificName: item.scientific_name ?? item.title ?? item.id,
      commonName: item.common_name ?? null,
      wppCode: item.wpp_code ?? null,
      depthM: item.depth_m ?? null,
      habitatNote: item.habitat_note ?? null,
    });
  }
  return JSON.stringify(normalized);
}

export function parseMarineMapPointClick(
  payload: string,
): MarineMapPointClickMessage | null {
  try {
    const parsed: unknown = JSON.parse(payload);
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }
    const obj = parsed as Record<string, unknown>;
    if (
      obj.type === 'pointclick' &&
      typeof obj.lat === 'number' &&
      typeof obj.lon === 'number' &&
      Number.isFinite(obj.lat) &&
      Number.isFinite(obj.lon)
    ) {
      return { type: 'pointclick', lat: obj.lat, lon: obj.lon };
    }
    return null;
  } catch {
    return null;
  }
}

export function parseMarineMapMoveEnd(
  payload: string,
): MarineMapCameraBbox | null {
  try {
    const parsed: unknown = JSON.parse(payload);
    if (!parsed || typeof parsed !== 'object') {
      return null;
    }
    const obj = parsed as Record<string, unknown>;
    const centerLat =
      typeof obj.centerLat === 'number'
        ? obj.centerLat
        : typeof obj.latitude === 'number'
          ? obj.latitude
          : NaN;
    const centerLon =
      typeof obj.centerLon === 'number'
        ? obj.centerLon
        : typeof obj.longitude === 'number'
          ? obj.longitude
          : NaN;
    const zoom = typeof obj.zoom === 'number' ? obj.zoom : NaN;
    const minLon = typeof obj.minLon === 'number' ? obj.minLon : NaN;
    const minLat = typeof obj.minLat === 'number' ? obj.minLat : NaN;
    const maxLon = typeof obj.maxLon === 'number' ? obj.maxLon : NaN;
    const maxLat = typeof obj.maxLat === 'number' ? obj.maxLat : NaN;

    if (
      ![minLon, minLat, maxLon, maxLat, centerLat, centerLon, zoom].every(
        Number.isFinite,
      )
    ) {
      return null;
    }
    return {
      minLon,
      minLat,
      maxLon,
      maxLat,
      centerLat,
      centerLon,
      latitude: centerLat,
      longitude: centerLon,
      zoom,
    };
  } catch {
    return null;
  }
}

export function parseMarineMapChange(payload: string): MarineMapChangeEvent {
  const value = payload.trim();
  if (!value) {
    return { kind: 'clear', value: '' };
  }
  if (WPP_NRI_CODES.has(value)) {
    return { kind: 'wpp', value };
  }
  return { kind: 'species', value };
}

export function formatBboxQueryParam(bbox: MarineMapCameraBbox): string {
  return `${bbox.minLon.toFixed(4)},${bbox.minLat.toFixed(4)},${bbox.maxLon.toFixed(4)},${bbox.maxLat.toFixed(4)}`;
}
