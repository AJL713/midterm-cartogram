"""EXPERIMENT: House cartogram layouts that keep states where they really are.

Writes data/layouts.json: {name: {"label", "shape", "hex": [...]}}. The experimental
build (bundle.py --experimental) includes it and shows a temporary "Layout" dropdown.
The real page never loads this file.

All layouts use the real outline of the country (data/geo.json) as the playing field.
Two ways of dealing the cells to states:

  outline   what is published: every state grows from its label point, then the cells
            are re-dealt so each state gets the ones nearest its (drifting) centre.
  geo       "true geography first": each cell starts with the state it physically sits
            in. States short of seats then take cells from better-off neighbours, one at
            a time, always from the neighbour with the most to spare, until every state
            has exactly its seat count. States with land to spare shed their farthest
            cells, which become gaps. Nothing moves that doesn't have to, so states stay
            put; only crowded ones (NJ, MA, MD) spill over their borders.

and three cell shapes: pointy-top hexagons (as now), flat-top hexagons, and squares,
plus a "roomy" grid (smaller cells, more of them, so shapes are truer and gaps show).

Run:  python scripts/layouts.py
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from shapely.geometry import Point
from shapely.prepared import prep

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_hex as bh  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEATS = bh.SEATS
SQRT3 = math.sqrt(3)
INSETS = ("AK", "HI")


# ----------------------------------------------------------------- grid geometries

class Hex:
    """Pointy-top hexagons, axial (q, r); the published grid."""
    shape = "hex"
    neighbours = bh.NEIGHBOURS

    @staticmethod
    def xy(q, r):
        return bh.hex_to_xy(q, r)

    @staticmethod
    def cell_near(x, y):
        r = round(y / 1.5)
        return round(x / SQRT3 - r / 2), r


class HexFlat:
    """Flat-top hexagons: columns are straight, rows zig-zag."""
    shape = "hexflat"
    neighbours = bh.NEIGHBOURS

    @staticmethod
    def xy(q, r):
        return 1.5 * q, SQRT3 * (r + q / 2)

    @staticmethod
    def cell_near(x, y):
        q = round(x / 1.5)
        return q, round(y / SQRT3 - q / 2)


class Square:
    """Squares spaced like hexagon columns (SQRT3 apart) so labels and zoom match."""
    shape = "square"
    neighbours = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    @staticmethod
    def xy(q, r):
        return q * SQRT3, r * SQRT3

    @staticmethod
    def cell_near(x, y):
        return round(x / SQRT3), round(y / SQRT3)


# ----------------------------------------------------------------- shared helpers

def pieces(geo, cells) -> list[set]:
    left, out = set(cells), []
    while left:
        todo, seen = [left.pop()], set()
        while todo:
            c = todo.pop()
            seen.add(c)
            for dq, dr in geo.neighbours:
                n = (c[0] + dq, c[1] + dr)
                if n in left:
                    left.remove(n)
                    todo.append(n)
        out.append(seen)
    return sorted(out, key=len, reverse=True)


def join_pieces(geo, regions: dict[str, list], free: set = frozenset()) -> dict[str, list]:
    """Until every state is in one piece: move a stray cell into free space next to
    the state's main piece, or swap it with a neighbour's cell there (as long as
    that neighbour stays whole)."""
    owner = {c: s for s, cells in regions.items() for c in cells}
    free = set(free)
    for _ in range(800):
        split = [(s, pieces(geo, regions[s])) for s in regions]
        split = [(s, ps) for s, ps in split if len(ps) > 1]
        if not split:
            return regions
        s, ps = split[0]
        main, stray = ps[0], ps[-1]
        done = False
        for c in sorted(stray):
            for m in main:
                for dq, dr in geo.neighbours:
                    d = (m[0] + dq, m[1] + dr)
                    t = owner.get(d)
                    if t == s:
                        continue
                    if t is None:
                        if d not in free:
                            continue
                        regions[s] = [x for x in regions[s] if x != c] + [d]
                        owner[d] = s
                        del owner[c]
                        free.discard(d)
                        free.add(c)
                        done = True
                        break
                    new_t = [x for x in regions[t] if x != d] + [c]
                    if len(pieces(geo, new_t)) > len(pieces(geo, regions[t])):
                        continue
                    regions[t] = new_t
                    regions[s] = [x for x in regions[s] if x != c] + [d]
                    owner[d], owner[c] = s, t
                    done = True
                    break
                if done:
                    break
            if done:
                break
        if not done:
            raise RuntimeError(f"could not join {s} into one piece")
    raise RuntimeError("too many swaps while joining pieces")


def to_records(geo, regions):
    out = []
    for state, cells in regions.items():
        cells = sorted(cells, key=lambda c: (round(geo.xy(*c)[1], 3), geo.xy(*c)[0]))
        for i, (q, r) in enumerate(cells, start=1):
            x, y = geo.xy(q, r)
            out.append({"id": bh.district_id(state, i), "state": state,
                        "q": q, "r": r, "x": round(x, 3), "y": round(y, 3)})
    return out


class Field:
    """The country outline laid over a grid: which cells are inside, at what scale."""

    def __init__(self, geo, slack: float):
        self.geo = geo
        country, mainland, labels = bh.country_outline()
        self.country, self.mainland, self.labels = prep(country), prep(mainland), labels
        minx, miny, maxx, maxy = country.bounds
        self.bounds = (minx, miny, maxx, maxy)
        lo, hi = 5.0, 40.0  # cells shrink as k grows; find the k that gives ~432*slack mainland cells
        for _ in range(18):
            k = (lo + hi) / 2
            _, n = self.cells_at(k)
            lo, hi = (k, hi) if n > 432 * slack else (lo, k)
        self.k = lo
        allowed, _ = self.cells_at(self.k)
        self.allowed = pieces(geo, allowed)[0]  # the connected mainland only; islands are dropped
        self.anchors = {s: (labels[s][0] / self.k, labels[s][1] / self.k) for s in SEATS}
        # Alaska and Hawaii: fixed cells at their inset positions, outside the mainland deal.
        self.insets = {}
        for s in INSETS:
            c = geo.cell_near(*self.anchors[s])
            self.insets[s] = [c, (c[0] + 1, c[1])][: SEATS[s]]
        self.mainland_seats = {s: n for s, n in SEATS.items() if s not in INSETS}

    def cells_at(self, k):
        minx, miny, maxx, maxy = self.bounds
        span = int(max(maxx, maxy) / k) + 6
        inside, on_mainland = set(), 0
        for q in range(-span, span):
            for r in range(-span, span):
                x, y = self.geo.xy(q, r)
                if not (minx <= x * k <= maxx and miny <= y * k <= maxy):
                    continue
                pt = Point(x * k, y * k)
                if self.country.contains(pt):
                    inside.add((q, r))
                    on_mainland += self.mainland.contains(pt)
        return inside, on_mainland

    def state_at(self, cell, shapes) -> str | None:
        x, y = self.geo.xy(*cell)
        pt = Point(x * self.k, y * self.k)
        for s, g in shapes.items():
            if g.contains(pt):
                return s
        return None


# ----------------------------------------------------------------- dealing methods

def deal_outline(field: Field, rounds: int):
    """The published method: grow, then re-deal optimally with drifting anchors."""
    geo, seats = field.geo, field.mainland_seats
    anchors = dict(field.anchors)
    # grow (from build_hex, which works on pointy hexes only) — reimplemented for any grid
    occupied, cells = set(), {}
    for s in sorted(seats, key=lambda s: seats[s]):
        cells[s] = [nearest_free(geo, occupied, field.allowed, *anchors[s])]
        occupied.add(cells[s][0])
    while True:
        todo = [s for s in seats if len(cells[s]) < seats[s]]
        if not todo:
            break
        s = min(todo, key=lambda s: (len(cells[s]) / seats[s], s))
        fr = {(q + dq, r + dr) for q, r in cells[s] for dq, dr in geo.neighbours
              if (q + dq, r + dr) in field.allowed and (q + dq, r + dr) not in occupied}
        c = min(fr, key=lambda c: dist2(geo, c, anchors[s])) if fr else nearest_free(geo, occupied, field.allowed, *anchors[s])
        cells[s].append(c)
        occupied.add(c)
    pool = [c for cs in cells.values() for c in cs]
    for _ in range(rounds):
        regions = assign(geo, pool, anchors, seats)
        for s, cs in regions.items():
            cx = sum(geo.xy(*c)[0] for c in cs) / len(cs)
            cy = sum(geo.xy(*c)[1] for c in cs) / len(cs)
            anchors[s] = (0.5 * anchors[s][0] + 0.5 * cx, 0.5 * anchors[s][1] + 0.5 * cy)
    regions = join_pieces(geo, assign(geo, pool, anchors, seats))
    regions.update(field.insets)
    return regions


def dist2(geo, c, p):
    x, y = geo.xy(*c)
    return (x - p[0]) ** 2 + (y - p[1]) ** 2


def nearest_free(geo, occupied, allowed, ax, ay):
    free = [c for c in allowed if c not in occupied]
    return min(free, key=lambda c: dist2(geo, c, (ax, ay)))


def assign(geo, pool, anchors, seats):
    slots = [s for s in sorted(seats) for _ in range(seats[s])]
    pts = np.array([geo.xy(*c) for c in pool])
    anc = np.array([anchors[s] for s in slots])
    cost = ((pts[:, None, :] - anc[None, :, :]) ** 2).sum(axis=2)
    rows, cols = linear_sum_assignment(cost)
    out = {s: [] for s in seats}
    for r, c in zip(rows, cols):
        out[slots[c]].append(pool[r])
    return out


def deal_geo(field: Field, label_weight: float = 0.05):
    """Balanced assignment on true geography. Each cell's cost for a state is how far
    the cell lies outside that state's real land (zero inside it), plus a small pull
    toward the state's label point so the cells a state takes beyond its borders are
    the near ones. The assignment gives every state exactly its seat count at the
    least total cost; cells left over (the grid has a few more than 432) go unused.
    States keep their place; crowded ones spill into the nearest neighbouring land."""
    geo, seats, allowed = field.geo, field.mainland_seats, field.allowed
    shapes = {s: g for s, g in state_polygons(prepared=False).items() if s in seats}
    cells = sorted(c for c in allowed if c not in {x for v in field.insets.values() for x in v})
    pts = [Point(geo.xy(*c)[0] * field.k, geo.xy(*c)[1] * field.k) for c in cells]
    names = sorted(seats)
    cost = np.zeros((len(cells), 432 + (len(cells) - 432)))
    col = 0
    slots = []
    for s in names:
        d = np.array([shapes[s].distance(pt) / field.k for pt in pts])
        pull = np.array([dist2(geo, c, field.anchors[s]) for c in cells])
        for _ in range(seats[s]):
            cost[:, col] = d ** 2 + label_weight * pull
            slots.append(s)
            col += 1
    cost[:, col:] = 0.0  # spare slots: a cell nobody needs costs nothing
    index = {c: i for i, c in enumerate(cells)}
    slot_cols = {}
    for i, s in enumerate(slots):
        slot_cols.setdefault(s, []).append(i)
    # Deal; where a state comes out in pieces, make its stray cells dear to it and
    # deal again. A few rounds settle it; join_pieces mends anything left.
    for _ in range(80):
        rows, cols = linear_sum_assignment(cost)
        regions = {s: [] for s in seats}
        for r, c in zip(rows, cols):
            if c < len(slots):
                regions[slots[c]].append(cells[r])
        strays = [(s, c) for s in seats for pc in pieces(geo, regions[s])[1:] for c in pc]
        if not strays:
            break
        for s, c in strays:
            cost[index[c], slot_cols[s]] += 25.0
    used = {c for cs in regions.values() for c in cs}
    regions = join_pieces(geo, regions, free=set(cells) - used)
    regions.update(field.insets)
    return regions


def state_polygons(prepared=True):
    """State outlines as shapely shapes."""
    import re
    from shapely.geometry import Polygon
    from shapely.ops import unary_union

    geo = json.loads((DATA / "geo.json").read_text())
    out = {}
    for st in geo["states"]:
        polys = []
        for sub in re.findall(r"M([^M]+)", st["path"]):
            pts = [tuple(map(float, p.split(","))) for p in re.findall(r"[-\d.]+,[-\d.]+", sub)]
            if len(pts) >= 3:
                polys.append(Polygon(pts).buffer(0))
        out[st["state"]] = prep(unary_union(polys)) if prepared else unary_union(polys)
    return out


# ----------------------------------------------------------------- the menu

def main() -> None:
    layouts = {}

    def add(key, label, geo, slack, deal):
        field = Field(geo, slack)
        print('building', key, flush=True)
        regions = deal(field)
        recs = to_records(geo, regions)
        assert len(recs) == 435 and len({h["id"] for h in recs}) == 435, key
        layouts[key] = {"label": label, "shape": geo.shape, "hex": recs}
        print(f"{key:14s} {len(recs)} cells  (scale {field.k:.2f})")

    layouts["current"] = {"label": "Current (published)", "shape": "hex",
                          "hex": json.loads((DATA / "hex.json").read_text())}
    add("geo", "True geography, same grid", Hex(), bh.OUTLINE_SLACK, deal_geo)
    add("geo-roomy", "True geography, roomier grid", Hex(), 1.25, deal_geo)
    add("geo-tight", "True geography, stronger pull to centre", Hex(), bh.OUTLINE_SLACK, lambda f: deal_geo(f, 0.4))
    add("geo-flat", "True geography, flat-top hexagons", HexFlat(), 1.10, deal_geo)
    add("geo-squares", "True geography, squares", Square(), 1.2, deal_geo)

    (DATA / "layouts.json").write_text(json.dumps(layouts, separators=(",", ":")))
    print("wrote", DATA / "layouts.json")


if __name__ == "__main__":
    main()
