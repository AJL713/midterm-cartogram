"""Build the geographic map and the population dots.

Writes data/geo.json with:
  states  [{state, path, x, y}]   SVG outline of each state + a label point
  dots    [x, y, s, x, y, s, ...] one dot per DOT_PEOPLE residents; s indexes STATE_ORDER
  meta    what one dot means, and where the numbers came from

Inputs (all in data/source/):
  states-albers-10m.json, counties-albers-10m.json
      US Census boundaries, packaged by the us-atlas project (npm: us-atlas@3).
      Already projected to a 975 x 610 Albers USA layout, so no map maths needed.
  county_population_estimate.csv
      County populations (Census estimates, about 2012) by FIPS code.
  state_population_2020.csv
      Official 2020 Census state totals.

Why both population files? The county file has every county but is older, so
each county keeps its SHARE of its state from that file, and every state is
scaled to its 2020 total. Growth between states (Texas, Florida) is then right;
shifts between counties inside a state since ~2012 are not captured.

Run:  python scripts/build_geo.py
"""

from __future__ import annotations

import csv
import json
import random
from pathlib import Path

from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.prepared import prep

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "data" / "source"

DOT_PEOPLE = 25_000   # residents per dot: ~13,000 dots, readable at phone width
SEED = 2026           # fixed so every build places the dots in the same spots

FIPS_TO_STATE = {
    "01": "AL", "02": "AK", "04": "AZ", "05": "AR", "06": "CA", "08": "CO", "09": "CT",
    "10": "DE", "11": "DC", "12": "FL", "13": "GA", "15": "HI", "16": "ID", "17": "IL",
    "18": "IN", "19": "IA", "20": "KS", "21": "KY", "22": "LA", "23": "ME", "24": "MD",
    "25": "MA", "26": "MI", "27": "MN", "28": "MS", "29": "MO", "30": "MT", "31": "NE",
    "32": "NV", "33": "NH", "34": "NJ", "35": "NM", "36": "NY", "37": "NC", "38": "ND",
    "39": "OH", "40": "OK", "41": "OR", "42": "PA", "44": "RI", "45": "SC", "46": "SD",
    "47": "TN", "48": "TX", "49": "UT", "50": "VT", "51": "VA", "53": "WA", "54": "WV",
    "55": "WI", "56": "WY",
}
# County codes that changed between the population file and the map file.
RENAMED = {"02270": "02158", "46113": "46102", "51515": "51019"}


# ---------------------------------------------------------------- TopoJSON

def decode_arcs(topo: dict) -> list[list[tuple[float, float]]]:
    """TopoJSON stores each border once, as integer steps; turn them into x/y points."""
    (sx, sy), (tx, ty) = topo["transform"]["scale"], topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)
    return arcs


def ring(arcs, indexes) -> list[tuple[float, float]]:
    """Join arcs into one closed ring. A negative index (~i) means 'arc i, reversed'."""
    out = []
    for i in indexes:
        pts = arcs[i] if i >= 0 else arcs[~i][::-1]
        out.extend(pts if not out else pts[1:])
    return out


def to_shape(geom, arcs):
    polys = geom["arcs"] if geom["type"] == "MultiPolygon" else [geom["arcs"]]
    shapes = []
    for p in polys:
        shell = ring(arcs, p[0])
        if len(shell) < 4:  # a speck of an island, too small to draw at this scale
            continue
        holes = [h for h in (ring(arcs, h) for h in p[1:]) if len(h) >= 4]
        shapes.append(Polygon(shell, holes).buffer(0))  # buffer(0) repairs tiny self-crossings
    if not shapes:
        return None
    return MultiPolygon([g for s in shapes for g in getattr(s, "geoms", [s])]) if len(shapes) > 1 else shapes[0]


def svg_path(shape) -> str:
    """Shapely polygon -> SVG path text, rounded to 0.1 to keep the file small."""
    polys = shape.geoms if isinstance(shape, MultiPolygon) else [shape]
    parts = []
    for p in polys:
        for r in [p.exterior, *p.interiors]:
            xy = r.coords
            parts.append("M" + "L".join(f"{x:.1f},{y:.1f}" for x, y in xy) + "Z")
    return "".join(parts)


# ---------------------------------------------------------------- population

def county_people() -> dict[str, float]:
    """County population, rescaled so each state sums to its 2020 Census total."""
    raw: dict[str, int] = {}
    for row in csv.DictReader(open(SRC / "county_population_estimate.csv")):
        fips = RENAMED.get(row["FIPS"].zfill(5), row["FIPS"].zfill(5))
        raw[fips] = raw.get(fips, 0) + int(row["TOT_POP"])
    names = {v: k for k, v in json.loads((ROOT / "data" / "names.json").read_text()).items()}
    totals = {names[r["state"]]: int(r["population_2020"])
              for r in csv.DictReader(open(SRC / "state_population_2020.csv"))}
    by_state: dict[str, int] = {}
    for fips, n in raw.items():
        st = FIPS_TO_STATE.get(fips[:2])
        if st in totals:
            by_state[st] = by_state.get(st, 0) + n
    return {f: n / by_state[FIPS_TO_STATE[f[:2]]] * totals[FIPS_TO_STATE[f[:2]]]
            for f, n in raw.items() if FIPS_TO_STATE.get(f[:2]) in totals}


def sample_points(shape, n: int, rng: random.Random) -> list[tuple[float, float]]:
    """n random points inside a shape ("dart throwing" inside its bounding box)."""
    if n == 0:
        return []
    test = prep(shape)
    minx, miny, maxx, maxy = shape.bounds
    pts, tries = [], 0
    while len(pts) < n and tries < n * 400:
        tries += 1
        p = (rng.uniform(minx, maxx), rng.uniform(miny, maxy))
        if test.contains(Point(p)):
            pts.append(p)
    while len(pts) < n:  # tiny or sliver county: fall back to its centre
        c = shape.representative_point()
        pts.append((c.x, c.y))
    return pts


def county_lines(topo: dict, arcs: list, tolerance: float = 0.3) -> dict[str, str]:
    """County borders inside each state, as one SVG path per state.

    Only lines shared by two counties of the same state are kept (state
    borders are drawn separately), and each is simplified slightly: these are
    faint guide lines shown when a state is zoomed in, not a precise map.
    Coordinates are rounded first and then written as relative steps, so the
    rounding never accumulates along a long border.
    """
    from shapely.geometry import LineString

    owners: dict[int, list[str]] = {}
    for g in topo["objects"]["counties"]["geometries"]:
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]]
        for p in polys:
            for r in p:
                for i in r:
                    owners.setdefault(i if i >= 0 else ~i, []).append(g["id"][:2])
    paths: dict[str, list[str]] = {}
    for arc, fips in owners.items():
        st = FIPS_TO_STATE.get(fips[0])
        if len(fips) != 2 or fips[0] != fips[1] or st in (None, "DC"):
            continue
        pts = [(round(x, 1), round(y, 1)) for x, y in LineString(arcs[arc]).simplify(tolerance).coords]
        steps = (f"l{round(x1 - x0, 1):g} {round(y1 - y0, 1):g}" for (x0, y0), (x1, y1) in zip(pts, pts[1:]))
        d = f"M{pts[0][0]:g} {pts[0][1]:g}" + "".join(steps)
        paths.setdefault(st, []).append(d)
    return {st: "".join(ds) for st, ds in sorted(paths.items())}


# States whose 2026 House map differs from the Census file (January 1, 2026):
# AL, FL, LA and TN redrew in April-May 2026; Missouri's 2025 map was held back
# by a referendum, so its 2022 map was used. Their district lines are left out.
DISTRICTS_NOT_CURRENT = {"AL", "FL", "LA", "TN", "MO"}


def district_shapes(states: dict) -> dict[str, object]:
    """Each current district ("WA-03") trimmed to its state's land outline."""
    from shapely.geometry import shape

    path = SRC / "districts_albers.json"
    if not path.exists():
        return {}
    out = {}
    for f in json.loads(path.read_text())["features"]:
        st = FIPS_TO_STATE.get(f["properties"]["STATE"])
        if not st or st in DISTRICTS_NOT_CURRENT or st not in states:
            continue
        geom = shape(f["geometry"]).buffer(0).intersection(states[st])
        if not geom.is_empty:
            out[f"{st}-{f['properties']['CD120']}"] = geom
    return out


def district_paths(districts: dict, tolerance: float = 0.3) -> dict[str, str]:
    """District shapes as SVG paths, keyed like the House seats ("WA-03")."""
    out = {}
    for key, geom in sorted(districts.items()):
        g = geom.simplify(tolerance, preserve_topology=True)
        polys = [p for p in getattr(g, "geoms", [g]) if p.geom_type == "Polygon" and p.area > 0.05]
        if polys:
            out[key] = svg_path(MultiPolygon(polys) if len(polys) > 1 else polys[0])
    return out


def district_lines(states: dict, tolerance: float = 0.3) -> dict[str, str]:
    """Lines between House districts inside each state, as one SVG path per state.

    Source: data/source/districts_albers.json, the Census 120th Congressional
    Districts already projected to this map by scripts/project_districts.mjs.
    Each district is trimmed to its state's land outline (Census districts run
    into lakes and coastal water); only borders between two districts are kept.
    """
    from shapely.geometry import shape
    from shapely.ops import unary_union

    path = SRC / "districts_albers.json"
    if not path.exists():
        return {}
    fips_to_state = FIPS_TO_STATE
    by_state: dict[str, list] = {}
    for f in json.loads(path.read_text())["features"]:
        st = fips_to_state.get(f["properties"]["STATE"])
        if st and st not in DISTRICTS_NOT_CURRENT:
            by_state.setdefault(st, []).append(shape(f["geometry"]).buffer(0))
    out = {}
    for st, polys in sorted(by_state.items()):
        if len(polys) < 2 or st not in states:
            continue  # one at-large district: no lines inside the state
        land = states[st]
        lines = unary_union([p.intersection(land).boundary for p in polys])
        # Remove the state's own outline (drawn separately), keep the inner borders.
        inner = lines.difference(land.boundary.buffer(0.6)).simplify(tolerance)
        parts = getattr(inner, "geoms", [inner])
        d = []
        for ln in parts:
            if ln.geom_type != "LineString" or ln.length < 1:
                continue  # crumbs left where a border meets the coast
            pts = [(round(x, 1), round(y, 1)) for x, y in ln.coords]
            steps = (f"l{round(x1 - x0, 1):g} {round(y1 - y0, 1):g}" for (x0, y0), (x1, y1) in zip(pts, pts[1:]))
            d.append(f"M{pts[0][0]:g} {pts[0][1]:g}" + "".join(steps))
        out[st] = "".join(d)
    return out


def main() -> None:
    rng = random.Random(SEED)
    order = sorted(v for v in FIPS_TO_STATE.values() if v != "DC")

    st_topo = json.loads((SRC / "states-albers-10m.json").read_text())
    st_arcs = decode_arcs(st_topo)
    states = []
    state_shapes = {}
    for g in st_topo["objects"]["states"]["geometries"]:
        st = FIPS_TO_STATE.get(g["id"])
        if not st or st == "DC":
            continue
        shape = to_shape(g, st_arcs)
        state_shapes[st] = shape
        label = label_point(shape)
        states.append({"state": st, "path": svg_path(shape),
                       "x": round(label.x, 1), "y": round(label.y, 1)})

    co_topo = json.loads((SRC / "counties-albers-10m.json").read_text())
    co_arcs = decode_arcs(co_topo)
    people = county_people()
    dots: list[float] = []
    dot_county: list[int] = []    # for each dot, its county (index into county_order)
    county_order: list[str] = []  # county codes (FIPS) in the order first used
    carry: dict[str, float] = {}  # leftover people per state, so small counties still add up
    for g in co_topo["objects"]["counties"]["geometries"]:
        fips = g["id"]
        st = FIPS_TO_STATE.get(fips[:2])
        if st not in order or fips not in people:
            continue
        shape = to_shape(g, co_arcs)
        if shape is None:
            continue
        exact = people[fips] / DOT_PEOPLE + carry.get(st, 0.0)
        n = int(exact)
        carry[st] = exact - n
        points = sample_points(shape, n, rng)
        if points:
            county_order.append(fips)
        for x, y in points:
            dots += [round(x, 1), round(y, 1), order.index(st)]
            dot_county.append(len(county_order) - 1)

    districts = district_shapes(state_shapes)

    out = {
        "states": sorted(states, key=lambda s: s["state"]),
        "county_lines": county_lines(co_topo, co_arcs),
        "district_lines": district_lines(state_shapes),
        "district_paths": district_paths(districts),
        "districts_not_current": sorted(DISTRICTS_NOT_CURRENT),
        "state_order": order,
        "dots": dots,
        "dot_county": dot_county,
        "county_order": county_order,
        "meta": {
            "dot_people": DOT_PEOPLE,
            "population_total": round(sum(people.values())),
            "population_source": "2020 Census state totals; county shares from Census estimates (~2012)",
            "boundaries_source": "US Census Bureau via us-atlas 3.0.1 (Albers USA projection)",
            "districts_source": "US Census Bureau TIGERweb, 120th Congressional Districts (January 1, 2026 vintage)",
        },
    }
    (ROOT / "data" / "geo.json").write_text(json.dumps(out, separators=(",", ":")))
    print(f"wrote {len(states)} state outlines and {len(dots) // 3} dots "
          f"({DOT_PEOPLE:,} people each) to data/geo.json")


# Label points for states whose shape centre falls awkwardly (Florida's
# peninsula, Michigan's two halves, Louisiana's coast).
def label_point(shape):
    """Where a state's name goes: the "pole of inaccessibility" of its largest part,
    the inside point farthest from every edge, so names look centred even in odd
    shapes (Idaho's panhandle, Florida, Michigan's two peninsulas, Louisiana's coast)."""
    from shapely.geometry import MultiPolygon
    from shapely.ops import polylabel
    main = max(shape.geoms, key=lambda g: g.area) if isinstance(shape, MultiPolygon) else shape
    return polylabel(main, tolerance=0.5)

if __name__ == "__main__":
    main()
