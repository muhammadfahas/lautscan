# `@lautscan/marine-map`

Custom Expo Exact Native Module providing the `<marine-map>` interactive geospatial component for **LAUT SCAN**.

## Why a Custom Native Module?

Expo Exact's built-in `@exact/maps` (`exact-map`) supports a single XYZ base tile layer, simple pin markers, `change` (marker click), and `moveend`. LAUT SCAN additionally requires:
1. Multi-layer oceanographic XYZ raster overlays (`sst`, `chlorophyll`, `currents`) with independent visibility toggles and CSS opacity.
2. Interactive **WPP-NRI (571-718)** GeoJSON polygon outlines and zone selection chips.
3. Free-coordinate ocean **Point Inspection** (`pointclick(lat, lon)`) emitting `message` events for `GET /v1/map/point`.
4. **Daylight Maritime** (`#F8FAFC`) and **Night Maritime** (`#0A0E27`) bridge-friendly theming with WCAG `>= 44x44px` touch targets and deterministic `implementation.plain()` offline test mode.

## Module Structure

- `package.json`: Package metadata and Exact/JS subpath exports (`.`, `./web`, `./contract`).
- `exact.json`: Exact interface manifest (`kind: "interface"`, view tag `marine-map`, 15 typed props, 3 declared events, web tile config defaults).
- `web/index.js`: Self-contained Web Mercator (`EPSG:3857`) HTML/Canvas2D/SVG renderer implementing both Exact package-view (`roster`, `implementation`) and module-table ABI v1 (`abi`, `create`, `setProps`, `destroy`) entry points. Zero external CDN dependencies.
- `contract.ts`: Strict TypeScript interfaces and JSON builders/parsers for props, GeoJSON normalization, species markers, and events.

## `<marine-map>` Props (`exact.json`)

| Prop | Exact Type | Default | Description |
|---|---|---|---|
| `centerLat` | `number` | `-2.5` | Camera center latitude (`EPSG:4326`) |
| `centerLon` | `number` | `118.0` | Camera center longitude (`EPSG:4326`) |
| `zoom` | `number` | `5` | Web Mercator zoom (`2`-`14`) |
| `baseStyle` | `string` | `"daylight"` | `"daylight"` (`#F8FAFC`) or `"night"` (`#0A0E27`) |
| `sstVisible` | `bool` | `false` | Toggle SST (`plasma`) XYZ overlay |
| `sstOpacity` | `number` | `0.72` | SST layer opacity (`0.0`-`1.0`) |
| `chlorophyllVisible` | `bool` | `false` | Toggle Chlorophyll-a (`viridis`) XYZ overlay |
| `chlorophyllOpacity` | `number` | `0.65` | Chlorophyll-a layer opacity (`0.0`-`1.0`) |
| `currentsVisible` | `bool` | `false` | Toggle Ocean Currents (`cividis`) XYZ overlay |
| `currentsOpacity` | `number` | `0.65` | Currents layer opacity (`0.0`-`1.0`) |
| `selectedDate` | `string` | `"latest"` | Target UTC date (`YYYY-MM-DD` or `"latest"`) |
| `tileBaseUrl` | `string` | `""` | FastAPI base URL (e.g. `http://127.0.0.1:8080`) |
| `wppGeoJsonCollection` | `string` | `""` | Serialized GeoJSON FeatureCollection or `WppZoneRecord[]` |
| `selectedWppCode` | `string` | `""` | Active WPP-NRI code (`571`-`718` or `""`) |
| `speciesMarkers` | `string` | `"[]"` | Serialized `SpeciesOccurrenceRecord[]` or `MapMarker[]` |

## `<marine-map>` Events

- **`change`** (`string`): Emits selected WPP-NRI code (e.g. `"712"`), species marker ID, or `""` when deselected.
- **`moveend`** (`string` JSON): Emits `{"minLon", "minLat", "maxLon", "maxLat", "centerLat", "centerLon", "latitude", "longitude", "zoom"}` after pan/zoom/prop movement settles (`250ms`).
- **`message`** (`string` JSON): Emits `{"type":"pointclick","lat":<number>,"lon":<number>}` when the user taps/clicks ocean coordinates or presses `Enter`/`Space` on the focused map.

## Phase 2 Native Hosts

Apple hosts (iOS / macOS) will implement `apple/exact.json` + Swift `MKMapView` (`MKTileOverlay`, `MKPolygon`, `MKPointAnnotation`) matching this identical Contract prop/event surface.
