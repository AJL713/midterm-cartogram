// Project the Census district file (longitude/latitude) into the same
// 975 x 610 Albers USA frame as the state and county maps from us-atlas,
// which were made with d3.geoAlbersUsa().scale(1300).translate([487.5, 305]).
// Alaska and Hawaii are moved to their insets by the same projection.
//
// Run (needs Node and the d3-geo package; `npm install d3-geo@3`):
//   node scripts/project_districts.mjs data/source/districts_2026.geojson data/source/districts_albers.json
import { readFileSync, writeFileSync } from "node:fs";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { geoAlbersUsa } = require(process.env.D3_GEO || "d3-geo");

const [, , src, out] = process.argv;
const fc = JSON.parse(readFileSync(src, "utf8"));
const project = geoAlbersUsa().scale(1300).translate([487.5, 305]);

// Project every point of a ring; drop points the projection can't place
// (outside the three map areas). Round to 0.01 map units.
const ring = (r) => r.map((p) => project(p)).filter(Boolean).map(([x, y]) => [Math.round(x * 100) / 100, Math.round(y * 100) / 100]);
const geom = (g) => g.type === "Polygon"
  ? { type: "Polygon", coordinates: g.coordinates.map(ring) }
  : { type: "MultiPolygon", coordinates: g.coordinates.map((p) => p.map(ring)) };

// Keep only real districts: drop non-voting delegates (98) and unassigned water (ZZ).
const features = fc.features
  .filter((f) => f.geometry && !["98", "ZZ"].includes(f.properties.CD120))
  .map((f) => ({ type: "Feature", properties: f.properties, geometry: geom(f.geometry) }));
writeFileSync(out, JSON.stringify({ type: "FeatureCollection", features }));
console.log(`projected ${features.length} districts to ${out}`);
