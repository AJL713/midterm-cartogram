"""EXPERIMENT: alternative House cartogram layouts, side by side.

Writes data/layouts.json: {name: {"label": ..., "shape": "hex"|"square", "hex": [...]}}.
The experimental build (bundle.py --experimental) includes it and shows a temporary
"Layout" dropdown. The real page never loads this file.

Layouts:
  current   data/hex.json as published (grow together, optimal re-deal, compaction)
  tuned     same algorithm, but anchors stay closer to true geography
  outline   hexagons may only be placed inside the real US silhouette (from
            data/geo.json); states are dealt inside it
  dorling   each state is a round blob of hexagons at its true position, blobs
            pushed apart just until they don't overlap (a "Dorling" cartogram)
  squares   the current algorithm on a square grid (FiveThirtyEight style)

Run:  python scripts/layouts.py
"""

from __future__ import annotations

import json
import math
import re
import sys
from pathlib import Path

import numpy as np
from scipy.optimize import linear_sum_assignment
from shapely.geometry import MultiPolygon, Point, Polygon
from shapely.ops import unary_union

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_hex as bh  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
SEATS = bh.SEATS
SQRT3 = math.sqrt(3)


# ----------------------------------------------------------------- grid geometry

class Hex:
    shape = "hex"
    neighbours = bh.NEIGHBOURS

    @staticmethod
    def xy(q, r):
        return bh.hex_to_xy(q, r)

    @staticmethod
    def cell_near(x, y):
        r = round(y / 1.5)
        return round(x / SQRT3 - r / 2), r


class Square:
    shape = "square"
    neighbours = [(1, 0), (-1, 0), (0, 1), (0, -1)]

    # Squares are spaced like hexagon columns (SQRT3 apart), so labels and zoom match.
    @staticmethod
    def xy(q, r):
        return q * SQRT3, r * SQRT3

    @staticmethod
    def cell_near(x, y):
        return round(x / SQRT3), round(y / SQRT3)


def nearest_free(geo, occupied, ax, ay, allowed=None):
    q0, r0 = geo.cell_near(ax, ay)
    best, best_d = None, math.inf
    for dr in range(-14, 15):
        for dq in range(-14, 15):
            c = (q0 + dq, r0 + dr)
            if c in occupied or (allowed is not None and c not in allowed):
                continue
            x, y = geo.xy(*c)
            d = (x - ax) ** 2 + (y - ay) ** 2
            if d < best_d:
                best, best_d = c, d
    if best is None and allowed is not None:  # boxed in: take the nearest free cell anywhere in the mask
        free = [c for c in allowed if c not in occupied]
        best = min(free, key=lambda c: (geo.xy(*c)[0] - ax) ** 2 + (geo.xy(*c)[1] - ay) ** 2)
    if best is None:
        raise RuntimeError("no free cell near anchor")
    return best


def grow_all(geo, anchors, occupied, allowed=None):
    """Every state grows one cell per turn, least-complete state first (as in build_hex)."""
    cells = {}
    for s in sorted(SEATS, key=lambda s: SEATS[s]):
        cells[s] = [nearest_free(geo, occupied, *anchors[s], allowed)]
        occupied.add(cells[s][0])

    def dist(c, s):
        x, y = geo.xy(*c)
        return (x - anchors[s][0]) ** 2 + (y - anchors[s][1]) ** 2

    while True:
        todo = [s for s in SEATS if len(cells[s]) < SEATS[s]]
        if not todo:
            return cells
        s = min(todo, key=lambda s: (len(cells[s]) / SEATS[s], s))
        frontier = {(q + dq, r + dr) for q, r in cells[s] for dq, dr in geo.neighbours
                    if (q + dq, r + dr) not in occupied and (allowed is None or (q + dq, r + dr) in allowed)}
        c = min(frontier, key=lambda c: dist(c, s)) if frontier else nearest_free(geo, occupied, *anchors[s], allowed)
        cells[s].append(c)
        occupied.add(c)


def assign_optimally(geo, pool, anchors):
    slots = [s for s in sorted(SEATS) for _ in range(SEATS[s])]
    pts = np.array([geo.xy(*c) for c in pool])
    anc = np.array([anchors[s] for s in slots])
    cost = ((pts[:, None, :] - anc[None, :, :]) ** 2).sum(axis=2)
    rows, cols = linear_sum_assignment(cost)
    out = {s: [] for s in SEATS}
    for r, c in zip(rows, cols):
        out[slots[c]].append(pool[r])
    return out


def lloyd(geo, pool, anchors, rounds=4):
    anchors = dict(anchors)
    for _ in range(rounds):
        regions = assign_optimally(geo, pool, anchors)
        for s, cells in regions.items():
            cx = sum(geo.xy(*c)[0] for c in cells) / len(cells)
            cy = sum(geo.xy(*c)[1] for c in cells) / len(cells)
            anchors[s] = (0.5 * anchors[s][0] + 0.5 * cx, 0.5 * anchors[s][1] + 0.5 * cy)
    return assign_optimally(geo, pool, anchors)


def compact(geo, regions):
    """Slide whole states sideways toward the centre while the cells they move into are empty."""
    movable = [s for s in regions if s not in ("AK", "HI")]
    pts = [geo.xy(*c) for s in movable for c in regions[s]]
    cx = sum(p[0] for p in pts) / len(pts)

    def centre_x(cells):
        return sum(geo.xy(*c)[0] for c in cells) / len(cells)

    moved = True
    while moved:
        moved = False
        occupied = {c for cells in regions.values() for c in cells}
        for s in sorted(movable, key=lambda s: abs(centre_x(regions[s]) - cx)):
            own = set(regions[s])
            here = abs(centre_x(regions[s]) - cx)
            best = None
            for dq, dr in ((1, 0), (-1, 0)):
                shifted = [(q + dq, r + dr) for q, r in regions[s]]
                if any(c in occupied and c not in own for c in shifted):
                    continue
                d = abs(centre_x(shifted) - cx)
                if d < here - 0.5 and (best is None or d < best[0]):
                    best = (d, shifted)
            if best:
                occupied -= own
                regions[s] = best[1]
                occupied |= set(best[1])
                moved = True
    return regions


def to_records(geo, regions):
    out = []
    for state, cells in regions.items():
        cells = sorted(cells, key=lambda c: (geo.xy(*c)[1], geo.xy(*c)[0]))
        for i, (q, r) in enumerate(cells, start=1):
            x, y = geo.xy(q, r)
            out.append({"id": bh.district_id(state, i), "state": state,
                        "q": q, "r": r, "x": round(x, 3), "y": round(y, 3)})
    return out


# ----------------------------------------------------------------- real geography

def state_shapes() -> dict[str, MultiPolygon]:
    """Each state's outline from data/geo.json (Albers USA, Alaska and Hawaii inset)."""
    geo = json.loads((DATA / "geo.json").read_text())
    shapes = {}
    for st in geo["states"]:
        polys = []
        for sub in re.findall(r"M([^M]+)", st["path"]):
            pts = [tuple(map(float, p.split(","))) for p in re.findall(r"[-\d.]+,[-\d.]+", sub)]
            if len(pts) >= 3:
                polys.append(Polygon(pts))
        shapes[st["state"]] = unary_union([p.buffer(0) for p in polys])
    return shapes


def label_points() -> dict[str, tuple[float, float]]:
    geo = json.loads((DATA / "geo.json").read_text())
    return {st["state"]: (float(st["x"]), float(st["y"])) for st in geo["states"]}


# ----------------------------------------------------------------- the layouts

def layout_current():
    return json.loads((DATA / "hex.json").read_text())


def layout_tuned():
    """Anchors closer to geography (EQUALIZE 0.3 instead of 0.5), then compacted as now."""
    old = bh.EQUALIZE
    bh.EQUALIZE = 0.3
    try:
        anchors = {s: bh.anchor_xy(s) for s in SEATS}
    finally:
        bh.EQUALIZE = old
    geo = Hex()
    grown = grow_all(geo, anchors, set())
    pool = [c for cells in grown.values() for c in cells]
    return to_records(geo, compact(geo, lloyd(geo, pool, anchors)))


def layout_outline():
    """Only cells inside the real US silhouette may be used."""
    geo = Hex()
    shapes = state_shapes()
    country = unary_union(list(shapes.values()))
    mainland = unary_union([g for st, g in shapes.items() if st not in ("AK", "HI")])
    labels = label_points()
    minx, miny, maxx, maxy = country.bounds

    def mask_at(k):  # k = map pixels per hex unit
        allowed = set()
        for r in range(int(miny / k / 1.5) - 2, int(maxy / k / 1.5) + 3):
            for q in range(int(minx / k / SQRT3) - r // 2 - 3, int(maxx / k / SQRT3) - r // 2 + 4):
                x, y = geo.xy(q, r)
                if country.contains(Point(x * k, y * k)):
                    allowed.add((q, r))
        return allowed

    lo, hi = 5.0, 40.0  # binary search the scale so the mainland holds ~ 432 * 1.15 cells (AK, HI have their own)
    for _ in range(18):
        k = (lo + hi) / 2
        n = sum(1 for q, r in mask_at(k) if mainland.contains(Point(geo.xy(q, r)[0] * k, geo.xy(q, r)[1] * k)))
        if n > 432 * 1.15:
            lo = k
        else:
            hi = k
    k = lo
    allowed = mask_at(k)
    anchors = {s: (labels[s][0] / k, labels[s][1] / k) for s in SEATS}
    # Alaska and Hawaii are insets too small to hold a hexagon; give each its own cells there.
    for s in ("AK", "HI"):
        c = geo.cell_near(*anchors[s])
        allowed |= {c} | {(c[0] + dq, c[1] + dr) for dq, dr in geo.neighbours}
    grown = grow_all(geo, anchors, set(), allowed)
    pool = [c for cells in grown.values() for c in cells]
    return to_records(geo, lloyd(geo, pool, anchors, rounds=3))


def layout_dorling():
    """Round blobs at true positions, pushed apart until they no longer overlap."""
    geo = Hex()
    labels = label_points()
    total_area = 435 * 2.598  # hexagon of radius 1
    # Scale the map so the blobs cover about 55% of the mainland's box.
    xs = [p[0] for s, p in labels.items() if s not in ("AK", "HI")]
    ys = [p[1] for s, p in labels.items() if s not in ("AK", "HI")]
    box = (max(xs) - min(xs)) * (max(ys) - min(ys))
    k = math.sqrt(box / (total_area / 0.55))
    pos = {s: [labels[s][0] / k, labels[s][1] / k] for s in SEATS}
    rad = {s: 0.909 * math.sqrt(SEATS[s]) + 0.6 for s in SEATS}
    home = {s: tuple(pos[s]) for s in SEATS}
    for _ in range(400):  # Dorling relaxation: overlapping circles repel, all drift home a little
        for a in SEATS:
            for b in SEATS:
                if a >= b:
                    continue
                dx, dy = pos[b][0] - pos[a][0], pos[b][1] - pos[a][1]
                d = math.hypot(dx, dy) or 1e-6
                overlap = rad[a] + rad[b] - d
                if overlap > 0:
                    wa = SEATS[b] / (SEATS[a] + SEATS[b])
                    pos[a][0] -= dx / d * overlap * wa * 0.5
                    pos[a][1] -= dy / d * overlap * wa * 0.5
                    pos[b][0] += dx / d * overlap * (1 - wa) * 0.5
                    pos[b][1] += dy / d * overlap * (1 - wa) * 0.5
        for s in SEATS:
            pos[s][0] += (home[s][0] - pos[s][0]) * 0.02
            pos[s][1] += (home[s][1] - pos[s][1]) * 0.02
    # Build each blob alone (so it is round), then drop it onto the shared grid.
    regions, occupied = {}, set()
    for s in sorted(SEATS, key=lambda s: -SEATS[s]):
        own = set()
        c0 = geo.cell_near(0, 0)
        own.add(c0)
        while len(own) < SEATS[s]:
            frontier = {(q + dq, r + dr) for q, r in own for dq, dr in geo.neighbours} - own
            own.add(min(frontier, key=lambda c: geo.xy(*c)[0] ** 2 + geo.xy(*c)[1] ** 2))
        # place: try offsets spiralling out from the wanted cell until nothing overlaps
        want = geo.cell_near(*pos[s])
        placed = None
        for ring in range(0, 30):
            cands = [(want[0] + dq, want[1] + dr) for dq in range(-ring, ring + 1) for dr in range(-ring, ring + 1)
                     if max(abs(dq), abs(dr)) == ring]
            cands.sort(key=lambda c: (geo.xy(*c)[0] - pos[s][0]) ** 2 + (geo.xy(*c)[1] - pos[s][1]) ** 2)
            for off in cands:
                cells = {(q + off[0], r + off[1]) for q, r in own}
                if not cells & occupied:
                    placed = cells
                    break
            if placed:
                break
        regions[s] = list(placed)
        occupied |= placed
    return to_records(geo, regions)


def layout_squares():
    geo = Square()
    # Same anchors as the current layout, converted from hex units to square units.
    anchors = {}
    for s in SEATS:
        x, y = bh.anchor_xy(s)
        anchors[s] = (x * 0.93, y / 1.5 * SQRT3 * 1.05)
    grown = grow_all(geo, anchors, set())
    pool = [c for cells in grown.values() for c in cells]
    return to_records(geo, compact(geo, lloyd(geo, pool, anchors)))


def main() -> None:
    layouts = {
        "current": {"label": "Current (published)", "shape": "hex", "hex": layout_current()},
        "tuned": {"label": "Anchors closer to geography", "shape": "hex", "hex": layout_tuned()},
        "outline": {"label": "Inside the US outline", "shape": "hex", "hex": layout_outline()},
        "dorling": {"label": "Dorling bubbles", "shape": "hex", "hex": layout_dorling()},
        "squares": {"label": "Square grid", "shape": "square", "hex": layout_squares()},
    }
    for name, lay in layouts.items():
        assert len(lay["hex"]) == 435, (name, len(lay["hex"]))
        ids = {h["id"] for h in lay["hex"]}
        assert len(ids) == 435, name
    (DATA / "layouts.json").write_text(json.dumps(layouts, separators=(",", ":")))
    print("wrote", DATA / "layouts.json", {k: len(v["hex"]) for k, v in layouts.items()})


if __name__ == "__main__":
    main()
