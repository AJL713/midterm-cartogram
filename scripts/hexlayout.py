"""House cartogram layout: hexagons inside a squeezed outline of the country.

Used by build_hex.py (build_house). Steps:
  1. warp_map squeezes the real map east-west where there are few seats and stretches
     it where there are many (WARP_X in build_hex.py, 0 = no squeeze, 1 = every seat
     the same width). The empty Mountain West narrows, so the Pacific states sit next
     to the rest of the country, and the Northeast widens, so New York is on the coast.
  2. Field lays a hexagon grid over that squeezed outline, scaled so the mainland holds
     a little more than 432 hexagons (OUTLINE_SLACK); only cells inside are used.
     Alaska and Hawaii get fixed cells at their inset positions.
  3. deal_outline grows every state from its (squeezed) label point at once, re-deals
     the claimed cells optimally a few rounds (ROUNDS) so states are compact, and
     join_pieces repairs any state left in two pieces.
This was option C ("Squeeze the empty West: strong") on the experiment branch.
"""

from __future__ import annotations

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


class Hex:
    """Pointy-top hexagons, axial (q, r)."""
    shape = "hex"
    neighbours = bh.NEIGHBOURS

    @staticmethod
    def xy(q, r):
        return bh.hex_to_xy(q, r)

    @staticmethod
    def cell_near(x, y):
        r = round(y / 1.5)
        return round(x / SQRT3 - r / 2), r


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

    def __init__(self, geo, slack: float, warp=None):
        self.geo = geo
        self.shapes, labels = warp or (state_polygons(prepared=False), bh.country_outline()[2])
        from shapely.ops import unary_union
        country = unary_union(list(self.shapes.values()))
        mainland = unary_union([g for st, g in self.shapes.items() if st not in INSETS])
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


def deal_outline(field: Field, rounds: int):
    """Grow every state from its label point at once, then re-deal the cells optimally
    with anchors that drift to each state's centre (a few rounds), then join pieces."""
    geo, seats = field.geo, field.mainland_seats
    anchors = dict(field.anchors)
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
    regions = assign(geo, pool, anchors, seats)
    regions = join_pieces(geo, regions, free=set(field.allowed) - set(pool))
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


def warp_map(ax: float, ay: float = 0.0, sigma: float = 45.0):
    """Stretch the map where seats are dense and squeeze it where they are sparse,
    separately along x (east-west) and y (north-south), before laying out cells.

    Along x, each thin north-south band of the map gets a new width proportional to
    (1 - ax) + ax * (seats near that band / average). ax = 0 leaves the map as it is;
    ax = 1 makes every seat take the same width. "Seats near" is a smooth (Gaussian,
    sigma map pixels) sum over the states' label points weighted by their seats. The
    same along y with ay. The result: the empty Mountain West narrows (no "fjord"),
    the Midwest and the East widen, and New York moves back toward the coast."""
    from shapely.ops import transform

    shapes = state_polygons(prepared=False)
    labels = bh.country_outline()[2]
    main = [s for s in SEATS if s not in INSETS]
    xs = np.array([labels[s][0] for s in main]); ys = np.array([labels[s][1] for s in main])
    w = np.array([SEATS[s] for s in main], dtype=float)
    from shapely.ops import unary_union
    minx, miny, maxx, maxy = unary_union(list(shapes.values())).bounds

    def axis_map(vals, lo, hi, a):
        if a <= 0:
            return lambda v: v
        g = np.linspace(lo - 1, hi + 1, 4001)
        dens = (w[None, :] * np.exp(-((g[:, None] - vals[None, :]) ** 2) / (2 * sigma ** 2))).sum(axis=1)
        dens = (1 - a) + a * dens / dens.mean()
        cdf = np.concatenate([[0], np.cumsum((dens[1:] + dens[:-1]) / 2 * np.diff(g))])
        cdf = g[0] + cdf / cdf[-1] * (g[-1] - g[0])
        return lambda v: np.interp(v, g, cdf)

    fx, fy = axis_map(xs, minx, maxx, ax), axis_map(ys, miny, maxy, ay)

    def f(x, y, z=None):
        return fx(np.asarray(x)), fy(np.asarray(y))

    warped = {}
    for st, g in shapes.items():
        if st in INSETS:  # the insets keep their size and only move with their anchor
            cx, cy = labels[st]
            nx, ny = float(fx(cx)), float(fy(cy))
            from shapely.affinity import translate
            warped[st] = translate(g, nx - cx, ny - cy)
        else:
            warped[st] = transform(f, g).buffer(0)
    wlabels = {st: (float(fx(x)), float(fy(y))) for st, (x, y) in labels.items()}
    return warped, wlabels
