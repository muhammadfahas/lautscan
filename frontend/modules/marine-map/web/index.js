// @lautscan/marine-map Web Host implementation for Expo Exact
//
// Self-contained Web Mercator (EPSG:3857) HTML/Canvas2D/SVG marine map engine:
// - Base XYZ OpenStreetMap tiles (or deterministic plain grid in test mode)
// - Multi-layer oceanographic XYZ overlays (SST, Chlorophyll-a, Currents) with CSS opacity
// - GeoJSON WPP-NRI (571-718) polygon boundaries & interactive zone chips
// - Species occurrence markers (OBIS / MapMarker) with >= 44x44px hit targets
// - Pan, drag, two-finger pinch, mouse wheel, keyboard navigation, and 44x44px +/- zoom controls
// - Click/tap on ocean coordinates emits `events.message(JSON.stringify({ type: 'pointclick', lat, lon }))`
// - Zone/marker selection emits `events.change(id)`
// - Camera stop emits `moveend` with serialized bbox + camera JSON

const TILE_SIZE = 256;
const MIN_ZOOM = 2;
const DEFAULT_MAX_ZOOM = 14;
const DEFAULT_CENTER_LAT = -2.5;
const DEFAULT_CENTER_LON = 118.0;
const DEFAULT_ZOOM = 5;
const REST_MS = 250;
const DRAG_THRESHOLD_PX = 5;
const DEFAULT_OSM_TILES = 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';
const DEFAULT_ATTRIBUTION = '© OpenStreetMap contributors';
const INDONESIA_BOUNDS = { minLon: 88, minLat: -16, maxLon: 148, maxLat: 12 };
const MAX_RENDERED_MARKERS = 150;

const STYLE = `
.lautscan-marine-map {
  --mm-bg: #F8FAFC;
  --mm-ocean: #E6F0FA;
  --mm-surface: #FFFFFF;
  --mm-ink: #1E293B;
  --mm-muted: #475569;
  --mm-border: #E2E8F0;
  --mm-focus: #3B82F6;
  --mm-cta: #F97316;
  --mm-plain-tile: #E8ECEF;
  --mm-plain-grid: #CBD5E1;
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  overflow: hidden;
  background: var(--mm-bg);
  color: var(--mm-ink);
  font-family: "Fira Sans", system-ui, -apple-system, sans-serif;
  touch-action: none;
  user-select: none;
  -webkit-user-select: none;
  cursor: grab;
  outline-offset: -3px;
}
.lautscan-marine-map.theme-night {
  --mm-bg: #0A0E27;
  --mm-ocean: #0A0E27;
  --mm-surface: #0D1117;
  --mm-ink: #E6EDF3;
  --mm-muted: #94A3B8;
  --mm-border: #30363D;
  --mm-focus: #60A5FA;
  --mm-cta: #F97316;
  --mm-plain-tile: #111834;
  --mm-plain-grid: #243056;
}
.lautscan-marine-map.dragging {
  cursor: grabbing;
}
.lautscan-marine-map:focus-visible,
.lautscan-marine-map button:focus-visible {
  outline: 2px solid var(--mm-focus);
  outline-offset: 2px;
}
.lautscan-marine-map .graticule-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 0;
}
.lautscan-marine-map .tile-layer {
  position: absolute;
  inset: 0;
  overflow: hidden;
  pointer-events: none;
}
.lautscan-marine-map .base-layer {
  z-index: 1;
}
.lautscan-marine-map.theme-night .base-layer img.tile {
  filter: invert(90%) hue-rotate(180deg) brightness(0.84) contrast(0.94) saturate(0.75);
}
.lautscan-marine-map .overlay-layer {
  z-index: 2;
  transition: opacity 200ms ease;
}
.lautscan-marine-map .overlay-chlorophyll {
  z-index: 3;
}
.lautscan-marine-map .overlay-potential {
  z-index: 4;
}
.lautscan-marine-map .overlay-currents {
  z-index: 4;
}
.lautscan-marine-map .currents-canvas {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 5;
  transition: opacity 200ms ease;
}
.lautscan-marine-map .tile {
  position: absolute;
  left: 0;
  top: 0;
  width: ${TILE_SIZE}px;
  height: ${TILE_SIZE}px;
  transform-origin: 0 0;
  pointer-events: none;
}
.lautscan-marine-map .tile.plain {
  box-sizing: border-box;
  background: var(--mm-plain-tile);
  border-right: 1px solid var(--mm-plain-grid);
  border-bottom: 1px solid var(--mm-plain-grid);
}
.lautscan-marine-map .tile.plain-overlay {
  box-sizing: border-box;
  border-right: 1px dashed rgba(249, 115, 22, 0.25);
  border-bottom: 1px dashed rgba(249, 115, 22, 0.25);
}
.lautscan-marine-map .tile.plain-sst {
  background: rgba(249, 115, 22, 0.22);
}
.lautscan-marine-map .tile.plain-chlorophyll {
  background: rgba(34, 197, 94, 0.20);
}
.lautscan-marine-map .tile.plain-potential {
  background: rgba(20, 184, 166, 0.24);
}
.lautscan-marine-map .tile.plain-currents {
  background: rgba(59, 130, 246, 0.20);
}
.lautscan-marine-map .wpp-svg {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  pointer-events: none;
  z-index: 6;
}
.lautscan-marine-map .wpp-path {
  fill: rgba(59, 130, 246, 0.06);
  stroke: #3B82F6;
  stroke-width: 1.5;
  stroke-linejoin: round;
  transition: stroke 180ms ease, fill 180ms ease, stroke-width 180ms ease;
}
.lautscan-marine-map.theme-night .wpp-path {
  fill: rgba(96, 165, 250, 0.08);
  stroke: #60A5FA;
}
.lautscan-marine-map .wpp-path.selected {
  fill: rgba(249, 115, 22, 0.16);
  stroke: #F97316;
  stroke-width: 2.5;
}
.lautscan-marine-map .wpp-labels-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 8;
}
.lautscan-marine-map .wpp-chip {
  position: absolute;
  transform: translate(-50%, -50%);
  min-width: 44px;
  min-height: 44px;
  padding: 4px;
  margin: 0;
  border: 0;
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
  cursor: pointer;
}
.lautscan-marine-map .wpp-chip-pill {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  padding: 3px 7px;
  border-radius: 999px;
  border: 1px solid var(--mm-border);
  background: rgba(255, 255, 255, 0.88);
  color: var(--mm-ink);
  font-family: "Fira Code", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.2;
  white-space: nowrap;
  box-shadow: 0 1px 3px rgba(15, 23, 42, 0.18);
  transition: background-color 180ms ease, border-color 180ms ease, color 180ms ease;
}
.lautscan-marine-map.theme-night .wpp-chip-pill {
  background: rgba(13, 17, 23, 0.88);
  box-shadow: 0 1px 4px rgba(0, 0, 0, 0.45);
}
.lautscan-marine-map .wpp-chip:hover .wpp-chip-pill {
  border-color: var(--mm-focus);
}
.lautscan-marine-map .wpp-chip[aria-pressed="true"] .wpp-chip-pill {
  background: var(--mm-cta);
  border-color: var(--mm-cta);
  color: #FFFFFF;
}
.lautscan-marine-map .markers-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 7;
}
.lautscan-marine-map .species-marker {
  position: absolute;
  transform: translate(-50%, -50%);
  min-width: 44px;
  min-height: 44px;
  border: 0;
  padding: 4px;
  margin: 0;
  background: transparent;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  pointer-events: auto;
  cursor: pointer;
}
.lautscan-marine-map .species-marker-pill {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 8px 3px 4px;
  border-radius: 999px;
  border: 1px solid var(--mm-border);
  background: rgba(255, 255, 255, 0.94);
  color: var(--mm-ink);
  font-family: "Fira Sans", system-ui, sans-serif;
  font-size: 11px;
  font-weight: 700;
  line-height: 1.2;
  white-space: nowrap;
  box-shadow: 0 2px 6px rgba(15, 23, 42, 0.18);
  transition: transform 160ms ease, background-color 160ms ease, border-color 160ms ease, color 160ms ease;
}
.lautscan-marine-map.theme-night .species-marker-pill {
  background: rgba(13, 17, 23, 0.92);
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.48);
}
.lautscan-marine-map .species-marker-dot {
  width: 20px;
  height: 20px;
  border-radius: 999px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  color: #FFFFFF;
  flex-shrink: 0;
}
.lautscan-marine-map .species-marker:hover .species-marker-pill {
  transform: scale(1.06);
  border-color: var(--mm-focus);
}
.lautscan-marine-map .species-marker[aria-pressed="true"] .species-marker-pill {
  background: var(--mm-cta);
  border-color: var(--mm-cta);
  color: #FFFFFF;
  transform: scale(1.08);
}
.lautscan-marine-map .pin-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 9;
}
.lautscan-marine-map .inspect-pin {
  position: absolute;
  transform: translate(-50%, -50%);
  width: 28px;
  height: 28px;
  pointer-events: none;
}
.lautscan-marine-map .zoom-controls {
  position: absolute;
  left: 12px;
  bottom: 12px;
  z-index: 10;
  display: flex;
  flex-direction: column;
  border-radius: 10px;
  overflow: hidden;
  border: 1px solid var(--mm-border);
  background: var(--mm-surface);
  box-shadow: 0 2px 8px rgba(15, 23, 42, 0.16);
}
.lautscan-marine-map.theme-night .zoom-controls {
  box-shadow: 0 2px 10px rgba(0, 0, 0, 0.45);
}
.lautscan-marine-map .zoom-btn {
  min-width: 44px;
  min-height: 44px;
  width: 44px;
  height: 44px;
  border: 0;
  padding: 0;
  margin: 0;
  background: var(--mm-surface);
  color: var(--mm-ink);
  display: inline-flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  transition: background-color 180ms ease, color 180ms ease;
}
.lautscan-marine-map .zoom-btn + .zoom-btn {
  border-top: 1px solid var(--mm-border);
}
.lautscan-marine-map .zoom-btn:hover:not(:disabled) {
  background: rgba(59, 130, 246, 0.10);
}
.lautscan-marine-map .zoom-btn:disabled {
  opacity: 0.45;
  cursor: not-allowed;
}
.lautscan-marine-map .map-hud {
  position: absolute;
  right: 8px;
  bottom: 8px;
  z-index: 10;
  display: flex;
  align-items: center;
  gap: 8px;
  max-width: calc(100% - 80px);
  padding: 4px 8px;
  border-radius: 6px;
  border: 1px solid var(--mm-border);
  background: rgba(255, 255, 255, 0.88);
  color: var(--mm-muted);
  font-size: 11px;
  line-height: 1.3;
  pointer-events: none;
}
.lautscan-marine-map.theme-night .map-hud {
  background: rgba(13, 17, 23, 0.88);
}
.lautscan-marine-map .hud-coords {
  font-family: "Fira Code", ui-monospace, monospace;
  font-variant-numeric: tabular-nums;
  color: var(--mm-ink);
  white-space: nowrap;
}
.lautscan-marine-map .hud-credit {
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.lautscan-marine-map.plain-mode,
.lautscan-marine-map.plain-mode * {
  transition: none !important;
  animation: none !important;
}
@media (prefers-reduced-motion: reduce) {
  .lautscan-marine-map,
  .lautscan-marine-map * {
    transition: none !important;
    animation: none !important;
  }
}
`;

const styledDocs = new WeakSet();

const clamp = (value, low, high) => Math.min(high, Math.max(low, value));
const round = (value, places) => {
  const factor = 10 ** places;
  return Math.round(value * factor) / factor;
};

const parseNum = (value, fallback) => {
  if (value === null || value === undefined || value === '') return fallback;
  const n = Number(value);
  return Number.isFinite(n) ? n : fallback;
};

const parseBool = (value, fallback) => {
  if (typeof value === 'boolean') return value;
  if (value === 'true' || value === '1') return true;
  if (value === 'false' || value === '0') return false;
  return fallback;
};

const parseStr = (value, fallback = '') => {
  if (typeof value === 'string') return value;
  if (value === null || value === undefined) return fallback;
  return String(value);
};

// Web Mercator projection in world pixels at zoom z (world width = 256 * 2^z).
export function project(lat, lon, z) {
  const scale = TILE_SIZE * 2 ** z;
  const clampedLat = clamp(lat, -85.05112878, 85.05112878);
  const sinLat = Math.sin((clampedLat * Math.PI) / 180);
  const x = ((lon + 180) / 360) * scale;
  const y = (0.5 - Math.log((1 + sinLat) / (1 - sinLat)) / (4 * Math.PI)) * scale;
  return [x, y];
}

export function unproject(x, y, z) {
  const scale = TILE_SIZE * 2 ** z;
  const n = Math.PI - (2 * Math.PI * y) / scale;
  const lat = (180 / Math.PI) * Math.atan(Math.sinh(n));
  const lon = ((((x / scale) * 360) % 360) + 360) % 360 - 180;
  return [lat, lon];
}

function tileBounds(z, x, y) {
  const n = 2 ** z;
  const west = (x / n) * 360 - 180;
  const east = ((x + 1) / n) * 360 - 180;
  const north = (180 / Math.PI) * Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n)));
  const south = (180 / Math.PI) * Math.atan(Math.sinh(Math.PI * (1 - (2 * (y + 1)) / n)));
  return { west, south, east, north };
}

function intersectsIndonesia(z, x, y) {
  if (z <= 3) return true;
  const b = tileBounds(z, x, y);
  return !(
    b.east < INDONESIA_BOUNDS.minLon ||
    b.west > INDONESIA_BOUNDS.maxLon ||
    b.north < INDONESIA_BOUNDS.minLat ||
    b.south > INDONESIA_BOUNDS.maxLat
  );
}

function normalizeBaseUrl(raw) {
  const trimmed = parseStr(raw, '').trim();
  if (!trimmed || trimmed === 'none' || trimmed === 'offline') return '';
  return trimmed.replace(/\/+$/, '');
}

function buildZoomInSvg() {
  return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M12 5v14M5 12h14"/></svg>';
}

function buildZoomOutSvg() {
  return '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" aria-hidden="true"><path d="M5 12h14"/></svg>';
}

function buildSpeciesSvg() {
  return '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M6.5 12c.94-3.46 4.94-6 8.5-6 3.56 0 6.06 2.54 7 6-.94 3.46-3.44 6-7 6-3.56 0-7.56-2.54-8.5-6Z"/><path d="M18 12v.5"/><path d="M7 10.67C7 8 5.58 5.97 2.73 5.5c-1 1.5-1 5 .23 6.5-1.24 1.5-1.24 5-.23 6.5C5.58 18.03 7 16 7 13.33"/></svg>';
}

function shortFishLabel(commonName, sciName) {
  const raw = parseStr(commonName, '').trim();
  const idPart = raw.includes('/') ? raw.split('/').pop().trim() : (raw || parseStr(sciName, 'Ikan').trim());
  const cleaned = idPart.replace(/^ikan\s+/i, '').trim();
  if (!cleaned) return 'Ikan';
  const firstWord = cleaned.split(/\s+/)[0];
  return firstWord.charAt(0).toUpperCase() + firstWord.slice(1);
}

function buildInspectPinSvg() {
  return '<svg viewBox="0 0 28 28" aria-hidden="true"><circle cx="14" cy="14" r="10" fill="rgba(249,115,22,0.18)" stroke="#F97316" stroke-width="2"/><circle cx="14" cy="14" r="3.5" fill="#F97316" stroke="#FFFFFF" stroke-width="1.5"/><path d="M14 2v4M14 22v4M2 14h4M22 14h4" stroke="#F97316" stroke-width="1.6" stroke-linecap="round"/></svg>';
}

function bboxPolygon(minLon, minLat, maxLon, maxLat) {
  return {
    type: 'Polygon',
    coordinates: [
      [
        [minLon, minLat],
        [maxLon, minLat],
        [maxLon, maxLat],
        [minLon, maxLat],
        [minLon, minLat],
      ],
    ],
  };
}

function computePolygonBboxAndCenter(geometry) {
  let minLon = Infinity;
  let minLat = Infinity;
  let maxLon = -Infinity;
  let maxLat = -Infinity;
  const visitRing = (ring) => {
    if (!Array.isArray(ring)) return;
    for (const pt of ring) {
      if (!Array.isArray(pt) || pt.length < 2) continue;
      const lon = Number(pt[0]);
      const lat = Number(pt[1]);
      if (!Number.isFinite(lon) || !Number.isFinite(lat)) continue;
      if (lon < minLon) minLon = lon;
      if (lon > maxLon) maxLon = lon;
      if (lat < minLat) minLat = lat;
      if (lat > maxLat) maxLat = lat;
    }
  };
  if (geometry?.type === 'Polygon' && Array.isArray(geometry.coordinates)) {
    for (const ring of geometry.coordinates) visitRing(ring);
  } else if (geometry?.type === 'MultiPolygon' && Array.isArray(geometry.coordinates)) {
    for (const poly of geometry.coordinates) {
      if (Array.isArray(poly)) for (const ring of poly) visitRing(ring);
    }
  }
  if (!Number.isFinite(minLon)) {
    return null;
  }
  return {
    minLon,
    minLat,
    maxLon,
    maxLat,
    centroidLat: (minLat + maxLat) / 2,
    centroidLon: (minLon + maxLon) / 2,
  };
}

function normalizeWppFeatures(text) {
  const raw = parseStr(text, '').trim();
  if (!raw || raw === 'null') return [];
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  const rawItems = Array.isArray(parsed)
    ? parsed
    : Array.isArray(parsed?.features)
      ? parsed.features
      : Array.isArray(parsed?.items)
        ? parsed.items
        : parsed?.type === 'Feature'
          ? [parsed]
          : [];

  const features = [];
  for (const item of rawItems) {
    if (!item || typeof item !== 'object') continue;
    if (item.type === 'Feature' && item.geometry) {
      const props = item.properties ?? {};
      const code = parseStr(props.wpp_code ?? item.id, '').trim();
      const bounds = computePolygonBboxAndCenter(item.geometry);
      if (!bounds) continue;
      features.push({
        code,
        name: parseStr(props.name, code ? `WPP-NRI ${code}` : 'WPP-NRI'),
        watersId: parseStr(props.waters_id, ''),
        centroidLat: parseNum(props.centroid_lat, bounds.centroidLat),
        centroidLon: parseNum(props.centroid_lon, bounds.centroidLon),
        minLon: parseNum(props.min_lon, bounds.minLon),
        minLat: parseNum(props.min_lat, bounds.minLat),
        maxLon: parseNum(props.max_lon, bounds.maxLon),
        maxLat: parseNum(props.max_lat, bounds.maxLat),
        geometry: item.geometry,
      });
      continue;
    }

    // WppZoneRecord shape support
    const code = parseStr(item.wpp_code, '').trim();
    if (!code) continue;
    let geometry = null;
    if (typeof item.geometry_geojson === 'string' && item.geometry_geojson.trim()) {
      try {
        const g = JSON.parse(item.geometry_geojson);
        if (g && (g.type === 'Polygon' || g.type === 'MultiPolygon') && Array.isArray(g.coordinates)) {
          geometry = g;
        }
      } catch {
        geometry = null;
      }
    }
    const minLon = parseNum(item.min_lon, NaN);
    const minLat = parseNum(item.min_lat, NaN);
    const maxLon = parseNum(item.max_lon, NaN);
    const maxLat = parseNum(item.max_lat, NaN);
    if (!geometry && [minLon, minLat, maxLon, maxLat].every(Number.isFinite)) {
      geometry = bboxPolygon(minLon, minLat, maxLon, maxLat);
    }
    if (!geometry) continue;
    const bounds = computePolygonBboxAndCenter(geometry);
    if (!bounds) continue;
    features.push({
      code,
      name: parseStr(item.name, `WPP-NRI ${code}`),
      watersId: parseStr(item.waters_id, ''),
      centroidLat: parseNum(item.centroid_lat, bounds.centroidLat),
      centroidLon: parseNum(item.centroid_lon, bounds.centroidLon),
      minLon: Number.isFinite(minLon) ? minLon : bounds.minLon,
      minLat: Number.isFinite(minLat) ? minLat : bounds.minLat,
      maxLon: Number.isFinite(maxLon) ? maxLon : bounds.maxLon,
      maxLat: Number.isFinite(maxLat) ? maxLat : bounds.maxLat,
      geometry,
    });
  }
  return features;
}

function normalizeMarkers(text) {
  const raw = parseStr(text, '').trim();
  if (!raw || raw === 'null') return [];
  let parsed;
  try {
    parsed = JSON.parse(raw);
  } catch {
    return [];
  }
  const list = Array.isArray(parsed)
    ? parsed
    : Array.isArray(parsed?.items)
      ? parsed.items
      : [];
  const out = [];
  for (const item of list) {
    if (!item || typeof item !== 'object') continue;
    const id = parseStr(item.id, '').trim();
    const lat = parseNum(item.lat ?? item.latitude, NaN);
    const lon = parseNum(item.lon ?? item.longitude, NaN);
    if (!id || !Number.isFinite(lat) || !Number.isFinite(lon)) continue;
    const label = parseStr(
      item.common_name ?? item.commonName ?? item.scientific_name ?? item.scientificName ?? item.title,
      id,
    );
    const sciName = parseStr(item.scientific_name ?? item.scientificName ?? item.title, label);
    const depthM = parseNum(item.depth_m ?? item.depthM, NaN);
    out.push({
      id,
      lat,
      lon,
      label,
      shortName: shortFishLabel(label, sciName),
      scientificName: sciName,
      wppCode: parseStr(item.wpp_code ?? item.wppCode, ''),
      depthM: Number.isFinite(depthM) ? depthM : null,
      habitatNote: parseStr(item.habitat_note ?? item.habitatNote, ''),
    });
  }
  return out;
}

export class MarineMap {
  constructor({ implementation, element, props = {}, events = {}, view = '0' }) {
    const doc = element.ownerDocument;
    if (!styledDocs.has(doc)) {
      const styleEl = doc.createElement('style');
      styleEl.setAttribute('data-lautscan-marine-map', '1');
      styleEl.textContent = STYLE;
      doc.head.append(styleEl);
      styledDocs.add(doc);
    }

    this.doc = doc;
    this.element = element;
    this.events = events;
    this.view = view;
    this.implementation = implementation;
    this.config = implementation?.config ?? {};
    this.plain = !!implementation?.plain?.();
    this.maxZoom = parseNum(this.config.maxZoom, DEFAULT_MAX_ZOOM);
    this.osmTemplate = parseStr(this.config.tiles, DEFAULT_OSM_TILES) || DEFAULT_OSM_TILES;
    this.attributionText = parseStr(this.config.attribution, DEFAULT_ATTRIBUTION) || DEFAULT_ATTRIBUTION;

    const computedPos =
      typeof getComputedStyle === 'function'
        ? getComputedStyle(element)?.position
        : element.style.position;
    if (!computedPos || computedPos === 'static') {
      element.style.position = 'relative';
    }

    this.map = doc.createElement('div');
    this.map.className = 'lautscan-marine-map theme-daylight';
    if (this.plain) this.map.classList.add('plain-mode');
    this.map.tabIndex = 0;
    this.map.setAttribute('role', 'application');
    this.map.setAttribute('aria-roledescription', 'map');
    this.map.setAttribute('aria-label', 'Interactive Indonesian marine intelligence map');
    this.map.dataset.testid = 'marine-map-root';

    this.gridCanvas = doc.createElement('canvas');
    this.gridCanvas.className = 'graticule-canvas';
    this.gridCanvas.setAttribute('aria-hidden', 'true');

    this.baseLayer = doc.createElement('div');
    this.baseLayer.className = 'tile-layer base-layer';
    this.baseLayer.setAttribute('aria-hidden', 'true');

    this.sstLayer = doc.createElement('div');
    this.sstLayer.className = 'tile-layer overlay-layer overlay-sst';
    this.sstLayer.setAttribute('aria-hidden', 'true');

    this.chlorophyllLayer = doc.createElement('div');
    this.chlorophyllLayer.className = 'tile-layer overlay-layer overlay-chlorophyll';
    this.chlorophyllLayer.setAttribute('aria-hidden', 'true');

    this.potentialLayer = doc.createElement('div');
    this.potentialLayer.className = 'tile-layer overlay-layer overlay-potential';
    this.potentialLayer.setAttribute('aria-hidden', 'true');

    this.currentsLayer = doc.createElement('div');
    this.currentsLayer.className = 'tile-layer overlay-layer overlay-currents';
    this.currentsLayer.setAttribute('aria-hidden', 'true');

    this.currentsCanvas = doc.createElement('canvas');
    this.currentsCanvas.className = 'currents-canvas';
    this.currentsCanvas.setAttribute('aria-hidden', 'true');

    this.wppSvg = doc.createElementNS('http://www.w3.org/2000/svg', 'svg');
    this.wppSvg.setAttribute('class', 'wpp-svg');
    this.wppSvg.setAttribute('aria-hidden', 'true');

    this.wppLabelsLayer = doc.createElement('div');
    this.wppLabelsLayer.className = 'wpp-labels-layer';

    this.markersLayer = doc.createElement('div');
    this.markersLayer.className = 'markers-layer';

    this.pinLayer = doc.createElement('div');
    this.pinLayer.className = 'pin-layer';
    this.pinLayer.setAttribute('aria-hidden', 'true');

    this.zoomBox = doc.createElement('div');
    this.zoomBox.className = 'zoom-controls';
    this.zoomBox.setAttribute('role', 'group');
    this.zoomBox.setAttribute('aria-label', 'Map zoom controls');
    this.zoomInBtn = doc.createElement('button');
    this.zoomInBtn.type = 'button';
    this.zoomInBtn.className = 'zoom-btn';
    this.zoomInBtn.setAttribute('aria-label', 'Zoom in');
    this.zoomInBtn.dataset.testid = 'marine-map-zoom-in';
    this.zoomInBtn.innerHTML = buildZoomInSvg();
    this.zoomOutBtn = doc.createElement('button');
    this.zoomOutBtn.type = 'button';
    this.zoomOutBtn.className = 'zoom-btn';
    this.zoomOutBtn.setAttribute('aria-label', 'Zoom out');
    this.zoomOutBtn.dataset.testid = 'marine-map-zoom-out';
    this.zoomOutBtn.innerHTML = buildZoomOutSvg();
    this.zoomBox.append(this.zoomInBtn, this.zoomOutBtn);

    this.hud = doc.createElement('div');
    this.hud.className = 'map-hud';
    this.hudCoords = doc.createElement('span');
    this.hudCoords.className = 'hud-coords';
    this.hudCredit = doc.createElement('span');
    this.hudCredit.className = 'hud-credit';
    this.hudCredit.textContent = this.plain ? 'Plain tiles' : this.attributionText;
    this.hud.append(this.hudCoords, this.hudCredit);

    this.map.append(
      this.gridCanvas,
      this.baseLayer,
      this.sstLayer,
      this.chlorophyllLayer,
      this.potentialLayer,
      this.currentsLayer,
      this.currentsCanvas,
      this.wppSvg,
      this.wppLabelsLayer,
      this.markersLayer,
      this.pinLayer,
      this.zoomBox,
      this.hud,
    );
    element.append(this.map);

    const initRect = this.map.getBoundingClientRect?.();
    this.size = {
      w: initRect?.width || 0,
      h: initRect?.height || 0,
    };
    this.center = [DEFAULT_CENTER_LAT, DEFAULT_CENTER_LON];
    this.zoom = DEFAULT_ZOOM;
    this.baseStyle = 'daylight';
    this.layers = {
      sst: { visible: false, opacity: 0.62, container: this.sstLayer, tiles: new Map() },
      chlorophyll: { visible: false, opacity: 0.65, container: this.chlorophyllLayer, tiles: new Map() },
      potential: { visible: false, opacity: 0.88, container: this.potentialLayer, tiles: new Map() },
      currents: { visible: false, opacity: 0.88, container: this.currentsLayer, tiles: new Map() },
    };
    this.currentsRasterVisible = false;
    this.showSpeciesPins = true;
    this.baseTiles = new Map();
    this.selectedDate = 'latest';
    this.tileBaseUrl = '';
    this.wppFeatures = [];
    this.selectedWppCode = '';
    this.markers = [];
    this.selectedMarkerId = '';
    this.inspectedPoint = null;
    this.parts = new Map();
    this.lastProps = {};
    this.resting = null;
    this.tileFetchTimer = null;
    this.skipTileFetch = false;
    this.currentsVectors = [];
    this.currentsField = null;
    this.currentsParticles = [];
    this.currentsFetchKey = '';
    this.currentsFetchTimer = null;
    this.currentsAbort = null;
    this.currentsRaf = null;
    this.currentsLastFrameTs = 0;
    this._renderedWppScreenPts = [];

    if (typeof ResizeObserver === 'function') {
      this.resize = new ResizeObserver(() => {
        const rect = this.map.getBoundingClientRect();
        this.size = { w: rect.width, h: rect.height };
        this.draw();
      });
      this.resize.observe(this.map);
    } else {
      const rect = this.map.getBoundingClientRect();
      this.size = { w: rect.width || 800, h: rect.height || 600 };
    }

    this.listen();
    this.setProps(props, true);
    this.implementation?.made?.(this.view, this);
    this.events?.load?.();
  }

  setProps(props = {}, first = false) {
    const safeProps = props && typeof props === 'object' ? props : {};
    const changed = (key) => first || safeProps[key] !== this.lastProps[key];

    let cameraMoved = false;
    const latChanged = changed('centerLat');
    const lonChanged = changed('centerLon');
    if (latChanged || lonChanged) {
      const nextLat = latChanged ? parseNum(safeProps.centerLat, this.center[0]) : this.center[0];
      const nextLon = lonChanged ? parseNum(safeProps.centerLon, this.center[1]) : this.center[1];
      if (
        Number.isFinite(nextLat) &&
        Number.isFinite(nextLon) &&
        (nextLat !== this.center[0] || nextLon !== this.center[1])
      ) {
        this.center = [clamp(nextLat, -85, 85), ((((nextLon + 180) % 360) + 360) % 360) - 180];
        cameraMoved = true;
      }
    }

    const zoomChanged = changed('zoom');
    if (zoomChanged) {
      const nextZoom = parseNum(safeProps.zoom, this.zoom);
      const clampedZoom = this.clampZoom(nextZoom);
      if (clampedZoom !== this.zoom) {
        this.zoom = clampedZoom;
        cameraMoved = true;
      }
    }

    if (changed('baseStyle')) {
      const style = parseStr(safeProps.baseStyle, 'daylight').toLowerCase() === 'night' ? 'night' : 'daylight';
      this.baseStyle = style;
      this.map.classList.toggle('theme-night', style === 'night');
      this.map.classList.toggle('theme-daylight', style !== 'night');
    }

    if (changed('potentialVisible')) this.layers.potential.visible = parseBool(safeProps.potentialVisible, false);
    if (changed('potentialOpacity')) this.layers.potential.opacity = clamp(parseNum(safeProps.potentialOpacity, 0.88), 0, 1);
    if (changed('sstVisible')) this.layers.sst.visible = parseBool(safeProps.sstVisible, false);
    if (changed('sstOpacity')) this.layers.sst.opacity = clamp(parseNum(safeProps.sstOpacity, 0.62), 0, 1);
    if (changed('chlorophyllVisible')) this.layers.chlorophyll.visible = parseBool(safeProps.chlorophyllVisible, false);
    if (changed('chlorophyllOpacity')) this.layers.chlorophyll.opacity = clamp(parseNum(safeProps.chlorophyllOpacity, 0.65), 0, 1);
    if (changed('currentsVisible')) this.layers.currents.visible = parseBool(safeProps.currentsVisible, false);
    if (changed('currentsOpacity')) this.layers.currents.opacity = clamp(parseNum(safeProps.currentsOpacity, 0.88), 0, 1);
    if (changed('currentsRasterVisible')) this.currentsRasterVisible = parseBool(safeProps.currentsRasterVisible, false);
    if (changed('showSpeciesPins')) this.showSpeciesPins = parseBool(safeProps.showSpeciesPins, true);

    const dateChanged = changed('selectedDate');
    const baseUrlChanged = changed('tileBaseUrl');
    if (dateChanged) this.selectedDate = parseStr(safeProps.selectedDate, 'latest').trim() || 'latest';
    if (baseUrlChanged) this.tileBaseUrl = normalizeBaseUrl(safeProps.tileBaseUrl);
    if (!first && (dateChanged || baseUrlChanged)) {
      this.clearOverlayTiles();
      this.currentsFetchKey = '';
      this.currentsVectors = [];
      this.currentsField = null;
      this.currentsParticles = [];
    }

    if (changed('wppGeoJsonCollection')) {
      this.wppFeatures = normalizeWppFeatures(safeProps.wppGeoJsonCollection);
    }

    if (changed('selectedWppCode')) {
      const nextWpp = parseStr(safeProps.selectedWppCode, '').trim();
      const prevWpp = this.selectedWppCode;
      this.selectedWppCode = nextWpp;
      if (!first && nextWpp && nextWpp !== prevWpp && !latChanged && !lonChanged && !zoomChanged) {
        if (this.focusWppZone(nextWpp)) {
          cameraMoved = true;
        }
      }
    }

    if (changed('speciesMarkers')) {
      this.markers = normalizeMarkers(safeProps.speciesMarkers);
    }

    this.lastProps = { ...safeProps };
    this.syncLayerStyles();
    this.draw();
    this.reportState();
    if (cameraMoved && !first) {
      this.rest();
    }
  }

  clampZoom(z) {
    return clamp(z, MIN_ZOOM, this.maxZoom);
  }

  focusWppZone(code) {
    const zone = this.wppFeatures.find((f) => f.code === code);
    if (!zone) return false;
    this.center = [clamp(zone.centroidLat, -85, 85), zone.centroidLon];
    if (this.size.w > 0 && this.size.h > 0) {
      const lonSpan = Math.max(0.5, zone.maxLon - zone.minLon);
      const latSpan = Math.max(0.5, zone.maxLat - zone.minLat);
      const zoomLon = Math.log2((this.size.w * 360) / (TILE_SIZE * lonSpan * 1.35));
      const zoomLat = Math.log2((this.size.h * 170) / (TILE_SIZE * latSpan * 1.35));
      this.zoom = this.clampZoom(round(Math.min(zoomLon, zoomLat), 2));
    }
    return true;
  }

  clearOverlayTiles() {
    for (const layerState of Object.values(this.layers)) {
      for (const node of layerState.tiles.values()) node.remove();
      layerState.tiles.clear();
    }
  }

  syncLayerStyles() {
    for (const [layerName, layerState] of Object.entries(this.layers)) {
      const showRaster = layerName === 'currents' ? layerState.visible && this.currentsRasterVisible : layerState.visible;
      layerState.container.style.display = showRaster ? 'block' : 'none';
      layerState.container.style.opacity = String(layerState.opacity);
    }
    this.currentsCanvas.style.display = this.layers.currents.visible ? 'block' : 'none';
    this.currentsCanvas.style.opacity = String(this.layers.currents.opacity);
    this.markersLayer.style.display = this.showSpeciesPins ? 'block' : 'none';
    this.zoomInBtn.disabled = this.zoom >= this.maxZoom;
    this.zoomOutBtn.disabled = this.zoom <= MIN_ZOOM;
    this.syncCurrentsAnimation();
  }

  prefersReducedMotion() {
    return typeof window !== 'undefined' && window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches === true;
  }

  syncCurrentsAnimation() {
    const active = this.layers.currents.visible && this.layers.currents.opacity > 0 && !this.plain && !this.prefersReducedMotion();
    if (!active) {
      if (this.currentsRaf !== null) {
        cancelAnimationFrame(this.currentsRaf);
        this.currentsRaf = null;
      }
      return;
    }
    if (this.currentsRaf !== null || typeof requestAnimationFrame !== 'function') return;
    this.currentsLastFrameTs = 0;
    const stepFrame = (ts) => {
      if (!this.layers.currents.visible || !this.map.isConnected) {
        this.currentsRaf = null;
        return;
      }
      if (!this.currentsLastFrameTs || ts - this.currentsLastFrameTs >= 32) {
        const dt = this.currentsLastFrameTs ? Math.min(0.06, (ts - this.currentsLastFrameTs) / 1000) : 0.033;
        this.currentsLastFrameTs = ts;
        const { w, h } = this.size;
        if (w && h && this.currentsField && !this.skipTileFetch) {
          this.advanceCurrentsParticles(dt);
          const z = Math.min(this.maxZoom, Math.max(0, Math.round(this.zoom)));
          const k = 2 ** (this.zoom - z);
          const [cx, cy] = project(this.center[0], this.center[1], z);
          this.renderCurrentsStreamlines(w, h, z, k, cx - w / 2 / k, cy - h / 2 / k, 2 ** z);
        }
      }
      this.currentsRaf = requestAnimationFrame(stepFrame);
    };
    this.currentsRaf = requestAnimationFrame(stepFrame);
  }

  cameraBbox() {
    const w = this.size.w || 800;
    const h = this.size.h || 600;
    const [cx, cy] = project(this.center[0], this.center[1], this.zoom);
    const [maxLat, minLon] = unproject(cx - w / 2, cy - h / 2, this.zoom);
    const [minLat, maxLon] = unproject(cx + w / 2, cy + h / 2, this.zoom);
    const centerLat = round(this.center[0], 6);
    const centerLon = round(this.center[1], 6);
    return {
      minLon: round(minLon, 6),
      minLat: round(minLat, 6),
      maxLon: round(maxLon, 6),
      maxLat: round(maxLat, 6),
      centerLat,
      centerLon,
      latitude: centerLat,
      longitude: centerLon,
      zoom: round(this.zoom, 3),
    };
  }

  reportState() {
    this.implementation?.propsOf?.(this.view, {
      camera: this.cameraBbox(),
      baseStyle: this.baseStyle,
      layers: {
        potential: { visible: this.layers.potential.visible, opacity: this.layers.potential.opacity },
        sst: { visible: this.layers.sst.visible, opacity: this.layers.sst.opacity },
        chlorophyll: { visible: this.layers.chlorophyll.visible, opacity: this.layers.chlorophyll.opacity },
        currents: { visible: this.layers.currents.visible, opacity: this.layers.currents.opacity },
      },
      showSpeciesPins: this.showSpeciesPins,
      selectedDate: this.selectedDate,
      selectedWppCode: this.selectedWppCode,
      selectedMarkerId: this.selectedMarkerId,
      markers: this.markers.map((m) => m.id),
      wppZones: this.wppFeatures.map((f) => f.code),
      inspectedPoint: this.inspectedPoint,
    });
  }

  emitMoveEnd() {
    const payload = JSON.stringify(this.cameraBbox());
    if (typeof this.events?.emit === 'function') {
      this.events.emit('moveend', payload);
    } else if (typeof this.events?.moveend === 'function') {
      this.events.moveend(payload);
    }
  }

  emitChange(value) {
    this.events?.change?.(String(value ?? ''));
  }

  emitPointClick(lat, lon, markerId = '') {
    const roundedLat = round(clamp(lat, -85, 85), 5);
    const roundedLon = round(lon, 5);
    this.inspectedPoint = { lat: roundedLat, lon: roundedLon };
    this.drawPin();
    this.reportState();
    const payload = {
      type: 'pointclick',
      lat: roundedLat,
      lon: roundedLon,
    };
    if (markerId) payload.markerId = markerId;
    this.events?.message?.(JSON.stringify(payload));
  }

  rest() {
    clearTimeout(this.resting);
    this.resting = setTimeout(() => {
      this.reportState();
      this.emitMoveEnd();
    }, REST_MS);
  }

  zoomBy(dz, px = 0, py = 0, deferFetch = false) {
    const z0 = this.zoom;
    const [x, y] = project(this.center[0], this.center[1], z0);
    const under = unproject(x + px, y + py, z0);
    this.zoom = this.clampZoom(z0 + dz);
    const [ux, uy] = project(under[0], under[1], this.zoom);
    const [nextLat, nextLon] = unproject(ux - px, uy - py, this.zoom);
    this.center = [clamp(nextLat, -85, 85), nextLon];
    this.syncLayerStyles();
    if (deferFetch && !this.plain) {
      this.skipTileFetch = true;
      this.draw();
      clearTimeout(this.tileFetchTimer);
      this.tileFetchTimer = setTimeout(() => {
        this.skipTileFetch = false;
        this.draw();
      }, 90);
    } else {
      this.skipTileFetch = false;
      this.draw();
    }
    this.rest();
  }

  panBy(dx, dy) {
    const [x, y] = project(this.center[0], this.center[1], this.zoom);
    const [nextLat, nextLon] = unproject(x + dx, y + dy, this.zoom);
    this.center = [clamp(nextLat, -85, 85), nextLon];
    this.draw();
  }

  osmTileUrl(z, x, y) {
    return this.osmTemplate
      .replace('{z}', String(z))
      .replace('{x}', String(x))
      .replace('{y}', String(y));
  }

  overlayTileUrl(layer, z, x, y) {
    const safeDate = encodeURIComponent(this.selectedDate || 'latest');
    const path = `/v1/tiles/${encodeURIComponent(layer)}/${safeDate}/${z}/${x}/${y}.png`;
    return this.tileBaseUrl ? `${this.tileBaseUrl}${path}` : path;
  }

  draw() {
    const { w, h } = this.size;
    if (!w || !h) return;

    const z = Math.min(this.maxZoom, Math.max(0, Math.round(this.zoom)));
    const k = 2 ** (this.zoom - z);
    const [cx, cy] = project(this.center[0], this.center[1], z);
    const left = cx - w / 2 / k;
    const top = cy - h / 2 / k;
    const n = 2 ** z;

    this.hudCoords.textContent = `Z${round(this.zoom, 1)} · ${this.center[0].toFixed(2)}°, ${this.center[1].toFixed(2)}°`;

    this.drawGraticule(w, h, z, k, left, top);
    this.drawBaseTiles(w, h, z, k, left, top, n);
    this.drawOverlayTiles(w, h, z, k, left, top, n);
    this.drawCurrentsVectors(w, h, z, k, left, top, n);
    this.drawWppGeoJson(w, h, z, k, left, top, n);
    this.drawMarkers(w, h, z, k, left, top, n);
    this.drawPin(z, k, left, top);
  }

  drawGraticule(w, h, z, k, left, top) {
    const canvas = this.gridCanvas;
    const dpr = typeof window !== 'undefined' && window.devicePixelRatio ? Math.min(window.devicePixelRatio, 2) : 1;
    const pw = Math.max(1, Math.round(w * dpr));
    const ph = Math.max(1, Math.round(h * dpr));
    if (canvas.width !== pw || canvas.height !== ph) {
      canvas.width = pw;
      canvas.height = ph;
    }
    const ctx = canvas.getContext?.('2d');
    if (!ctx) return;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const night = this.baseStyle === 'night';
    ctx.fillStyle = night ? '#0A0E27' : '#EAF2F8';
    ctx.fillRect(0, 0, w, h);

    const step = this.zoom >= 10 ? 0.5 : this.zoom >= 8 ? 1 : this.zoom >= 6 ? 2 : this.zoom >= 4 ? 5 : 10;
    const [northLat, westLon] = unproject(left, top, z);
    const [southLat, eastLon] = unproject(left + w / k, top + h / k, z);

    ctx.strokeStyle = night ? 'rgba(148, 163, 184, 0.14)' : 'rgba(30, 41, 59, 0.10)';
    ctx.lineWidth = 1;
    ctx.font = '10px "Fira Code", ui-monospace, monospace';
    ctx.fillStyle = night ? 'rgba(148, 163, 184, 0.55)' : 'rgba(71, 85, 105, 0.65)';

    const startLat = Math.floor(Math.max(-80, southLat) / step) * step;
    const endLat = Math.ceil(Math.min(80, northLat) / step) * step;
    for (let lat = startLat; lat <= endLat + 1e-6; lat += step) {
      const [, py] = project(lat, this.center[1], z);
      const sy = (py - top) * k;
      if (sy < 0 || sy > h) continue;
      ctx.beginPath();
      ctx.moveTo(0, sy);
      ctx.lineTo(w, sy);
      ctx.stroke();
      ctx.fillText(`${lat.toFixed(step < 1 ? 1 : 0)}°`, 8, Math.max(12, sy - 3));
    }

    const lonStart = Math.floor(westLon / step) * step;
    const lonSpan = eastLon >= westLon ? eastLon - westLon : 360 - westLon + eastLon;
    for (let offset = 0; offset <= lonSpan + step; offset += step) {
      const lon = ((((lonStart + offset + 180) % 360) + 360) % 360) - 180;
      const [px] = project(this.center[0], lon, z);
      const worldW = TILE_SIZE * 2 ** z * k;
      let sx = (px - left) * k;
      while (sx < 0) sx += worldW;
      while (sx > w) sx -= worldW;
      if (sx < 0 || sx > w) continue;
      ctx.beginPath();
      ctx.moveTo(sx, 0);
      ctx.lineTo(sx, h);
      ctx.stroke();
      ctx.fillText(`${lon.toFixed(step < 1 ? 1 : 0)}°`, Math.min(w - 34, sx + 4), 14);
    }
  }

  positionTileNode(tile, tileZ, tx, ty, w, h) {
    const tk = 2 ** (this.zoom - tileZ);
    const [cxZ, cyZ] = project(this.center[0], this.center[1], tileZ);
    const leftZ = cxZ - w / (2 * tk);
    const topZ = cyZ - h / (2 * tk);
    tile.style.transform = `translate(${(tx * TILE_SIZE - leftZ) * tk}px, ${(ty * TILE_SIZE - topZ) * tk}px) scale(${tk})`;
  }

  drawTileSet({
    tileMap,
    container,
    w,
    h,
    z,
    k,
    left,
    top,
    n,
    keyPrefix,
    plainClass,
    layerName,
    urlFor,
    filterFn,
  }) {
    const seen = new Set();
    let currentAllLoaded = true;

    if (!this.skipTileFetch) {
      const minTx = Math.floor(left / TILE_SIZE);
      const maxTx = Math.floor((left + w / k) / TILE_SIZE);
      const minTy = Math.floor(top / TILE_SIZE);
      const maxTy = Math.floor((top + h / k) / TILE_SIZE);

      for (let ty = minTy; ty <= maxTy; ty++) {
        if (ty < 0 || ty >= n) continue;
        for (let tx = minTx; tx <= maxTx; tx++) {
          const wx = ((tx % n) + n) % n;
          if (filterFn && !filterFn(z, wx, ty)) continue;
          const key = `${keyPrefix}${z}/${wx}/${ty}@${tx}`;
          seen.add(key);
          let tile = tileMap.get(key);
          if (!tile) {
            if (this.plain) {
              tile = this.doc.createElement('div');
              tile.className = plainClass;
              if (layerName) tile.dataset.layer = layerName;
              tile.dataset.tile = `${z}/${wx}/${ty}`;
              tile.dataset.loaded = '1';
            } else {
              tile = this.doc.createElement('img');
              tile.className = 'tile';
              tile.alt = '';
              tile.decoding = 'async';
              if (layerName) tile.dataset.layer = layerName;
              tile.dataset.tile = `${z}/${wx}/${ty}`;
              tile.dataset.loaded = '0';
              tile.addEventListener('load', () => {
                tile.dataset.loaded = '1';
                this.pruneStaleTiles(tileMap, z);
              });
              tile.addEventListener('error', () => {
                tile.dataset.loaded = '1';
                tile.style.visibility = 'hidden';
                this.pruneStaleTiles(tileMap, z);
              });
              tile.src = urlFor(z, wx, ty);
            }
            tile.dataset.z = String(z);
            tile.dataset.tx = String(tx);
            tile.dataset.ty = String(ty);
            tileMap.set(key, tile);
            container.append(tile);
          }
          if (tile.dataset.loaded !== '1') {
            currentAllLoaded = false;
          }
          tile.style.zIndex = '1';
          tile.style.transform = `translate(${(tx * TILE_SIZE - left) * k}px, ${(ty * TILE_SIZE - top) * k}px) scale(${k})`;
        }
      }
    } else {
      currentAllLoaded = false;
    }

    let retainedCount = 0;
    for (const [key, tile] of tileMap) {
      if (seen.has(key)) continue;
      const tileZ = Number(tile.dataset.z);
      const isLoaded = tile.dataset.loaded === '1';
      const canRetain =
        !this.plain &&
        isLoaded &&
        Number.isFinite(tileZ) &&
        (this.skipTileFetch || (!currentAllLoaded && tileZ !== z)) &&
        retainedCount < 36;
      if (canRetain) {
        retainedCount += 1;
        tile.style.zIndex = '0';
        this.positionTileNode(
          tile,
          tileZ,
          Number(tile.dataset.tx),
          Number(tile.dataset.ty),
          w,
          h,
        );
      } else {
        tile.remove();
        tileMap.delete(key);
      }
    }
  }

  pruneStaleTiles(tileMap, activeZ) {
    let anyLoading = false;
    for (const tile of tileMap.values()) {
      if (Number(tile.dataset.z) === activeZ && tile.dataset.loaded !== '1') {
        anyLoading = true;
        break;
      }
    }
    if (anyLoading) return;
    for (const [key, tile] of tileMap) {
      if (Number(tile.dataset.z) !== activeZ) {
        tile.remove();
        tileMap.delete(key);
      }
    }
  }

  drawBaseTiles(w, h, z, k, left, top, n) {
    this.drawTileSet({
      tileMap: this.baseTiles,
      container: this.baseLayer,
      w,
      h,
      z,
      k,
      left,
      top,
      n,
      keyPrefix: '',
      plainClass: 'tile plain',
      layerName: '',
      urlFor: (tz, wx, ty) => this.osmTileUrl(tz, wx, ty),
      filterFn: null,
    });
  }

  drawOverlayTiles(w, h, z, k, left, top, n) {
    for (const [layerName, layerState] of Object.entries(this.layers)) {
      const renderRaster = layerName === 'currents' ? layerState.visible && this.currentsRasterVisible : layerState.visible;
      if (!renderRaster || layerState.opacity <= 0) {
        if (layerState.tiles.size > 0) {
          for (const node of layerState.tiles.values()) node.remove();
          layerState.tiles.clear();
        }
        continue;
      }

      this.drawTileSet({
        tileMap: layerState.tiles,
        container: layerState.container,
        w,
        h,
        z,
        k,
        left,
        top,
        n,
        keyPrefix: `${layerName}:${this.selectedDate}:`,
        plainClass: `tile plain-overlay plain-${layerName}`,
        layerName,
        urlFor: (tz, wx, ty) => this.overlayTileUrl(layerName, tz, wx, ty),
        filterFn: (tz, wx, ty) => intersectsIndonesia(tz, wx, ty),
      });
    }
  }

  currentsGridUrl(minLon, minLat, maxLon, maxLat) {
    const safeDate = encodeURIComponent(this.selectedDate || 'latest');
    const bbox = `${round(minLon, 3)},${round(minLat, 3)},${round(maxLon, 3)},${round(maxLat, 3)}`;
    const path = `/v1/currents/grid?bbox=${encodeURIComponent(bbox)}&date=${safeDate}&max_vectors=289`;
    return this.tileBaseUrl ? `${this.tileBaseUrl}${path}` : path;
  }

  buildCurrentsField(vectors) {
    if (!Array.isArray(vectors) || vectors.length === 0) return null;
    const latSet = new Set();
    const lonSet = new Set();
    for (const v of vectors) {
      if (Number.isFinite(v.lat) && Number.isFinite(v.lon)) {
        latSet.add(v.lat);
        lonSet.add(v.lon);
      }
    }
    const lats = [...latSet].sort((a, b) => a - b);
    const lons = [...lonSet].sort((a, b) => a - b);
    const rows = lats.length;
    const cols = lons.length;
    if (rows < 2 || cols < 2) return null;

    const latIdx = new Map(lats.map((val, idx) => [val, idx]));
    const lonIdx = new Map(lons.map((val, idx) => [val, idx]));
    const uGrid = new Float32Array(rows * cols).fill(NaN);
    const vGrid = new Float32Array(rows * cols).fill(NaN);
    const oceanCells = [];

    for (const vec of vectors) {
      const r = latIdx.get(vec.lat);
      const c = lonIdx.get(vec.lon);
      if (r === undefined || c === undefined) continue;
      let u = Number(vec.u_ms);
      let v = Number(vec.v_ms);
      if (!Number.isFinite(u) || !Number.isFinite(v)) {
        const spd = Number(vec.speed_ms) || 0;
        const rad = ((Number(vec.direction_deg) || 0) * Math.PI) / 180;
        u = Math.sin(rad) * spd;
        v = Math.cos(rad) * spd;
      }
      const idx = r * cols + c;
      uGrid[idx] = u;
      vGrid[idx] = v;
      if (Math.hypot(u, v) >= 0.01) {
        oceanCells.push({ lat: vec.lat, lon: vec.lon, u, v });
      }
    }
    if (oceanCells.length === 0) return null;

    const dLat = (lats[rows - 1] - lats[0]) / Math.max(1, rows - 1);
    const dLon = (lons[cols - 1] - lons[0]) / Math.max(1, cols - 1);
    return {
      lats,
      lons,
      rows,
      cols,
      uGrid,
      vGrid,
      oceanCells,
      minLat: lats[0],
      maxLat: lats[rows - 1],
      minLon: lons[0],
      maxLon: lons[cols - 1],
      dLat,
      dLon,
    };
  }

  sampleCurrentVelocity(lat, lon) {
    const f = this.currentsField;
    if (!f) return null;
    if (lat < f.minLat || lat > f.maxLat || lon < f.minLon || lon > f.maxLon) return null;

    let r0 = 0;
    while (r0 + 1 < f.rows - 1 && f.lats[r0 + 1] < lat) r0++;
    let c0 = 0;
    while (c0 + 1 < f.cols - 1 && f.lons[c0 + 1] < lon) c0++;
    const r1 = Math.min(f.rows - 1, r0 + 1);
    const c1 = Math.min(f.cols - 1, c0 + 1);

    const ty = f.lats[r1] > f.lats[r0] ? clamp((lat - f.lats[r0]) / (f.lats[r1] - f.lats[r0]), 0, 1) : 0;
    const tx = f.lons[c1] > f.lons[c0] ? clamp((lon - f.lons[c0]) / (f.lons[c1] - f.lons[c0]), 0, 1) : 0;

    const corners = [
      { idx: r0 * f.cols + c0, w: (1 - tx) * (1 - ty) },
      { idx: r0 * f.cols + c1, w: tx * (1 - ty) },
      { idx: r1 * f.cols + c0, w: (1 - tx) * ty },
      { idx: r1 * f.cols + c1, w: tx * ty },
    ];

    let wSum = 0;
    let uSum = 0;
    let vSum = 0;
    let validCount = 0;
    for (const corner of corners) {
      const cu = f.uGrid[corner.idx];
      const cv = f.vGrid[corner.idx];
      if (Number.isFinite(cu) && Number.isFinite(cv)) {
        validCount++;
        wSum += corner.w;
        uSum += cu * corner.w;
        vSum += cv * corner.w;
      }
    }

    if (validCount < 3 || wSum <= 0.35) return null;
    const u = uSum / wSum;
    const v = vSum / wSum;
    const speedMs = Math.hypot(u, v);
    if (speedMs < 0.01) return null;
    return { u, v, speedMs, speedKnots: speedMs * 1.94384 };
  }

  seedStreamParticle(particle, randomAge = false, preferredIdx = -1) {
    const f = this.currentsField;
    if (!f || f.oceanCells.length === 0) return false;
    let lat = 0;
    let lon = 0;
    let found = false;
    const nCells = f.oceanCells.length;
    const baseCell = preferredIdx >= 0
      ? f.oceanCells[preferredIdx % nCells]
      : f.oceanCells[Math.floor(Math.random() * nCells)];

    for (let attempt = 0; attempt < 6; attempt++) {
      const cell = attempt === 0 ? baseCell : f.oceanCells[Math.floor(Math.random() * nCells)];
      const candLat = cell.lat + (Math.random() - 0.5) * f.dLat * 0.82;
      const candLon = cell.lon + (Math.random() - 0.5) * f.dLon * 0.82;
      if (this.sampleCurrentVelocity(candLat, candLon)) {
        lat = candLat;
        lon = candLon;
        found = true;
        break;
      }
    }
    if (!found) {
      lat = baseCell.lat;
      lon = baseCell.lon;
    }

    const trailLen = particle.trailLat.length;
    particle.lat = lat;
    particle.lon = lon;
    particle.maxAge = 2.8 + Math.random() * 2.4;
    particle.age = randomAge ? Math.random() * particle.maxAge * 0.65 : 0;
    particle.trailCount = 1;
    particle.trailHead = 0;
    for (let i = 0; i < trailLen; i++) {
      particle.trailLat[i] = lat;
      particle.trailLon[i] = lon;
    }
    const sample = this.sampleCurrentVelocity(lat, lon);
    particle.speedKnots = sample ? sample.speedKnots : 0.4;
    return true;
  }

  initStreamParticles(w) {
    const f = this.currentsField;
    if (!f) {
      this.currentsParticles = [];
      return;
    }
    const nCells = f.oceanCells.length;
    const count = clamp(Math.round(nCells * 1.45), w < 640 ? 110 : 190, w < 640 ? 160 : 260);
    const trailLen = 44;
    const particles = [];
    for (let i = 0; i < count; i++) {
      const p = {
        lat: 0,
        lon: 0,
        age: 0,
        maxAge: 3.6,
        speedKnots: 0.4,
        trailLat: new Float64Array(trailLen),
        trailLon: new Float64Array(trailLen),
        trailCount: 0,
        trailHead: 0,
      };
      this.seedStreamParticle(p, true, i);
      const warmup = 12 + (i % 30);
      for (let s = 0; s < warmup; s++) {
        this.stepSingleParticle(p, 0.032, false);
      }
      particles.push(p);
    }
    this.currentsParticles = particles;
  }

  stepSingleParticle(p, dt, wrapAge = true) {
    p.age += dt;
    if (wrapAge && p.age >= p.maxAge) {
      this.seedStreamParticle(p, false);
      return;
    }
    const v1 = this.sampleCurrentVelocity(p.lat, p.lon);
    if (!v1) {
      if (wrapAge) this.seedStreamParticle(p, false);
      return;
    }
    const pxPerDeg = (TILE_SIZE * 2 ** this.zoom) / 360.0;
    const degScale = 86.0 / Math.max(8.0, pxPerDeg);
    const cosLat1 = Math.max(0.35, Math.cos((p.lat * Math.PI) / 180));
    const midLat = p.lat + v1.v * degScale * dt * 0.5;
    const midLon = p.lon + (v1.u / cosLat1) * degScale * dt * 0.5;
    const v2 = this.sampleCurrentVelocity(midLat, midLon) || v1;
    const cosLat2 = Math.max(0.35, Math.cos((midLat * Math.PI) / 180));
    const nextLat = p.lat + v2.v * degScale * dt;
    const nextLon = p.lon + (v2.u / cosLat2) * degScale * dt;

    if (!this.sampleCurrentVelocity(nextLat, nextLon)) {
      if (wrapAge) this.seedStreamParticle(p, false);
      return;
    }

    p.lat = nextLat;
    p.lon = nextLon;
    p.speedKnots = v2.speedKnots;
    const maxLen = p.trailLat.length;
    p.trailHead = (p.trailHead + 1) % maxLen;
    p.trailLat[p.trailHead] = nextLat;
    p.trailLon[p.trailHead] = nextLon;
    if (p.trailCount < maxLen) p.trailCount++;
  }

  advanceCurrentsParticles(dt) {
    if (!this.currentsField || this.currentsParticles.length === 0) return;
    for (const p of this.currentsParticles) {
      this.stepSingleParticle(p, dt, true);
    }
  }

  drawCurrentsVectors(w, h, z, k, left, top, n) {
    const curState = this.layers.currents;
    const canvas = this.currentsCanvas;
    if (!curState.visible || curState.opacity <= 0) {
      const ctx = canvas.getContext?.('2d');
      if (ctx && canvas.width > 0 && canvas.height > 0) {
        ctx.clearRect(0, 0, canvas.width, canvas.height);
      }
      return;
    }

    const cam = this.cameraBbox();
    const minLon = Math.max(INDONESIA_BOUNDS.minLon, cam.minLon);
    const maxLon = Math.min(INDONESIA_BOUNDS.maxLon, cam.maxLon);
    const minLat = Math.max(INDONESIA_BOUNDS.minLat, cam.minLat);
    const maxLat = Math.min(INDONESIA_BOUNDS.maxLat, cam.maxLat);

    if (minLon >= maxLon || minLat >= maxLat) {
      this.currentsVectors = [];
      this.currentsField = null;
      this.currentsParticles = [];
      this.renderCurrentsStreamlines(w, h, z, k, left, top, n);
      return;
    }

    if (this.plain) {
      if (!this.currentsField) {
        const synthetic = [];
        for (let lat = Math.ceil(minLat); lat <= maxLat; lat += 2) {
          for (let lon = Math.ceil(minLon); lon <= maxLon; lon += 2) {
            const speed = 0.45 + 0.35 * Math.abs(Math.sin(lat * 0.35 + lon * 0.15));
            const dir = ((lat * 19 + lon * 13) % 360 + 360) % 360;
            const rad = (dir * Math.PI) / 180;
            synthetic.push({
              lat,
              lon,
              u_ms: Math.sin(rad) * speed,
              v_ms: Math.cos(rad) * speed,
              speed_ms: speed,
              speed_knots: speed * 1.94384,
              direction_deg: dir,
            });
          }
        }
        this.currentsVectors = synthetic;
        this.currentsField = this.buildCurrentsField(synthetic);
        this.initStreamParticles(w);
      }
      this.renderCurrentsStreamlines(w, h, z, k, left, top, n);
      return;
    }

    const fetchKey = `${this.selectedDate}:${this.tileBaseUrl}:${round(minLon, 1)},${round(minLat, 1)},${round(maxLon, 1)},${round(maxLat, 1)},z${Math.round(this.zoom)}`;
    if (fetchKey !== this.currentsFetchKey && typeof fetch === 'function' && !this.skipTileFetch) {
      this.currentsFetchKey = fetchKey;
      clearTimeout(this.currentsFetchTimer);
      const delay = this.currentsVectors.length === 0 ? 0 : 140;
      this.currentsFetchTimer = setTimeout(async () => {
        this.currentsAbort?.abort?.();
        const ctrl = typeof AbortController === 'function' ? new AbortController() : null;
        this.currentsAbort = ctrl;
        try {
          const resp = await fetch(this.currentsGridUrl(minLon, minLat, maxLon, maxLat), ctrl ? { signal: ctrl.signal } : undefined);
          if (!resp.ok) return;
          const data = await resp.json();
          if (this.currentsFetchKey !== fetchKey || !Array.isArray(data?.vectors)) return;
          this.currentsVectors = data.vectors;
          this.currentsField = this.buildCurrentsField(data.vectors);
          const { w: cw, h: ch } = this.size;
          this.initStreamParticles(cw || w);
          if (cw && ch) {
            const cz = Math.min(this.maxZoom, Math.max(0, Math.round(this.zoom)));
            const ck = 2 ** (this.zoom - cz);
            const [cx, cy] = project(this.center[0], this.center[1], cz);
            this.renderCurrentsStreamlines(cw, ch, cz, ck, cx - cw / 2 / ck, cy - ch / 2 / ck, 2 ** cz);
          }
        } catch {
          // Ignore aborted/transient network errors during rapid pan/zoom
        }
      }, delay);
    }

    this.renderCurrentsStreamlines(w, h, z, k, left, top, n);
  }

  renderCurrentsStreamlines(w, h, z, k, left, top, n) {
    const canvas = this.currentsCanvas;
    const dpr = typeof window !== 'undefined' && window.devicePixelRatio ? Math.min(window.devicePixelRatio, 2) : 1;
    const pw = Math.max(1, Math.round(w * dpr));
    const ph = Math.max(1, Math.round(h * dpr));
    if (canvas.width !== pw || canvas.height !== ph) {
      canvas.width = pw;
      canvas.height = ph;
    }
    const ctx = canvas.getContext?.('2d');
    if (!ctx) return;

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);
    if (!this.layers.currents.visible || this.currentsParticles.length === 0) return;

    const night = this.baseStyle === 'night';
    const rgbTiers = night
      ? [
          [125, 211, 252], // cyan glow
          [94, 234, 212],  // emerald teal
          [252, 211, 77],  // warm gold
        ]
      : [
          [2, 132, 199],   // clear ocean blue
          [13, 148, 136],  // emerald teal
          [217, 119, 6],   // warm amber
        ];

    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';

    for (const p of this.currentsParticles) {
      const cnt = p.trailCount;
      if (cnt < 4) continue;
      const life = clamp(Math.sin((p.age / p.maxAge) * Math.PI), 0, 1);
      if (life < 0.14) continue;

      const maxLen = p.trailLat.length;
      const startIdx = (p.trailHead - cnt + 1 + maxLen) % maxLen;
      const pts = [];
      let clipped = false;
      for (let i = 0; i < cnt; i++) {
        const idx = (startIdx + i) % maxLen;
        const [sx, sy] = this.projectPointToViewport(p.trailLat[idx], p.trailLon[idx], z, k, left, top, n);
        if (i > 0 && Math.hypot(sx - pts[pts.length - 1][0], sy - pts[pts.length - 1][1]) > 85) {
          clipped = true;
          break;
        }
        pts.push([sx, sy]);
      }
      if (clipped || pts.length < 4) continue;

      const tailPt = pts[0];
      const headPt = pts[pts.length - 1];
      if (headPt[0] < -60 || headPt[0] > w + 60 || headPt[1] < -60 || headPt[1] > h + 60) continue;

      const totalLen = Math.hypot(headPt[0] - tailPt[0], headPt[1] - tailPt[1]);
      if (totalLen < 14) continue;

      const tier = p.speedKnots >= 1.2 ? 2 : p.speedKnots >= 0.5 ? 1 : 0;
      const [r, g, b] = rgbTiers[tier];
      const peakAlpha = clamp(life * (night ? 0.9 : 0.84), 0.12, 0.92);

      const grad = ctx.createLinearGradient(tailPt[0], tailPt[1], headPt[0], headPt[1]);
      grad.addColorStop(0, `rgba(${r}, ${g}, ${b}, 0)`);
      grad.addColorStop(0.35, `rgba(${r}, ${g}, ${b}, ${(peakAlpha * 0.35).toFixed(3)})`);
      grad.addColorStop(0.82, `rgba(${r}, ${g}, ${b}, ${(peakAlpha * 0.85).toFixed(3)})`);
      grad.addColorStop(1, night ? `rgba(255, 255, 255, ${peakAlpha.toFixed(3)})` : `rgba(${r}, ${g}, ${b}, ${peakAlpha.toFixed(3)})`);

      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length - 1; i++) {
        const mx = (pts[i][0] + pts[i + 1][0]) * 0.5;
        const my = (pts[i][1] + pts[i + 1][1]) * 0.5;
        ctx.quadraticCurveTo(pts[i][0], pts[i][1], mx, my);
      }
      ctx.lineTo(headPt[0], headPt[1]);
      ctx.strokeStyle = grad;
      ctx.lineWidth = tier === 2 ? 2.1 : 1.65;
      ctx.stroke();
    }
  }

  projectPointToViewport(lat, lon, z, k, left, top, n) {
    const worldPx = TILE_SIZE * n;
    const [wx, wy] = project(lat, lon, z);
    const centerPx = left + this.size.w / (2 * k);
    let adjustedX = wx;
    if (adjustedX - centerPx > worldPx / 2) adjustedX -= worldPx;
    else if (centerPx - adjustedX > worldPx / 2) adjustedX += worldPx;
    return [(adjustedX - left) * k, (wy - top) * k];
  }

  drawWppGeoJson(w, h, z, k, left, top, n) {
    const svg = this.wppSvg;
    svg.setAttribute('viewBox', `0 0 ${w} ${h}`);
    const pathNodes = [];
    const chipNodes = [];

    const oldParts = this.parts ?? new Map();
    const nextParts = new Map();
    for (const [id, el] of oldParts) {
      if (!id.startsWith('wpp:')) nextParts.set(id, el);
    }

    const ringToPath = (ring) => {
      if (!Array.isArray(ring) || ring.length < 3) return '';
      let d = '';
      for (let i = 0; i < ring.length; i++) {
        const pt = ring[i];
        if (!Array.isArray(pt) || pt.length < 2) continue;
        const [sx, sy] = this.projectPointToViewport(Number(pt[1]), Number(pt[0]), z, k, left, top, n);
        d += `${i === 0 ? 'M' : 'L'}${round(sx, 1)},${round(sy, 1)}`;
      }
      return d ? `${d}Z` : '';
    };

    const chipCoords = [];
    for (const feature of this.wppFeatures) {
      let d = '';
      if (feature.geometry.type === 'Polygon') {
        for (const ring of feature.geometry.coordinates) {
          d += ringToPath(ring);
        }
      } else if (feature.geometry.type === 'MultiPolygon') {
        for (const poly of feature.geometry.coordinates) {
          for (const ring of poly) {
            d += ringToPath(ring);
          }
        }
      }
      if (!d) continue;

      const selected = feature.code !== '' && feature.code === this.selectedWppCode;
      const path = this.doc.createElementNS('http://www.w3.org/2000/svg', 'path');
      path.setAttribute('d', d);
      path.setAttribute('fill-rule', 'evenodd');
      path.setAttribute('class', selected ? 'wpp-path selected' : 'wpp-path');
      if (feature.code) path.dataset.wpp = feature.code;
      pathNodes.push(path);

      if (feature.code) {
        const [cx, cy] = this.projectPointToViewport(feature.centroidLat, feature.centroidLon, z, k, left, top, n);
        if (cx >= -60 && cx <= w + 60 && cy >= -40 && cy <= h + 40) {
          chipCoords.push([cx, cy]);
          const partId = `wpp:${feature.code}`;
          let btn = oldParts.get(partId);
          if (!btn) {
            btn = this.doc.createElement('button');
            btn.type = 'button';
            btn.className = 'wpp-chip';
            btn.dataset.wpp = feature.code;
            btn.dataset.testid = `wpp-chip-${feature.code}`;
            const pill = this.doc.createElement('span');
            pill.className = 'wpp-chip-pill';
            pill.textContent = `WPP ${feature.code}`;
            btn.append(pill);
          }
          btn.setAttribute(
            'aria-label',
            `Select ${feature.name}${feature.watersId ? ` (${feature.watersId})` : ''}`,
          );
          btn.setAttribute('aria-pressed', String(selected));
          btn.style.left = `${round(cx, 1)}px`;
          btn.style.top = `${round(cy, 1)}px`;
          nextParts.set(partId, btn);
          chipNodes.push(btn);
        }
      }
    }

    this._renderedWppScreenPts = chipCoords;
    this.parts = nextParts;
    svg.replaceChildren(...pathNodes);
    this.wppLabelsLayer.replaceChildren(...chipNodes);
  }

  drawMarkers(w, h, z, k, left, top, n) {
    const oldParts = this.parts ?? new Map();
    const nextParts = new Map();
    for (const [id, el] of oldParts) {
      if (id.startsWith('wpp:')) nextParts.set(id, el);
    }

    if (!this.showSpeciesPins) {
      this.parts = nextParts;
      this.markersLayer.replaceChildren();
      return;
    }

    const wppPts = this._renderedWppScreenPts ?? [];
    const placedPts = [];
    const offsets = [
      [0, 0],
      [0, -30],
      [0, 30],
      [78, 0],
      [-78, 0],
      [60, -28],
      [-60, -28],
      [60, 28],
      [-60, 28],
    ];
    const rendered = [];
    for (const marker of this.markers) {
      if (rendered.length >= MAX_RENDERED_MARKERS) break;
      const [baseX, baseY] = this.projectPointToViewport(marker.lat, marker.lon, z, k, left, top, n);
      if (baseX < -44 || baseX > w + 44 || baseY < -44 || baseY > h + 44) continue;

      let sx = baseX;
      let sy = baseY;
      for (const [ox, oy] of offsets) {
        const cx = baseX + ox;
        const cy = baseY + oy;
        if (cx < 24 || cx > w - 24 || cy < 20 || cy > h - 20) continue;
        const hitsWpp = wppPts.some(([wx, wy]) => Math.abs(cx - wx) < 60 && Math.abs(cy - wy) < 24);
        const hitsPin = placedPts.some(([px, py]) => Math.abs(cx - px) < 74 && Math.abs(cy - py) < 26);
        if (!hitsWpp && !hitsPin) {
          sx = cx;
          sy = cy;
          break;
        }
      }
      placedPts.push([sx, sy]);

      let btn = oldParts.get(marker.id);
      const selected = marker.id === this.selectedMarkerId;
      if (!btn) {
        btn = this.doc.createElement('button');
        btn.type = 'button';
        btn.className = 'species-marker';
        btn.dataset.marker = marker.id;
        btn.dataset.testid = `species-marker-${marker.id}`;
      }
      btn.setAttribute('aria-label', `${marker.shortName} - ${marker.label}${marker.wppCode ? ` (WPP ${marker.wppCode})` : ''}`);
      btn.setAttribute('aria-pressed', String(selected));
      btn.style.left = `${round(sx, 1)}px`;
      btn.style.top = `${round(sy, 1)}px`;

      const dotColor = selected
        ? '#F97316'
        : marker.depthM !== null && marker.depthM >= 80
          ? '#1D4ED8'
          : marker.depthM !== null && marker.depthM >= 40
            ? '#0D9488'
            : '#0284C7';
      const drawnState = `${selected ? '1' : '0'}:${dotColor}:${marker.shortName}`;
      if (btn.dataset.drawn !== drawnState) {
        btn.dataset.drawn = drawnState;
        const pill = this.doc.createElement('span');
        pill.className = 'species-marker-pill';
        const dot = this.doc.createElement('span');
        dot.className = 'species-marker-dot';
        dot.style.background = selected ? '#FFFFFF' : dotColor;
        if (selected) dot.style.color = '#F97316';
        dot.innerHTML = buildSpeciesSvg();
        const nameEl = this.doc.createElement('span');
        nameEl.className = 'species-marker-name';
        nameEl.textContent = marker.shortName || 'Ikan';
        pill.append(dot, nameEl);
        btn.replaceChildren(pill);
      }
      nextParts.set(marker.id, btn);
      rendered.push(btn);
    }

    this.parts = nextParts;
    this.markersLayer.replaceChildren(...rendered);
  }

  drawPin(zArg, kArg, leftArg, topArg) {
    if (!this.inspectedPoint || !this.size.w || !this.size.h) {
      this.pinLayer.replaceChildren();
      return;
    }
    const z = zArg ?? Math.min(this.maxZoom, Math.max(0, Math.round(this.zoom)));
    const k = kArg ?? 2 ** (this.zoom - z);
    const [cx, cy] = project(this.center[0], this.center[1], z);
    const left = leftArg ?? cx - this.size.w / 2 / k;
    const top = topArg ?? cy - this.size.h / 2 / k;
    const n = 2 ** z;
    const [sx, sy] = this.projectPointToViewport(
      this.inspectedPoint.lat,
      this.inspectedPoint.lon,
      z,
      k,
      left,
      top,
      n,
    );
    let pin = this.pinLayer.firstElementChild;
    if (!pin) {
      pin = this.doc.createElement('div');
      pin.className = 'inspect-pin';
      pin.dataset.testid = 'marine-map-inspect-pin';
      pin.innerHTML = buildInspectPinSvg();
      this.pinLayer.append(pin);
    }
    pin.style.left = `${round(sx, 1)}px`;
    pin.style.top = `${round(sy, 1)}px`;
  }

  /** Lookup helper for Exact test driver (`tap <view>/<partId>`). */
  part(id) {
    if (id === 'zoom-in') return this.zoomInBtn.isConnected ? this.zoomInBtn : null;
    if (id === 'zoom-out') return this.zoomOutBtn.isConnected ? this.zoomOutBtn : null;
    const el = this.parts?.get(id);
    return el?.isConnected ? el : null;
  }

  partIds() {
    return ['zoom-in', 'zoom-out', ...(this.parts?.keys() ?? [])];
  }

  listen() {
    const m = this.map;
    this.zoomInBtn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      this.zoomBy(1);
    });
    this.zoomOutBtn.addEventListener('click', (ev) => {
      ev.stopPropagation();
      this.zoomBy(-1);
    });

    const pointers = new Map();
    let pressedChild = null;
    let totalMove = 0;

    m.addEventListener('pointerdown', (ev) => {
      if (ev.button !== 0 && ev.pointerType === 'mouse') return;
      if (ev.target.closest?.('.zoom-controls')) return;

      const wppBtn = ev.target.closest?.('.wpp-chip');
      if (wppBtn) {
        pressedChild = { type: 'wpp', id: wppBtn.dataset.wpp };
        return;
      }
      const markerBtn = ev.target.closest?.('.species-marker');
      if (markerBtn) {
        pressedChild = { type: 'marker', id: markerBtn.dataset.marker };
        return;
      }

      pressedChild = null;
      pointers.set(ev.pointerId, { x: ev.clientX, y: ev.clientY });
      totalMove = 0;
      try {
        m.setPointerCapture(ev.pointerId);
      } catch {
        // Synthetic pointer events in headless tests may not support capture.
      }
      m.classList.add('dragging');
    });

    m.addEventListener('pointermove', (ev) => {
      const p = pointers.get(ev.pointerId);
      if (!p) return;

      if (pointers.size === 2) {
        const [a, b] = [...pointers.values()];
        const before = Math.hypot(a.x - b.x, a.y - b.y);
        p.x = ev.clientX;
        p.y = ev.clientY;
        const [c, d] = [...pointers.values()];
        const after = Math.hypot(c.x - d.x, c.y - d.y);
        if (before > 0 && after > 0) {
          this.zoom = this.clampZoom(this.zoom + Math.log2(after / before));
          this.syncLayerStyles();
          this.draw();
        }
        totalMove = DRAG_THRESHOLD_PX + 1;
        return;
      }

      const dx = ev.clientX - p.x;
      const dy = ev.clientY - p.y;
      p.x = ev.clientX;
      p.y = ev.clientY;
      totalMove += Math.hypot(dx, dy);
      if (totalMove > DRAG_THRESHOLD_PX && (dx || dy)) {
        this.panBy(-dx, -dy);
      }
    });

    const finishPointer = (ev) => {
      if (pressedChild) {
        if (ev.type === 'pointerup') {
          if (pressedChild.type === 'wpp') {
            const wppBtn = ev.target.closest?.('.wpp-chip');
            if (wppBtn?.dataset.wpp === pressedChild.id) {
              const nextCode = this.selectedWppCode === pressedChild.id ? '' : pressedChild.id;
              this.selectedWppCode = nextCode;
              this.draw();
              this.reportState();
              this.emitChange(nextCode);
            }
          } else if (pressedChild.type === 'marker') {
            const markerBtn = ev.target.closest?.('.species-marker');
            if (markerBtn?.dataset.marker === pressedChild.id) {
              const markerObj = this.markers.find((item) => item.id === pressedChild.id);
              this.selectedMarkerId = pressedChild.id;
              this.draw();
              this.reportState();
              this.emitChange(pressedChild.id);
              if (markerObj) {
                this.emitPointClick(markerObj.lat, markerObj.lon, markerObj.id);
              }
            }
          }
        }
        pressedChild = null;
        return;
      }

      if (!pointers.delete(ev.pointerId)) return;
      if (pointers.size === 0) {
        m.classList.remove('dragging');
        if (totalMove > DRAG_THRESHOLD_PX) {
          this.rest();
        } else if (ev.type === 'pointerup') {
          const rect = m.getBoundingClientRect();
          const dx = ev.clientX - rect.left - rect.width / 2;
          const dy = ev.clientY - rect.top - rect.height / 2;
          const [cx, cy] = project(this.center[0], this.center[1], this.zoom);
          const [lat, lon] = unproject(cx + dx, cy + dy, this.zoom);
          this.emitPointClick(lat, lon);
        }
      }
    };

    m.addEventListener('pointerup', finishPointer);
    m.addEventListener('pointercancel', finishPointer);

    m.addEventListener(
      'wheel',
      (ev) => {
        ev.preventDefault();
        const rect = m.getBoundingClientRect();
        const px = ev.clientX - rect.left - rect.width / 2;
        const py = ev.clientY - rect.top - rect.height / 2;
        this.zoomBy(-ev.deltaY * (ev.ctrlKey ? 0.01 : 0.002), px, py, true);
      },
      { passive: false },
    );

    m.addEventListener('keydown', (ev) => {
      if (ev.target !== m) return;
      const step = 80;
      const panKeys = {
        ArrowLeft: [-step, 0],
        ArrowRight: [step, 0],
        ArrowUp: [0, -step],
        ArrowDown: [0, step],
      };
      if (panKeys[ev.key]) {
        ev.preventDefault();
        this.panBy(...panKeys[ev.key]);
        this.rest();
      } else if (ev.key === '+' || ev.key === '=') {
        ev.preventDefault();
        this.zoomBy(1);
      } else if (ev.key === '-' || ev.key === '_') {
        ev.preventDefault();
        this.zoomBy(-1);
      } else if (ev.key === 'Enter' || ev.key === ' ') {
        ev.preventDefault();
        this.emitPointClick(this.center[0], this.center[1]);
      }
    });
  }

  destroy() {
    clearTimeout(this.resting);
    clearTimeout(this.tileFetchTimer);
    clearTimeout(this.currentsFetchTimer);
    if (this.currentsRaf !== null) {
      cancelAnimationFrame(this.currentsRaf);
      this.currentsRaf = null;
    }
    this.currentsAbort?.abort?.();
    this.resize?.disconnect?.();
    this.implementation?.gone?.(this.view);
    this.map.remove();
  }
}

export const abi = 1;
export const roster = { 'marine-map': { view: MarineMap, snapshot: false } };

/**
 * Exact extension implementation factory tracking active map instances and
 * enabling deterministic `plain()` tiles during automated test runs.
 */
export function implementation({ agent, config } = {}) {
  const maps = new Map();
  let live = false;
  return {
    config: config ?? {},
    plain: () => !!agent && !live,
    preferred(values) {
      live =
        values?.['marine-map.tiles'] === 'live' ||
        values?.['maps.tiles'] === 'live' ||
        values?.tiles === 'live';
    },
    made(view, map) {
      maps.set(String(view), { map });
    },
    gone(view) {
      maps.delete(String(view));
    },
    propsOf(view, snapshot) {
      const entry = maps.get(String(view));
      if (entry) Object.assign(entry, snapshot);
    },
    state() {
      return {
        maps: [...maps].map(([view, m]) => ({
          view,
          camera: m.camera ?? null,
          baseStyle: m.baseStyle ?? 'daylight',
          layers: m.layers ?? {},
          selectedDate: m.selectedDate ?? 'latest',
          selectedWppCode: m.selectedWppCode ?? '',
          selectedMarkerId: m.selectedMarkerId ?? '',
          markers: m.markers ?? [],
          wppZones: m.wppZones ?? [],
          inspectedPoint: m.inspectedPoint ?? null,
          tiles: m.map?.plain ? 'plain' : 'live',
        })),
      };
    },
  };
}

/**
 * Expo Exact module-table ABI v1 adapters (`create`, `setProps`, `destroy`)
 * for host setups loading `./web/index.js` as a standalone native module table.
 */
export function create(tag, element, propsJson, event) {
  if (tag !== 'marine-map') {
    throw new Error(`Unknown marine-map view tag: ${tag}`);
  }
  const props = typeof propsJson === 'string' ? JSON.parse(propsJson || '{}') : propsJson ?? {};
  const events = {
    press: (payload) => event?.(0, payload),
    change: (payload) => event?.(1, payload),
    hover: (payload) => event?.(2, payload),
    focus: (payload) => event?.(3, payload),
    blur: (payload) => event?.(4, payload),
    key: (payload) => event?.(5, payload),
    submit: (payload) => event?.(6, payload),
    load: (payload) => event?.(7, payload),
    message: (payload) => event?.(8, payload),
    emit: (name, ...args) => event?.(8, JSON.stringify({ 'exact:event': String(name), args })),
  };
  return new MarineMap({ element, props, events, view: element?.id ?? '0' });
}

export function setProps(handle, propsJson) {
  const next = typeof propsJson === 'string' ? JSON.parse(propsJson || '{}') : propsJson ?? {};
  handle?.setProps?.(next);
}

export function destroy(handle) {
  handle?.destroy?.();
}
